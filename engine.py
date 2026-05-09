# -*- coding: utf-8 -*-
"""行情获取 & 订单执行模块"""
import ccxt
import pandas as pd
from config import API_KEY, SECRET_KEY, get_proxy_config


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
