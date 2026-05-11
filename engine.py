# -*- coding: utf-8 -*-
"""行情获取 & 订单执行模块"""
import logging
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
                if p.get("positionSide") == side:
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
                p_side = p.get("positionSide", "")
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
        """撤销当前交易对所有挂单（止盈止损单）"""
        try:
            orders = self.exchange.fetch_open_orders(self._symbol)
            for o in orders:
                self.exchange.cancel_order(o["id"], self._symbol)
            if orders:
                logger.info(f"已撤销 {len(orders)} 个挂单")
        except Exception as e:
            logger.warning(f"撤销挂单异常: {e}")

    def calc_contract_amount(self, usdt_amount: float, price: float) -> float:
        """计算合约数量 = (USDT金额 × 杠杆) / 当前价"""
        raw = (usdt_amount * self.leverage) / price
        market = self.exchange.market(self._symbol)
        precision = market["precision"]["amount"]
        return float(self.exchange.amount_to_precision(self._symbol, raw))

    def market_buy(self, symbol: str, amount: float) -> dict:
        """市价开多 — 固定 0.05 BTC"""
        market = self.exchange.market(self._symbol)
        qty = float(self.exchange.amount_to_precision(self._symbol, self.order_qty))
        return self.exchange.create_market_buy_order(self._symbol, qty, {"positionSide": "LONG"})

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
        market = self.exchange.market(self._symbol)
        qty = float(self.exchange.amount_to_precision(self._symbol, self.order_qty))
        return self.exchange.create_market_sell_order(self._symbol, qty, {"positionSide": "SHORT"})

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
        """将 order_qty 按交易所精度格式化"""
        return float(self.exchange.amount_to_precision(self._symbol, self.order_qty))

    def _get_precise_price(self, price: float) -> float:
        """将价格按交易所精度格式化"""
        return float(self.exchange.price_to_precision(self._symbol, price))

    def set_tp_sl_long(self, entry_price: float):
        """开多后挂止盈止损单 (reduceOnly, 币安侧)"""
        qty = self._get_precise_qty()
        tp_price = self._get_precise_price(entry_price * (1 + MIN_PROFIT_RATE))
        sl_price = self._get_precise_price(entry_price * (1 - MAX_LOSS_RATE))

        self.cancel_all_orders()
        try:
            self.exchange.create_order(
                self._symbol, "TAKE_PROFIT_MARKET", "sell", qty, None,
                {"stopPrice": tp_price, "reduceOnly": True, "positionSide": "LONG"},
            )
            logger.info(f"✅ 多单止盈挂单 {tp_price}")
        except Exception as e:
            logger.warning(f"止盈挂单失败: {e}")
        try:
            self.exchange.create_order(
                self._symbol, "STOP_MARKET", "sell", qty, None,
                {"stopPrice": sl_price, "reduceOnly": True, "positionSide": "LONG"},
            )
            logger.info(f"✅ 多单止损挂单 {sl_price}")
        except Exception as e:
            logger.warning(f"止损挂单失败: {e}")

    def set_tp_sl_short(self, entry_price: float):
        """开空后挂止盈止损单 (reduceOnly, 币安侧)"""
        qty = self._get_precise_qty()
        tp_price = self._get_precise_price(entry_price * (1 - MIN_PROFIT_RATE))
        sl_price = self._get_precise_price(entry_price * (1 + MAX_LOSS_RATE))

        self.cancel_all_orders()
        try:
            self.exchange.create_order(
                self._symbol, "TAKE_PROFIT_MARKET", "buy", qty, None,
                {"stopPrice": tp_price, "reduceOnly": True, "positionSide": "SHORT"},
            )
            logger.info(f"✅ 空单止盈挂单 {tp_price}")
        except Exception as e:
            logger.warning(f"止盈挂单失败: {e}")
        try:
            self.exchange.create_order(
                self._symbol, "STOP_MARKET", "buy", qty, None,
                {"stopPrice": sl_price, "reduceOnly": True, "positionSide": "SHORT"},
            )
            logger.info(f"✅ 空单止损挂单 {sl_price}")
        except Exception as e:
            logger.warning(f"止损挂单失败: {e}")

    def get_current_price(self, symbol: str) -> float:
        """获取当前实时价格"""
        try:
            ticker = self.exchange.fetch_ticker(self._symbol)
            return float(ticker["last"])
        except Exception:
            return 0.0
