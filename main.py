#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量化交易框架 —— 入口"""
import argparse
import time
import logging

import pandas as pd

from config import (
    SYMBOL, CONTRACT_SYMBOL, TIMEFRAME, LIMIT, SHORT_MA, LONG_MA,
    MAX_POSITION_USDT, DAILY_LOSS_LIMIT, MAX_TRADES_PER_DAY,
    MIN_PROFIT_RATE, MAX_LOSS_RATE, LEVERAGE,
    STRATEGY_NAME, STRATEGY_KWARGS, PAPER_TRADING,
    RSI_TIMEFRAMES, RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_ALERT_COOLDOWN,
)
from engine import FuturesEngine, OKXEngine
from strategy import BUY, SELL, HOLD, STRATEGIES, calc_rsi_series, calc_macd, calc_kdj, calc_bollinger_bands, check_buy_conditions
from risk_manager import RiskManager
from notifier import Notifier
from strategy_manager import load_strategy, apply_to_config

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SIGNAL_MAP = {BUY: "\U0001f7e2买入", SELL: "\U0001f534卖出", HOLD: "⚪观望"}


def calc_rsi(series: pd.Series, period: int = 14) -> float:
    """计算 RSI 值（使用标准 EMA 平滑法）"""
    rsi_series = calc_rsi_series(series, period)
    return float(rsi_series.iloc[-1])


def check_rsi_alert(rsi_values: dict, last_alert: float, notifier: Notifier) -> float:
    now = time.time()
    if now - last_alert < RSI_ALERT_COOLDOWN:
        return last_alert

    all_overbought = all(v > RSI_OVERBOUGHT for v in rsi_values.values())
    all_oversold = all(v < RSI_OVERSOLD for v in rsi_values.values())

    if not all_overbought and not all_oversold:
        return last_alert

    direction = "超买" if all_overbought else "超卖"
    emoji = "\U0001f534" if all_overbought else "\U0001f7e2"
    lines = [f"<b>{emoji} BTC RSI {direction}警报</b>"]
    for tf, rsi in rsi_values.items():
        lines.append(f"{tf}: RSI {rsi:.1f}")
    msg = "\n".join(lines)

    logger.info(msg.replace("<b>", "").replace("</b>", ""))
    notifier.send(msg)
    return now


