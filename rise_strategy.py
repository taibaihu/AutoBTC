#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全维度下跌监控策略
riseRt = 100+ 币种中上涨的比例（0~1）

4 个时间维度的占比同步下降 → 市场全面转弱 → 推送 Telegram 告警
  - 10minute: 最近 N 分钟趋势向下
  - 1Hour:    最近 N 分钟趋势向下
  - 2Hour:    最近 N 分钟趋势向下
  - day:      最近 N 分钟趋势向下 (数据点稀疏，窗口更大)
"""
import os
import time
import logging
from typing import Optional
import numpy as np
import pymysql
import ccxt
from datetime import datetime
from config import get_proxy_config
from notifier import Notifier

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ===== 数据库配置（从环境变量读取）=====
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", ""),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", ""),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", ""),
    "connect_timeout": 5,
}

# ===== 策略参数 =====
CHECK_INTERVAL = 30           # 检查间隔（秒）
ALERT_COOLDOWN = 300          # 告警冷却期（秒）
TREND_WINDOW = 30             # 10min/1Hour/2Hour 趋势检测窗口（分钟）
TREND_WINDOW_DAY = 120        # day 数据趋势检测窗口（分钟，数据稀疏故更长）
MIN_DATA_POINTS = 5           # 最少数据点数（<此值不判定）
FIELD_NAMES = ["10minute", "1Hour", "2Hour", "day"]
FIELD_LABELS = {
    "10minute": "10min",
    "1Hour": "1Hour",
    "2Hour": "2Hour",
    "day": "Day",
}


def get_conn():
    return pymysql.connect(**DB_CONFIG)


def fetch_recent(cur, field_name: str, minutes: int):
    """获取某维度最近 N 分钟的数据（按时间升序）"""
    sql = """
        SELECT modify_time, CAST(riseRt AS DECIMAL(10,6))
        FROM rf_avg_history
        WHERE fieldName = %s AND modify_time >= NOW() - INTERVAL %s MINUTE
        ORDER BY modify_time ASC
    """
    cur.execute(sql, (field_name, minutes))
    rows = cur.fetchall()
    if not rows:
        return [], []
    return [r[0] for r in rows], [float(r[1]) for r in rows]


def trend_info(values):
    """返回 (是否下降, 斜率, 当前值)"""
    if len(values) < MIN_DATA_POINTS:
        return False, 0.0, values[-1] if values else 0.0
    x = np.arange(len(values), dtype=float)
    slope = np.polyfit(x, values, 1)[0]
    return slope < 0, slope, values[-1]


_exchange = None


def _get_exchange():
    global _exchange
    if _exchange is None:
        proxies = get_proxy_config()
        _exchange = ccxt.binance({"enableRateLimit": True, "proxies": proxies})
    return _exchange


def fetch_btc_eth_prices():
    """获取 BTC/ETH 实时价"""
    try:
        ex = _get_exchange()
        result = {}
        for sym in ["BTC/USDT", "ETH/USDT"]:
            t = ex.fetch_ticker(sym)
            result[sym] = {"price": t["last"], "change": t.get("percentage", 0) or 0}
        return result
    except Exception as e:
        logger.warning(f"获取价格失败: {e}")
        return None


def check_signal() -> tuple:
    """检测 4 个维度是否全在下降"""
    conn = get_conn()
    cur = conn.cursor()
    try:
        trends = {}
        all_down = True
        for fn in FIELD_NAMES:
            window = TREND_WINDOW_DAY if fn == "day" else TREND_WINDOW
            _, vals = fetch_recent(cur, fn, window)
            down, slope, current = trend_info(vals)
            trends[fn] = {"down": down, "slope": slope, "current": current, "n": len(vals)}
            if not down:
                all_down = False

        # 构建消息
        lines = []
        for fn in FIELD_NAMES:
            t = trends[fn]
            arrow = "🔻" if t["down"] else "🔺"
            lines.append(
                f"{arrow} <b>{FIELD_LABELS[fn]}</b>: {t['current']:.3f}  "
                f"(slope={t['slope']:+.4f}, n={t['n']})"
            )

        detail = " | ".join(
            f"{FIELD_LABELS[fn]}:{'↓' if trends[fn]['down'] else '↑'}"
            for fn in FIELD_NAMES
        )

        if all_down:
            prices = fetch_btc_eth_prices()
            price_lines = ""
            if prices:
                for sym, info in prices.items():
                    coin = sym.split("/")[0]
                    arrow = "🟢" if info["change"] >= 0 else "🔴"
                    price_lines += (
                        f"{arrow} <b>{coin}</b>: ${info['price']:,.2f} "
                        f"({info['change']:+.2f}%)\n"
                    )

            msg = (
                f"<b>🚨 全维度下跌告警</b>\n"
                f"<code>──────────────────</code>\n" +
                "\n".join(lines) +
                f"\n<code>──────────────────</code>\n"
                f"{price_lines}"
                f"<code>──────────────────</code>\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return True, msg, trends, prices

        return False, detail, trends, None

    finally:
        cur.close()
        conn.close()


def main():
    notifier = Notifier()
    last_alert_time = 0.0

    logger.info("🔍 全维度下跌监控启动")
    notifier.send(
        f"<b>🔍 全维度下跌监控启动</b>\n"
        f"检测: 10min/1Hour/2Hour 近{TREND_WINDOW}min + Day 近{TREND_WINDOW_DAY}min\n"
        f"条件: 4维度同步下降 | 间隔{CHECK_INTERVAL}s | 冷却{ALERT_COOLDOWN}s"
    )

    while True:
        try:
            triggered, info, trends, _ = check_signal()

            if triggered:
                now = time.time()
                if now - last_alert_time > ALERT_COOLDOWN:
                    logger.warning(f"🚨 触发! {info}")
                    notifier.send(info)
                    last_alert_time = now
                else:
                    cd = int(ALERT_COOLDOWN - (now - last_alert_time))
                    logger.info(f"⏳ 冷却中({cd}s) — {info}")
            else:
                logger.info(f"📊 {info}")

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("🛑 手动停止")
            break
        except Exception as e:
            logger.error(f"⚠️ 异常: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
