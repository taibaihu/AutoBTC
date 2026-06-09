# -*- coding: utf-8 -*-
"""策略引擎 —— 信号生成"""
import pandas as pd
import numpy as np
from typing import Optional
from config import PAPER_TRADING
import config as cfg

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



def calc_amplitude(df: pd.DataFrame, window: int = 16) -> float:
    """Calculate price amplitude over a window (default 4h for 15m bars)"""
    if len(df) < window: return 0.0
    recent = df.tail(window)
    high = recent['high'].max()
    low = recent['low'].min()
    return (high / low) - 1 if low > 0 else 0.0

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
    bb_period = 14
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
    paper_trading = True  # 默认模拟, 子类可覆写为 False 开启实盘

    def generate_signal(self, df: pd.DataFrame, df_5m: pd.DataFrame = None) -> tuple[int, dict]:
        raise NotImplementedError


class MACrossoverStrategy(Strategy):
    """双均线交叉策略"""

    def __init__(self, short_window: int = 7, long_window: int = 25):
        self.short_window = short_window
        self.long_window = long_window

    def generate_signal(self, df: pd.DataFrame, df_5m: pd.DataFrame = None) -> tuple[int, dict]:
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

    def generate_signal(self, df: pd.DataFrame, df_5m: pd.DataFrame = None) -> tuple[int, dict]:
        rsi_series = calc_rsi_series(df["close"], self.period)
        indicators = {"rsi": float(rsi_series.iloc[-1])}

        if indicators["rsi"] < self.oversold:
            return BUY, indicators
        if indicators["rsi"] > self.overbought:
            return SELL, indicators
        return HOLD, indicators