def main(user_id: str = "default"):
    # 从 DB 加载策略配置并覆盖 config 模块变量
    cfg = load_strategy(user_id)
    apply_to_config(cfg)

    engine = FuturesEngine(leverage=LEVERAGE)
    engine.set_leverage()
    engine_okx = OKXEngine()

    strategy_cls = STRATEGIES[cfg.strategy_type]
    strategy = strategy_cls(**STRATEGY_KWARGS)

    risk = RiskManager(
        max_position_usdt=MAX_POSITION_USDT,
        daily_loss_limit=DAILY_LOSS_LIMIT,
        max_trades_per_day=MAX_TRADES_PER_DAY,
        min_profit_rate=MIN_PROFIT_RATE,
        max_loss_rate=MAX_LOSS_RATE,
        leverage=LEVERAGE,
    )
    notifier = Notifier()

    logger.info(f"🚀 合约引擎启动 | 用户: {user_id} | {CONTRACT_SYMBOL} | {TIMEFRAME} | {LEVERAGE}x | 策略: {STRATEGY_NAME}")
    logger.info(f"RSI监控启用 | 周期: {RSI_TIMEFRAMES} | 超买: >{RSI_OVERBOUGHT} | 超卖: <{RSI_OVERSOLD}")
    notifier.send(f"<b>🚀 合约引擎启动</b>\n用户: {user_id}\n{CONTRACT_SYMBOL} {TIMEFRAME} {LEVERAGE}x\n策略: {STRATEGY_NAME}")

    last_rsi_alert = 0.0

    while True:
        try:
            # 1. 获取合约行情
            df = engine.fetch_ohlcv(CONTRACT_SYMBOL, TIMEFRAME, LIMIT)
            price = float(df["close"].iloc[-1])

            # 1b. 获取实时价格对比（合约 vs OKX 现货）
            try:
                live_binance = engine.get_current_price(CONTRACT_SYMBOL)
            except Exception:
                live_binance = None
            try:
                live_okx = engine_okx.get_current_price(SYMBOL)
            except Exception:
                live_okx = None
            if live_binance and live_okx:
                spread = live_binance - live_okx
                logger.info(f"🔥 合约价 B:{live_binance:.2f}  O现货:{live_okx:.2f}  Δ:{spread:+.2f}")
            elif live_binance:
                logger.info(f"🔥 合约价 B:{live_binance:.2f}  O现货:获取失败")

            # 2. 持仓检查 —— 止盈/止损
            if risk.position:
                reason = risk.should_close(price)
                if reason:
                    pnl = risk.calc_pnl(price)
                    risk.record_trade(pnl, exit_price=price)
                    engine.cancel_all_orders()
                    logger.info(f"💰 {reason} | 当前价: {price:.4f} | 盈亏: {pnl:+.2f} ({LEVERAGE}x)")
                    notifier.send(
                        f"<b>{reason}</b>\n"
                        f"交易对: {CONTRACT_SYMBOL}\n"
                        f"价格: {price:.4f}\n"
                        f"盈亏: {pnl:+.2f} USDT ({LEVERAGE}x)"
                    )

            # 3. 生成信号
            signal, indicators = strategy.generate_signal(df)

            # 日志
            indicator_parts = []
            for k, v in indicators.items():
                indicator_parts.append(f"{k}: {v:.4f}")
            logger.info(
                f"📊 价格: {price:.4f} | "
                f"{' | '.join(indicator_parts)} | "
                f"信号: {SIGNAL_MAP[signal]}"
            )

            # 4. 执行交易（模拟模式不下真实单，只算盈亏记库）
            if signal == BUY and not risk.position:
                ok, reason = risk.can_trade()
                if ok:
                    risk.open_position(price)
                    label = "🟢 合约开多(模拟)" if PAPER_TRADING else "🟢 合约开多"
                    pos_value = MAX_POSITION_USDT * LEVERAGE
                    logger.info(f"{label} | {price:.4f} | 保证金:{MAX_POSITION_USDT}U | {LEVERAGE}x | 名义价值:{pos_value:.2f}U")
                    notifier.send(
                        f"<b>{label}</b>\n"
                        f"{CONTRACT_SYMBOL} @ {price:.4f}\n"
                        f"保证金: {MAX_POSITION_USDT} USDT | {LEVERAGE}x\n"
                        f"名义价值: {pos_value:.2f} USDT"
                    )
                    if not PAPER_TRADING:
                        engine.market_buy(CONTRACT_SYMBOL, MAX_POSITION_USDT)
                else:
                    logger.warning(f"⛔ 风控拦截: {reason}")

            elif signal == SELL and risk.position:
                engine.cancel_all_orders()
                pnl = risk.calc_pnl(price)
                risk.record_trade(pnl, exit_price=price)
                label = "🔴 合约平多(模拟)" if PAPER_TRADING else "🔴 合约平多"
                logger.info(f"{label} | {price:.4f} | 盈亏: {pnl:+.2f}")
                notifier.send(
                    f"<b>{label}</b>\n"
                    f"{CONTRACT_SYMBOL} @ {price:.4f}\n"
                    f"盈亏: {pnl:+.2f} USDT ({LEVERAGE}x)\n"
                    f"统计: 今日{risk.trade_count}笔 / 盈亏{risk.daily_pnl:+.2f}"
                )
                if not PAPER_TRADING:
                    engine.market_sell(CONTRACT_SYMBOL, MAX_POSITION_USDT)

            # ===== 多周期指标监控（合约数据，实时价参与）=====
            def _calc_indicators(exchange_obj, main_tf_df=None):
                """获取 RSI(多周期) + MACD + KDJ，最后一根用实时价更新 close/high/low"""
                rsi_res = {}
                macd_res = {}
                kdj_res = {}
                live_df = None
                for tf in RSI_TIMEFRAMES:
                    need = max(RSI_PERIOD + 10, 60)
                    if exchange_obj is engine and tf == TIMEFRAME and df is not None:
                        df_tf = df.copy()
                    else:
                        df_tf = exchange_obj.fetch_ohlcv(CONTRACT_SYMBOL, tf, need)

                    close = df_tf["close"].copy()
                    high = df_tf["high"].copy()
                    low = df_tf["low"].copy()
                    try:
                        live = exchange_obj.get_current_price(CONTRACT_SYMBOL)
                        if live:
                            close.iloc[-1] = live
                            if live > high.iloc[-1]:
                                high.iloc[-1] = live
                            if live < low.iloc[-1]:
                                low.iloc[-1] = live
                    except Exception:
                        pass

                    rsi_res[tf] = calc_rsi(close, RSI_PERIOD)

                    if tf == TIMEFRAME:
                        macd_res = calc_macd(close)
                        kdj_res = calc_kdj(close, high, low)
                        df_tf["close"] = close
                        df_tf["high"] = high
                        df_tf["low"] = low
                        live_df = df_tf
                return rsi_res, macd_res, kdj_res, live_df

            def _indicator_str(macd: dict, kdj: dict) -> str:
                parts = []
                if macd:
                    cross = "🟢" if macd["macd"] > macd["signal"] else "🔴"
                    parts.append(f"MACD:{macd['macd']:.1f}/{macd['signal']:.1f}({cross})")
                    parts.append(f"H:{macd['histogram']:.1f}")
                if kdj:
                    parts.append(f"K:{kdj['k']:.1f} D:{kdj['d']:.1f} J:{kdj['j']:.1f}")
                return " | ".join(parts)

            # 合约指标（含实时价更新后的 df）
            rsi_values, macd_data, kdj_data, live_df = _calc_indicators(engine, df)

            # 布林带（5m + 15m，周期20，标准差2）
            bb_5m = calc_bollinger_bands(df["close"], 20, 2)
            try:
                df_15m = engine.fetch_ohlcv(CONTRACT_SYMBOL, "15m", 25)
                bb_15m = calc_bollinger_bands(df_15m["close"], 20, 2)
            except Exception:
                bb_15m = None

            # 日志输出
            rsi_parts = [f"{tf} B:{rsi_values[tf]:.1f}" for tf in RSI_TIMEFRAMES]
            bb_parts = []
            for name, bb in [("5m", bb_5m), ("15m", bb_15m)]:
                if bb:
                    pct = f"{bb['position']*100:.0f}%"
                    bb_parts.append(f"{name} U:{bb['upper']:.0f} M:{bb['middle']:.0f} L:{bb['lower']:.0f}({pct})")
            logger.info(f"📈 {' | '.join(rsi_parts)} | {' | '.join(bb_parts)} | {_indicator_str(macd_data, kdj_data)}")

            # 五重过滤买入检查（用实时价更新的 live_df）
            if macd_data and kdj_data and live_df is not None:
                buy_signal, buy_msg = check_buy_conditions(live_df, macd_data, kdj_data)
                if buy_signal:
                    logger.info(f"🚨 {buy_msg}")
                    notifier.send(
                        f"<b>🟢 买入预警</b>\n"
                        f"{CONTRACT_SYMBOL} @ {price:.2f}\n"
                        f"{buy_msg}\n"
                        f"MACD:{macd_data['macd']:.1f} K:{kdj_data['k']:.1f} J:{kdj_data['j']:.1f}"
                    )
                elif buy_msg:
                    logger.info(f"⛔ {buy_msg}")

            last_rsi_alert = check_rsi_alert(rsi_values, last_rsi_alert, notifier)

            # 6. 状态摘要
            if risk.trade_count > 0:
                s = risk.summary
                logger.info(f"状态: {s}")

            time.sleep(5)

        except KeyboardInterrupt:
            logger.info("🛑 手动停止")
            break
        except Exception as e:
            logger.error(f"⚠️ 异常: {e}")
            time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="量化交易框架")
    parser.add_argument("--user", "-u", default="default", help="用户标识")
    args = parser.parse_args()
    main(user_id=args.user)
