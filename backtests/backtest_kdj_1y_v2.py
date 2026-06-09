#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KDJ金叉策略回测 — 1年15m数据
【关键改进】
- 考虑盘中成交：用 H/L 模拟限价单成交和止盈止损触发
- 往下挂单 -50 的成交逻辑
- 挂单15分钟未成交自动撤单
- +0.5%固定止盈（替代布林上轨）
"""
import sys, os, time, math
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
import pandas as pd
import numpy as np

# ── 当前 bot 实际参数 ──

BOT_PARAMS = {
    "k_period": 9,              # KDJ K 周期
    "d_period": 2,              # KDJ D 周期 (bot用的是2)
    "oversold_k": 25,           # K<25 超卖 (回测最佳)
    "cooldown_bars": 2,         # 平仓后冷却2根(30min)
    "max_hold_candles": 8,      # 最多持有8根(2h)
    "ema_period": 100,          # EMA趋势过滤
    "ema_dev_filter": 0,        # 仅价格>EMA100才开多 (回测正EV关键)
    "stop_loss_pct": 0.8,       # -0.8%止损
    "take_profit_pct": 0.3,     # +0.3%固定止盈
    "entry_offset": -40,        # 限价单低于市价$40
    "order_timeout_bars": 1,    # 挂单1根K线(15min)未成交撤单
}

# ── 调优参数 ──

TUNE_RANGES = {
    "oversold_k": [25, 30, 35, 40, 45],
    "stop_loss_pct": [0.3, 0.5, 0.8, 1.0],
    "take_profit_pct": [0.3, 0.5, 0.8, 1.0, 1.5],
    "entry_offset": [-30, -40, -50, -60, -80],
    "max_hold_candles": [8, 12, 16, 24],
}


# ── KDJ 计算 ──

def calc_kdj(high, low, close, k_period=9, d_period=3):
    low_min = low.rolling(k_period).min()
    high_max = high.rolling(k_period).max()
    rsv = (close - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1 / d_period, adjust=False).mean()
    d = k.ewm(alpha=1 / d_period, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


# ── 带盘中成交模拟的回测 ──

def simulate(params: dict, df: pd.DataFrame) -> dict:
    """
    模拟 KDJ 策略，考虑盘中 H/L 成交。
    返回统计数据。
    """
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    # 提前计算指标
    k_series, d_series, j_series = calc_kdj(
        df["high"], df["low"], df["close"],
        params["k_period"], params["d_period"],
    )
    ema_series = df["close"].ewm(span=params["ema_period"], adjust=False).mean()

    need = max(params["ema_period"], 150)
    trades = []
    position = None          # "long" or None
    entry_price = 0.0
    entry_bar = 0
    last_trade_bar = -9999

    pending_order_price = 0.0   # 挂单价
    pending_order_bar = -9999   # 挂单起始K线

    for i in range(need, n):
        cur_close = close[i]
        cur_high = high[i]
        cur_low = low[i]
        cur_time = df.index[i]

        # ── 有挂单中，检查是否成交或超时 ──
        if position is None and pending_order_bar >= 0:
            bars_pending = i - pending_order_bar
            filled = cur_low <= pending_order_price  # 盘中最低价触到挂单价即成交

            if filled:
                entry_price = pending_order_price
                position = "long"
                entry_bar = i
                last_trade_bar = i
                pending_order_bar = -9999
                pending_order_price = 0

            elif bars_pending >= params["order_timeout_bars"]:
                # 超时撤单
                pending_order_bar = -9999
                pending_order_price = 0
                # 撤单后不清掉 last_trade_bar，可以立即检查新信号

        # ── 持仓中，检查平仓（考虑盘中触发） ──
        if position == "long":
            exit_reason = None
            exit_price = cur_close  # 默认按收盘

            # 止损：盘中最低价触到止损线
            sl_price = entry_price * (1 - params["stop_loss_pct"] / 100)
            if cur_low <= sl_price:
                exit_reason = "止损"
                exit_price = sl_price

            # 止盈：盘中最高价触到止盈线
            if exit_reason is None:
                tp_price = entry_price * (1 + params["take_profit_pct"] / 100)
                if cur_high >= tp_price:
                    exit_reason = "止盈+0.5%"
                    exit_price = tp_price

            # 超时
            bars_held = i - entry_bar
            if exit_reason is None and bars_held >= params["max_hold_candles"]:
                exit_reason = "超时"

            if exit_reason:
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    "entry_time": df.index[entry_bar],
                    "exit_time": cur_time,
                    "entry_price": round(entry_price, 1),
                    "exit_price": round(exit_price, 1),
                    "pnl_pct": round(pnl_pct, 2),
                    "bars_held": i - entry_bar,
                    "exit_reason": exit_reason,
                })
                position = None

        # ── 无持仓、无挂单 -> 检查开仓信号 ──
        if position is None and pending_order_bar < 0:
            bars_since_trade = i - last_trade_bar if last_trade_bar > 0 else 9999
            in_cooldown = bars_since_trade < params["cooldown_bars"]

            if not in_cooldown:
                cur_k = k_series.iloc[i]
                cur_d = d_series.iloc[i]
                prev_k = k_series.iloc[i - 1]
                prev_d = d_series.iloc[i - 1]

                golden_cross = prev_k <= prev_d and cur_k > cur_d
                ema_val = ema_series.iloc[i]
                ema_dev = (cur_close / ema_val - 1) * 100

                if golden_cross and cur_k < params["oversold_k"] and ema_dev > params["ema_dev_filter"]:
                    # 挂限价单（低于市价$50）
                    limit_price = cur_close + params["entry_offset"]
                    pending_order_price = limit_price
                    pending_order_bar = i

    # ── 计算统计 ──
    if not trades:
        return {"total_trades": 0, "win_rate": 0, "total_pnl_pct": 0,
                "max_dd_pct": 0, "sharpe": 0, "trades": [], "avg_hold_bars": 0}

    pnl_list = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]
    total_pnl = sum(pnl_list)
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    # 最大回撤 + 权益曲线
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

    # 夏普
    if len(pnl_list) > 1:
        avg_pnl = np.mean(pnl_list)
        std_pnl = np.std(pnl_list)
        bars_per_year = 365 * 24 * 4  # 15min
        trades_per_year = len(trades) / (n / bars_per_year)
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
        "win_loss_ratio": round(abs(np.mean(wins) / np.mean(losses)), 2) if losses and wins else 0,
        "equity_curve": equity_curve,
    }


def fetch_data(symbol="BTC/USDC:USDC", tf="15m", days=365):
    """从币安分批获取历史K线，带本地缓存"""
    cache_file = f"/tmp/kdj_backtest_{symbol.replace('/','_').replace(':','_')}_{tf}_{days}d.pkl"
    if os.path.exists(cache_file):
        print(f"  从缓存加载: {cache_file}")
        return pd.read_pickle(cache_file)

    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
    now = ex.milliseconds()
    since = now - days * 86400 * 1000
    all_ohlcv = []
    limit = 1000

    print(f"  下载中... ({days}天, {tf})")
    while since < now:
        ohlcv = ex.fetch_ohlcv(symbol, tf, since=since, limit=limit)
        if not ohlcv:
            break
        all_ohlcv.extend(ohlcv)
        since = ohlcv[-1][0] + 1
        if len(ohlcv) < limit:
            break
        print(f"    已获取 {len(all_ohlcv)} 根K线...")
        time.sleep(0.3)

    df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df.to_pickle(cache_file)
    print(f"  已缓存: {cache_file}")
    return df


def _print_result(r, title="回测结果"):
    print(f"\n{'─'*40}")
    print(f" {title}")
    print(f"{'─'*40}")
    if r["total_trades"] == 0:
        print("  ⚠️ 无交易")
        return
    print(f"  总交易:     {r['total_trades']:>4} 笔")
    print(f"  胜率:       {r['win_rate']:>5.1f}%")
    print(f"  总盈亏:     {r['total_pnl_pct']:>+7.2f}%")
    print(f"  平均每笔:   {r['avg_pnl_pct']:>+7.2f}%")
    print(f"  平均盈利:   {r['avg_win_pct']:>+7.2f}%")
    print(f"  平均亏损:   {r['avg_loss_pct']:>+7.2f}%")
    print(f"  盈亏比:     {r['win_loss_ratio']:>5.2f}")
    print(f"  最大回撤:   {r['max_dd_pct']:>5.1f}%")
    print(f"  夏普比率:   {r['sharpe']:>5.2f}")
    print(f"  平均持有:   {r['avg_hold_bars']:.0f}K线 ({r['avg_hold_bars']*15/60:.1f}h)")

    if r["trades"]:
        by_reason = defaultdict(list)
        for t in r["trades"]:
            by_reason[t["exit_reason"]].append(t)
        print(f"\n  退出分布:")
        for reason, ts in sorted(by_reason.items()):
            pnls = [t["pnl_pct"] for t in ts]
            wr = sum(1 for p in pnls if p > 0) / len(ts) * 100
            print(f"    {reason:<10}: {len(ts):>3}笔 胜率{wr:>4.0f}% 均盈亏{np.mean(pnls):+>.2f}%")

        # 最近20笔明细
        print(f"\n  最近20笔:")
        print(f"    {'时间':<16} {'入场':>8} {'出场':>8} {'盈亏%':>7} {'原因':<10}")
        for t in r["trades"][-20:]:
            et = t["entry_time"].strftime("%m-%d %H:%M") if hasattr(t["entry_time"], 'strftime') else str(t["entry_time"])
            print(f"    {et:<16} {t['entry_price']:>8.0f} {t['exit_price']:>8.0f} {t['pnl_pct']:>+6.2f}% {t['exit_reason']:<10}")


def make_sparkline(curve, width=40):
    if not curve:
        return ""
    mn, mx = min(curve), max(curve)
    rng = mx - mn if mx > mn else 1
    bars = []
    step = max(1, len(curve) // width)
    for v in curve[::step]:
        h = int((v - mn) / rng * 8)
        bars.append("▁▂▃▄▅▆▇█"[min(h, 7)])
    return "".join(bars)


def run_backtest():
    params = dict(BOT_PARAMS)

    print("=" * 60)
    print("  KDJ金叉策略回测（带盘中成交 + 限价单-50）")
    print("=" * 60)

    # 获取数据
    print(f"\n📥 获取1年15m数据...")
    df = fetch_data("BTC/USDC:USDC", "15m", days=365)
    print(f"  ✓ 共 {len(df)} 根K线")
    print(f"    范围: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")

    # ── 1. 当前参数回测 ──
    print(f"\n{'='*50}")
    print("  【1】当前参数回测（-50入场，+0.5%止盈，盘中成交）")
    print(f"{'='*50}")
    result = simulate(params, df)
    _print_result(result, "")

    # 权益曲线
    if result["equity_curve"]:
        print(f"\n  权益曲线: {make_sparkline(result['equity_curve'])}")
        print(f"  终值: {result['equity_curve'][-1]:.1f} (起始100)")

    # ── 2. 对比：布林上轨止盈 vs +0.5%固定止盈 ──
    print(f"\n{'='*50}")
    print("  【2】对比：布林上轨止盈 vs +0.5%固定止盈")
    print(f"{'='*50}")

    bb_params = dict(BOT_PARAMS)
    bb_params["use_bb_exit"] = True

    def calc_bb(close, period=14, std_mult=2.0):
        mid = close.rolling(period).mean()
        std = close.rolling(period).std()
        return mid + std_mult * std

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    k_series, d_series, _ = calc_kdj(df["high"], df["low"], df["close"], 9, 2)
    ema_series = df["close"].ewm(span=100, adjust=False).mean()
    bb_up_series = calc_bb(df["close"], 14, 2.0)

    n = len(df)
    need = 150
    trades_bb = []
    pos = None; ep = 0; eb = 0; ltb = -9999; pp = 0.0; pb = -9999

    for i in range(need, n):
        cur_close = close[i]
        cur_high = high[i]
        cur_low = low[i]

        if pos is None and pb >= 0:
            if cur_low <= pp:
                pos = "long"; ep = pp; eb = i; ltb = i; pb = -9999
            elif i - pb >= 1:
                pb = -9999

        if pos == "long":
            exit_reason = None; exit_price = cur_close
            sl = ep * (1 - 0.3/100)
            if cur_low <= sl:
                exit_reason = "止损"; exit_price = sl
            if exit_reason is None:
                bb_val = bb_up_series.iloc[i]
                if not np.isnan(bb_val) and cur_high >= bb_val * 0.995:
                    exit_reason = "上轨止盈"; exit_price = bb_val * 0.995
            if exit_reason is None and (i - eb) >= 12:
                exit_reason = "超时"
            if exit_reason:
                pnl = (exit_price - ep) / ep * 100
                trades_bb.append(pnl)
                pos = None

        if pos is None and pb < 0:
            bs = i - ltb if ltb > 0 else 9999
            if bs >= 2:
                ck = k_series.iloc[i]; cd = d_series.iloc[i]
                pk = k_series.iloc[i-1]
                if pk <= cd and ck > cd and ck < 40:
                    pp = cur_close - 50; pb = i

    bb_pnls = np.array(trades_bb) if trades_bb else np.array([0])
    bb_wr = (bb_pnls > 0).sum() / len(bb_pnls) * 100
    bb_total = bb_pnls.sum()
    bb_avg = bb_pnls.mean()

    tp_pnls = np.array([t["pnl_pct"] for t in result["trades"]])
    tp_wr = (tp_pnls > 0).sum() / len(tp_pnls) * 100
    tp_total = tp_pnls.sum()
    tp_avg = tp_pnls.mean()

    print(f"\n  {'指标':<14} {'布林上轨止盈':<16} {'+0.5%固定止盈':<16}")
    print(f"  {'─'*46}")
    print(f"  {'总交易':<12} {len(trades_bb):>6}笔          {result['total_trades']:>6}笔")
    print(f"  {'胜率':<12} {bb_wr:>5.1f}%          {tp_wr:>5.1f}%")
    print(f"  {'总盈亏':<12} {bb_total:>+7.2f}%        {tp_total:>+7.2f}%")
    print(f"  {'均每笔':<12} {bb_avg:>+7.2f}%        {tp_avg:>+7.2f}%")
    print(f"  {'最大回撤':<12} {result['max_dd_pct']:>5.1f}%          {result['max_dd_pct']:>5.1f}%")

    # ── 3. 撤单率统计 ──
    print(f"\n{'='*50}")
    print("  【3】挂单成交率统计")
    print(f"{'='*50}")
    total_signals = 0
    filled_signals = 0
    cancelled_signals = 0
    # 重新模拟统计
    pos = None
    ep = 0
    eb = 0
    ltb = -9999
    pp = 0.0
    pb = -9999
    for i in range(need, n):
        cur_close = close[i]
        cur_low = low[i]

        if pos is None and pb >= 0:
            if cur_low <= pp:
                pos = "long"
                ep = pp
                eb = i
                ltb = i
                pb = -9999
                filled_signals += 1
            elif i - pb >= 1:
                pb = -9999
                cancelled_signals += 1

        if pos == "long":
            sl = ep * (1 - 0.3/100)
            tp = ep * (1 + 0.5/100)
            if cur_low <= sl or high[i] >= tp or (i - eb) >= 12:
                pos = None

        if pos is None and pb < 0:
            bs = i - ltb if ltb > 0 else 9999
            if bs >= 2:
                ck = k_series.iloc[i]
                cd = d_series.iloc[i]
                pk = k_series.iloc[i - 1]
                if pk <= cd and ck > cd and ck < 40:
                    pp = cur_close - 50
                    pb = i
                    total_signals += 1

    cancel_rate = cancelled_signals / total_signals * 100 if total_signals > 0 else 0
    print(f"  总信号: {total_signals}")
    print(f"  成交:   {filled_signals} ({filled_signals/total_signals*100:.0f}%)")
    print(f"  撤单:   {cancelled_signals} ({cancel_rate:.0f}%)")
    print(f"  撤单原因: 挂单1根K线(15min)未成交自动撤")

    # ── 4. 参数调优 ──
    print(f"\n{'='*50}")
    print("  【4】参数调优扫描")
    print(f"{'='*50}")

    best_sharpe = -999
    best_params = None
    best_result = None

    for param_name, values in TUNE_RANGES.items():
        print(f"\n  ▶ {param_name} = {values}")
        local_best = -999
        for v in values:
            test_params = dict(BOT_PARAMS)
            test_params[param_name] = v
            r = simulate(test_params, df)
            score = r["sharpe"] * 2 + r["win_rate"] / 10 + min(r["total_pnl_pct"] / 5, 5) - abs(r["max_dd_pct"]) / 5
            marker = " ◀" if r["sharpe"] > local_best else ""
            if r["sharpe"] > local_best:
                local_best = r["sharpe"]
            print(f"    {v:>4}: {r['total_trades']:>3}笔 胜率{r['win_rate']:>4.0f}% "
                  f"PnL{r['total_pnl_pct']:>+6.2f}% DD{r['max_dd_pct']:>5.1f}% "
                  f"Sh{r['sharpe']:>5.2f}{marker}")

            if r["sharpe"] > best_sharpe and r["total_trades"] >= 10:
                best_sharpe = r["sharpe"]
                best_params = dict(test_params)
                best_result = r

    # ── 5. 最优参数 ──
    if best_params:
        print(f"\n{'='*50}")
        print("  【5】最优参数组合")
        print(f"{'='*50}")
        for k, v in best_params.items():
            default = BOT_PARAMS[k]
            flag = " ★" if v != default else ""
            print(f"    {k}: {v} (默认={default}){flag}")
        _print_result(best_result, "")

        if best_result["equity_curve"]:
            print(f"\n  权益曲线: {make_sparkline(best_result['equity_curve'])}")
            print(f"  终值: {best_result['equity_curve'][-1]:.1f} (起始100)")


if __name__ == "__main__":
    run_backtest()
