#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KDJ金叉策略回测 — 1年15m数据，参数优化"""
import sys, os, time, json, math
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
import pandas as pd
import numpy as np

from strategy import BUY, SELL, HOLD

# ── 参数定义（可调） ──

DEFAULT_PARAMS = {
    "k_period": 9,          # KDJ K 周期
    "d_period": 3,          # KDJ D 周期
    "oversold_k": 40,       # [OPT] 原30→40 放宽超卖阈值
    "overbought_j": 100,    # J>100 平多（当前未用）
    "cooldown_bars": 4,     # 平仓后冷却(4根=1h)
    "max_hold_candles": 12, # 最多持有12根(3h)
    "ema_period": 100,      # EMA趋势过滤
    "stop_loss_pct": 0.3,   # [OPT] 原0.5→0.3 更紧止损
    "ema_dev_filter": -3,   # EMA100偏离>-3%才开多
    "use_bb_exit": True,    # 布林上轨平仓
    "bb_period": 14,        # 布林周期
    "bb_std": 2.0,          # 布林标准差
    "bb_exit_threshold": 0.995,  # 触及上轨99.5%平仓
    "entry_offset": -20,    # [OPT] 原-10→-20 更低入场
    "use_limit_entry": True, # 限价单（模拟滑点）
}

# ── 多参数调优范围 ──

TUNE_RANGES = {
    "k_period": [5, 7, 9, 12, 14],
    "oversold_k": [20, 25, 30, 35, 40],
    "stop_loss_pct": [0.3, 0.5, 0.8, 1.0, 1.5],
    "max_hold_candles": [8, 12, 16, 24],  # 2h, 3h, 4h, 6h
    "entry_offset": [-5, -10, -15, -20, 0],
    "ema_period": [50, 100, 150, 200],
}


# ── KDJ 计算（同 strategy.py 逻辑一致） ──

def calc_kdj(high, low, close, k_period=9, d_period=3):
    low_min = low.rolling(k_period).min()
    high_max = high.rolling(k_period).max()
    rsv = (close - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1 / d_period, adjust=False).mean()
    d = k.ewm(alpha=1 / d_period, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def calc_bb(close, period=14, std_mult=2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid + std_mult * std, mid, mid - std_mult * std


# ── 模拟交易 ──

def simulate(params: dict, df: pd.DataFrame, verbose=False) -> dict:
    """
    在 df 上模拟 KDJ 策略。
    返回 {total_trades, win_rate, total_pnl_pct, max_dd_pct, sharpe, trades[]}
    """
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    index = df.index
    n = len(df)

    # 提前计算 KDJ
    k_series, d_series, j_series = calc_kdj(
        df["high"], df["low"], df["close"],
        params["k_period"], params["d_period"],
    )
    # 提前计算 EMA100
    ema_series = df["close"].ewm(span=params["ema_period"], adjust=False).mean()
    # 提前计算布林
    bb_up_series, _, _ = calc_bb(df["close"], params["bb_period"], params["bb_std"])

    need = max(params["ema_period"], 200)  # 预热

    trades = []
    position = None          # "long" or None
    entry_price = 0.0
    entry_bar = 0
    last_trade_bar = -9999

    for i in range(need, n):
        cur_price = close[i]
        cur_time = index[i]

        # -- 冷却（只禁止开新仓，不禁止平仓） --
        bars_since_trade = i - last_trade_bar if last_trade_bar > 0 else 9999
        in_cooldown = bars_since_trade < params["cooldown_bars"]

        # -- 开仓逻辑 --
        if position is None and not in_cooldown:
            cur_k = k_series.iloc[i]
            cur_d = d_series.iloc[i]
            prev_k = k_series.iloc[i - 1]
            prev_d = d_series.iloc[i - 1]

            golden_cross = prev_k <= prev_d and cur_k > cur_d
            ema_val = ema_series.iloc[i]
            ema_dev = (cur_price / ema_val - 1) * 100

            if golden_cross and cur_k < params["oversold_k"] and ema_dev > params["ema_dev_filter"]:
                # 开仓
                entry = cur_price + params["entry_offset"] if params["use_limit_entry"] else cur_price
                position = "long"
                entry_price = entry
                entry_bar = i
                last_trade_bar = i

        # -- 持仓中，检查平仓 --
        if position == "long":
            exit_reason = None
            exit_price = cur_price  # 默认市价平

            # 止损
            loss_pct = (cur_price - entry_price) / entry_price * 100
            if loss_pct <= -params["stop_loss_pct"]:
                exit_reason = "止损"
                exit_price = entry_price * (1 - params["stop_loss_pct"] / 100)

            # 超时
            bars_held = i - entry_bar
            if exit_reason is None and bars_held >= params["max_hold_candles"]:
                exit_reason = "超时"

            # 布林上轨
            if exit_reason is None and params["use_bb_exit"]:
                bb_up = bb_up_series.iloc[i]
                if not np.isnan(bb_up) and cur_price >= bb_up * params["bb_exit_threshold"]:
                    exit_reason = "布林上轨"

            if exit_reason:
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    "entry_time": index[entry_bar],
                    "exit_time": cur_time,
                    "entry_price": round(entry_price, 1),
                    "exit_price": round(exit_price, 1),
                    "pnl_pct": round(pnl_pct, 2),
                    "bars_held": i - entry_bar,
                    "exit_reason": exit_reason,
                })
                position = None

    # ── 计算统计 ──
    if not trades:
        return {"total_trades": 0, "win_rate": 0, "total_pnl_pct": 0,
                "max_dd_pct": 0, "sharpe": 0, "trades": [], "avg_hold_bars": 0}

    pnl_list = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]
    total_pnl = sum(pnl_list)
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    # 最大回撤（从权益曲线算）
    equity = 100.0
    peak = 100.0
    max_dd = 0.0
    equity_curve = [100.0]
    for p in pnl_list:
        equity *= (1 + p / 100)
        equity_curve.append(equity)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # 夏普（年化，无风险0）
    if len(pnl_list) > 1:
        avg_pnl = np.mean(pnl_list)
        std_pnl = np.std(pnl_list)
        # 假设每笔约3小时 = 每天8笔
        trades_per_year = len(trades) / (n / (365 * 24 * 4))  # 15min bars
        sharpe = (avg_pnl / std_pnl) * math.sqrt(trades_per_year) if std_pnl > 0 else 0
    else:
        sharpe = 0

    avg_hold = np.mean([t["bars_held"] for t in trades])

    return {
        "total_trades": len(trades),
        "win_rate": round(win_rate, 1),
        "total_pnl_pct": round(total_pnl, 2),
        "avg_pnl_pct": round(np.mean(pnl_list), 2) if pnl_list else 0,
        "avg_win_pct": round(np.mean(wins), 2) if wins else 0,
        "avg_loss_pct": round(np.mean(losses), 2) if losses else 0,
        "max_dd_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "avg_hold_bars": round(avg_hold, 1),
        "trades": trades,
        "equity_curve": [round(e, 2) for e in equity_curve],
        "win_loss_ratio": round(abs(np.mean(wins) / np.mean(losses)), 2) if losses and wins else 0,
    }


