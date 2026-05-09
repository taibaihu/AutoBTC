# -*- coding: utf-8 -*-
"""行情获取 & 订单执行模块"""
import logging
from typing import Optional

import ccxt
import pandas as pd
from config import API_KEY, SECRET_KEY, get_proxy_config

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

    def get_position(self) -> Optional[dict]:
        """查询当前多头持仓，返回 {size, entry_price, unrealized_pnl} 或 None"""
        try:
            positions = self.exchange.fetch_positions([self._symbol])
            for p in positions:
                size = float(p.get("contracts", 0) or 0)
                if size > 0 and p.get("side") == "long":
                    return {
                        "size": size,
                        "entry_price": float(p["entryPrice"]),
                        "unrealized_pnl": float(p["unrealizedPnl"]),
                    }
            return None
        except Exception as e:
            logger.warning(f"查询持仓失败: {e}")
            return None

    def calc_contract_amount(self, usdt_amount: float, price: float) -> float:
        """计算合约数量 = (USDT金额 × 杠杆) / 当前价"""
        raw = (usdt_amount * self.leverage) / price
        market = self.exchange.market(self._symbol)
        precision = market["precision"]["amount"]
        return float(self.exchange.amount_to_precision(self._symbol, raw))

    def market_buy(self, symbol: str, amount: float) -> dict:
        """市价开多 (amount 为 USDT 金额, 自动换算合约数)"""
        price = self.get_current_price(symbol) or self.get_current_price(self._symbol)
        quantity = self.calc_contract_amount(amount, price)
        return self.exchange.create_market_buy_order(self._symbol, quantity, {"positionSide": "LONG"})

    def market_sell(self, symbol: str, amount: float) -> dict:
        """市价平多 (amount 为 USDT 金额, 自动换算合约数)"""
        price = self.get_current_price(symbol) or self.get_current_price(self._symbol)
        quantity = self.calc_contract_amount(amount, price)
        return self.exchange.create_market_sell_order(self._symbol, quantity, {"positionSide": "LONG", "reduceOnly": True})

    def get_current_price(self, symbol: str) -> float:
        """获取当前实时价格"""
        try:
            ticker = self.exchange.fetch_ticker(self._symbol)
            return float(ticker["last"])
        except Exception:
            return 0.0
