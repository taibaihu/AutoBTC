#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KDJ多空对称策略 - BTC/USDC合约 实盘"""
import sys, os, time, json, logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ccxt
import pandas as pd
import numpy as np
from strategy import KDJReversalStrategy, BUY, SELL, HOLD
from config import API_KEY, SECRET_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SYMBOL = "BTC/USDC:USDC"
TF = "15m"
LIMIT = 250
ORDER_QTY = 0.05         # 0.05 BTC / 单
ENTRY_OFFSET = -50       # 多头: 低于市价$50; 空头: 高于市价$50
STOP_LOSS_PCT = 1.0      # 止损 ±1.0% (最优方案)
TAKE_PROFIT_PCT = 1.5    # 止盈 ±1.5% (最优方案)
ORDER_TIMEOUT = 1800     # 挂单30分钟未成交自动撤单 (回测最佳)
CHECK_INTERVAL = 60      # 60秒轮询
OVERBOUGHT_K = 70        # K>70 超买区死叉 => 开空 (回测最佳)
STATE_FILE = Path(__file__).parent / "kdj_btcusdc_state.json"


class KDJBot:
    def __init__(self):
        self.exchange = ccxt.binance({
            "apiKey": API_KEY, "secret": SECRET_KEY,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        self.exchange.load_markets()
        self.strategy = KDJReversalStrategy(
            oversold_k=30, stop_loss_pct=STOP_LOSS_PCT,
            max_hold_candles=24, cooldown_bars=2, k_period=14, d_period=2,
            vol_filter_pct=0.8, ema_filter=True, ema_period=50,
        )
        self.state = self._load_state()
        self._last_ind = {}
        self._last_trade_time = 0  # 最近一次平仓时间，用于冷却检查
        logger.info(f"KDJ多空对称策略启动: {SYMBOL} 每单{ORDER_QTY}BTC")
        logger.info(f"  多头: 金叉K<{self.strategy.oversold_k}  -\${abs(ENTRY_OFFSET)}挂  TP+{TAKE_PROFIT_PCT}%  SL-{STOP_LOSS_PCT}%")
        logger.info(f"  空头: 死叉K>{OVERBOUGHT_K}  +${abs(ENTRY_OFFSET)}挂  TP+{TAKE_PROFIT_PCT}%  SL+{STOP_LOSS_PCT}%")
        logger.info(f"  TP/SL: {TAKE_PROFIT_PCT}%/{STOP_LOSS_PCT}%  盈亏比{TAKE_PROFIT_PCT/STOP_LOSS_PCT:.1f}")
        logger.info(f"  参数: KDJ({self.strategy.k_period},{self.strategy.d_period}) 超时{ORDER_TIMEOUT/60}分挂单/{self.strategy.max_hold_candles*15//60}h持仓 冷却{self.strategy.cooldown_bars}根")

        try:
            self.exchange.set_leverage(100, SYMBOL)
        except Exception:
            pass

    def _load_state(self):
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text())
                if "closed_positions" not in data: data["closed_positions"] = []
                if "orders" not in data: data["orders"] = {}
                if "positions" not in data: data["positions"] = {}
                if "filled_today" not in data: data["filled_today"] = {}
                return data
        except: pass
        return {"position": None, "entry_price": 0, "order_id": None, "entry_time": None,
                "closed_positions": [], "orders": {}, "positions": {}, "filled_today": {}}

    def _save_state(self):
        STATE_FILE.write_text(json.dumps(self.state, indent=2, default=str))

    def fetch_15m(self):
        ohlcv = self.exchange.fetch_ohlcv(SYMBOL, "15m", limit=LIMIT)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def get_mark_price(self):
        return float(self.exchange.fetch_ticker(SYMBOL)["last"])

    def place_limit_order(self, side, price):
        """挂限价单 side='long'/'short'  保存订单到state"""
        price_prec = self.exchange.price_to_precision(SYMBOL, price)
        if side == "long":
            order = self.exchange.create_limit_buy_order(SYMBOL, ORDER_QTY, price_prec, {"positionSide": "LONG"})
            side_cn = "买入开多"
        else:
            order = self.exchange.create_limit_sell_order(SYMBOL, ORDER_QTY, price_prec, {"positionSide": "SHORT"})
            side_cn = "卖出开空"
        logger.info(f"挂单 {side_cn} {ORDER_QTY}BTC @ {price_prec}")

        self.state.setdefault("orders", {})
        self.state["orders"]["BTC"] = {
            "coin": "BTC", "price": float(price_prec), "quantity": ORDER_QTY,
            "placed_at": time.time(), "status": "挂单中",
            "order_id": order["id"], "side": side,
        }
        self._save_state()
        return order["id"]

    def cancel_order(self, order_id):
        try:
            self.exchange.cancel_order(order_id, SYMBOL)
            logger.info(f"撤单 {order_id}")
        except: pass

    def check_order(self, order_id):
        try:
            o = self.exchange.fetch_order(order_id, SYMBOL)
            return o["status"], float(o.get("filled", 0) or 0), float(o.get("average", 0) or o.get("price", 0))
        except: return None, 0, 0

    def place_market_close(self, side):
        """市价平仓"""
        if side == "long":
            order = self.exchange.create_market_sell_order(SYMBOL, ORDER_QTY, {"positionSide": "LONG"})
            logger.info(f"市价平多 {ORDER_QTY}BTC")
        else:
            order = self.exchange.create_market_buy_order(SYMBOL, ORDER_QTY, {"positionSide": "SHORT"})
            logger.info(f"市价平空 {ORDER_QTY}BTC")
        return order

    def _save_close_record(self, close_price, pnl_pct, reason, side):
        """保存平仓记录"""
        self._last_trade_time = time.time()  # 记录平仓时间用于冷却
        pos_order_id = self.state.get("positions", {}).get("BTC", {}).get("order_id", "")
        entry_price = self.state.get("entry_price", 0)
        if side == "long":
            pnl = round((close_price - entry_price) * ORDER_QTY, 2)
        else:
            pnl = round((entry_price - close_price) * ORDER_QTY, 2)
        rec = {
            "coin": "BTC", "side": side,
            "entry_price": entry_price, "close_price": close_price,
            "pnl": pnl, "pnl_pct": round(pnl_pct, 2),
            "filled_at_str": datetime.fromtimestamp(self.state.get("entry_time", 0)).strftime("%m-%d %H:%M") if self.state.get("entry_time") else "-",
            "close_time_str": datetime.now().strftime("%m-%d %H:%M"),
            "reason": reason, "order_id": pos_order_id,
        }
        self.state.setdefault("closed_positions", [])
        self.state["closed_positions"].append(rec)
        if len(self.state["closed_positions"]) > 50:
            self.state["closed_positions"] = self.state["closed_positions"][-50:]
        self.state["positions"].pop("BTC", None)
        self._save_state()
        side_cn = "多头" if side == "long" else "空头"
        logger.info(f"平仓记录已保存 {side_cn}: {rec['pnl']:+.2f}U ({rec['pnl_pct']:+.2f}%) {reason}")

    def run(self):
        logger.info("KDJ多空对称策略 开始运行")
        while True:
            try:
                mark = self.get_mark_price()
                pos = self.state.get("position")     # "long" / "short" / None
                oid = self.state.get("order_id")

                df = self.fetch_15m()
                signal, ind = self.strategy.generate_signal(df)
                self._last_ind = ind

                # 冷却检查（平仓后等待cooldown_bars根15mK线）
                cooldown_sec = self.strategy.cooldown_bars * 15 * 60
                in_cooldown = False
                if self._last_trade_time > 0:
                    elapsed = time.time() - self._last_trade_time
                    in_cooldown = elapsed < cooldown_sec

                # -- 判断空头信号 (策略当前只有多头BUY，空头需要自己算) --
                short_signal = False

                if not in_cooldown and ind and "K" in ind and "K_prev" in ind and "D_prev" in ind:
                    # 波动率过低时不开仓
                    if not ind.get("vol_filter_block"):
                        cur_k = float(ind.get("K", 50))
                        cur_d = float(ind.get("D", 50))
                        prev_k = float(ind.get("K_prev", 50))
                        prev_d = float(ind.get("D_prev", 50))
                        death_cross = prev_k >= prev_d and cur_k < cur_d
                        # EMA200过滤: 空头只在价<EMA200时开仓
                        above_ema = ind.get("above_ema", True)
                        if death_cross and cur_k > OVERBOUGHT_K and (not above_ema):
                            short_signal = True

                # -- 有挂单未成交 --
                if oid and not pos:
                    status, filled, avg = self.check_order(oid)
                    order_side = self.state.get("orders", {}).get("BTC", {}).get("side", "long")

                    if status == "closed" and filled > 0:
                        logger.info(f"挂单成交 {filled}BTC @ {avg} 方向={order_side}")
                        self.state["position"] = order_side
                        self.state["entry_price"] = avg
                        self.state["entry_time"] = time.time()
                        self.state["order_id"] = None
                        self.state.setdefault("positions", {})
                        ex_oid = self.state.get("orders", {}).get("BTC", {}).get("order_id", oid)

                        if order_side == "long":
                            sl_price = round(avg * (1 - STOP_LOSS_PCT / 100), 1)
                            tp_price = round(avg * (1 + TAKE_PROFIT_PCT / 100), 1)
                        else:
                            sl_price = round(avg * (1 + STOP_LOSS_PCT / 100), 1)
                            tp_price = round(avg * (1 - TAKE_PROFIT_PCT / 100), 1)

                        self.state["positions"]["BTC"] = {
                            "coin": "BTC", "entry_price": avg, "quantity": ORDER_QTY,
                            "filled_at": time.time(),
                            "tp_price": tp_price, "sl_price": sl_price,
                            "current_price": mark, "order_id": ex_oid, "side": order_side,
                        }
                        self.state["orders"].pop("BTC", None)
                        self._save_state()

                    elif status == "open":
                        placed = self.state.get("orders", {}).get("BTC", {}).get("placed_at", 0)
                        if placed and (time.time() - placed) > ORDER_TIMEOUT:
                            logger.info(f"挂单超时({(time.time()-placed)/60:.0f}分)，撤单")
                            self.cancel_order(oid)
                            self.state["order_id"] = None
                            self.state["orders"].pop("BTC", None)
                            self._save_state()
                    elif status in ("canceled", "expired"):
                        self.state["order_id"] = None
                        self.state["orders"].pop("BTC", None)
                        self._save_state()

                # -- 持仓中 -> 检查平仓 --
                if pos in ("long", "short"):
                    ep = self.state.get("entry_price", 0)
                    held = (time.time() - self.state.get("entry_time", time.time())) / 3600

                    self.state.setdefault("positions", {})
                    if "BTC" in self.state["positions"]:
                        self.state["positions"]["BTC"]["current_price"] = mark

                    if ep > 0:
                        if pos == "long":
                            loss_pct = (mark - ep) / ep * 100
                            profit_pct = (mark - ep) / ep * 100
                            tp_hit = profit_pct >= TAKE_PROFIT_PCT
                            sl_hit = loss_pct <= -STOP_LOSS_PCT
                        else:
                            loss_pct = (ep - mark) / ep * 100
                            profit_pct = (ep - mark) / ep * 100
                            tp_hit = profit_pct >= TAKE_PROFIT_PCT
                            sl_hit = loss_pct <= -STOP_LOSS_PCT

                        # 止损
                        if sl_hit:
                            self.place_market_close(pos)
                            pnl = (mark - ep) / ep * 100 if pos == "long" else (ep - mark) / ep * 100
                            logger.info(f"止损平仓{'多' if pos == 'long' else '空'}: 入场{ep:.0f} 出场{mark:.0f} 盈亏{pnl:+.2f}%")
                            self._save_close_record(mark, pnl, "止损", pos)
                            self.state["position"] = None
                            self.state["entry_time"] = None
                            self.strategy._entry_price = None
                            self._save_state()
                            time.sleep(CHECK_INTERVAL)
                            continue

                        # 止盈
                        if tp_hit:
                            self.place_market_close(pos)
                            pnl = (mark - ep) / ep * 100 if pos == "long" else (ep - mark) / ep * 100
                            logger.info(f"止盈平仓{'多' if pos == 'long' else '空'}: 入场{ep:.0f} 出场{mark:.0f} 盈亏{pnl:+.2f}%")
                            self._save_close_record(mark, pnl, "止盈+0.3%", pos)
                            self.state["position"] = None
                            self.state["entry_time"] = None
                            self.strategy._entry_price = None
                            self._save_state()

                        # 超时强平 (max_hold_candles根15mK线)
                        max_hold_hours = self.strategy.max_hold_candles * 15 / 60
                        if held >= max_hold_hours:
                            self.place_market_close(pos)
                            pnl = (mark - ep) / ep * 100 if pos == "long" else (ep - mark) / ep * 100
                            logger.info(f"超时平仓{'多' if pos == 'long' else '空'}({held:.1f}h): 入场{ep:.0f} 出场{mark:.0f} 盈亏{pnl:+.2f}%")
                            self._save_close_record(mark, pnl, "超时平仓", pos)
                            self.state["position"] = None
                            self.state["entry_time"] = None
                            self.strategy._entry_price = None
                            self._save_state()

                # -- 无持仓、无挂单 -> 检查开仓 --
                if not pos and not oid:
                    if signal == BUY:
                        entry_price = mark + ENTRY_OFFSET
                        logger.info(f"KDJ超卖金叉→开多: 当前{mark:.0f} 挂单@{entry_price:.0f}")
                        self._last_trade_time = time.time()
                        self.strategy._last_trade_bar = df.index[-1]
                        oid = self.place_limit_order("long", entry_price)
                        self.state["order_id"] = oid
                        self.state["orders"]["BTC"]["side"] = "long"
                        self._save_state()
                    elif short_signal:
                        entry_price = mark - ENTRY_OFFSET  # 空头: 高于市价
                        logger.info(f"KDJ超买死叉→开空: 当前{mark:.0f} 挂单@{entry_price:.0f}")
                        # 更新策略冷却时间，防止冷却期内多头误开
                        self.strategy._last_trade_bar = df.index[-1]
                        self.strategy._entry_price = None
                        oid = self.place_limit_order("short", entry_price)
                        self.state["order_id"] = oid
                        self.state["orders"]["BTC"]["side"] = "short"
                        self._save_state()

                # -- 日志 --
                cur_k = self._last_ind.get("K", "-")
                cur_d = self._last_ind.get("D", "-")
                cur_j = self._last_ind.get("J", "-")
                cur_ema_dev = self._last_ind.get("ema_dev_pct", "-")
                logger.info(f"状态: 持仓={pos} 价格={mark:.0f} K={cur_k} D={cur_d} J={cur_j} EMA偏离={cur_ema_dev}% 振幅={ind.get("amplitude_4h","-")}%"
                            f"{' 🔒冷却' if in_cooldown and not pos else ''}")

                time.sleep(CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"运行异常: {e}")
                time.sleep(5)


if __name__ == "__main__":
    bot = KDJBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("停止")