def fetch_data(symbol="BTC/USDT", tf="15m", days=365) -> pd.DataFrame:
    """从币安分批获取历史K线（处理分页限制）"""
    ex = ccxt.binance({"enableRateLimit": True})
    now = ex.milliseconds()
    since = now - days * 86400 * 1000
    all_ohlcv = []
    limit = 1000  # 单次最大条数

    while since < now:
        ohlcv = ex.fetch_ohlcv(symbol, tf, since=since, limit=limit)
        if not ohlcv:
            break
        all_ohlcv.extend(ohlcv)
        since = ohlcv[-1][0] + 1  # 下一批次从最后一条之后开始
        if len(ohlcv) < limit:
            break
        time.sleep(0.3)

    df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df


def run_backtest():
    params = dict(DEFAULT_PARAMS)

    print("=" * 60)
    print("KDJ金叉策略回测")
    print("=" * 60)
    print(f"\n获取1年15m数据...")
    df = fetch_data("BTC/USDT", "15m", days=365)
    print(f"  共 {len(df)} 根K线 ({df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')})")

    # ── 1. 默认参数回测 ──
    print(f"\n{'─'*40}")
    print("【1】默认参数回测")
    print(f"{'─'*40}")
    result = simulate(params, df, verbose=True)
    _print_result(result)

    # ── 2. 退出方式分布 ──
    print(f"\n{'─'*40}")
    print("【2】退出方式分析")
    print(f"{'─'*40}")
    if result["trades"]:
        reasons = defaultdict(list)
        for t in result["trades"]:
            reasons[t["exit_reason"]].append(t["pnl_pct"])
        for reason, pnls in sorted(reasons.items()):
            cnt = len(pnls)
            avg = np.mean(pnls)
            wr = sum(1 for p in pnls if p > 0) / cnt * 100
            print(f"  {reason}: {cnt}笔, 胜率{wr:.0f}%, 均盈亏{avg:+.2f}%")

    # ── 3. 参数调优 ──
    print(f"\n{'─'*40}")
    print("【3】参数调优扫描")
    print(f"{'─'*40}")

    best_sharpe = -999
    best_params = None
    best_result = None

    for param_name, values in TUNE_RANGES.items():
        print(f"\n  ▶ 调优 {param_name} = {values}")
        local_best = -999
        local_best_val = None
        for v in values:
            test_params = dict(DEFAULT_PARAMS)
            test_params[param_name] = v
            r = simulate(test_params, df)
            score = r["sharpe"] * 2 + r["win_rate"] / 10 + min(r["total_pnl_pct"] / 5, 5) - abs(r["max_dd_pct"]) / 5
            marker = " ◀" if r["sharpe"] > local_best else ""
            if r["sharpe"] > local_best:
                local_best = r["sharpe"]
                local_best_val = v
            print(f"    {param_name}={v:>4}: {r['total_trades']:>3}笔 胜率{r['win_rate']:>4.0f}% PnL{r['total_pnl_pct']:>+6.2f}% "
                  f"DD{r['max_dd_pct']:>5.1f}% Sharpe{r['sharpe']:>5.2f}{marker}")

            if r["sharpe"] > best_sharpe and r["total_trades"] >= 10:
                best_sharpe = r["sharpe"]
                best_params = dict(test_params)
                best_result = r

    # ── 4. 新旧参数对比 ──
    print(f"\n{'─'*40}")
    print("【4】新旧参数对比")
    print(f"{'─'*40}")
    old_params = dict(DEFAULT_PARAMS)
    old_params["oversold_k"] = 30
    old_params["stop_loss_pct"] = 0.5
    old_params["entry_offset"] = -10
    old_result = simulate(old_params, df)

    print(f"  {'指标':<16} {'旧(30/0.5/-10)':<20} {'新(40/0.3/-20)':<20}")
    print(f"  {'─'*52}")
    for key, label in [("total_trades", "总交易"), ("win_rate", "胜率%"),
                        ("total_pnl_pct", "总盈亏%"), ("avg_pnl_pct", "均每笔%"),
                        ("avg_win_pct", "均盈利%"), ("avg_loss_pct", "均亏损%"),
                        ("win_loss_ratio", "盈亏比"), ("max_dd_pct", "最大回撤%"),
                        ("sharpe", "夏普"), ("avg_hold_bars", "均持有(K线)")]:
        old_v = old_result.get(key, 0)
        new_v = result.get(key, 0)
        fmt = f"%>{len(key)+4}.2f" if isinstance(old_v, float) else f"%>{len(key)+4}"
        print(f"  {label:<14} {old_v:>16} {new_v:>16}")
    print()
    # PnL 对比图（文本）
    if old_result["equity_curve"] and result["equity_curve"]:
        def make_sparkline(curve, width=40):
            if not curve:
                return ""
            mn, mx = min(curve), max(curve)
            rng = mx - mn if mx > mn else 1
            bars = []
            for v in curve[::max(1, len(curve)//width)]:
                h = int((v - mn) / rng * 8)
                bars.append("▁▂▃▄▅▆▇█"[min(h, 7)])
            return "".join(bars)
        print(f"  权益曲线（旧）: {make_sparkline(old_result['equity_curve'])}")
        print(f"  权益曲线（新）: {make_sparkline(result['equity_curve'])}")
        print(f"  终值(旧): {old_result['equity_curve'][-1]:.1f}  终值(新): {result['equity_curve'][-1]:.1f}")

    # ── 5. 最优参数组合回测 ──
    if best_params:
        print(f"\n{'─'*40}")
        print("【4】最优参数组合")
        print(f"{'─'*40}")
        for k, v in best_params.items():
            default = DEFAULT_PARAMS[k]
            flag = " ★" if v != default else ""
            print(f"  {k}: {v} (默认={default}){flag}")
        print()
        _print_result(best_result)


def _print_result(r):
    if r["total_trades"] == 0:
        print("  ⚠️ 无交易")
        return
    print(f"  总交易: {r['total_trades']} 笔")
    print(f"  胜率: {r['win_rate']:.1f}%")
    print(f"  总盈亏: {r['total_pnl_pct']:+.2f}%")
    print(f"  平均每笔: {r['avg_pnl_pct']:+.2f}%")
    print(f"  平均盈利: {r['avg_win_pct']:+.2f}%")
    print(f"  平均亏损: {r['avg_loss_pct']:+.2f}%")
    print(f"  盈亏比: {r['win_loss_ratio']}")
    print(f"  最大回撤: {r['max_dd_pct']:.1f}%")
    print(f"  夏普比率: {r['sharpe']}")
    print(f"  平均持有: {r['avg_hold_bars']:.0f} 根K线 ({r['avg_hold_bars']*15/60:.1f}h)")

    if r["trades"]:
        by_reason = defaultdict(list)
        for t in r["trades"]:
            by_reason[t["exit_reason"]].append(t)
        print(f"\n  退出分布:")
        for reason, ts in sorted(by_reason.items()):
            pnls = [t["pnl_pct"] for t in ts]
            wr = sum(1 for p in pnls if p > 0) / len(ts) * 100
            print(f"    {reason}: {len(ts)}笔 胜率{wr:.0f}% 均盈亏{np.mean(pnls):+.2f}%")


if __name__ == "__main__":
    run_backtest()
