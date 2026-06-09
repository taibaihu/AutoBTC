# -*- coding: utf-8 -*-
"""行情获取 & 订单执行模块"""
import logging
import time
from typing import Optional

import ccxt
import pandas as pd
from config import API_KEY, SECRET_KEY, FIXED_ORDER_QTY, MIN_PROFIT_RATE, MAX_LOSS_RATE, get_proxy_config

logger = logging.getLogger(__name__)


class BinanceEngine:
    """币安交易所接口封装"""

    def __init__(self):
        proxies = get_proxy_config()
        self.exchange = ccxt.binance({"proxies": proxies,
            "apiKey": API_KEY,
            "secret": SECRET_KEY,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """获取 K 线数据，返回 DataFrame"""
        raw = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(
            raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def get_balance(self, asset: str = "USDT") -> float:
        """查询可用余额"""
        try:
            balance = self.exchange.fetch_balance()
            return float(balance["free"].get(asset, 0))
        except Exception:
            return 0.0

    def market_buy(self, symbol: str, amount: float) -> dict:
        """市价买入 (amount 为 USDT 金额，直接按金额下单省去 ticker 请求)"""
        return self.exchange.create_market_buy_order_with_cost(symbol, amount)

    def market_sell(self, symbol: str, amount: float) -> dict:
        """市价卖出 (amount 为币数)"""
        market = self.exchange.market(symbol)
        precision = market["precision"]["amount"]
        quantity = self.exchange.amount_to_precision(symbol, amount)
        return self.exchange.create_market_sell_order(symbol, float(quantity))

    def get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        ticker = self.exchange.fetch_ticker(symbol)
        return float(ticker["last"])


class OKXEngine:
    """OKX 行情接口封装（仅公开数据，无需 API Key）"""

    def __init__(self):
        proxies = get_proxy_config()
        self.exchange = ccxt.okx({
            "proxies": proxies,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """获取 K 线数据，返回 DataFrame"""
        raw = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(
            raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def get_current_price(self, symbol: str) -> float:
        """获取当前实时价格"""
        ticker = self.exchange.fetch_ticker(symbol)
        return float(ticker["last"])


class FuturesEngine:
    """币安 USDT-M 永续合约交易引擎"""

    def __init__(self, leverage: int = 100):
        proxies = get_proxy_config()
        self.exchange = ccxt.binance({
            "proxies": proxies,
            "apiKey": API_KEY,
            "secret": SECRET_KEY,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        self.leverage = leverage
        self._symbol = "BTC/USDT:USDT"
        self.order_qty = FIXED_ORDER_QTY

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """获取 K 线数据，返回 DataFrame"""
        raw = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(
            raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def set_leverage(self):
        """设置合约杠杆"""
        try:
            self.exchange.set_leverage(self.leverage, self._symbol)
        except Exception as e:
            logger.warning(f"设置杠杆失败: {e}")

    def get_balance(self, asset: str = "USDT") -> float:
        """查询合约账户可用余额"""
        try:
            balance = self.exchange.fetch_balance()
            return float(balance["free"].get(asset, 0))
        except Exception:
            return 0.0

    def get_position_size(self, symbol: str, side: str = "LONG") -> float:
        """查询某方向持仓数量（0 表示无持仓）"""
        try:
            positions = self.exchange.fetch_positions([symbol])
            for p in positions:
                if p.get("info", {}).get("positionSide") == side:
                    return float(p.get("contracts", 0) or 0)
            return 0.0
        except Exception:
            return 0.0

    def get_position(self, side: str = "LONG") -> Optional[dict]:
        """查询持仓，返回 {size, entry_price, unrealized_pnl} 或 None"""
        try:
            positions = self.exchange.fetch_positions([self._symbol])
            for p in positions:
                size = float(p.get("contracts", 0) or 0)
                p_side = p.get("info", {}).get("positionSide", "")
                if size > 0 and p_side == side:
                    return {
                        "size": size,
                        "entry_price": float(p["entryPrice"]),
                        "unrealized_pnl": float(p["unrealizedPnl"]),
                    }
            return None
        except Exception as e:
            logger.warning(f"查询持仓失败: {e}")
            return None

    def cancel_all_orders(self):
        """撤销当前交易对所有挂单（含普通订单和 TP/SL algo 订单）"""
        # 1) 撤销普通订单
        orders = []
        try:
            orders = self.exchange.fetch_open_orders(self._symbol)
        except Exception as e:
            logger.warning(f"查询挂单异常: {e}")
        success = 0
        for o in orders:
            try:
                self.exchange.cancel_order(o["id"], self._symbol)
                success += 1
            except Exception as e:
                logger.warning(f"撤销挂单 {o['id']} 失败: {e}")
        if orders:
            logger.info(f"已撤销 {success}/{len(orders)} 个普通挂单")

        # 2) 撤销 TP/SL algo 订单
        self._cancel_algo_orders()

    def get_algo_orders(self) -> list:
        """获取所有 TP/SL algo 条件订单"""
        try:
            return self.exchange.fapiPrivateGetOpenAlgoOrders() or []
        except Exception as e:
            logger.warning(f"查询 algo 挂单异常: {e}")
            return []

    def check_tp_sl_algo(self, side: str = "LONG") -> tuple:
        """
        检查 algo TP/SL 是否存在
        返回 (has_tp, has_sl)
        """
        algo_list = self.get_algo_orders()
        has_tp = False
        has_sl = False
        for o in algo_list:
            if o.get("positionSide") != side:
                continue
            otype = o.get("orderType", "")
            if otype == "TAKE_PROFIT_MARKET":
                has_tp = True
            elif otype == "STOP_MARKET":
                has_sl = True
        return has_tp, has_sl

    def _cancel_algo_orders(self):
        """撤销 TP/SL algo 条件订单"""
        algo_list = self.get_algo_orders()
        if not algo_list:
            return
        success = 0
        for o in algo_list:
            try:
                algo_id = o.get("algoId", "")
                if algo_id:
                    self.exchange.fapiPrivateDeleteAlgoOrder(
                        {"symbol": self._symbol.replace("/", ""), "algoId": algo_id}
                    )
                    success += 1
            except Exception as e:
                logger.warning(f"撤销 algo 订单失败: {e}")
        if success:
            logger.info(f"已撤销 {success}/{len(algo_list)} 个 TP/SL 条件订单")

    def calc_contract_amount(self, usdt_amount: float, price: float) -> float:
        """计算合约数量 = (USDT金额 × 杠杆) / 当前价"""
        raw = (usdt_amount * self.leverage) / price
        market = self.exchange.market(self._symbol)
        precision = market["precision"]["amount"]
        return float(self.exchange.amount_to_precision(self._symbol, raw))

    def market_buy(self, symbol: str, amount: float) -> dict:
        """市价开多 — 固定 0.05 BTC"""
        qty = self._get_precise_qty()
        return self.exchange.create_market_buy_order(self._symbol, qty, {"positionSide": "LONG"})

    def limit_buy_open(self) -> dict:
        """挂单开多 — post-only limit at best bid, 2s未成交回退市价"""
        ticker = self.exchange.fetch_ticker(self._symbol)
        bid = ticker.get("bid")
        if bid is None:
            logger.warning(f"挂单开多: ticker.bid 为 None，直接市价开")
            return self.market_buy(self._symbol, 0)
        bid = float(bid)
        qty = self._get_precise_qty()
        try:
            order = self.exchange.create_order(
                self._symbol, "LIMIT", "buy", qty, bid,
                {"positionSide": "LONG", "postOnly": True},
            )
            time.sleep(2)
            fetched = self.exchange.fetch_order(order["id"], self._symbol)
            filled = float(fetched.get("filled", 0) or 0)
            if filled >= qty * 0.999:
                logger.info(f"✅ 挂单开多 maker 成交 @ {bid}")
                return fetched
            logger.info(f"⏳ 挂单开多未成交(已填{filled:.4f}/{qty})，撤单回退市价")
            self.exchange.cancel_order(order["id"], self._symbol)
        except Exception as e:
            logger.warning(f"挂单开多异常: {e}")
        return self.market_buy(self._symbol, 0)

    def market_sell(self, symbol: str, amount: float) -> dict:
        """市价平多 — 按实际持仓数量平仓，确保全部平掉"""
        qty = self.get_position_size(symbol, "LONG")
        if qty <= 0:
            logger.warning("market_sell: 无多头持仓")
            return {"status": "no_position", "filled": 0}
        return self.exchange.create_market_sell_order(
            self._symbol, qty, {"positionSide": "LONG"}
        )

    # ── 做空 ────────────────────────────────────────────────

    def market_sell_short(self, symbol: str, amount: float) -> dict:
        """市价开空 — 固定 0.05 BTC"""
        qty = self._get_precise_qty()
        return self.exchange.create_market_sell_order(self._symbol, qty, {"positionSide": "SHORT"})

    def limit_sell_short_open(self) -> dict:
        """挂单开空 — post-only limit at best ask, 2s未成交回退市价"""
        ticker = self.exchange.fetch_ticker(self._symbol)
        ask = ticker.get("ask")
        if ask is None:
            logger.warning(f"挂单开空: ticker.ask 为 None，直接市价开")
            return self.market_sell_short(self._symbol, 0)
        ask = float(ask)
        qty = self._get_precise_qty()
        try:
            order = self.exchange.create_order(
                self._symbol, "LIMIT", "sell", qty, ask,
                {"positionSide": "SHORT", "postOnly": True},
            )
            time.sleep(2)
            fetched = self.exchange.fetch_order(order["id"], self._symbol)
            filled = float(fetched.get("filled", 0) or 0)
            if filled >= qty * 0.999:
                logger.info(f"✅ 挂单开空 maker 成交 @ {ask}")
                return fetched
            logger.info(f"⏳ 挂单开空未成交(已填{filled:.4f}/{qty})，撤单回退市价")
            self.exchange.cancel_order(order["id"], self._symbol)
        except Exception as e:
            logger.warning(f"挂单开空异常: {e}")
        return self.market_sell_short(self._symbol, 0)

    def market_buy_cover(self, symbol: str, amount: float) -> dict:
        """市价平空 — 按实际持仓数量平仓"""
        qty = self.get_position_size(symbol, "SHORT")
        if qty <= 0:
            logger.warning("market_buy_cover: 无空头持仓")
            return {"status": "no_position", "filled": 0}
        return self.exchange.create_market_buy_order(
            self._symbol, qty, {"positionSide": "SHORT"}
        )

    # ── TP/SL 挂单 ──────────────────────────────────────

    def _get_precise_qty(self) -> float:
        """将 order_qty 按交易所精度格式化，失败则取原始值"""
        try:
            result = self.exchange.amount_to_precision(self._symbol, self.order_qty)
            if result is None:
                self.exchange.load_markets()
                result = self.exchange.amount_to_precision(self._symbol, self.order_qty)
            return float(result) if result is not None else self.order_qty
        except Exception:
            return self.order_qty

    def _get_precise_price(self, price: float) -> float:
        """将价格按交易所精度格式化，失败则取原始值"""
        try:
            result = self.exchange.price_to_precision(self._symbol, price)
            if result is None:
                self.exchange.load_markets()
                result = self.exchange.price_to_precision(self._symbol, price)
            return float(result) if result is not None else price
        except Exception:
            return price

    def set_tp_sl_long(self, entry_price: float):
        """开多后挂止盈止损单 — 1.5% TP/SL, 出场用市价"""
        qty = self._get_precise_qty()
        tp_price = self._get_precise_price(entry_price * (1 + MIN_PROFIT_RATE))
        sl_price = self._get_precise_price(entry_price * (1 - MAX_LOSS_RATE))

        self.cancel_all_orders()
        try:
            self.exchange.create_order(
                self._symbol, "TAKE_PROFIT_MARKET", "sell", qty, None,
                {"stopPrice": tp_price, "positionSide": "LONG"},
            )
            logger.info(f"✅ 多单止盈挂单 {tp_price}")
        except Exception as e:
            logger.warning(f"止盈挂单失败: {e}")
        try:
            self.exchange.create_order(
                self._symbol, "STOP_MARKET", "sell", qty, None,
                {"stopPrice": sl_price, "positionSide": "LONG"},
            )
            logger.info(f"✅ 多单止损挂单 {sl_price}")
        except Exception as e:
            logger.warning(f"止损挂单失败: {e}")

    def set_tp_sl_short(self, entry_price: float):
        """开空后挂止盈止损单 — 1.5% TP/SL, 出场用市价"""
        qty = self._get_precise_qty()
        tp_price = self._get_precise_price(entry_price * (1 - MIN_PROFIT_RATE))
        sl_price = self._get_precise_price(entry_price * (1 + MAX_LOSS_RATE))

        self.cancel_all_orders()
        try:
            self.exchange.create_order(
                self._symbol, "TAKE_PROFIT_MARKET", "buy", qty, None,
                {"stopPrice": tp_price, "positionSide": "SHORT"},
            )
            logger.info(f"✅ 空单止盈挂单 {tp_price}")
        except Exception as e:
            logger.warning(f"止盈挂单失败: {e}")
        try:
            self.exchange.create_order(
                self._symbol, "STOP_MARKET", "buy", qty, None,
                {"stopPrice": sl_price, "positionSide": "SHORT"},
            )
            logger.info(f"✅ 空单止损挂单 {sl_price}")
        except Exception as e:
            logger.warning(f"止损挂单失败: {e}")

    def limit_sell_close(self) -> dict:
        """限价平多 — best bid挂单, 2s未成交回退市价"""
        qty = self.get_position_size(self._symbol, "LONG")
        if qty <= 0:
            logger.warning("limit_sell_close: 无多头持仓")
            return {"status": "no_position", "filled": 0}
        qty = float(self.exchange.amount_to_precision(self._symbol, qty))
        ticker = self.exchange.fetch_ticker(self._symbol)
        bid = ticker.get("bid")
        if bid is None:
            logger.warning(f"限价平多: bid 为 None，直接市价平")
            return self.market_sell(self._symbol, 0)
        bid = float(bid)
        try:
            order = self.exchange.create_order(
                self._symbol, "LIMIT", "sell", qty, bid,
                {"positionSide": "LONG", "postOnly": True},
            )
            time.sleep(2)
            fetched = self.exchange.fetch_order(order["id"], self._symbol)
            filled = float(fetched.get("filled", 0) or 0)
            if filled >= qty * 0.999:
                logger.info(f"✅ 限价平多 maker 成交 @ {bid}")
                return fetched
            logger.info(f"⏳ 限价平多未成交(已填{filled:.4f}/{qty})，撤单回退市价")
            self.exchange.cancel_order(order["id"], self._symbol)
        except Exception as e:
            logger.warning(f"限价平多异常: {e}")
        return self.market_sell(self._symbol, 0)

    def limit_buy_close(self) -> dict:
        """限价平空 — best ask挂单, 2s未成交回退市价"""
        qty = self.get_position_size(self._symbol, "SHORT")
        if qty <= 0:
            logger.warning("limit_buy_close: 无空头持仓")
            return {"status": "no_position", "filled": 0}
        qty = float(self.exchange.amount_to_precision(self._symbol, qty))
        ticker = self.exchange.fetch_ticker(self._symbol)
        ask = ticker.get("ask")
        if ask is None:
            logger.warning(f"限价平空: ask 为 None，直接市价平")
            return self.market_buy_cover(self._symbol, 0)
        ask = float(ask)
        try:
            order = self.exchange.create_order(
                self._symbol, "LIMIT", "buy", qty, ask,
                {"positionSide": "SHORT", "postOnly": True},
            )
            time.sleep(2)
            fetched = self.exchange.fetch_order(order["id"], self._symbol)
            filled = float(fetched.get("filled", 0) or 0)
            if filled >= qty * 0.999:
                logger.info(f"✅ 限价平空 maker 成交 @ {ask}")
                return fetched
            logger.info(f"⏳ 限价平空未成交(已填{filled:.4f}/{qty})，撤单回退市价")
            self.exchange.cancel_order(order["id"], self._symbol)
        except Exception as e:
            logger.warning(f"限价平空异常: {e}")
        return self.market_buy_cover(self._symbol, 0)

    def get_current_price(self, symbol: str) -> float:
        """获取当前实时价格"""
        try:
            ticker = self.exchange.fetch_ticker(self._symbol)
            return float(ticker["last"])
        except Exception:
            return 0.0