class FastRangeStrategy(Strategy):
    """
    快速买入卖出策略 —— 震荡行情专用 (推荐 15m 周期)

    震荡判断:
      1. ADX < 30 (无强趋势)
      2. BB带宽在历史均值 0.25~2.0 倍内 (不过分剧烈)
      3. 7周期均线斜率 < 1.0% (方向不明)

    买入: 价格触及布林下轨(位置 ≤15%) + 前一根K线确认信号
      - 长下影线: 下影线 > 实体×1.2 且 低点跌破下轨
      - 小阳线:   收>开 且 实体占比 <60%
    拒绝买入: 连续3根K线收盘价都低于下轨(贴轨阴跌)
    
    卖出: 价格触及布林上轨 + 长上影线/小阴线确认
    """

    def __init__(self,
                 bb_period: int = 20,
                 bb_std: float = 2.0,
                 adx_period: int = 14,
                 adx_threshold: float = 35.0,
                 bbw_ratio_upper: float = 2.0,
                 bbw_ratio_lower: float = 0.25,
                 max_slope: float = 0.02,
                 shadow_body_ratio: float = 0.25,
                 max_body_ratio: float = 0.6,
                 buy_zone: float = 0.10,
                 sell_zone: float = 0.95,
                 creep_lookback: int = 3,
                 trend_ema_period: int = 100,
                 cooldown_bars: int = 2,
                 sell_shadow_body_ratio: float = 1.2,
                 sell_max_body_ratio: float = 0.6):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.adx_period = adx_period
        self.bbw_ratio_upper = bbw_ratio_upper
        self.bbw_ratio_lower = bbw_ratio_lower
        self.max_slope = max_slope
        self.shadow_body_ratio = shadow_body_ratio
        self.max_body_ratio = max_body_ratio
        self.sell_max_body_ratio = sell_max_body_ratio
        self.buy_zone = buy_zone
        self.sell_zone = sell_zone
        self.creep_lookback = creep_lookback
        self.trend_ema_period = trend_ema_period
        self.cooldown_bars = cooldown_bars
        self.sell_shadow_body_ratio = sell_shadow_body_ratio
        self.paper_trading = cfg.PAPER_TRADING
        self._last_trade_bar: Optional[pd.Timestamp] = None

    # ── 布林带 ──────────────────────────────────────────────

    def _calc_bb(self, close: pd.Series):
        middle = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()
        upper = middle + self.bb_std * std
        lower = middle - self.bb_std * std
        return upper, middle, lower

    @staticmethod
    def _bb_position(price: float, upper: float, lower: float) -> float:
        denom = upper - lower
        return 0.5 if denom < 1e-8 else (price - lower) / denom

    # ── ADX ────────────────────────────────────────────────

    def _calc_adx(self, df: pd.DataFrame) -> float:
        """计算 ADX (Wilder 平滑)"""
        high, low, close = df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float)
        n = len(close)

        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
            up = high[i] - high[i - 1]
            dn = low[i - 1] - low[i]
            if up > dn and up > 0:
                plus_dm[i] = up
            if dn > up and dn > 0:
                minus_dm[i] = dn

        alpha = 1.0 / self.adx_period
        atr = pd.Series(tr).ewm(alpha=alpha, adjust=False, min_periods=self.adx_period).mean().values
        if atr[-1] == 0 or np.isnan(atr[-1]):
            return 0.0

        pdi = pd.Series(plus_dm).ewm(alpha=alpha, adjust=False).mean().values / atr * 100
        mdi = pd.Series(minus_dm).ewm(alpha=alpha, adjust=False).mean().values / atr * 100
        d_sum = pdi + mdi
        dx = np.where(d_sum > 0, np.abs(pdi - mdi) / d_sum * 100, 0)
        adx_series = pd.Series(dx).ewm(alpha=alpha, adjust=False, min_periods=self.adx_period).mean()
        return float(adx_series.iloc[-1]) if not pd.isna(adx_series.iloc[-1]) else 0.0

    # ── 震荡判断 ───────────────────────────────────────────

    def _is_ranging(self, df: pd.DataFrame, adx: Optional[float] = None, bb_result: Optional[tuple] = None) -> bool:
        close = df["close"]
        if bb_result is not None:
            upper, middle, lower = bb_result
        else:
            upper, middle, lower = self._calc_bb(close)
        bandwidth = (upper - lower) / middle

        cur_bw = float(bandwidth.iloc[-1])
        avg_bw = float(bandwidth.rolling(24).mean().iloc[-1])
        if pd.isna(avg_bw) or avg_bw == 0:
            return False

        # 1) BB带宽未剧烈扩缩
        bbw_ok = self.bbw_ratio_lower * avg_bw <= cur_bw <= self.bbw_ratio_upper * avg_bw
        if not bbw_ok:
            return False

        # 2) ADX < 30 → 无强趋势
        if adx is None:
            adx = self._calc_adx(df)
        if adx >= self.adx_threshold:
            return False

        # 3) 短期均线斜率平缓 → 无明显单边
        ma7 = close.rolling(7).mean()
        slope = abs(float(ma7.iloc[-1] - ma7.iloc[-5]) / max(float(ma7.iloc[-5]), 1e-8))
        return slope < self.max_slope

    # ── K线确认 ────────────────────────────────────────────

    def _has_long_lower_shadow(self, row, lower_val: float) -> bool:
        """长下影线: 下影线 > 实体×ratio 且 低点跌破/触及下轨"""
        o, h, l_val, c = row["open"], row["high"], row["low"], row["close"]
        body = abs(c - o)
        lower_shadow = min(o, c) - l_val
        if body < 1e-8:
            return lower_shadow > 0 and l_val <= lower_val * 1.02
        return lower_shadow > body * self.shadow_body_ratio and l_val <= lower_val * 1.02

    def _is_small_bullish(self, row) -> bool:
        """小阳线: 收>开 且 实体占比 < max_body_ratio (不再要求靠近下轨)"""
        o, h, l_val, c = row["open"], row["high"], row["low"], row["close"]
        if c <= o:
            return False
        total_range = h - l_val
        if total_range < 1e-8:
            return False
        return (c - o) / total_range < self.max_body_ratio

    def _has_long_upper_shadow(self, row, upper_val: float) -> bool:
        """长上影线: 上影线 > 实体×sell_ratio 且 高点突破上轨"""
        o, h, l_val, c = row["open"], row["high"], row["low"], row["close"]
        body = abs(c - o)
        upper_shadow = h - max(o, c)
        if body < 1e-8:
            return upper_shadow > 0 and h >= upper_val * 0.98
        return upper_shadow > body * self.sell_shadow_body_ratio and h >= upper_val * 0.98

    def _is_small_bearish(self, row) -> bool:
        """小阴线: 收<开 且 实体占比 < sell_max_body_ratio"""
        o, h, l_val, c = row["open"], row["high"], row["low"], row["close"]
        if c >= o:
            return False
        total_range = h - l_val
        if total_range < 1e-8:
            return False
        return (o - c) / total_range < self.sell_max_body_ratio

    # ── 贴轨阴跌检测 ──────────────────────────────────────

    def _is_creeping_decline(self, df: pd.DataFrame, bb_result: Optional[tuple] = None) -> bool:
        """
        连续 creep_lookback 根K线收盘价全部低于布林下轨 → 贴轨阴跌
        """
        close = df["close"]
        if bb_result is not None:
            upper, middle, lower = bb_result
        else:
            upper, middle, lower = self._calc_bb(close)
        if len(close) < self.creep_lookback:
            return False
        for i in range(1, self.creep_lookback + 1):
            c = float(close.iloc[-i])
            l = float(lower.iloc[-i])
            if c >= l:
                return False
        return True

    # ── 主信号 ────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame, df_5m: pd.DataFrame = None) -> tuple[int, dict]:
        require = max(self.trend_ema_period, self.adx_period + self.bb_period) + 30
        if len(df) < require:
            return HOLD, {}

        close = df["close"]
        bb_result = self._calc_bb(close)
        upper, middle, lower = bb_result
        u = float(upper.iloc[-1])
        m = float(middle.iloc[-1])
        l_val = float(lower.iloc[-1])
        cur_price = float(close.iloc[-1])
        pos = self._bb_position(cur_price, u, l_val)
        adx_val = self._calc_adx(df)

        indicators = {
            "bb_position": round(pos, 4),
            "bb_upper": round(u, 2),
            "bb_middle": round(m, 2),
            "bb_lower": round(l_val, 2),
            "adx": round(adx_val, 1),
        }

        # ── 平多(SELL): 独立于震荡判断，价格到布林上轨即出场 ──
        if pos >= 0.99:
            self._last_trade_bar = df.index[-1]
            return SELL, indicators

        # 非震荡行情 → 不开仓（不影响出场）
        if not self._is_ranging(df, adx=adx_val, bb_result=bb_result):
            indicators["range"] = 0
            return HOLD, indicators
        indicators["range"] = 1

        # 贴轨阴跌 → 不买入
        creeping = self._is_creeping_decline(df, bb_result=bb_result)

        # ── 大方向过滤 ──
        ema_trend = close.ewm(span=self.trend_ema_period, adjust=False).mean().iloc[-1]
        indicators["trend_ema"] = round(float(ema_trend), 2)
        is_downtrend = cur_price < ema_trend
        indicators["downtrend"] = 1 if is_downtrend else 0

        # ── 冷却检查：最近交易后等待足够 K 线再入场 ──
        bars_since_trade = 9999
        if self._last_trade_bar is not None:
            bars_since_trade = (df.index[-1] - self._last_trade_bar).total_seconds() / 60 // 15
        if bars_since_trade < self.cooldown_bars:
            indicators["cooldown"] = int(bars_since_trade)
            return HOLD, indicators

        # ── 买入: 前一根K线的低点触及/跌破下轨 + 确认反弹 ──
        #       大方向下跌时不抄底（震荡市 RANGE_IGNORE_TREND_FILTER 时取消此限制）
        if not creeping and (not is_downtrend or (cfg.RANGE_IGNORE_TREND_FILTER and adx_val < self.adx_threshold)):
            # 直接入场: 当前价格超跌至 -0.25 以下 (无需K线确认)
            if pos <= -0.25:
                indicators["direct_entry"] = 1
                indicators["confirmed_by"] = "超跌直入"
                self._last_trade_bar = df.index[-1]
                return BUY, indicators

            prev = df.iloc[-2]
            u_prev = float(upper.iloc[-2])
            l_prev = float(lower.iloc[-2])
            prev_low = float(prev["low"])

            low_pos = self._bb_position(prev_low, u_prev, l_prev)
            low_touched_band = low_pos <= -0.02

            if low_touched_band:
                indicators["low_pos"] = round(low_pos, 4)
                indicators["low_touched"] = 1

                shadow_ok = self._has_long_lower_shadow(prev, l_prev)
                if shadow_ok:
                    indicators["confirmed_by"] = "长下影线"
                    self._last_trade_bar = df.index[-1]
                    return BUY, indicators
        elif creeping:
            indicators["creeping"] = 1

        return HOLD, indicators


