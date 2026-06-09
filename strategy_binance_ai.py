# -*- coding: utf-8 -*-
"""Binance AI策略 — 基于 Binance_top_value 评分数据，多币种 USDT 合约挂单"""
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import ccxt

from config import API_KEY, SECRET_KEY
from ai_bot_base import AiBotBase, TP_PCT, SL_PCT, MAX_POSITIONS, MIN_SCORE, CHECK_INTERVAL, ORDER_EXPIRE_HOURS, SYMBOL_SUFFIX

logger = logging.getLogger(__name__)

ORDER_AMOUNT = 200  # Binance 每单 200 USDT


class BinanceAiBot(AiBotBase):
    """Binance AI 策略：从 Binance_top_value 表选出优质币种，挂 USDT 限价单入场"""

    STATE_DEFAULTS = {"orders": {}, "positions": {}, "filled_today": {}, "closed_positions": []}

    def __init__(self, data_file: str = None):
        self.exchange = ccxt.binance({
            "options": {"defaultType": "future"},
            "apiKey": API_KEY,
            "secret": SECRET_KEY,
            "enableRateLimit": True,
        })
        self.exchange.load_markets()

        # 状态文件
        if data_file is None:
            data_file = str(Path(__file__).parent / "binance_ai_state.json")
        self.data_file = data_file
        self.state = self._load_state()

        # 支持的 USDT/USDC 合约 symbol 集合（缓存）
        self.supported_symbols = {}
        for s in self.exchange.symbols:
            if s.endswith("/USDT:USDT") or s.endswith("/USDC:USDC"):
                coin = s.split("/")[0]
                self.supported_symbols[coin] = s

        # 检测账户持仓模式：双向(hedge) / 单向(one-way)
        self.one_way_mode = True
        try:
            resp = self.exchange.fapiPrivateGetPositionSideDual()
            if resp.get("dualSidePosition") is True:
                self.one_way_mode = False
                logger.info("账户持仓模式: 双向对冲 (Hedge Mode)")
            else:
                logger.info("账户持仓模式: 单向 (One-way Mode)")
        except Exception as e:
            logger.warning(f"检测持仓模式失败，默认单向: {e}")

        logger.info(f"BinanceAiBot 初始化完成，支持 {len(self.supported_symbols)} 个合约")

    # ── 数据库查询 ──

    def fetch_signals(self) -> list[dict]:
        """查询符合条件的币种：profit_score >= MIN_SCORE"""
        try:
            conn = self._get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DATE_FORMAT(analysis_time, '%Y-%m-%d %H:%i') AS minute_time
                    FROM Binance_top_value
                    GROUP BY minute_time
                    HAVING COUNT(*) >= 10
                    ORDER BY minute_time DESC
                    LIMIT 1
                """)
                latest = cur.fetchone()
                if not latest:
                    logger.warning("数据库无完整数据")
                    return []
                minute_time = latest["minute_time"]
                start_t = minute_time + ":00"
                end_t = (datetime.strptime(minute_time, "%Y-%m-%d %H:%M") + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")

                cur.execute("""
                    SELECT t1.symbol, t1.current_price, t1.profit_score, t1.rating,
                           t1.callback_points, t1.entry_suggestion,
                           t1.stop_loss, t1.target_price
                    FROM Binance_top_value t1
                    INNER JOIN (
                        SELECT symbol, MAX(analysis_time) AS max_time
                        FROM Binance_top_value
                        WHERE analysis_time >= %s AND analysis_time < %s
                        GROUP BY symbol
                    ) t2 ON t1.symbol = t2.symbol AND t1.analysis_time = t2.max_time
                    WHERE t1.profit_score >= %s
                    ORDER BY t1.profit_score DESC
                """, (start_t, end_t, MIN_SCORE))
                rows = cur.fetchall()
            conn.close()
            logger.info(f"查询到 {len(rows)} 个符合条件的币种 (score>={MIN_SCORE})")
            return rows
        except Exception as e:
            logger.error(f"数据库查询失败: {e}")
            return []

    # ── 交易所操作 ──

    def _get_usdt_symbol(self, coin: str) -> Optional[str]:
        """获取币种对应的合约 symbol（优先 USDT，降级 USDC）"""
        symbol = f"{coin}{SYMBOL_SUFFIX}"
        if symbol in self.supported_symbols.values():
            return symbol
        if coin in self.supported_symbols:
            return self.supported_symbols[coin]
        return None

    def _calc_quantity(self, symbol: str, price: float) -> Optional[float]:
        """计算 ORDER_AMOUNT USDT 对应的合约数量"""
        try:
            raw_qty = ORDER_AMOUNT / price if price > 0 else 0
            qty = self.exchange.amount_to_precision(symbol, raw_qty)
            return float(qty)
        except Exception as e:
            logger.warning(f"计算数量失败 {symbol}: {e}")
            return None

    def _calc_bb_lower(self, symbol: str, timeframe: str = "5m") -> Optional[float]:
        """用币安公开数据计算布林下轨（20周期，2倍标准差）"""
        try:
            if not hasattr(self, '_bb_checker'):
                self._bb_checker = ccxt.binance({"enableRateLimit": True})
            coin = symbol.split("/")[0]
            spot_sym = f"{coin}/USDT"
            ohlcv = self._bb_checker.fetch_ohlcv(spot_sym, timeframe, 30)
            close = [c[4] for c in ohlcv]
            if len(close) < 20:
                return None
            sma = sum(close[-20:]) / 20
            variance = sum((c - sma) ** 2 for c in close[-20:]) / 20
            std = variance ** 0.5
            return sma - 2 * std
        except Exception as e:
            logger.warning(f"计算布林下轨失败 {symbol}({timeframe}): {e}")
            return None

    def _detect_position_mode(self):
        """重新检测持仓模式，每次下单前调用"""
        try:
            resp = self.exchange.fapiPrivateGetPositionSideDual()
            if resp.get("dualSidePosition") is True:
                self.one_way_mode = False
            else:
                self.one_way_mode = True
        except Exception:
            pass  # 保持原有模式

    def place_limit_order(self, coin: str, symbol: str, price: float, quantity: float,
                          tp_price: float, sl_price: float) -> Optional[str]:
        """挂限价买入单"""
        try:
            self._detect_position_mode()
            price_prec = self.exchange.price_to_precision(symbol, price)
            side_params = {} if self.one_way_mode else {"positionSide": "LONG"}
            order = self.exchange.create_order(symbol, "limit", "buy", quantity, price_prec, side_params)
            order_id = order.get("id", "")
            logger.info(f"✅ 挂单成功 {coin} {symbol}: 买入 {quantity} @ {price_prec} (TP={tp_price}, SL={sl_price})")

            self.state["orders"][coin] = {
                "order_id": order_id, "coin": coin, "symbol": symbol,
                "side": "buy", "price": float(price_prec), "quantity": quantity,
                "tp_price": float(tp_price), "sl_price": float(sl_price),
                "placed_at": time.time(), "status": "open",
            }
            self._save_state()
            return order_id
        except Exception as e:
            logger.error(f"挂单失败 {coin} {symbol}: {e}")
            return None

    def check_order_status(self, coin: str, order_info: dict) -> str:
        try:
            order = self.exchange.fetch_order(order_info["order_id"], order_info["symbol"])
            status = order.get("status", "open")
            filled_qty = float(order.get("filled", 0) or 0)

            if status == "closed":
                avg_price = float(order.get("average", 0) or order.get("price", 0) or 0)
                logger.info(f"🎯 订单已成交 {coin}: {filled_qty} @ {avg_price}")
                self.state["positions"][coin] = {
                    "coin": coin, "symbol": order_info["symbol"],
                    "entry_price": avg_price,
                    "quantity": filled_qty,
                    "tp_price": order_info["tp_price"],
                    "sl_price": order_info["sl_price"],
                    "order_id": order_info["order_id"],
                    "filled_at": time.time(),
                }
                self.state["orders"].pop(coin, None)
                self._place_tp_sl(coin, self.state["positions"][coin])
                self._save_state()
                return "closed"
            elif status == "open":
                if filled_qty > 0.000001:
                    # 部分成交：记录持仓，撤消剩余部分
                    avg_price = float(order.get("average", 0) or order_info["price"])
                    logger.info(f"⚠️ 部分成交 {coin}: 已填{filled_qty} @ {avg_price}，撤销剩余")
                    try:
                        self.exchange.cancel_order(order_info["order_id"], order_info["symbol"])
                    except Exception:
                        pass
                    self.state["positions"][coin] = {
                        "coin": coin, "symbol": order_info["symbol"],
                        "entry_price": avg_price, "quantity": filled_qty,
                        "tp_price": order_info["tp_price"],
                        "sl_price": order_info["sl_price"],
                        "order_id": order_info["order_id"],
                        "filled_at": time.time(),
                    }
                    self.state["orders"].pop(coin, None)
                    self._place_tp_sl(coin, self.state["positions"][coin])
                    self._save_state()
                    return "partial_filled"
                return "open"
            else:
                logger.info(f"订单状态={status} {coin}: {order_info['order_id']}")
                self.state["orders"].pop(coin, None)
                self._save_state()
                return status
        except Exception as e:
            logger.warning(f"查询订单状态失败 {coin}: {e}")
            return "unknown"

    def _place_tp_sl(self, coin: str, pos: dict):
        """成交后挂止盈止损（单边模式不带 reduceOnly，对冲模式带）"""
        symbol = pos["symbol"]
        qty = pos["quantity"]
        tp = float(pos["tp_price"]) if pos["tp_price"] else 0
        sl = float(pos["sl_price"]) if pos["sl_price"] else 0

        # 对冲模式需要 positionSide，单边模式不需要
        if self.one_way_mode:
            tp_params = {}
        else:
            tp_params = {"positionSide": "LONG"}

        try:
            self.exchange.cancel_all_orders(symbol)
        except Exception:
            pass

        if tp > 0:
            try:
                tp_price = self.exchange.price_to_precision(symbol, tp)
                tp_order = self.exchange.create_order(
                    symbol, "TAKE_PROFIT_MARKET", "sell", qty, None,
                    {"stopPrice": tp_price, **tp_params},
                )
                logger.info(f"📈 止盈单已挂 {coin}: 卖出 {qty} @ {tp_price}")
                pos["tp_order_id"] = tp_order.get("id", "")
                pos.pop("_tp_failed", None)
            except Exception as e:
                logger.warning(f"挂止盈单失败 {coin}: {e}")
                pos["_tp_failed"] = True

        if sl > 0:
            try:
                sl_price = self.exchange.price_to_precision(symbol, sl)
                sl_order = self.exchange.create_order(
                    symbol, "STOP_MARKET", "sell", qty, None,
                    {"stopPrice": sl_price, **tp_params},
                )
                logger.info(f"📉 止损单已挂 {coin}: 卖出 {qty} @ {sl_price}")
                pos["sl_order_id"] = sl_order.get("id", "")
                pos.pop("_sl_failed", None)
            except Exception as e:
                logger.warning(f"挂止损单失败 {coin}: {e}")
                pos["_sl_failed"] = True

        self._save_state()

    def _close_position_market(self, coin: str, pos: dict, reason: str = ""):
        """市价平仓并记录"""
        try:
            self.exchange.create_market_sell_order(pos["symbol"], pos["quantity"],
                                                   {} if self.one_way_mode else {"positionSide": "LONG"})
            logger.info(f"💹 市价平仓 {coin}: {pos['symbol']} {pos['quantity']} {reason}")

            # 等成交确认
            time.sleep(1)
            # 记录平仓
            close_price = pos.get("current_price", 0) or 0
            entry_price = pos.get("entry_price", 0) or 0
            qty = pos.get("quantity", 0) or 0
            pnl = round((close_price - entry_price) * qty, 2) if entry_price and qty else 0
            pnl_pct = round((close_price - entry_price) / entry_price * 100, 2) if entry_price > 0 else 0
            rec = {
                "coin": coin, "symbol": pos["symbol"], "direction": "LONG",
                "entry_price": entry_price, "quantity": qty,
                "filled_at": pos.get("filled_at", 0),
                "filled_at_str": datetime.fromtimestamp(pos.get("filled_at", 0)).strftime("%m-%d %H:%M") if pos.get("filled_at") else "-",
                "close_time": time.time(),
                "close_time_str": datetime.now().strftime("%m-%d %H:%M"),
                "close_price": close_price, "pnl": pnl, "pnl_pct": pnl_pct,
                "strategy": "Binance AI策略", "reason": reason,
                "order_id": pos.get("order_id", ""),
            }
            self.state.setdefault("closed_positions", [])
            self.state["closed_positions"].append(rec)
            if len(self.state["closed_positions"]) > 200:
                self.state["closed_positions"] = self.state["closed_positions"][-200:]
            self.state["positions"].pop(coin, None)
            self._save_state()
            logger.info(f"✅ {coin} 已平仓: PnL={pnl:+.2f} ({pnl_pct:+.2f}%) {reason}")
        except Exception as e:
            logger.error(f"❌ 市价平仓失败 {coin}: {e}")

    def check_position_closed(self, coin: str, pos: dict) -> bool:
        try:
            all_positions = self.exchange.fetch_positions([pos["symbol"]])
            for p in all_positions:
                amt = float(p.get("info", {}).get("positionAmt", 0))
                if abs(amt) > 0.000001:
                    return False
            # 撤销普通挂单 + TP/SL 条件单
            try:
                self.exchange.cancel_all_orders(pos["symbol"])
            except Exception:
                pass
            try:
                symbol_raw = pos["symbol"].replace("/", "").replace(":USDT", "USDT").replace(":USDC", "USDC")
                algo_list = self.exchange.fapiPrivateGetOpenAlgoOrders()
                for a in algo_list:
                    if a.get("symbol") == symbol_raw:
                        aid = a.get("algoId", "")
                        if aid:
                            self.exchange.fapiPrivateDeleteAlgoOrder({"symbol": symbol_raw, "algoId": aid})
                logger.info(f"🧹 {coin} 已撤销所有残留挂单及条件单")
            except Exception as e:
                logger.warning(f"撤销条件单失败 {coin}: {e}")
            # 跳过 bot 未主动管理的持仓
            if pos.get("_synced") and not pos.get("tp_price") and not pos.get("sl_price"):
                logger.info(f"⏭ {coin} 为同步旧单，跳过已平仓记录")
                self.state["positions"].pop(coin, None)
                self._save_state()
                return True

            close_time = time.time()
            close_price = pos.get("current_price", 0) or 0
            entry_price = pos.get("entry_price", 0) or 0
            qty = pos.get("quantity", 0) or 0
            pnl = round((close_price - entry_price) * qty, 2) if entry_price and qty else 0
            pnl_pct = round((close_price - entry_price) / entry_price * 100, 2) if entry_price > 0 else 0

            closed_record = {
                "coin": coin, "symbol": pos["symbol"], "direction": "LONG",
                "entry_price": entry_price, "quantity": qty,
                "filled_at": pos.get("filled_at", 0),
                "filled_at_str": datetime.fromtimestamp(pos.get("filled_at", 0)).strftime("%m-%d %H:%M") if pos.get("filled_at") else "-",
                "close_time": close_time,
                "close_time_str": datetime.fromtimestamp(close_time).strftime("%m-%d %H:%M"),
                "close_price": close_price, "pnl": pnl, "pnl_pct": pnl_pct,
                "strategy": "Binance AI策略",
                "order_id": pos.get("order_id", ""),
            }
            if "closed_positions" not in self.state:
                self.state["closed_positions"] = []
            self.state["closed_positions"].append(closed_record)
            if len(self.state["closed_positions"]) > 200:
                self.state["closed_positions"] = self.state["closed_positions"][-200:]

            logger.info(f"✅ 持仓已平 {coin}: {pos['symbol']} 入场={entry_price} 平仓={close_price} PnL={pnl:+.2f}")
            self.state["positions"].pop(coin, None)
            today = datetime.now().strftime("%Y-%m-%d")
            if today in self.state.get("filled_today", {}) and coin in self.state["filled_today"][today]:
                del self.state["filled_today"][today][coin]
                logger.info(f"🔄 {coin} 已从今日已成交列表中移除，可再次入场")
            self._save_state()
            return True
        except Exception as e:
            logger.warning(f"检查持仓状态失败 {coin}: {e}")
            return False

    def sync_positions_from_exchange(self):
        try:
            positions = self.exchange.fetch_positions()
            for p in positions:
                amt = float(p.get("info", {}).get("positionAmt", 0))
                if amt <= 0.000001:
                    continue
                symbol = p.get("symbol", "")
                if not symbol or not symbol.endswith(":USDT"):
                    continue
                coin = symbol.split("/")[0]
                if coin in self.state["positions"]:
                    continue
                entry = float(p.get("entryPrice", 0))
                logger.info(f"🔄 恢复持仓 {coin}: {symbol} {amt} @ {entry}")
                self.state["positions"][coin] = {
                    "coin": coin, "symbol": symbol,
                    "entry_price": entry, "quantity": abs(amt),
                    "tp_price": 0, "sl_price": 0, "filled_at": time.time(),
                    "_synced": True,
                }
            self._save_state()
            logger.info(f"交易所持仓同步完成，当前 {len(self.state['positions'])} 个持仓")
        except Exception as e:
            logger.warning(f"同步持仓失败: {e}")

    def update_positions_pnl(self):
        """从交易所实际持仓数据更新盈亏（使用 markPrice，更准确）"""
        try:
            exchange_positions = {p.get("symbol", ""): p for p in self.exchange.fetch_positions()}
        except Exception:
            exchange_positions = {}
        for coin, pos in self.state.get("positions", {}).items():
            try:
                ep = exchange_positions.get(pos["symbol"])
                if ep:
                    info = ep.get("info", {})
                    mark = float(info.get("markPrice", 0))
                    upnl = float(info.get("unRealizedProfit", 0))
                    pos["current_price"] = mark
                    pos["unrealized_pnl"] = round(upnl, 2)
                    entry = pos["entry_price"]
                    pos["unrealized_pnl_pct"] = round(upnl / (entry * pos["quantity"]) * 100, 2) if entry > 0 else 0
                else:
                    ticker = self.exchange.fetch_ticker(pos["symbol"])
                    cur_price = ticker.get("last", 0)
                    if cur_price and cur_price > 0:
                        entry = pos["entry_price"]
                        qty = pos["quantity"]
                        pos["current_price"] = cur_price
                        pos["unrealized_pnl"] = round((cur_price - entry) * qty, 2)
                        pos["unrealized_pnl_pct"] = round((cur_price - entry) / entry * 100, 2) if entry > 0 else 0
            except Exception as e:
                logger.warning(f"获取 {coin} 盈亏失败: {e}")
        self._save_state()

    def positions_count(self) -> int:
        """当前持仓数"""
        return len(self.state.get("positions", {}))

    def cancel_excess_limit_orders(self):
        """已有 MAX_POSITIONS 个已成交持仓时，撤销所有未成交限价挂单
        撤销前检查部分成交，避免丢失仓位"""
        if len(self.state.get("positions", {})) < MAX_POSITIONS:
            return
        orders = self.state.get("orders", {})
        if not orders:
            return
        logger.info(f"⏸ 持仓已达上限 {MAX_POSITIONS}，撤销 {len(orders)} 个未成交挂单")
        for coin, info in list(orders.items()):
            if info.get("side") != "buy":
                continue
            # 撤单前检查是否有部分成交
            try:
                order = self.exchange.fetch_order(info["order_id"], info["symbol"])
                filled = float(order.get("filled", 0) or 0)
                if filled > 0.000001:
                    avg_price = float(order.get("average", 0) or info["price"])
                    logger.info(f"⚠️ 撤单发现部分成交 {coin}: 已填{filled} @ {avg_price}")
                    self.state["positions"][coin] = {
                        "coin": coin, "symbol": info["symbol"],
                        "entry_price": avg_price, "quantity": filled,
                        "tp_price": info["tp_price"], "sl_price": info["sl_price"],
                        "order_id": info["order_id"], "filled_at": time.time(),
                    }
                    self._place_tp_sl(coin, self.state["positions"][coin])
            except Exception as e:
                logger.warning(f"撤单前检查部分成交失败 {coin}: {e}")
            # 撤单
            try:
                self.exchange.cancel_order(info["order_id"], info["symbol"])
            except Exception as e:
                logger.warning(f"撤单失败 {coin}: {e}")
            self.state["orders"].pop(coin, None)
        self._save_state()

    # ── 孤儿条件单清理 ──────────────────────────────────────

    def _cleanup_orphan_tpsl(self):
        """扫描交易所所有条件单，取消那些对应持仓已不存在的孤儿单"""
        try:
            # 获取当前有持仓的币种（取 coin 名做匹配）
            current_coins = set()
            for p in self.exchange.fetch_positions():
                amt = float(p.get("info", {}).get("positionAmt", 0))
                if abs(amt) > 0.000001:
                    coin = p["symbol"].split("/")[0]
                    current_coins.add(coin)

            algo_list = self.exchange.fapiPrivateGetOpenAlgoOrders()
            for a in algo_list:
                sym = a.get("symbol", "")  # e.g. "TONUSDT"
                coin = sym.replace("USDT", "").replace("USDC", "")
                if coin not in current_coins:
                    aid = a.get("algoId", "")
                    if aid:
                        self.exchange.fapiPrivateDeleteAlgoOrder({"symbol": sym, "algoId": aid})
                        logger.info(f"🧹 孤儿条件单已清理: {sym} {a.get('orderType','')} @ {a.get('triggerPrice','?')} algoId={aid}")
        except Exception as e:
            logger.warning(f"清理孤儿条件单异常: {e}")

    # ── 主循环 ──

    def run_once(self):
        try:
            self._detect_position_mode()
            self._cleanup_orphan_tpsl()  # 每轮都检查孤儿条件单
            self.cancel_expired_orders()

            # 超过持仓上限则撤销所有限价挂单
            self.cancel_excess_limit_orders()

            # 定期同步交易所持仓（每10轮 ≈ 10分钟），修复幽灵持仓
            self._cycle_counter = getattr(self, '_cycle_counter', 0) + 1
            if self._cycle_counter % 10 == 1:
                self.sync_positions_from_exchange()

            for coin, info in list(self.state["orders"].items()):
                self.check_order_status(coin, info)

            for coin, pos in list(self.state["positions"].items()):
                self.check_position_closed(coin, pos)

            # 补挂缺漏的止盈止损
            for coin, pos in list(self.state["positions"].items()):
                # 为从交易所同步回来的老持仓补上 TP/SL 价格
                if pos.get("_synced") and not pos.get("tp_price") and not pos.get("sl_price"):
                    pos["tp_price"] = pos["entry_price"] * (1 + TP_PCT)
                    pos["sl_price"] = pos["entry_price"] * (1 - SL_PCT)
                    logger.info(f"🔄 {coin} 同步持仓，补算 TP={pos['tp_price']:.4f} SL={pos['sl_price']:.4f}")

                has_tp = pos.get("tp_order_id") and pos["tp_order_id"] not in ("", "-")
                has_sl = pos.get("sl_order_id") and pos["sl_order_id"] not in ("", "-")
                need_tp = not has_tp and pos.get("tp_price", 0) > 0
                need_sl = not has_sl and pos.get("sl_price", 0) > 0
                if need_tp or need_sl:
                    logger.info(f"🔄 补挂 {coin} TP/SL")
                    self._place_tp_sl(coin, pos)
                    # 如果 TP 补挂失败且当前价已超过止盈价，直接市价平仓
                    tp_still_missing = pos.get("tp_order_id") in ("", None, "-") or not pos.get("tp_order_id")
                    cur_price = pos.get("current_price", 0) or 0
                    tp_price = pos.get("tp_price", 0) or 0
                    if tp_still_missing and tp_price > 0 and cur_price >= tp_price:
                        logger.info(f"🚀 {coin} 当前价{cur_price}已超过止盈价{tp_price}，市价止盈")
                        self._close_position_market(coin, pos, "止盈(超价)")

            self.update_positions_pnl()

            # [NEW] 持仓>2小时且盈利≥1%，主动止盈
            now_ts = time.time()
            for coin, pos in list(self.state["positions"].items()):
                filled = pos.get("filled_at", 0)
                pnl_pct = pos.get("unrealized_pnl_pct", 0) or 0
                if filled and (now_ts - filled) > 7200 and pnl_pct >= 1.0:
                    logger.info(f"⏰ {coin} 持仓>2h(+{(now_ts-filled)/3600:.1f}h)且盈利{pnl_pct:.2f}%，主动止盈")
                    self._close_position_market(coin, pos, "持仓>2h止盈")

            if self.is_max_positions_reached():
                return

            market_bearish = self._check_market_trend()
            if market_bearish:
                ti = getattr(self, '_trend_info', {})
                logger.info(f"🔴 评分{ti.get('btc_score','?')}<50 大盘空头，暂停开新多单")
                for coin, info in list(self.state.get("orders", {}).items()):
                    if info.get("side") == "buy":
                        try:
                            self.exchange.cancel_order(info["order_id"], info["symbol"])
                            logger.info(f"❌ 空头行情撤单 {coin}")
                        except Exception:
                            pass
                        self.state["orders"].pop(coin, None)
                self._save_state()
                return
            else:
                ti = getattr(self, '_trend_info', {})
                logger.info(f"🟢 评分{ti.get('btc_score','?')}>=50 大盘偏多，正常开单")

            signals = [] if market_bearish else self.fetch_signals()

            for row in signals:
                raw_symbol = row["symbol"]
                coin = self._parse_symbol(raw_symbol)
                score = row["profit_score"]

                # Binance: callback_points 格式为 'high-low'
                entry_low, entry_high = self._parse_entry_price(row["callback_points"], row["entry_suggestion"], low_first=False)
                entry_price, label = self.get_entry_price(score, entry_low, entry_high)

                if not entry_price or entry_price <= 0:
                    logger.info(f"⏭ {coin}: 无法解析入场价格，跳过")
                    continue
                if coin in self.state["orders"]:
                    continue
                if coin in self.state["positions"]:
                    continue
                if self.is_today_filled(coin):
                    logger.info(f"⏭ {coin} 今天已成交过，跳过")
                    continue

                symbol = self._get_usdt_symbol(coin)
                if not symbol:
                    logger.info(f"⏭ {coin} 无 USDT 合约，跳过")
                    continue

                qty = self._calc_quantity(symbol, entry_price)
                if not qty or qty <= 0:
                    logger.warning(f"⏭ {coin} 计算数量失败，跳过")
                    continue

                tp_price = entry_price * (1 + TP_PCT)
                sl_price = entry_price * (1 - SL_PCT)

                logger.info(f"🆕 发现机会 {coin}: score={score} {label}={entry_price} TP={tp_price:.4f} SL={sl_price:.4f}")
                self.place_limit_order(coin, symbol, entry_price, qty, tp_price, sl_price)

                if self.is_max_positions_reached():
                    logger.info(f"⏸ 已达最大持仓上限 {MAX_POSITIONS}，停止本轮挂单")
                    break

        except Exception as e:
            logger.error(f"运行异常: {e}", exc_info=True)

    def run(self):
        logger.info("🤖 Binance AI 策略启动")
        logger.info(f"   参数: 每单={ORDER_AMOUNT} USDT, 最低评分={MIN_SCORE}, 挂单过期={ORDER_EXPIRE_HOURS}h, TP={TP_PCT*100}% SL={SL_PCT*100}%")
        logger.info(f"   检查间隔: {CHECK_INTERVAL}s, 状态文件: {self.data_file}")

        self.sync_positions_from_exchange()

        while True:
            self.run_once()
            time.sleep(CHECK_INTERVAL)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    bot = BinanceAiBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("🛑 策略已停止")


if __name__ == "__main__":
    main()
