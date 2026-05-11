#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10天回测脚本 —— 使用当前策略参数 (FastRangeStrategy + FastRangeShortStrategy)
模拟开多/开空/平仓，统计盈亏、胜率等
"""
import sys, os, json, logging
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import LEVERAGE, MAX_POSITION_USDT
from engine import FuturesEngine
from strategy import FastRangeStrategy, FastRangeShortStrategy

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger("backtest_10d")

# ── 当前线上参数 (与 config.py / DB 一致) ──
LONG_PARAMS = {
    "buy_zone": 0.20, "sell_zone": 0.95,
    "adx_threshold": 35.0, "max_slope": 0.02,
    "cooldown_bars": 2, "trend_ema_period": 100,
}
SHORT_PARAMS = {
    "buy_zone": 0.15, "sell_zone": 0.80,
    "adx_threshold": 35.0, "max_slope": 0.02,
    "cooldown_bars": 2, "trend_ema_period": 100,
}

SYMBOL = "BTC/USDT:USDT"
TIMEFRAME = "15m"
DAYS = 10
LIMIT = DAYS * 24 * 4 + 300  # 15m 周期


def run_backtest():
    engine = FuturesEngine()

    logger.info(f"拉取 {DAYS} 天 {TIMEFRAME} 数据...")
    df = engine.fetch_ohlcv(SYMBOL, TIMEFRAME, LIMIT)
    logger.info(f"获取到 {len(df)} 根 K 线 ({df.index[0]} ~ {df.index[-1]})")

    long_strat = FastRangeStrategy(**LONG_PARAMS)
    short_strat = FastRangeShortStrategy(**SHORT_PARAMS)

    # ── 交易记录 ──
    trades = []
    long_pos = None   # {entry_price, entry_idx, entry_time}
    short_pos = None

    total_bars = len(df)
    require = 160  # 预热

    for i in range(require, total_bars):
        slice_df = df.iloc[:i + 1]
        price = float(df["close"].iloc[i])
        ts = df.index[i]

        # === 多头策略 ===
        signal_long, ind_long = long_strat.generate_signal(slice_df)
        if signal_long == 1 and long_pos is None:   # BUY = 开多
            long_pos = {"entry_price": price, "entry_idx": i, "entry_time": ts}
            trades.append({
                "type": "LONG", "action": "开多", "time": ts,
                "price": price, "exit_price": None, "pnl": None,
                "reason": ind_long.get("confirmed_by", ""),
            })
        elif signal_long == -1 and long_pos is not None:  # SELL = 平多
            pnl_pct = (price - long_pos["entry_price"]) / long_pos["entry_price"]
            pnl_usdt = pnl_pct * MAX_POSITION_USDT * LEVERAGE
            trades.append({
                "type": "LONG", "action": "平多", "time": ts,
                "price": price, "entry_price": long_pos["entry_price"],
                "entry_time": long_pos["entry_time"],
                "pnl_pct": round(pnl_pct * 100, 2),
                "pnl_usdt": round(pnl_usdt, 2),
                "reason": ind_long.get("confirmed_by", ""),
            })
            long_pos = None

        # === 空头策略 ===
        signal_short, ind_short = short_strat.generate_signal(slice_df)
        if signal_short == -1 and short_pos is None:   # SELL = 开空
            short_pos = {"entry_price": price, "entry_idx": i, "entry_time": ts}
            trades.append({
                "type": "SHORT", "action": "开空", "time": ts,
                "price": price, "exit_price": None, "pnl": None,
                "reason": ind_short.get("confirmed_by", ""),
            })
        elif signal_short == 1 and short_pos is not None:  # BUY = 平空
            pnl_pct = (short_pos["entry_price"] - price) / short_pos["entry_price"]
            pnl_usdt = pnl_pct * MAX_POSITION_USDT * LEVERAGE
            trades.append({
                "type": "SHORT", "action": "平空", "time": ts,
                "price": price, "entry_price": short_pos["entry_price"],
                "entry_time": short_pos["entry_time"],
                "pnl_pct": round(pnl_pct * 100, 2),
                "pnl_usdt": round(pnl_usdt, 2),
                "reason": ind_short.get("confirmed_by", ""),
            })
            short_pos = None

    return df, trades


def print_stats(trades, df):
    print("\n" + "=" * 80)
    print(f"📊 10天回测报告 ({DAYS}天 {TIMEFRAME})")
    start = df.index[0] if len(df) else "?"
    end = df.index[-1] if len(df) else "?"
    print(f"   数据范围: {start} ~ {end}")
    price_start = float(df["close"].iloc[0]) if len(df) else 0
    price_end = float(df["close"].iloc[-1]) if len(df) else 0
    print(f"   起止价格: {price_start:.0f} → {price_end:.0f} ({(price_end-price_start)/price_start*100:+.2f}%)")
    print("=" * 80)

    # 按策略分类
    long_trades = [t for t in trades if t["type"] == "LONG"]
    short_trades = [t for t in trades if t["type"] == "SHORT"]

    # 已完成交易（有盈亏的）
    closed_long = [t for t in long_trades if t.get("pnl_usdt") is not None]
    closed_short = [t for t in short_trades if t.get("pnl_usdt") is not None]

    for label, closed, all_t in [("🟢 多头 LONG", closed_long, long_trades),
                                   ("🔴 空头 SHORT", closed_short, short_trades)]:
        opens = [t for t in all_t if t["action"] == "开多" or t["action"] == "开空"]
        closes = closed

        print(f"\n{label}:")
        print(f"   开仓信号: {len(opens)} 次")
        print(f"   平仓信号: {len(closes)} 次")

        if closes:
            wins = [t for t in closes if t["pnl_usdt"] > 0]
            losses = [t for t in closes if t["pnl_usdt"] <= 0]
            win_rate = len(wins) / len(closes) * 100
            total_pnl = sum(t["pnl_usdt"] for t in closes)
            avg_pnl = total_pnl / len(closes)
            max_win = max(t["pnl_usdt"] for t in closes) if wins else 0
            max_loss = min(t["pnl_usdt"] for t in closes) if losses else 0
            avg_win = sum(t["pnl_usdt"] for t in wins) / len(wins) if wins else 0
            avg_loss = sum(t["pnl_usdt"] for t in losses) / len(losses) if losses else 0

            print(f"   胜  率: {win_rate:.1f}% ({len(wins)}胜/{len(losses)}负)")
            print(f"   总盈亏: {total_pnl:+.2f} USDT (100U×{LEVERAGE}x)")
            print(f"   平均盈亏: {avg_pnl:+.2f} USDT/笔")
            print(f"   最大盈利: {max_win:+.2f} USDT")
            print(f"   最大亏损: {max_loss:+.2f} USDT")
            print(f"   平均盈: {avg_win:.2f} / 平均亏: {avg_loss:.2f}")
            if avg_loss != 0:
                print(f"   盈亏比: {abs(avg_win/avg_loss):.2f}")
        else:
            print("   无平仓记录 (全部持仓中)")

    # 全部交易明细
    print("\n" + "-" * 80)
    print("📋 详细交易记录:")
    print("-" * 80)
    fmt = "{:<6} {:<8} {:<20} {:<10} {:<10} {:<10} {:<10}"
    print(fmt.format("类型", "方向", "时间", "价格", "入场价", "盈亏%", "盈亏U"))
    print("-" * 80)
    for t in trades:
        if t["action"] in ("开多", "开空"):
            print(f"{t['type']:<6} {t['action']:<8} {str(t['time'])[:19]:<20} {t['price']:<10.0f} {'-':<10} {'-':<10} {'-':<10}")
        else:
            print(f"{t['type']:<6} {t['action']:<8} {str(t['time'])[:19]:<20} {t['price']:<10.0f} {t['entry_price']:<10.0f} {t['pnl_pct']:<+9.2f}% {t['pnl_usdt']:<+9.2f}")

    # 汇总
    print("\n" + "=" * 80)
    all_closed = closed_long + closed_short
    if all_closed:
        total_pnl = sum(t["pnl_usdt"] for t in all_closed)
        wins = [t for t in all_closed if t["pnl_usdt"] > 0]
        print(f"📈 总  结: {len(all_closed)} 笔平仓 | 总盈亏 {total_pnl:+.2f} USDT | 胜率 {len(wins)/len(all_closed)*100:.1f}%")
    print("=" * 80)


def main():
    df, trades = run_backtest()
    print_stats(trades, df)


if __name__ == "__main__":
    main()