class FastRangeShortStrategy(FastRangeStrategy):
    """
    快速做空策略 —— 震荡行情专用 (推荐 15m 周期)

    逻辑是 FastRangeStrategy 的镜像:

    开空(SELL): 前一根K线高点触及布林上轨(high_pos ≥ sell_zone) + 反转确认
      - 长上影线: 上影线 > 实体×ratio 且 高点突破上轨
      - 小阴线:   收<开 且 实体占比 < max_body_ratio
    拒绝开空: 连续3根K线收盘高于上轨 (贴轨上涨, 不摸底)

    平空(BUY): 价格触及布林下轨 (收盘价位置 ≤ buy_zone)
    """


    def _is_creeping_rise(self, df: pd.DataFrame, bb_result: Optional[tuple] = None) -> bool:
        """
        连续3根K线收盘价全部高于布林上轨 → 贴轨上涨, 不开空
        """
        close = df["close"]
        if bb_result is not None:
            upper, middle, lower = bb_result
        else:
            upper, middle, lower = self._calc_bb(close)
        lookback = self.creep_lookback
        if len(close) < lookback:
            return False
        for i in range(1, lookback + 1):
            if float(close.iloc[-i]) <= float(upper.iloc[-i]):
                return False
        return True

    def generate_signal(self, df: pd.DataFrame, df_5m: pd.DataFrame = None) -> tuple[int, dict]:
        require = max(self.trend_ema_period, self.adx_period + self.bb_period) + 30
        if len(df) < require:
            return HOLD, {}

        close = df["close"]
        bb_result = self._calc_bb(close)
        upper, middle, lower = bb_result
        u = float(upper.iloc[-1])
        m = float(middle.iloc[-1])
        l_val = float(lower.iloc[-1])
        cur_price = float(close.iloc[-1])
        pos = self._bb_position(cur_price, u, l_val)
        adx_val = self._calc_adx(df)

        indicators = {
            "bb_position": round(pos, 4),
            "bb_upper": round(u, 2),
            "bb_middle": round(m, 2),
            "bb_lower": round(l_val, 2),
            "adx": round(adx_val, 1),
        }

        # ── 平空(BUY): 独立于震荡判断，价格到布林下轨即出场 ──
        if pos <= 0.01:
            self._last_trade_bar = df.index[-1]
            return BUY, indicators

        # 非震荡 → 不开仓（不影响出场）
        if not self._is_ranging(df, adx=adx_val, bb_result=bb_result):
            indicators["range"] = 0
            return HOLD, indicators
        indicators["range"] = 1

        creeping_rise = self._is_creeping_rise(df, bb_result=bb_result)

        # ── 大方向过滤：EMA50 ──
        ema_trend = close.ewm(span=self.trend_ema_period, adjust=False).mean().iloc[-1]
        indicators["trend_ema"] = round(float(ema_trend), 2)
        is_uptrend = cur_price > ema_trend
        indicators["uptrend"] = 1 if is_uptrend else 0

        # ── 冷却检查：与做多策略共享冷却状态 ──
        bars_since_trade = 9999
        if self._last_trade_bar is not None:
            bars_since_trade = (df.index[-1] - self._last_trade_bar).total_seconds() / 60 // 15
        if bars_since_trade < self.cooldown_bars:
            indicators["cooldown"] = int(bars_since_trade)
            return HOLD, indicators

        # ── 开空(SELL): 前一根K线高点触及上轨 + 反转确认 ──
        #       大方向上涨时不开空（震荡市 RANGE_IGNORE_TREND_FILTER 时取消此限制）
        if creeping_rise:
            indicators["creeping_rise"] = 1
        elif is_uptrend and not (cfg.RANGE_IGNORE_TREND_FILTER and adx_val < self.adx_threshold):
            indicators["uptrend_block"] = 1
        else:
            # 直接入场: 当前价格超涨至 1.25 以上 (无需K线确认)
            if pos >= 1.25:
                indicators["direct_entry"] = 1
                indicators["confirmed_by"] = "超涨直入"
                self._last_trade_bar = df.index[-1]
                return SELL, indicators

            prev = df.iloc[-2]
            u_prev = float(upper.iloc[-2])
            l_prev = float(lower.iloc[-2])
            prev_high = float(prev["high"])

            high_pos = self._bb_position(prev_high, u_prev, l_prev)
            high_touched_band = high_pos >= 1.02

            if high_touched_band:
                indicators["high_pos"] = round(high_pos, 4)
                shadow_ok = self._has_long_upper_shadow(prev, u_prev)
                if shadow_ok:
                    indicators["confirmed_by"] = "长上影线"
                    self._last_trade_bar = df.index[-1]
                    return SELL, indicators

        return HOLD, indicators


