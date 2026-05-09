#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回溯扫描：从当前时间往前推 24 小时，检测符合五重过滤买入条件的信号并入库
"""
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import pymysql
from pymysql.constants import CLIENT

from config import (
    SYMBOL, TIMEFRAME, RSI_TIMEFRAMES, RSI_PERIOD,
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME,
)
from engine import BinanceEngine
from strategy import calc_rsi_series, calc_macd, calc_macd_series, calc_kdj, check_buy_conditions

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger("backtest")


def _get_conn(database=None):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, database=database,
        connect_timeout=5, client_flag=CLIENT.MULTI_STATEMENTS,
    )


def _ensure_table():
    conn = _get_conn(database=DB_NAME)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS buy_signals (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                signal_time   DATETIME,
                price         DECIMAL(20, 8),

                rsi_5m        DECIMAL(10, 4),
                rsi_1h        DECIMAL(10, 4),
                rsi_2h        DECIMAL(10, 4),

                macd          DECIMAL(20, 8),
                macd_signal   DECIMAL(20, 8),
                macd_hist     DECIMAL(20, 8),

                k_val         DECIMAL(10, 4),
                d_val         DECIMAL(10, 4),
                j_val         DECIMAL(10, 4),

                bb_width      DECIMAL(10, 6),
                ema120        DECIMAL(20, 8),
                volume        DECIMAL(20, 4),
                vol_mean_20   DECIMAL(20, 4),

                filter_detail VARCHAR(500),
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()
    conn.close()
    logger.info("表 buy_signals 已就绪")


def save_signal(row: dict):
    conn = _get_conn(database=DB_NAME)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO buy_signals
                (signal_time, price,
                 rsi_5m, rsi_1h, rsi_2h,
                 macd, macd_signal, macd_hist,
                 k_val, d_val, j_val,
                 bb_width, ema120, volume, vol_mean_20,
                 filter_detail)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            row["signal_time"], row["price"],
            row["rsi_5m"], row["rsi_1h"], row["rsi_2h"],
            row["macd"], row["macd_signal"], row["macd_hist"],
            row["k"], row["d"], row["j"],
            row["bb_width"], row["ema120"], row["volume"], row["vol_mean_20"],
            row.get("filter_detail", ""),
        ))
    conn.commit()
    conn.close()


def get_1h_close_up_to(target_time: pd.Timestamp, df1h: pd.DataFrame) -> pd.Series:
    """返回 target_time 对应的 1h 数据（含 K 线 close，最后一条用 target 的 close 替代）"""
    df = df1h[df1h.index <= target_time].copy()
    if df.empty:
        return pd.Series(dtype=float)
    return df["close"]


def get_2h_close_up_to(target_time: pd.Timestamp, df2h: pd.DataFrame) -> pd.Series:
    df = df2h[df2h.index <= target_time].copy()
    if df.empty:
        return pd.Series(dtype=float)
    return df["close"]


def main():
    logger.info("=" * 60)
    logger.info("开始回溯扫描 24 小时买入信号")
    _ensure_table()

    engine = BinanceEngine()

    # ========== 1. 拉取足够的历史数据 ==========
    SCAN_HOURS = 24
    WARMUP = 200  # 指标预热 K 线数

    need_5m = SCAN_HOURS * 12 + WARMUP  # 5m = 12根/小时
    need_1h = SCAN_HOURS + 30
    need_2h = SCAN_HOURS // 2 + 20

    logger.info(f"拉取 5m({need_5m}根) 1h({need_1h}根) 2h({need_2h}根) 历史数据...")
    df5m = engine.fetch_ohlcv(SYMBOL, "5m", need_5m)
    df1h = engine.fetch_ohlcv(SYMBOL, "1h", need_1h)
    df2h = engine.fetch_ohlcv(SYMBOL, "2h", need_2h)
    logger.info(f"实际获取: 5m={len(df5m)} 1h={len(df1h)} 2h={len(df2h)}")

    # 扫描范围（去掉预热期）
    scan_start = WARMUP
    total = len(df5m)
    logger.info(f"扫描 {scan_start} ~ {total - 1} 共 {total - scan_start} 根 5m K线")

    # ========== 2. 预先计算全量指标序列 ==========
    close5 = df5m["close"]
    high5 = df5m["high"]
    low5 = df5m["low"]
    vol5 = df5m["volume"]

    # MACD 完整序列
    macd_line, macd_signal, macd_hist = calc_macd_series(close5)

    # KDJ 完整序列
    low_min = low5.rolling(9).min()
    high_max = high5.rolling(9).max()
    rsv = (close5 - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    k_series = rsv.ewm(alpha=1/3, adjust=False).mean()
    d_series = k_series.ewm(alpha=1/3, adjust=False).mean()
    j_series = 3 * k_series - 2 * d_series

    # 布林带宽
    bb_mid = close5.rolling(20).mean()
    bb_std = close5.rolling(20).std()
    bb_width_series = ((bb_mid + 2 * bb_std) - (bb_mid - 2 * bb_std)) / bb_mid
    bb_width_avg = bb_width_series.rolling(24).mean()

    # EMA120
    ema120_series = close5.ewm(span=120, adjust=False).mean()

    # 成交量均值
    vol_mean_series = vol5.rolling(20).mean()

    # ========== 3. 逐根 K 线扫描 ==========
    found = 0

    for i in range(scan_start, total):
        ts = df5m.index[i]
        close_i = close5.iloc[i]  # 当前 K 线收盘价 = "实时价"
        high_i = high5.iloc[i]
        low_i = low5.iloc[i]
        vol_i = vol5.iloc[i]

        # --- 3a. 检查当前 K 线的 MACD 金叉 + KDJ 金叉 ---
        macd_cur = macd_line.iloc[i]
        macd_sig_cur = macd_signal.iloc[i]
        macd_prev = macd_line.iloc[i - 1]
        macd_sig_prev = macd_signal.iloc[i - 1]
        macd_h_cur = macd_hist.iloc[i]

        k_cur = k_series.iloc[i]
        d_cur = d_series.iloc[i]
        j_cur = j_series.iloc[i]
        k_prev = k_series.iloc[i - 1]
        d_prev = d_series.iloc[i - 1]

        macd_cross_up = macd_prev <= macd_sig_prev and macd_cur > macd_sig_cur
        kdj_cross_up = k_prev <= d_prev and k_cur > d_cur

        if not macd_cross_up or not kdj_cross_up:
            continue

        # --- 3b. 构建 MACD/KDJ dict 供 check_buy_conditions 使用 ---
        macd_dict = {
            "macd": macd_cur, "signal": macd_sig_cur, "histogram": macd_h_cur,
            "macd_prev": macd_prev, "signal_prev": macd_sig_prev,
        }
        kdj_dict = {
            "k": k_cur, "d": d_cur, "j": j_cur,
            "k_prev": k_prev, "d_prev": d_prev,
        }

        # --- 3c. 构建实时价更新后的模拟 df（供 check_buy_conditions 检查过滤条件） ---
        live_df = df5m.iloc[:i + 1].copy()
        live_df.iloc[-1, live_df.columns.get_loc("close")] = close_i
        live_df.iloc[-1, live_df.columns.get_loc("high")] = max(high_i, close_i)
        live_df.iloc[-1, live_df.columns.get_loc("low")] = min(low_i, close_i)

        buy_ok, buy_msg = check_buy_conditions(live_df, macd_dict, kdj_dict)

        # --- 3d. 计算多周期 RSI（供日志 / 入库） ---
        rsi_5m_val = float(calc_rsi_series(close5.iloc[:i + 1], RSI_PERIOD).iloc[-1])

        # 1h RSI：取到当前 1h K 线（含），收盘用当前 5m close 替换
        close1h = get_1h_close_up_to(ts, df1h)
        if len(close1h) >= 2:
            close1h = close1h.copy()
            close1h.iloc[-1] = close_i
            rsi_1h_val = float(calc_rsi_series(close1h, RSI_PERIOD).iloc[-1])
        else:
            rsi_1h_val = None

        close2h = get_2h_close_up_to(ts, df2h)
        if len(close2h) >= 2:
            close2h = close2h.copy()
            close2h.iloc[-1] = close_i
            rsi_2h_val = float(calc_rsi_series(close2h, RSI_PERIOD).iloc[-1])
        else:
            rsi_2h_val = None

        # --- 3e. 记录 ---
        row = {
            "signal_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "price": round(close_i, 2),
            "rsi_5m": round(rsi_5m_val, 2) if rsi_5m_val is not None else None,
            "rsi_1h": round(rsi_1h_val, 2) if rsi_1h_val is not None else None,
            "rsi_2h": round(rsi_2h_val, 2) if rsi_2h_val is not None else None,
            "macd": round(macd_cur, 2),
            "macd_signal": round(macd_sig_cur, 2),
            "macd_hist": round(macd_h_cur, 2),
            "k": round(k_cur, 2),
            "d": round(d_cur, 2),
            "j": round(j_cur, 2),
            "bb_width": round(bb_width_series.iloc[i], 6) if pd.notna(bb_width_series.iloc[i]) else None,
            "ema120": round(ema120_series.iloc[i], 2) if pd.notna(ema120_series.iloc[i]) else None,
            "volume": round(vol_i, 2),
            "vol_mean_20": round(vol_mean_series.iloc[i], 2) if pd.notna(vol_mean_series.iloc[i]) else None,
            "filter_detail": buy_msg,
        }

        if buy_ok:
            found += 1
            save_signal(row)
            logger.info(
                f"✅ [{row['signal_time']}] 买入信号 #{found} @ {row['price']}  "
                f"RSI:{rsi_5m_val:.1f}/{rsi_1h_val:.1f}/{rsi_2h_val:.1f}  "
                f"MACD:{macd_cur:.1f}/{macd_sig_cur:.1f}  KDJ:{k_cur:.0f}/{d_cur:.0f}/{j_cur:.0f}"
            )
        else:
            logger.debug(
                f"⛔ [{ts.strftime('%H:%M')}] 金叉但{buy_msg}"
            )

    logger.info("=" * 60)
    logger.info(f"扫描完成，共发现 {found} 个符合条件的买入信号")


if __name__ == "__main__":
    main()
