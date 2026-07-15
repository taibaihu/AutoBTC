#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BB-Ride 执行策略 — OKX 版
"""
import json, os, time, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# 加载 .env 中的 OKX 密钥
load_dotenv(Path(__file__).parent / ".env")

import ccxt

from config import OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE

logger = logging.getLogger("BB_Ride_OKX_Exe")

ORDER_AMOUNT = 200         # USDT
MAX_LONG_ORDERS = 3
MAX_SHORT_ORDERS = 2      # 最多同时2空单（含持仓，回测显示空单胜率低）
TP_PCT = 0.05
SL_PCT = 0.025
CLOSE_AFTER_HOURS = 2.5
CLOSE_AT_PROFIT_PCT = 0.8
CHECK_INTERVAL = 10
SIGNAL_WINDOW_HOURS = 6
BB_PERIOD = 14
BB_STD = 2
BB_TIMEFRAME = "5m"
BB_TOUCH_PCT = 1.0
MA_TIMEFRAME = "12h"
MA_PERIOD = 20
ENTRY_LIMIT_EXPIRE_SECONDS = 300
ENTRY_OFFSET = 0.003
MAX_CONSECUTIVE_LOSSES = 3
BLACKLIST_HOURS = 24
WINDOW_CANDLES = 15

# ===== 模拟模式 =====
# True = 只打日志不下单，False = 实盘交易
PAPER_TRADING = True  # 与OKX扫描器一致


class BbRideOkxStrategy:
    STATE_DEFAULTS = {
        "orders": {}, "positions": {}, "closed_positions": [],
        "processed_signals": {},
        "loss_streaks": {},
        "blacklist": {},
        "total_stats": {"trades": 0, "wins": 0, "pnl": 0.0},
    }

    def __init__(self):
        # 先用无认证方式加载公开市场数据
        self.exchange = ccxt.okx({
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })
        # public markets only
        self.exchange.load_markets()
        self.api_ready = False

        # 如果有API密钥，尝试加载认证能力
        if OKX_API_KEY and OKX_SECRET_KEY and OKX_PASSPHRASE:
            try:
                auth_ex = ccxt.okx({
                    "apiKey": OKX_API_KEY, "secret": OKX_SECRET_KEY,
                    "password": OKX_PASSPHRASE, "enableRateLimit": True,
                    "options": {"defaultType": "swap"},
                })
                # load_markets(reload=True) 跳过 fetch_currencies
                auth_ex.load_markets()
                # 验证 API key
                auth_ex.fetch_balance()
                self.exchange = auth_ex
                self.api_ready = True
                logger.info("OKX API 认证成功")
            except Exception as e:
                logger.warning(f"OKX API 认证失败（仅展示模式）: {e}")
        else:
            logger.warning("OKX API 密钥未配置（仅展示模式）")

        self.data_file = str(Path(__file__).parent / "bb_ride_okx_state.json")
        self.state = self._load_state()
        self._cleanup_counter = 0

        self.supported_symbols = {}
        for s in self.exchange.symbols:
            if s.endswith("/USDT:USDT"):
                self.supported_symbols[s.split("/")[0]] = s
        self.tradfi_blacklist = self._load_tradfi_blacklist()

    def _load_tradfi_blacklist(self) -> set:
        """从数据库 okx_swap_coins 表加载 TradFi 分类币种"""
        try:
            from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD
            import pymysql
            from pymysql.cursors import DictCursor
            conn = pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, database='ll_test', cursorclass=DictCursor, connect_timeout=5)
            cur = conn.cursor()
            cur.execute("SELECT coin FROM okx_swap_coins WHERE category = 'TradFi'")
            coins = {r['coin'] for r in cur.fetchall()}
            cur.close()
            conn.close()
            logger.info(f"加载 {len(coins)} 个 TradFi 黑名单品种")
            return coins
        except Exception as e:
            logger.warning(f"加载 TradFi 黑名单失败: {e}")
            return set()

    # ── 状态持久化 ──
    def _load_state(self) -> dict:
        try:
            if os.path.exists(self.data_file):
                d = json.load(open(self.data_file))
                for k, v in self.STATE_DEFAULTS.items():
                    d.setdefault(k, v)
                return d
        except Exception as e:
            logger.warning(f"加载状态文件失败: {e}")
        return dict(self.STATE_DEFAULTS)

    def _save_state(self):
        try:
            with open(self.data_file, "w") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.warning(f"保存状态文件失败: {e}")

    # ── 辅助 ──
    def _get_usdt_symbol(self, coin: str) -> Optional[str]:
        symbol = f"{coin}/USDT:USDT"
        if symbol in self.supported_symbols.values():
            return symbol
        if coin in self.supported_symbols:
            return self.supported_symbols[coin]
        return None

    def _calc_quantity(self, symbol: str, price: float) -> Optional[float]:
        """计算币数量，状态文件存币数，下单时转张数"""
        try:
            raw = ORDER_AMOUNT / price if price > 0 else 0
            raw = self.exchange.amount_to_precision(symbol, raw)
            return float(raw)
        except Exception as e:
            logger.warning(f"计算数量失败 {symbol}: {e}")
            return None

    def _coin_to_contracts(self, symbol: str, coin_qty: float) -> float:
        """币数 → OKX合约张数（向下取整，保证不超200U）"""
        try:
            market = self.exchange.market(symbol)
            cs = float(market.get("contractSize", 1) or 1)
            contracts = coin_qty / cs
            # 按交易所精度调整（向下取整到lot size的倍数）
            contracts = self.exchange.amount_to_precision(symbol, contracts)
            return float(contracts)
        except:
            return coin_qty

    def _get_price(self, symbol: str) -> Optional[float]:
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return float(ticker.get("last", 0))
        except Exception:
            return None

    def _calc_bb(self, symbol: str) -> tuple:
        try:
            candles = self.exchange.fetch_ohlcv(symbol, BB_TIMEFRAME, limit=BB_PERIOD + 10)
            closes = [c[4] for c in candles[-BB_PERIOD:]]
            if len(closes) < BB_PERIOD:
                return None, None, None, None, None
            sma = sum(closes) / len(closes)
            variance = sum((c - sma) ** 2 for c in closes) / len(closes)
            std = variance ** 0.5
            upper = sma + BB_STD * std
            lower = sma - BB_STD * std
            latest = candles[-1]
            return sma, upper, lower, latest[2], latest[3]
        except Exception as e:
            logger.warning(f"计算BB失败 {symbol}: {e}")
            return None, None, None, None, None

    def _calc_ma(self, symbol: str) -> float | None:
        try:
            candles = self.exchange.fetch_ohlcv(symbol, MA_TIMEFRAME, limit=MA_PERIOD + 5)
            closes = [c[4] for c in candles[-MA_PERIOD:]]
            if len(closes) < MA_PERIOD:
                return None
            return sum(closes) / len(closes)
        except Exception as e:
            logger.warning(f"计算{MA_TIMEFRAME}MA{MA_PERIOD}失败 {symbol}: {e}")
            return None

    def _get_td_mode(self, symbol: str) -> str:
        """检测持仓的保证金模式，默认全仓"""
        try:
            for p in self.exchange.fetch_positions([symbol]):
                if abs(float(p.get("contracts", 0) or 0)) > 0:
                    return p.get("marginMode", "cross") or "cross"
        except:
            pass
        return "cross"

    # ── 入场（限价单） ──
    def place_limit_order(self, coin: str, symbol: str, direction: str,
                          entry_price: float, quantity: float) -> Optional[str]:
        if not self.api_ready:
            logger.warning(f"⏭ {direction} {coin}: API未认证，跳过挂单")
            return None
        try:
            price_prec = self.exchange.price_to_precision(symbol, entry_price)
            td_mode = self._get_td_mode(symbol)

            if direction == "LONG":
                side = "buy"
                pos_side = "long"
                tp_price = entry_price * (1 + TP_PCT)
                sl_price = entry_price * (1 - SL_PCT)
            else:
                side = "sell"
                pos_side = "short"
                tp_price = entry_price * (1 - TP_PCT)
                sl_price = entry_price * (1 + SL_PCT)

            order = self.exchange.create_order(symbol, "limit", side, self._coin_to_contracts(symbol, quantity), price_prec, {
                "tdMode": td_mode, "posSide": pos_side,
            })
            order_id = str(order.get("id", ""))
            logger.info(f"✅ {direction} {coin}: limit {side} {quantity} @ {price_prec}")

            key = self._get_key(coin, direction)
            self.state["orders"][key] = {
                "order_id": order_id, "coin": coin, "symbol": symbol,
                "direction": direction, "side": side,
                "price": float(price_prec), "quantity": quantity,
                "tp_price": float(tp_price), "sl_price": float(sl_price),
                "placed_at": time.time(), "status": "open",
            }
            self._save_state()
            return order_id
        except Exception as e:
            logger.error(f"挂单失败 {direction} {coin}: {e}")
            return None

    def _get_key(self, coin: str, direction: str) -> str:
        return f"{direction}:{coin}"

    def _count_by_direction(self, bucket: str, direction: str) -> int:
        return sum(1 for k in self.state.get(bucket, {}) if k.startswith(f"{direction}:"))

    # ── OKX TP/SL ──
    def _place_tp_sl(self, coin: str, pos: dict):
        """OKX止盈止损通过条件单API，先撤旧单再挂新单"""
        symbol = pos["symbol"]
        qty = pos["quantity"]
        direction = pos["direction"]
        tp = float(pos.get("tp_price", 0) or 0)
        sl = float(pos.get("sl_price", 0) or 0)

        # 撤所有旧条件单
        try:
            self._cancel_all_algo(symbol)
        except:
            pass

        try:
            inst_id = self.exchange.market(symbol)["id"]
        except:
            logger.warning(f"获取instId失败 {symbol}")
            return

        td_mode = self._get_td_mode(symbol)
        pos_side = "long" if direction == "LONG" else "short"
        close_side = "sell" if direction == "LONG" else "buy"

        def place_algo(trigger_px, is_tp):
            try:
                params = {
                    "instId": inst_id, "tdMode": td_mode,
                    "side": close_side, "sz": str(self._coin_to_contracts(symbol, qty)),
                    "ordType": "conditional", "posSide": pos_side,
                }
                if is_tp:
                    params["tpTriggerPx"] = str(trigger_px)
                    params["tpOrdPx"] = "-1"
                else:
                    params["slTriggerPx"] = str(trigger_px)
                    params["slOrdPx"] = "-1"
                algo = self.exchange.privatePostTradeOrderAlgo(params)
                aid = algo.get("data", [{}])[0].get("algoId", "")
                logger.info(f"  {'TP' if is_tp else 'SL'} {direction} {coin}: {trigger_px} (id={aid})")
                return aid
            except Exception as e:
                logger.warning(f"  {'TP' if is_tp else 'SL'}失败 {direction} {coin}: {e}")
                return ""

        if tp > 0:
            tp_id = place_algo(self.exchange.price_to_precision(symbol, tp), True)
            if tp_id:
                pos["tp_order_id"] = tp_id
        if sl > 0:
            sl_id = place_algo(self.exchange.price_to_precision(symbol, sl), False)
            if sl_id:
                pos["sl_order_id"] = sl_id
        self._save_state()

    def _cancel_all_algo(self, symbol: str):
        """取消某个币的所有条件单"""
        try:
            result = self.exchange.privateGetTradeOrdersAlgoPending({
                "instType": "SWAP", "ordType": "conditional", "state": "live",
            })
            for a in result.get("data", []):
                try:
                    self.exchange.privatePostTradeCancelAlgos([{
                        "algoId": a["algoId"], "instId": a["instId"],
                    }])
                except:
                    pass
        except:
            pass

    def _cleanup_ghost_orders(self):
        """清理无持仓对应的幽灵条件单"""
        try:
            result = self.exchange.privateGetTradeOrdersAlgoPending({
                "instType": "SWAP", "ordType": "conditional", "state": "live",
            })
            if not result.get("data"):
                return
            pos_coins = set()
            for p in self.exchange.fetch_positions():
                if abs(float(p.get("contracts", 0) or 0)) > 0.000001:
                    pos_coins.add(p["symbol"].split("/")[0])
            for a in result.get("data", []):
                coin = a["instId"].split("-")[0]
                if coin not in pos_coins:
                    self.exchange.privatePostTradeCancelAlgos([{
                        "algoId": a["algoId"], "instId": a["instId"],
                    }])
                    logger.info(f"🧹 清理幽灵条件单 {coin}")
        except Exception as e:
            logger.warning(f"清理幽灵单失败: {e}")

    # ── 订单检查 ──
    def check_order_status(self, key: str, info: dict):
        try:
            order = self.exchange.fetch_order(info["order_id"], info["symbol"])
            status = order.get("status", "open")
            filled_qty = float(order.get("filled", 0) or 0)
            direction = info["direction"]
            coin = info["coin"]

            if status in ("closed", "filled"):
                avg_price = float(order.get("average", 0) or order.get("price", 0) or 0)
                logger.info(f"🎯 成交 {direction} {coin}: {filled_qty} @ {avg_price}")
                pos = {
                    "coin": coin, "symbol": info["symbol"], "direction": direction,
                    "entry_price": avg_price, "quantity": filled_qty,
                    "tp_price": info["tp_price"], "sl_price": info["sl_price"],
                    "order_id": info["order_id"], "filled_at": time.time(),
                }
                self.state["positions"][key] = pos
                self.state["orders"].pop(key, None)
                self._place_tp_sl(coin, pos)
                self._save_state()
                return

            if filled_qty > 0.000001:
                intent_qty = info.get("quantity", 0) or 0
                fill_ratio = filled_qty / intent_qty if intent_qty > 0 else 0
                # 成交不足50% → 全撤，不入场
                if fill_ratio < 0.5:
                    logger.info(f"⚠️ 部分成交 {direction} {coin}: {filled_qty}/{intent_qty}({fill_ratio*100:.0f}%) 不足50%，全撤")
                    try:
                        self.exchange.cancel_order(info["order_id"], info["symbol"])
                    except:
                        pass
                    self.state["orders"].pop(key, None)
                    self._save_state()
                    return
                avg_price = float(order.get("average", 0) or info["price"])
                logger.info(f"⚠️ 部分成交 {direction} {coin}: {filled_qty} @ {avg_price}")
                try:
                    self.exchange.cancel_order(info["order_id"], info["symbol"])
                except:
                    pass
                pos = {
                    "coin": coin, "symbol": info["symbol"], "direction": direction,
                    "entry_price": avg_price, "quantity": filled_qty,
                    "tp_price": info["tp_price"], "sl_price": info["sl_price"],
                    "order_id": info["order_id"], "filled_at": time.time(),
                }
                self.state["positions"][key] = pos
                self.state["orders"].pop(key, None)
                self._place_tp_sl(coin, pos)
                self._save_state()
                return

            if status not in ("open", "live", "partially_filled"):
                logger.info(f"订单状态={status} {direction} {coin}")
                self.state["orders"].pop(key, None)
                self._save_state()
        except Exception as e:
            logger.warning(f"查询订单状态失败 {info.get('coin','?')}: {e}")

    # ── 持仓检查 ──
    def check_position_closed(self, key: str, pos: dict) -> bool:
        try:
            for p in self.exchange.fetch_positions([pos["symbol"]]):
                if abs(float(p.get("contracts", 0) or 0)) > 0.000001:
                    return False

            # 清理条件单
            try:
                self._cancel_all_algo(pos["symbol"])
            except:
                pass

            direction = pos["direction"]
            entry_price = float(pos.get("entry_price", 0) or 0)
            qty = float(pos.get("quantity", 0) or 0)
            close_price = float(pos.get("current_price", 0) or 0)
            if close_price <= 0:
                try:
                    ticker = self.exchange.fetch_ticker(pos["symbol"])
                    close_price = float(ticker.get("last", 0) or 0)
                except:
                    pass

            pnl = round((close_price - entry_price) * qty * (1 if direction == "LONG" else -1), 2)
            pnl_pct = round((close_price - entry_price) / entry_price * 100 * (1 if direction == "LONG" else -1), 2) if entry_price else 0
            self._update_loss_streak(pos["coin"], pnl)

            rec = {
                "coin": pos["coin"], "symbol": pos["symbol"], "direction": direction,
                "entry_price": entry_price, "quantity": qty,
                "filled_at": pos.get("filled_at", 0),
                "close_time": time.time(),
                "close_price": close_price, "pnl": pnl, "pnl_pct": pnl_pct,
                "order_id": pos.get("order_id", ""),
            }
            self.state.setdefault("closed_positions", []).append(rec)
            if len(self.state["closed_positions"]) > 1000:
                self.state["closed_positions"] = self.state["closed_positions"][-1000:]
            self.state["positions"].pop(key, None)
            self._save_state()
            logger.info(f"✅ 已平仓 {direction} {pos['coin']}: PnL={pnl:+.2f} ({pnl_pct:+.2f}%)")
            return True
        except Exception as e:
            logger.warning(f"检查持仓状态失败 {pos.get('coin','?')}: {e}")
            return False

    def _update_loss_streak(self, coin: str, pnl: float):
        streaks = self.state.setdefault("loss_streaks", {})
        blacklist = self.state.setdefault("blacklist", {})
        now = time.time()
        if pnl > 0:
            streaks.pop(coin, None)
        else:
            s = streaks.setdefault(coin, {"count": 0, "last_time": 0})
            s["count"] += 1
            s["last_time"] = now
            if s["count"] >= MAX_CONSECUTIVE_LOSSES:
                unlock_at = now + BLACKLIST_HOURS * 3600
                blacklist[coin] = unlock_at
                logger.warning(f"⛔ {coin} 连亏{s['count']}次，屏蔽24h")
        stats = self.state.setdefault("total_stats", {"trades": 0, "wins": 0, "pnl": 0.0})
        stats["trades"] = stats.get("trades", 0) + 1
        if pnl > 0:
            stats["wins"] = stats.get("wins", 0) + 1
        stats["pnl"] = round(stats.get("pnl", 0.0) + pnl, 2)

    def _is_blacklisted(self, coin: str) -> bool:
        blacklist = self.state.get("blacklist", {})
        if coin in blacklist:
            if time.time() < blacklist[coin]:
                return True
            else:
                del blacklist[coin]
        return False

    # ── 超时止盈 ──

    def close_profitable_positions(self):
        now = time.time()
        for key, pos in list(self.state.get("positions", {}).items()):
            filled_at = float(pos.get("filled_at", 0))
            if filled_at <= 0:
                continue
            elapsed_h = (now - filled_at) / 3600
            if elapsed_h < CLOSE_AFTER_HOURS:
                continue
            upnl_pct = float(pos.get("unrealized_pnl_pct", 0))
            if upnl_pct <= CLOSE_AT_PROFIT_PCT:
                continue

            coin = pos["coin"]
            symbol = pos["symbol"]
            direction = pos["direction"]
            qty = pos["quantity"]
            logger.info(f"⏰ 超时止盈 {direction} {coin}: 已持{elapsed_h:.1f}h")

            try:
                td_mode = self._get_td_mode(symbol)
                pos_side = "long" if direction == "LONG" else "short"
                close_side = "sell" if direction == "LONG" else "buy"
                self.exchange.create_order(symbol, "market", close_side, self._coin_to_contracts(symbol, qty), None, {
                    "tdMode": td_mode, "posSide": pos_side,
                    "reduceOnly": True,
                })
                try:
                    self._cancel_all_algo(symbol)
                except:
                    pass

                entry_price = float(pos.get("entry_price", 0) or 0)
                close_price = float(pos.get("current_price", 0) or 0)
                pnl = round((close_price - entry_price) * qty * (1 if direction == "LONG" else -1), 2)
                pnl_pct = round(upnl_pct, 2)
                self._update_loss_streak(coin, pnl)
                rec = {
                    "coin": coin, "symbol": symbol, "direction": direction,
                    "entry_price": entry_price, "quantity": qty,
                    "filled_at": filled_at, "close_time": time.time(),
                    "close_price": close_price, "pnl": pnl, "pnl_pct": pnl_pct,
                    "order_id": pos.get("order_id", ""),
                }
                self.state.setdefault("closed_positions", []).append(rec)
                if len(self.state["closed_positions"]) > 1000:
                    self.state["closed_positions"] = self.state["closed_positions"][-1000:]
                self.state["positions"].pop(key, None)
                self._save_state()
                logger.info(f"✅ 超时止盈平仓 {direction} {coin}: PnL={pnl:+.2f}")
            except Exception as e:
                logger.warning(f"超时止盈平仓失败 {direction} {coin}: {e}")

    # ── 过期撤单 ──
    def cancel_expired_orders(self):
        now = time.time()
        for key, info in list(self.state["orders"].items()):
            elapsed = now - info["placed_at"]
            if elapsed > ENTRY_LIMIT_EXPIRE_SECONDS:
                try:
                    self.exchange.cancel_order(info["order_id"], info["symbol"])
                    logger.info(f"⏰ 过期撤单 {info['direction']} {info['coin']}: 已挂{elapsed:.0f}秒(上限{ENTRY_LIMIT_EXPIRE_SECONDS}秒)")
                    self.state["orders"].pop(key, None)
                    self._save_state()
                except Exception as e:
                    # 撤单失败：可能是已成交/已不存在，查一下实际状态
                    logger.warning(f"撤过期单失败 {info['coin']}: {e}，检查订单状态")
                    try:
                        order = self.exchange.fetch_order(info["order_id"], info["symbol"])
                        if order.get("status") in ("closed", "filled"):
                            # 订单已成交 → 移至持仓并挂TP/SL
                            filled_qty = float(order.get("filled", 0) or 0)
                            avg_price = float(order.get("average", 0) or info.get("price", 0) or 0)
                            logger.info(f"🔍 订单已成交 {info['direction']} {info['coin']}: {filled_qty} @ {avg_price}")
                            pos = {
                                "coin": info["coin"], "symbol": info["symbol"],
                                "direction": info["direction"],
                                "entry_price": avg_price, "quantity": filled_qty,
                                "tp_price": info["tp_price"], "sl_price": info["sl_price"],
                                "order_id": info["order_id"], "filled_at": time.time(),
                            }
                            self.state["positions"][key] = pos
                            self.state["orders"].pop(key, None)
                            self._place_tp_sl(info["coin"], pos)
                            self._save_state()
                        else:
                            # 确实不在了 → 直接从state删除
                            logger.info(f"订单不存在 {info['coin']}，从状态文件清除")
                            self.state["orders"].pop(key, None)
                            self._save_state()
                    except Exception as e2:
                        logger.warning(f"查询订单状态也失败 {info['coin']}: {e2}")
                        # 无法确定状态，保守删除避免阻塞其他订单
                        self.state["orders"].pop(key, None)
                        self._save_state()

    # ── 交易所状态 ──
    def get_exchange_state(self) -> tuple:
        order_coins = set()
        position_coins = set()
        ex_long = 0
        ex_short = 0
        try:
            for o in self.exchange.fetch_open_orders():
                coin = o["symbol"].split("/")[0]
                order_coins.add(coin)
                if o.get("side") == "buy":
                    ex_long += 1
                else:
                    ex_short += 1
        except:
            pass
        try:
            for p in self.exchange.fetch_positions():
                amt = float(p.get("contracts", 0) or 0)
                if abs(amt) > 0.000001:
                    coin = p["symbol"].split("/")[0]
                    position_coins.add(coin)
                    if amt > 0:
                        ex_long += 1
                    else:
                        ex_short += 1
        except:
            pass
        return order_coins, position_coins, ex_long, ex_short

    def sync_exchange_positions(self):
        try:
            for p in self.exchange.fetch_positions():
                amt = float(p.get("contracts", 0) or 0)
                if abs(amt) <= 0.000001:
                    continue
                symbol = p.get("symbol", "")
                if not symbol or not symbol.endswith(":USDT"):
                    continue
                coin = symbol.split("/")[0]
                entry = float(p.get("entryPrice", 0) or 0)
                # 张数→币数
                try:
                    market = self.exchange.market(symbol)
                    cs = float(market.get("contractSize", 1) or 1)
                except:
                    cs = 1
                coin_qty = abs(amt) * cs
                value = coin_qty * entry
                if value > 1000:
                    continue
                direction = "LONG" if amt > 0 else "SHORT"
                key = self._get_key(coin, direction)
                if key in self.state["orders"] or key in self.state["positions"]:
                    continue
                logger.info(f"🔄 同步持仓 {direction} {coin}: {coin_qty}币 @ {entry}")
                self.state["positions"][key] = {
                    "coin": coin, "symbol": symbol, "direction": direction,
                    "entry_price": entry, "quantity": coin_qty,
                    "tp_price": 0, "sl_price": 0, "filled_at": time.time(),
                    "_synced": True,
                }
            self._save_state()
            logger.info(f"交易所持仓同步完成，当前 {len(self.state['positions'])} 个持仓记录")
        except Exception as e:
            logger.warning(f"同步持仓失败: {e}")

    # ── 信号（从 OKX 扫描器 JSON 文件读取）──
    def fetch_new_signals(self) -> list:
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        processed = set(self.state.get("processed_signals", {}).get(today, []))
        now_ts = datetime.now(timezone.utc).timestamp()

        try:
            result_file = Path(__file__).parent / "bb_ride_scanner_okx_results.json"
            if not result_file.exists():
                return []
            data = json.loads(result_file.read_text(encoding="utf-8"))
            signals = data.get("signals", [])
        except Exception as e:
            logger.error(f"读取OKX扫描结果失败: {e}")
            return []

        # 信号有效期6小时，计算signal_time
        new_sigs = []
        for s in signals:
            # 用 coin+方向+日期 做去重key
            date_key = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            sig_key = f"{s['coin']}|{s['direction']}|{date_key}"
            if sig_key in processed:
                continue

            # 估算 signal_time = pattern_start_bj + 3h45m
            if not s.get("pattern_start_bj"):
                continue
            try:
                start = datetime.strptime(str(s["pattern_start_bj"])[:19], "%Y-%m-%d %H:%M:%S")
            except:
                continue
            signal_time = start + timedelta(minutes=WINDOW_CANDLES * 15)
            # 只取6小时内
            if (datetime.now(timezone.utc) - signal_time.replace(tzinfo=timezone.utc)).total_seconds() > 6 * 3600:
                continue

            new_sigs.append({
                "id": sig_key,
                "coin": s["coin"],
                "current_price": s.get("current_price", 0),
                "direction": "up" if s.get("direction") == "up" else "down",
                "signal_time": signal_time,
                "score": s.get("score", 0),
            })

        if new_sigs:
            up = [r["coin"] for r in new_sigs if r["direction"] == "up"]
            down = [r["coin"] for r in new_sigs if r["direction"] == "down"]
            logger.info(f"📡 {len(new_sigs)}条 (多{len(up)}条 {','.join(up[:5])} / 空{len(down)}条 {','.join(down[:5])})")
        return new_sigs

    def mark_processed(self, signal_id: str):
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        if today not in self.state["processed_signals"]:
            self.state["processed_signals"][today] = []
        if signal_id not in self.state["processed_signals"][today]:
            self.state["processed_signals"][today].append(signal_id)
        self._save_state()

    def update_positions_pnl(self):
        for key, pos in list(self.state.get("positions", {}).items()):
            try:
                ticker = self.exchange.fetch_ticker(pos["symbol"])
                cur_price = float(ticker.get("last", 0))
                if cur_price <= 0:
                    continue
                pos["current_price"] = cur_price
                entry = pos["entry_price"]
                qty = pos["quantity"]
                direction = pos["direction"]
                if direction == "LONG":
                    upnl = (cur_price - entry) * qty
                    upnl_pct = (cur_price - entry) / entry * 100
                else:
                    upnl = (entry - cur_price) * qty
                    upnl_pct = (entry - cur_price) / entry * 100
                pos["unrealized_pnl"] = round(upnl, 2)
                pos["unrealized_pnl_pct"] = round(upnl_pct, 2)
            except Exception as e:
                logger.warning(f"获取 {pos.get('coin','?')} 盈亏失败: {e}")
        self._save_state()

    # ── 主循环 ──
    def run_once(self):
        try:
            if not self.api_ready:
                # API未认证：只扫描信号+日志，不交易
                signals = self.fetch_new_signals()
                if signals:
                    up = sum(1 for s in signals if s["direction"] == "up")
                    down = sum(1 for s in signals if s["direction"] == "down")
                    logger.info(f"📡 (展示模式) 信号{len(signals)}条: {up}多{down}空")
                logger.info(f"💓 (展示模式) 等待OKX API密钥配置后自动交易")
                time.sleep(CHECK_INTERVAL)
                return

            self._cleanup_counter += 1
            if self._cleanup_counter >= 20:
                self._cleanup_counter = 0
                self._cleanup_ghost_orders()

            # 1. 检查订单成交（必须先于撤单，避免已成交订单被误删）
            for key, info in list(self.state["orders"].items()):
                self.check_order_status(key, info)

            # 2. 撤过期单
            self.cancel_expired_orders()

            # 3. 更新持仓盈亏（实时价格 + PnL）→ 必须先于平仓检查，否则 close_price 为0
            self.update_positions_pnl()

            # 4. 检查持仓是否已平
            for key, pos in list(self.state["positions"].items()):
                self.check_position_closed(key, pos)

            # 5. 超时止盈
            self.close_profitable_positions()

            # \u540c\u6b65\u4ea4\u6613\u6240\u5b9e\u9645\u6570\u636e
            ex_order_coins, ex_position_coins, ex_long, ex_short = self.get_exchange_state()

            signals = self.fetch_new_signals()
            sig_up = sum(1 for s in signals if s["direction"] == "up")
            sig_down = sum(1 for s in signals if s["direction"] == "down")

            long_total = self._count_by_direction("orders", "LONG") + self._count_by_direction("positions", "LONG")
            short_total = self._count_by_direction("orders", "SHORT") + self._count_by_direction("positions", "SHORT")

            for sig in signals:
                direction_map = {"up": "LONG", "down": "SHORT"}
                direction = direction_map.get(sig["direction"])
                if not direction:
                    self.mark_processed(sig["id"])
                    continue

                coin = sig["coin"]

                # \u68c0\u67e5 TradFi \u9ed1\u540d\u5355
                if coin in self.tradfi_blacklist:
                    logger.info(f"\u23ed {coin} TradFi \u54c1\u79cd\uff0c\u8df3\u8fc7")
                    self.mark_processed(sig["id"])
                    continue

                if direction == "LONG" and long_total >= MAX_LONG_ORDERS:
                    continue
                if direction == "SHORT" and short_total >= MAX_SHORT_ORDERS:
                    continue

                key = self._get_key(coin, direction)
                if key in self.state["orders"] or key in self.state["positions"]:
                    continue
                if coin in ex_order_coins:
                    continue
                if coin in ex_position_coins:
                    continue
                if self._is_blacklisted(coin):
                    continue

                symbol = self._get_usdt_symbol(coin)
                if not symbol:
                    self.mark_processed(sig["id"])
                    continue

                opp_key = self._get_key(coin, "LONG" if direction == "SHORT" else "SHORT")
                if opp_key in self.state["orders"] or opp_key in self.state["positions"]:
                    continue

                bb_mid, bb_upper, bb_lower, candle_high, candle_low = self._calc_bb(symbol)
                if bb_lower is None:
                    continue

                price = self._get_price(symbol)
                if not price or price <= 0:
                    continue

                ma = self._calc_ma(symbol)
                if ma is None:
                    continue
                if direction == "LONG" and price < ma:
                    continue
                if direction == "SHORT" and price > ma:
                    continue

                if direction == "LONG":
                    if not (candle_low <= bb_lower * 1.005):
                        continue
                else:
                    if not (candle_high >= bb_upper * 0.995):
                        continue

                qty = self._calc_quantity(symbol, price)
                if not qty or qty <= 0:
                    continue

                if direction == "LONG":
                    limit_price = bb_lower * (1 + ENTRY_OFFSET)
                else:
                    limit_price = bb_upper * (1 - ENTRY_OFFSET)
                logger.info(f"🆕 {direction} {coin}: BB触碰 → 限价{limit_price:.6f} x{qty} (OKX)")
                if PAPER_TRADING:
                    logger.info("  ⓘ 模拟模式，跳过实际下单")
                    self.mark_processed(sig["id"])
                    if direction == "LONG":
                        long_total += 1
                    else:
                        short_total += 1
                    continue
                order_id = self.place_limit_order(coin, symbol, direction, float(limit_price), qty)
                if order_id:
                    self.mark_processed(sig["id"])
                    if direction == "LONG":
                        long_total += 1
                    else:
                        short_total += 1

            o_l = sum(1 for k in self.state.get("orders", {}) if k.startswith("LONG:"))
            o_s = sum(1 for k in self.state.get("orders", {}) if k.startswith("SHORT:"))
            p_l = sum(1 for k in self.state.get("positions", {}) if k.startswith("LONG:"))
            p_s = sum(1 for k in self.state.get("positions", {}) if k.startswith("SHORT:"))
            logger.info(f"💓 信号{sig_up}多{sig_down}空 → 挂单{o_l}多{o_s}空 持仓{p_l}多{p_s}空")

        except Exception as e:
            logger.error(f"运行异常: {e}", exc_info=True)

    def run(self):
        logger.info("=" * 60)
        logger.info("🤖 BB-Ride OKX 执行策略启动")
        if not self.api_ready:
            logger.info("   ⚠️  展示模式：仅显示信号，需要有效OKX API密钥才能交易")
        logger.info(f"   每单 {ORDER_AMOUNT} USDT  限价入场(偏移{ENTRY_OFFSET*100:.1f}%) TP+{TP_PCT*100:.0f}% / SL-{SL_PCT*100:.1f}%")
        logger.info(f"   信号窗口 {SIGNAL_WINDOW_HOURS}h  {MA_TIMEFRAME}MA{MA_PERIOD}方向过滤 + 5m布林线({BB_PERIOD},{BB_STD})触碰限价入场")
        logger.info(f"   连亏{MAX_CONSECUTIVE_LOSSES}次自动屏蔽{BLACKLIST_HOURS}h")
        logger.info(f"   多单上限 {MAX_LONG_ORDERS}  空单上限 {MAX_SHORT_ORDERS}")
        logger.info("=" * 60)

        self._cleanup_ghost_orders()

        closed_arr = self.state.get("closed_positions", [])
        if closed_arr and self.state.get("total_stats", {}).get("trades", 0) < len(closed_arr):
            trades = len(closed_arr)
            wins = sum(1 for c in closed_arr if c.get("pnl", 0) > 0)
            pnl = sum(c.get("pnl", 0) for c in closed_arr)
            self.state["total_stats"] = {"trades": trades, "wins": wins, "pnl": round(pnl, 2)}
            self._save_state()
            logger.info(f"回填累计统计: {trades}单 {wins}胜 PnL={pnl:.2f}")

        self.sync_exchange_positions()

        # 重挂TP/SL
        for key, pos in list(self.state.get("positions", {}).items()):
            if pos.get("tp_price", 0) > 0 and pos.get("sl_price", 0) > 0:
                logger.info(f"🔄 重挂TP/SL {pos['direction']} {pos['coin']}")
                self._place_tp_sl(pos["coin"], pos)

        while True:
            self.run_once()
            time.sleep(CHECK_INTERVAL)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    bot = BbRideOkxStrategy()
    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("🛑 策略已停止")


if __name__ == "__main__":
    main()
