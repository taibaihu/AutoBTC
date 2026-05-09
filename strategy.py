# -*- coding: utf-8 -*-
"""策略引擎 —— 信号生成"""
import pandas as pd
import numpy as np
from typing import Optional

# 信号枚举
HOLD = 0
BUY = 1
SELL = -1


def calc_rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    """计算 RSI 序列（Wilder 标准 RMA 平滑，与 TradingView/Binance 图表一致）"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    # Wilder's RMA: 首个周期用 SMA，之后指数平滑
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()

    # SMA 第一个有效值在 index=period 处，从 period+1 开始 Wilder 平滑
    alpha = 1.0 / period
    for i in range(period + 1, len(gain)):
        avg_gain.iloc[i] = avg_gain.iloc[i - 1] * (1 - alpha) + gain.iloc[i] * alpha
        avg_loss.iloc[i] = avg_loss.iloc[i - 1] * (1 - alpha) + loss.iloc[i] * alpha

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """计算 MACD，返回当前值及前后对比"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return {
        "macd": float(macd_line.iloc[-1]),
        "signal": float(signal_line.iloc[-1]),
        "histogram": float(histogram.iloc[-1]),
        "macd_prev": float(macd_line.iloc[-2]),
        "signal_prev": float(signal_line.iloc[-2]),
    }


def calc_kdj(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 9, k_smooth: int = 3, d_smooth: int = 3) -> dict:
    """计算 KDJ 指标，返回当前 K/D/J 值及前后对比"""
    low_min = low.rolling(period).min()
    high_max = high.rolling(period).max()
    rsv = (close - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)

    k = rsv.ewm(alpha=1 / k_smooth, adjust=False).mean()
    d = k.ewm(alpha=1 / d_smooth, adjust=False).mean()
    j = 3 * k - 2 * d

    return {
        "k": float(k.iloc[-1]),
        "d": float(d.iloc[-1]),
        "j": float(j.iloc[-1]),
        "k_prev": float(k.iloc[-2]),
        "d_prev": float(d.iloc[-2]),
    }


def calc_bollinger_bands(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> dict:
    """计算布林带，返回最新值 {upper, middle, lower, bandwidth}"""
    middle = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    current_price = close.iloc[-1]
    bandwidth = (upper.iloc[-1] - lower.iloc[-1]) / middle.iloc[-1]
    return {
        "upper": float(upper.iloc[-1]),
        "middle": float(middle.iloc[-1]),
        "lower": float(lower.iloc[-1]),
        "bandwidth": float(bandwidth),
        "position": float((current_price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])),
    }


def calc_macd_series(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """返回完整的 MACD 序列（用于历史检查）"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def check_buy_conditions(df: pd.DataFrame, macd: dict, kdj: dict) -> tuple[bool, str]:
    """
    方案7 五重过滤买入检查（MACD多头 + KDJ金叉 + 5道宽松过滤）
    返回 (是否买入, 原因/被拒理由)
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # ===== 基础条件：MACD多头 + KDJ金叉 =====
    macd_bull = macd["macd"] > macd["signal"]
    kdj_cross_up = kdj["k_prev"] <= kdj["d_prev"] and kdj["k"] > kdj["d"]

    if not macd_bull or not kdj_cross_up:
        return False, ""

    passes = ["MACD多头+KDJ金叉"]
    rejected = []

    # ===== 过滤1：波动率过滤（剔除横盘螃蟹市）=====
    bb_period = 20
    bb_mid = close.rolling(bb_period).mean()
    bb_std = close.rolling(bb_period).std()
    bb_width = ((bb_mid + 2 * bb_std) - (bb_mid - 2 * bb_std)) / bb_mid
    current_bbw = float(bb_width.iloc[-1])
    avg_bbw = float(bb_width.rolling(24).mean().iloc[-1])  # 过去24根均值
    if current_bbw < avg_bbw * 0.5:
        rejected.append(f"波动不足(BB带宽{current_bbw:.4f}<均值{avg_bbw:.4f}×0.5)")

    # ===== 过滤2：大周期空头趋势过滤（EMA120下方不买）=====
    ema_long = close.ewm(span=120, adjust=False).mean().iloc[-1]
    if close.iloc[-1] < ema_long:
        rejected.append(f"大周期空头(价{close.iloc[-1]:.1f}<EMA120{ema_long:.1f})")

    # ===== 过滤3：超买区金叉过滤（宽松版 K<85 D<85 J<90）=====
    if kdj["k"] > 85 or kdj["d"] > 85:
        rejected.append(f"超买区金叉(K:{kdj['k']:.1f}/D:{kdj['d']:.1f}>85)")
    elif kdj["j"] > 90:
        rejected.append(f"超买区金叉(J:{kdj['j']:.1f}>90)")

    # ===== 过滤4：无量上涨（Volume < 均值×0.8）=====
    vol_mean = volume.rolling(20).mean().iloc[-1]
    if volume.iloc[-1] < vol_mean * 0.8:
        rejected.append(f"无量(Vol:{volume.iloc[-1]:.0f}<均值{vol_mean:.0f}×0.8)")

    # ===== 过滤5：MACD死叉后复燃（过去3根K线内有过死叉）=====
    try:
        _, _, hist_series = calc_macd_series(close)
        hist_window = hist_series.iloc[-4:-1]  # 当前之前的3根
        if (hist_window < 0).any():
            rejected.append("MACD复燃(3周期内有过死叉)")
    except Exception:
        pass

    if rejected:
        return False, f"过滤未通过: {' | '.join(rejected)}"

    return True, f"买入预警: {' | '.join(passes)}"


class Strategy:
    """基类，所有策略继承此"""

    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        raise NotImplementedError


class MACrossoverStrategy(Strategy):
    """双均线交叉策略"""

    def __init__(self, short_window: int = 7, long_window: int = 25):
        self.short_window = short_window
        self.long_window = long_window

    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        # 计算均线
        ma_short = df["close"].rolling(self.short_window).mean()
        ma_long = df["close"].rolling(self.long_window).mean()

        indicators = {
            "ma_short": float(ma_short.iloc[-1]),
            "ma_long": float(ma_long.iloc[-1]),
        }

        if len(df) < self.long_window + 1:
            return HOLD, indicators

        # 上穿 = 金叉 → 买入; 下穿 = 死叉 → 卖出
        prev_short = float(ma_short.iloc[-2])
        prev_long = float(ma_long.iloc[-2])
        curr_short = float(ma_short.iloc[-1])
        curr_long = float(ma_long.iloc[-1])

        # 金叉
        if prev_short <= prev_long and curr_short > curr_long:
            return BUY, indicators
        # 死叉
        if prev_short >= prev_long and curr_short < curr_long:
            return SELL, indicators
        return HOLD, indicators


class RSIMeanReversionStrategy(Strategy):
    """RSI 均值回归策略 —— 超卖买入，超买卖出"""

    def __init__(self, period: int = 14, oversold: int = 30, overbought: int = 70):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        rsi_series = calc_rsi_series(df["close"], self.period)
        indicators = {"rsi": float(rsi_series.iloc[-1])}

        if indicators["rsi"] < self.oversold:
            return BUY, indicators
        if indicators["rsi"] > self.overbought:
            return SELL, indicators
        return HOLD, indicators


# 策略注册表 —— 在 config.py 中通过 STRATEGY_NAME 选择
STRATEGIES = {
    "ma_cross": MACrossoverStrategy,
    "rsi_revert": RSIMeanReversionStrategy,
}
