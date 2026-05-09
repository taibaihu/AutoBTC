#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时价格监控 —— 定时获取币安价格并推送到 Telegram"""
import time
import asyncio
import ccxt
from config import get_proxy_config
import os

# load_dotenv 已在 config.py 中调用

# ===== 配置 =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SYMBOLS = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]   # 监控的交易对
INTERVAL = 60                                      # 推送间隔（秒）

# ===== 币安（无需 API Key 也能查行情）=====
proxies = get_proxy_config()
exchange = ccxt.binance({"enableRateLimit": True, "proxies": proxies})


async def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[无Telegram配置] " + text)
        return
    try:
        from telegram import Bot
        await Bot(TELEGRAM_BOT_TOKEN).send_message(TELEGRAM_CHAT_ID, text, parse_mode="HTML")
    except Exception as e:
        print(f"推送失败: {e}")


async def main():
    # 启动推送
    await send_telegram("<b>📡 价格监控已启动</b>\n" + "\n".join(SYMBOLS))

    while True:
        lines = []
        for sym in SYMBOLS:
            try:
                ticker = exchange.fetch_ticker(sym)
                price = ticker["last"]
                change = ticker.get("percentage", 0) or 0
                arrow = "🟢" if change >= 0 else "🔴"
                lines.append(f"{arrow} <b>{sym}</b>: ${price:,.2f}  ({change:+.2f}%)")
            except Exception as e:
                lines.append(f"⚠️ {sym}: {e}")

        msg = "\n".join(lines)
        now = time.strftime("%H:%M:%S")
        print(f"[{now}]\n{msg}\n")
        await send_telegram(msg)

        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
