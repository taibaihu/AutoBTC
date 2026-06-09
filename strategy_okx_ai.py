#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OKX AI策略 — 基于 okx_top_value 评分数据，OKX USDT 合约挂单交易"""
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import ccxt

from config import OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, get_proxy_config
from ai_bot_base import AiBotBase, TP_PCT, SL_PCT, MAX_POSITIONS, MIN_SCORE, CHECK_INTERVAL, ORDER_EXPIRE_HOURS, SYMBOL_SUFFIX

logger = logging.getLogger(__name__)

ORDER_AMOUNT = 100  # OKX 每单 100 USDT

LEVERAGE = 20  # OKX 杠杆倍数


class OkxAiBot(AiBotBase):
    """OKX AI 策略：从 okx_top_value 表选出优质币种，挂 USDT 限价单入场"""

    STATE_DEFAULTS = {"orders": {}, "positions": {}, "filled_today": {}, "closed_positions": []}

    def __init__(self, data_file: str = None):
        proxies = get_proxy_config()
        self.exchange = ccxt.okx({
            "proxies": proxies,
            "apiKey": OKX_API_KEY,
            "secret": OKX_SECRET_KEY,
            "password": OKX_PASSPHRASE,
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })
        self.exchange.load_markets()

        # 状态文件
        if data_file is None:
            data_file = str(Path(__file__).parent / "okx_ai_state.json")
        self.data_file = data_file
        self.state = self._load_state()

        # USDT 合约 symbol 集合（缓存）
        self.usdt_symbols = set()
        for s in self.exchange.symbols:
            if s.endswith("/USDT:USDT"):
                self.usdt_symbols.add(s)

        logger.info(f"OkxAiBot 初始化完成，支持 {len(self.usdt_symbols)} 个 USDT 合约")

        # 启动时设置所有已有持仓的杠杆
        self._set_all_leverage()

    # ── 杠杆 & 保证金 ──

    def _set_all_leverage(self):
        """遍历所有持仓设置杠杆和逐仓模式"""
        try:
            positions = self.exchange.fetch_positions()
            set_count = 0
            for p in positions:
                symbol = p.get("symbol", "")
                if symbol and symbol.endswith("/USDT:USDT"):
                    try:
                        self.exchange.set_leverage(LEVERAGE, symbol)
                        set_count += 1
                    except Exception:
                        pass
                    try:
                        self.exchange.set_margin_mode("isolated", symbol)
                    except Exception:
                        pass
            if set_count:
                logger.info(f"已设置 {set_count} 个合约杠杆为 {LEVERAGE}x (逐仓)")
        except Exception as e:
            logger.warning(f"设置杠杆/逐仓失败: {e}")

    def _set_margin_mode(self, symbol: str):
        """设置逐仓模式（isolated）"""
        try:
            self.exchange.set_margin_mode("isolated", symbol)
        except Exception:
            pass

    # ── 数据库查询 ──

    def fetch_signals(self) -> list[dict]:
        """查询符合条件的币种：profit_score >= MIN_SCORE"""
        try:
            conn = self._get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DATE_FORMAT(analysis_time, '%Y-%m-%d %H:%i') AS minute_time
                    FROM okx_top_value
                    GROUP BY minute_time
                    HAVING COUNT(*) >= 5
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
                    FROM okx_top_value t1
                    INNER JOIN (
                        SELECT symbol, MAX(analysis_time) AS max_time
                        FROM okx_top_value
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
        """获取币种对应的 USDT 合约 symbol"""
        symbol = f"{coin}{SYMBOL_SUFFIX}"
        if symbol in self.usdt_symbols:
            return symbol
        symbol2 = f"{coin.upper()}/USDT:USDT"
        if symbol2 in self.usdt_symbols:
            return symbol2
        return None

    def _calc_quantity(self, symbol: str, price: float) -> Optional[float]:
        """计算 ORDER_AMOUNT USDT 价值对应的合约张数（OKX 合约单位为张，面值通常=1 USDT）"""
        try:
            market = self.exchange.market(symbol)
            contract_size = float(market.get("contractSize", 1) or 1)
            raw_qty = ORDER_AMOUNT / (price * contract_size)
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

    def place_limit_order(self, coin: str, symbol: str, price: float, quantity: float,
                          tp_price: float, sl_price: float) -> Optional[str]:
        """挂限价买入开多单（OKX 需要 posSide 参数）"""
        try:
            price_prec = self.exchange.price_to_precision(symbol, price)

            try:
                self.exchange.set_leverage(LEVERAGE, symbol)
            except Exception:
                pass
            self._set_margin_mode(symbol)

            order = self.exchange.create_order(
                symbol, "limit", "buy", quantity, price_prec,
                {"posSide": "long"},
            )
            order_id = order.get("id", "")
            logger.info(f"✅ 挂单成功 {coin} {symbol}: 买入 {quantity} 张 @ {price_prec} (TP={tp_price}, SL={sl_price})")

            # quantity存实际币数量（OKX入参是张数，需乘以contractSize）
            contract_size = self.exchange.market(symbol).get('contractSize', 1)
            qty_coin = round(quantity * float(contract_size), 6) if contract_size else quantity

            self.state["orders"][coin] = {
                "order_id": order_id, "coin": coin, "symbol": symbol,
                "side": "buy", "price": float(price_prec),
                "quantity": qty_coin,  # 存币数量（如2.2 ZEC），不存张数
                "quantity_contracts": quantity,  # 原始合约张数
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
            if status == "closed":
                filled_qty = float(order.get("filled", 0) or 0)
                avg_price = float(order.get("average", 0) or order.get("price", 0) or 0)
                logger.info(f"🎯 订单已成交 {coin}: {filled_qty} 张 @ {avg_price}")
                self.state["positions"][coin] = {
                    "coin": coin, "symbol": order_info["symbol"],
                    "entry_price": avg_price,
                    "quantity": order_info["quantity"],  # 币数量
                    "quantity_coin": order_info["quantity"],
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
        """成交后挂止盈止损 — 使用 OKX order-algo 接口"""
        symbol = pos["symbol"]
        qty = pos["quantity"]
        tp = float(pos["tp_price"]) if pos["tp_price"] else 0
        sl = float(pos["sl_price"]) if pos["sl_price"] else 0

        try:
            market = self.exchange.market(symbol)
            inst_id = market["id"]
            td_mode = "cross"
            try:
                pos_data = self.exchange.fetch_positions([symbol])
                for p in pos_data:
                    if float(p.get("contracts", 0) or 0) > 0:
                        pm = p.get("marginMode", "cross")
                        td_mode = "isolated" if pm == "isolated" else "cross"
                        logger.info(f"⚙ {coin} 保证金模式: {td_mode}")
                        break
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"获取市场信息失败 {symbol}: {e}")
            return

        def place_algo(price, tp_or_sl: str):
            try:
                px = self.exchange.price_to_precision(symbol, price)
                params = {
                    "instId": inst_id, "tdMode": td_mode,
                    "side": "sell", "sz": str(qty),
                    "ordType": "conditional", "posSide": "long",
                }
                if tp_or_sl == "tp":
                    params["tpTriggerPx"] = str(px)
                    params["tpOrdPx"] = "-1"
                else:
                    params["slTriggerPx"] = str(px)
                    params["slOrdPx"] = "-1"
                algo = self.exchange.privatePostTradeOrderAlgo(params)
                algo_id = algo.get("data", [{}])[0].get("algoId", "")
                label = "止盈" if tp_or_sl == "tp" else "止损"
                logger.info(f"📈 {label}单已挂 {coin}: 卖出 {qty} 张 @ {px}")
                if tp_or_sl == "tp":
                    pos["tp_order_id"] = algo_id
                else:
                    pos["sl_order_id"] = algo_id
            except Exception as e:
                logger.warning(f"挂{'止盈' if tp_or_sl == 'tp' else '止损'}单失败 {coin}: {e}")
                if tp_or_sl == "tp":
                    pos["_tp_failed"] = True
                else:
                    pos["_sl_failed"] = True

        cur_price = 0
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            cur_price = float(ticker.get("last", 0))
        except Exception:
            pass

        if tp > 0:
            if cur_price > 0 and tp <= cur_price:
                logger.warning(f"⏭ {coin} 止盈触发价 {tp} 低于当前市价 {cur_price}，跳过")
                pos["_tp_failed"] = True
            else:
                place_algo(tp, "tp")

        if sl > 0:
            if cur_price > 0 and sl >= cur_price:
                logger.warning(f"⏭ {coin} 止损触发价 {sl} 高于等于当前市价 {cur_price}，跳过")
                pos["_sl_failed"] = True
            else:
                place_algo(sl, "sl")

        self._save_state()

    def _close_position_market(self, coin: str, pos: dict, reason: str = ""):
        """市价平仓并记录（OKX 需 posSide 参数）"""
        try:
            self.exchange.create_market_sell_order(pos["symbol"], pos["quantity"],
                                                   {"posSide": "long", "reduceOnly": True})
            logger.info(f"💹 市价平仓 {coin}: {pos['symbol']} {pos['quantity']} {reason}")
            time.sleep(1)
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
                "close_time": time.time(), "close_time_str": datetime.now().strftime("%m-%d %H:%M"),
                "close_price": close_price, "pnl": pnl, "pnl_pct": pnl_pct,
                "strategy": "OKX AI策略", "reason": reason,
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
                amt = float(p.get("contracts", 0) or 0)
                if abs(amt) > 0.000001:
                    return False
            try:
                self.exchange.cancel_all_orders(pos["symbol"])
                logger.info(f"🧹 {coin} 已撤销所有残留挂单")
            except Exception:
                pass

            close_time = time.time()
            close_price = pos.get("current_price", 0) or 0
            entry_price = pos.get("entry_price", 0) or 0
            qty_coin = pos.get("quantity_coin", round(
                pos.get("quantity", 0) * float(self.exchange.market(pos["symbol"]).get("contractSize", 1) or 1), 6))
            pnl = round((close_price - entry_price) * qty_coin, 2) if entry_price and qty_coin else 0
            qty = qty_coin
            pnl_pct = round((close_price - entry_price) / entry_price * 100, 2) if entry_price > 0 else 0

            closed_record = {
                "coin": coin, "symbol": pos["symbol"], "direction": "LONG",
                "entry_price": entry_price, "quantity": qty, "quantity_coin": qty_coin,
                "filled_at": pos.get("filled_at", 0),
                "filled_at_str": datetime.fromtimestamp(pos.get("filled_at", 0)).strftime("%m-%d %H:%M") if pos.get("filled_at") else "-",
                "close_time": close_time,
                "close_time_str": datetime.fromtimestamp(close_time).strftime("%m-%d %H:%M"),
                "close_price": close_price, "pnl": pnl, "pnl_pct": pnl_pct,
                "strategy": "OKX AI策略",
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
                amt = float(p.get("contracts", 0) or 0)
                if abs(amt) < 0.000001:
                    continue
                symbol = p.get("symbol", "")
                if not symbol or not symbol.endswith(":USDT"):
                    continue
                coin = symbol.split("/")[0]
                if coin in self.state["positions"]:
                    continue
                entry = float(p.get("entryPrice", 0))
                logger.info(f"🔄 恢复持仓 {coin}: {symbol} {amt} 张 @ {entry}")
                self.state["positions"][coin] = {
                    "coin": coin, "symbol": symbol,
                    "entry_price": entry, "quantity": abs(amt),
                    "tp_price": 0, "sl_price": 0, "filled_at": time.time(),
                }
            self._save_state()
            logger.info(f"交易所持仓同步完成，当前 {len(self.state['positions'])} 个 USDT 持仓")
        except Exception as e:
            logger.warning(f"同步持仓失败: {e}")

    def update_positions_pnl(self):
        for coin, pos in self.state.get("positions", {}).items():
            try:
                ticker = self.exchange.fetch_ticker(pos["symbol"])
                cur_price = ticker.get("last", 0)
                if cur_price and cur_price > 0:
                    entry = pos["entry_price"]
                    qty_coin = pos.get("quantity_coin", pos["quantity"])
                    upnl = round((cur_price - entry) * qty_coin, 2)
                    upnl_pct = round((cur_price - entry) / entry * 100, 2) if entry > 0 else 0
                    pos["current_price"] = cur_price
                    pos["unrealized_pnl"] = upnl
                    pos["unrealized_pnl_pct"] = upnl_pct
            except Exception as e:
                logger.warning(f"获取 {coin} 市价失败: {e}")
        self._save_state()

    # ── 主循环 ──

    def run_once(self):
        try:
            self.cancel_expired_orders()

            for coin, info in list(self.state["orders"].items()):
                self.check_order_status(coin, info)

            for coin, pos in list(self.state["positions"].items()):
                self.check_position_closed(coin, pos)

            # 补挂缺漏的止盈止损
            for coin, pos in list(self.state["positions"].items()):
                has_tp = pos.get("tp_order_id") and pos["tp_order_id"] not in ("", "-")
                has_sl = pos.get("sl_order_id") and pos["sl_order_id"] not in ("", "-")
                need_tp = not has_tp and pos.get("tp_price", 0) > 0 and not pos.get("_tp_failed")
                need_sl = not has_sl and pos.get("sl_price", 0) > 0 and not pos.get("_sl_failed")
                if need_tp or need_sl:
                    logger.info(f"🔄 补挂 {coin} TP/SL")
                    self._place_tp_sl(coin, pos)

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
                if self.is_max_positions_reached():
                    logger.info("⏸ 已达最大持仓上限，暂停挂单")
                    break

                raw_symbol = row["symbol"]
                coin = self._parse_symbol(raw_symbol)
                score = row["profit_score"]

                # OKX: callback_points 格式为 'low-high'
                entry_low, entry_high = self._parse_entry_price(row["callback_points"], row["entry_suggestion"], low_first=True)
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
        logger.info("🤖 OKX AI 策略启动")
        logger.info(f"   参数: 每单={ORDER_AMOUNT} USDT, 最低评分={MIN_SCORE}, 挂单过期={ORDER_EXPIRE_HOURS}h")
        logger.info(f"   TP={TP_PCT*100:.1f}% SL={SL_PCT*100:.1f}% 杠杆={LEVERAGE}x 最大持仓={MAX_POSITIONS}")
        logger.info(f"   检查间隔: {CHECK_INTERVAL}s, 状态文件: {self.data_file}")

        self.sync_positions_from_exchange()
        self._set_all_leverage()

        while True:
            self.run_once()
            time.sleep(CHECK_INTERVAL)


def main():
    import sys
    sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    bot = OkxAiBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("🛑 策略已停止")


if __name__ == "__main__":
    main()