class KDJReversalStrategy(Strategy):
    """
    KDJ 超卖金叉反转策略 — 只做超卖区金叉，避开高位陷阱

    核心逻辑:
      买入条件: KDJ金叉(K上穿D) + K<30(超卖区) + 距前低不远
      卖出条件: KDJ死叉或超买区(J>100) 平多
      胜率: 超卖区金叉约70%，中高位金叉(<40%)大多为陷阱

    适用周期: 15m / 30m / 1h
    """

    def __init__(self, k_period: int = 9, d_period: int = 2, oversold_k: float = 40,
                 overbought_j: float = 100, cooldown_bars: int = 2,

                 max_hold_candles: int = 12,  # 12根15mK线=3小时平仓
                 ema_period: int = 100, stop_loss_pct: float = 0.3,
                 vol_filter_pct: float = 1.2):  # 波动率过滤: 4h振幅<此值不开仓
        self.k_period = k_period
        self.d_period = d_period
        self.oversold_k = oversold_k
        self.overbought_j = overbought_j
        self.cooldown_bars = cooldown_bars
        self.max_hold_candles = max_hold_candles
        self.ema_period = ema_period
        self.stop_loss_pct = stop_loss_pct
        self.vol_filter_pct = vol_filter_pct
        self._entry_price: Optional[float] = None
        self._last_trade_bar: Optional[pd.Timestamp] = None

    def generate_signal(self, df: pd.DataFrame, df_5m: pd.DataFrame = None) -> tuple[int, dict]:
        require = 200
        if len(df) < require:
            return HOLD, {}

        close = df["close"]
        high = df["high"]
        low = df["low"]

        # 计算 EMA100（趋势过滤）
        ema = close.ewm(span=self.ema_period, adjust=False).mean()
        cur_ema = float(ema.iloc[-1])

        # 计算KDJ
        low_min = low.rolling(self.k_period).min()
        high_max = high.rolling(self.k_period).max()
        rsv = (close - low_min) / (high_max - low_min) * 100
        rsv = rsv.fillna(50)

        k = rsv.ewm(alpha=1 / self.d_period, adjust=False).mean()
        d = k.ewm(alpha=1 / self.d_period, adjust=False).mean()
        j = 3 * k - 2 * d

        cur_k = float(k.iloc[-1])
        cur_d = float(d.iloc[-1])
        cur_j = float(j.iloc[-1])
        prev_k = float(k.iloc[-2])
        prev_d = float(d.iloc[-2])
        cur_price = float(close.iloc[-1])

        # 提前计算EMA偏差（确保冷却检查前就有值，用于日志显示）
        ema_dev = (cur_price / cur_ema - 1) * 100

        indicators = {
            "K": round(cur_k, 1), "D": round(cur_d, 1), "J": round(cur_j, 1),
            "K_prev": round(prev_k, 1), "D_prev": round(prev_d, 1),
        "ema_dev_pct": round(ema_dev, 2),
        }

        # 冷却检查：交易后等待足够K线
        bars_since_trade = 9999
        if self._last_trade_bar is not None:
            bars_since_trade = (df.index[-1] - self._last_trade_bar).total_seconds() / 60 // 15
        if bars_since_trade < self.cooldown_bars:
            indicators["cooldown"] = int(bars_since_trade)
            return HOLD, indicators

        # ── KDJ值（始终输出，供日志显示）──
        indicators["K"] = round(cur_k, 1)
        indicators["D"] = round(cur_d, 1)
        indicators["J"] = round(cur_j, 1)
        indicators["K_prev"] = round(prev_k, 1)
        indicators["D_prev"] = round(prev_d, 1)
        indicators["EMA100"] = round(cur_ema, 1)
        
        # ── 波动率过滤：4小时振幅 < vol_filter_pct 不开仓（剔除死寂行情）──
        if self.vol_filter_pct > 0:
            amp = calc_amplitude(df, 16) * 100
            indicators["amplitude_4h"] = round(amp, 2)
            if amp < self.vol_filter_pct:
                indicators["vol_filter_block"] = f"振幅{amp:.2f}%<{self.vol_filter_pct}%"
                return HOLD, indicators

        # ── 开多条件：KDJ金叉 + K<30 + 偏离EMA100>-3%（过滤暴跌假信号）──
        k_golden_cross = prev_k <= prev_d and cur_k > cur_d

        if k_golden_cross and cur_k < self.oversold_k and ema_dev > -100:
            indicators["signal_type"] = "超卖金叉+EMA100"
            self._entry_price = cur_price
            self._last_trade_bar = df.index[-1]
            return BUY, indicators

        # ── 止损：亏损达 stop_loss_pct% 立即平仓 ──
        if self._entry_price is not None and self._entry_price > 0:
            loss_pct = (cur_price - self._entry_price) / self._entry_price * 100
            if loss_pct <= -self.stop_loss_pct:
                indicators["exit_reason"] = f"止损({loss_pct:+.2f}%<=-{self.stop_loss_pct}%)"
                self._entry_price = None
                self._last_trade_bar = df.index[-1]
                return SELL, indicators

        # ── 超时平仓：持有超过3小时（12根15m线）──
        bars_held = bars_since_trade if self._last_trade_bar is not None else 0
        if bars_held >= self.max_hold_candles:
            indicators["exit_reason"] = f"超时平仓(持有{bars_held}根)"
            self._entry_price = None
            self._last_trade_bar = df.index[-1]
            return SELL, indicators

        # ── 平多条件：价格触及布林上轨(14,2) ──
        bb_period = 14
        bb_mid = close.rolling(bb_period).mean()
        bb_std = close.rolling(bb_period).std()
        bb_upper = bb_mid + 2 * bb_std
        cur_upper = float(bb_upper.iloc[-1])
        if cur_price >= cur_upper * 0.995:
            indicators["exit_reason"] = f"触及布林上轨({cur_price:.0f}>={cur_upper:.0f})"
            self._entry_price = None
            self._last_trade_bar = df.index[-1]
            return SELL, indicators

        return HOLD, indicators


# 策略注册表 —— 在 config.py 中通过 STRATEGY_NAME 选择
STRATEGIES = {
    "ma_cross": MACrossoverStrategy,
    "rsi_revert": RSIMeanReversionStrategy,
    "fast_range": FastRangeStrategy,
    "fast_range_short": FastRangeShortStrategy,
    "kdj_reversal": KDJReversalStrategy,
}
