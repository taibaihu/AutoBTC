#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""获取 BTC/USDT 和 ETH/USDT 实时价格，推送到 Telegram"""
import ccxt
from config import get_proxy_config
from notifier import Notifier

SYMBOLS = ["BTC/USDT", "ETH/USDT"]


def get_prices():
    proxies = get_proxy_config()
    exchange = ccxt.binance({"enableRateLimit": True, "proxies": proxies})
    messages = []
    for sym in SYMBOLS:
        try:
            ticker = exchange.fetch_ticker(sym)
            price = ticker["last"]
            change = ticker.get("percentage", 0) or 0
            emoji = "🟢" if change >= 0 else "🔴"
            messages.append(
                f"{emoji} <b>{sym}</b>\n"
                f"价格: <b>${price:,.2f}</b>\n"
                f"24h涨跌: {change:+.2f}%"
            )
        except Exception as e:
            messages.append(f"⚠️ <b>{sym}</b>\n获取失败: {e}")

    text = "\n\n".join(messages)
    return text


if __name__ == "__main__":
    notifier = Notifier()
    text = get_prices()
    print(text)
    notifier.send_sync(text)
    print("\n已推送到 Telegram.")
