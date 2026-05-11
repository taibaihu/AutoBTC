#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量化交易框架 —— 入口"""
import argparse
import time
import logging
from logging.handlers import TimedRotatingFileHandler

import pandas as pd

from config import (
    SYMBOL, CONTRACT_SYMBOL, TIMEFRAME, LIMIT, SHORT_MA, LONG_MA,
    MAX_POSITION_USDT, DAILY_LOSS_LIMIT, MAX_TRADES_PER_DAY,
    MIN_PROFIT_RATE, MAX_LOSS_RATE, LEVERAGE,
    FIXED_ORDER_QTY,
    STRATEGY_NAME, STRATEGY_KWARGS,
    RSI_TIMEFRAMES, RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_ALERT_COOLDOWN,
    POSITION_COOLDOWN_MINUTES, STARTUP_COOLDOWN,
)
from engine import FuturesEngine, OKXEngine
from strategy import BUY, SELL, HOLD, STRATEGIES, calc_rsi_series, calc_macd, calc_kdj, calc_bollinger_bands
from risk_manager import RiskManager
from db_manager import save_real_order, save_sim_order, create_local_trade, close_local_trade, get_latest_active_trade
from notifier import Notifier
from strategy_manager import load_strategy, apply_to_config

handler = TimedRotatingFileHandler("main.log", when="midnight", interval=1, backupCount=30, encoding="utf-8")
handler.suffix = "%Y-%m-%d"
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))


logging.basicConfig(level=logging.INFO, handlers=[handler])
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
        order_qty=FIXED_ORDER_QTY,
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
    next_trade_time = time.time() + STARTUP_COOLDOWN

    is_short_strategy = cfg.strategy_type in ("fast_range_short",)
    if is_short_strategy:
        logger.info("📉 做空模式: SELL=开空, BUY=平空")

    # ── 启动时同步币安实际持仓 ──
    if is_short_strategy:
        existing = engine.get_position("SHORT")
        if existing:
            risk.open_short(existing["entry_price"])
            logger.info(f"🔄 同步到现有空仓 | 数量:{existing['size']:.4f} BTC | 入场:{existing['entry_price']:.0f}")
            if not strategy.paper_trading:
                engine.set_tp_sl_short(existing["entry_price"])
    else:
        existing = engine.get_position("LONG")
        if existing:
            risk.open_position(existing["entry_price"])
            logger.info(f"🔄 同步到现有多仓 | 数量:{existing['size']:.4f} BTC | 入场:{existing['entry_price']:.0f}")
            if not strategy.paper_trading:
                engine.set_tp_sl_long(existing["entry_price"])
    # 清除启动前的残留挂单（防止重复开仓）
    if not strategy.paper_trading:
        engine.cancel_all_orders()

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
                logger.info(f"🔥 合约价 B:{live_binance:.0f}  O合约价:{live_okx:.0f}  Δ:{spread:+.2f}")
            elif live_binance:
                logger.info(f"🔥 合约价 B:{live_binance:.0f}  O合约价:获取失败")

            # 2. 持仓检查 —— 止盈/止损（多空独立检查）
            if risk.position:
                reason = risk.should_close(price)
                entry = risk._entry_price
                chg = (price - entry) / entry * 100
                logger.info(f"📌 [{user_id}] 多仓 | 入场:{entry:.0f} 当前:{price:.0f} 涨跌:{chg:+.2f}% 止盈:{risk.min_profit_rate*100:.1f}% 止损:{risk.max_loss_rate*100:.1f}% {'🔔 '+reason if reason else '⏳ 持有中'}")
                if reason:
                    pnl = risk.calc_pnl(price)
                    risk.record_trade(pnl, exit_price=price)
                    engine.cancel_all_orders()
                    close_label = "多单止盈止损"
                    logger.info(f"💰 {reason} | 当前价: {price:.0f} | 盈亏: {pnl:+.2f} ({LEVERAGE}x)")
                    notifier.send(
                        f"<b>{reason}</b>\n"
                        f"交易对: {CONTRACT_SYMBOL}\n"
                        f"价格: {price:.0f}\n"
                        f"盈亏: {pnl:+.2f} USDT ({LEVERAGE}x)"
                    )
                    if not strategy.paper_trading:
                        result = engine.market_sell(CONTRACT_SYMBOL, MAX_POSITION_USDT)
                        save_real_order(result, CONTRACT_SYMBOL, "SELL", "LONG",
                                        strategy.__class__.__name__, LEVERAGE, paper_trading=0, pnl=pnl)
                        bo_id = result.get("info", result).get("orderId") or result.get("id")
                        active = get_latest_active_trade("LONG")
                        if active and bo_id:
                            close_local_trade(active["id"], bo_id, price, pnl)
                    else:
                        save_sim_order(CONTRACT_SYMBOL, "SELL", "LONG", price,
                                       signal_type="tp_sl", strategy_name=strategy.__class__.__name__,
                                       msg=f"TP/SL平多 @ {price} | PnL:{pnl:+.2f}")
                    next_trade_time = time.time() + POSITION_COOLDOWN_MINUTES * 60

            if risk.short_position:
                reason = risk.should_close_short(price)
                entry = risk._short_entry_price
                chg = (entry - price) / entry * 100
                logger.info(f"📌 [{user_id}] 空仓 | 入场:{entry:.0f} 当前:{price:.0f} 涨跌:{chg:+.2f}% 止盈:{risk.min_profit_rate*100:.1f}% 止损:{risk.max_loss_rate*100:.1f}% {'🔔 '+reason if reason else '⏳ 持有中'}")
                if reason:
                    pnl = risk.calc_short_pnl(price)
                    risk.close_short(pnl, exit_price=price)
                    engine.cancel_all_orders()
                    logger.info(f"💰 {reason} | 当前价: {price:.0f} | 盈亏: {pnl:+.2f} ({LEVERAGE}x)")
                    notifier.send(
                        f"<b>{reason}</b>\n"
                        f"交易对: {CONTRACT_SYMBOL}\n"
                        f"价格: {price:.0f}\n"
                        f"盈亏: {pnl:+.2f} USDT ({LEVERAGE}x)"
                    )
                    if not strategy.paper_trading:
                        result = engine.market_buy_cover(CONTRACT_SYMBOL, MAX_POSITION_USDT)
                        save_real_order(result, CONTRACT_SYMBOL, "BUY", "SHORT",
                                        strategy.__class__.__name__, LEVERAGE, paper_trading=0, pnl=pnl)
                        bo_id = result.get("info", result).get("orderId") or result.get("id")
                        active = get_latest_active_trade("SHORT")
                        if active and bo_id:
                            close_local_trade(active["id"], bo_id, price, pnl)
                    else:
                        save_sim_order(CONTRACT_SYMBOL, "BUY", "SHORT", price,
                                       signal_type="tp_sl", strategy_name=strategy.__class__.__name__,
                                       msg=f"TP/SL平空 @ {price} | PnL:{pnl:+.2f}")
                    next_trade_time = time.time() + POSITION_COOLDOWN_MINUTES * 60

            if not risk.position and not risk.short_position:
                logger.info(f"📌 [{user_id}] 无持仓")

            # 3. 生成信号
            signal, indicators = strategy.generate_signal(df)

            # 日志
            indicator_parts = []
            for k, v in indicators.items():
                if isinstance(v, float):
                    indicator_parts.append(f"{k}: {v:.0f}")
                else:
                    indicator_parts.append(f"{k}: {v}")
            logger.info(
                f"📊 价格: {price:.0f} | "
                f"{' | '.join(indicator_parts)} | "
                f"信号: {SIGNAL_MAP[signal]}"
            )

            # 4. 执行交易（模拟模式不下真实单，只算盈亏记库）
            if is_short_strategy:
                # ── 做空模式: SELL=开空, BUY=平空 ──
                if signal == SELL and not risk.short_position:
                    if time.time() < next_trade_time:
                        logger.info(f"⏳ 冷却中({int(next_trade_time - time.time())}s)")
                    else:
                        ok, reason = risk.can_trade()
                        if ok:
                            # 互斥检查: 有反向持仓则不开
                            existing_long = engine.get_position_size(CONTRACT_SYMBOL, "LONG")
                            if existing_long > 0:
                                logger.warning(f"⛔ 已有反向多单 {existing_long:.4f} BTC，不開空")
                            else:
                                risk.open_short(price)
                                label = "🔴 合约开空(模拟)" if strategy.paper_trading else "🔴 合约开空"
                                pos_value = FIXED_ORDER_QTY * price
                                logger.info(f"{label} | {price:.0f} | 数量:{FIXED_ORDER_QTY}BTC | {LEVERAGE}x | 价值:{pos_value:.2f}U")
                                notifier.send(
                                    f"<b>{label}</b>\n"
                                    f"{CONTRACT_SYMBOL} @ {price:.0f}\n"
                                    f"数量: {FIXED_ORDER_QTY} BTC | {LEVERAGE}x\n"
                                    f"价值: {pos_value:.2f} USDT"
                                )
                                if not strategy.paper_trading:
                                    result = engine.limit_sell_short_open()
                                    save_real_order(result, CONTRACT_SYMBOL, "SELL", "SHORT",
                                                    strategy.__class__.__name__, LEVERAGE, paper_trading=0)
                                    bo_id = result.get("info", result).get("orderId") or result.get("id")
                                    if bo_id:
                                        create_local_trade(CONTRACT_SYMBOL, "SHORT", bo_id,
                                                           price, FIXED_ORDER_QTY, LEVERAGE,
                                                           strategy.__class__.__name__)
                                    engine.set_tp_sl_short(price)
                                else:
                                    save_sim_order(CONTRACT_SYMBOL, "SELL", "SHORT", price,
                                                   signal_type="strategy_signal", strategy_name=strategy.__class__.__name__,
                                               msg=f"开空 @ {price}")
                        else:
                            logger.warning(f"⛔ 风控拦截: {reason}")

                elif signal == BUY and risk.short_position:
                    engine.cancel_all_orders()
                    pnl = risk.calc_short_pnl(price)
                    risk.close_short(pnl, exit_price=price)
                    next_trade_time = time.time() + POSITION_COOLDOWN_MINUTES * 60
                    label = "🟢 合约平空(模拟)" if strategy.paper_trading else "🟢 合约平空"
                    logger.info(f"{label} | {price:.0f} | 盈亏: {pnl:+.2f}")
                    notifier.send(
                        f"<b>{label}</b>\n"
                        f"{CONTRACT_SYMBOL} @ {price:.0f}\n"
                        f"盈亏: {pnl:+.2f} USDT ({LEVERAGE}x)\n"
                        f"统计: 今日{risk.trade_count}笔 / 盈亏{risk.daily_pnl:+.2f}"
                    )
                    if not strategy.paper_trading:
                        result = engine.market_buy_cover(CONTRACT_SYMBOL, MAX_POSITION_USDT)
                        save_real_order(result, CONTRACT_SYMBOL, "BUY", "SHORT",
                                        strategy.__class__.__name__, LEVERAGE, paper_trading=0, pnl=pnl)
                        bo_id = result.get("info", result).get("orderId") or result.get("id")
                        active = get_latest_active_trade("SHORT")
                        if active and bo_id:
                            close_local_trade(active["id"], bo_id, price, pnl)
                    else:
                        save_sim_order(CONTRACT_SYMBOL, "BUY", "SHORT", price,
                                       signal_type="strategy_signal", strategy_name=strategy.__class__.__name__,
                                       msg=f"平空 @ {price} | PnL:{pnl:+.2f}")
            else:
                # ── 做多模式: BUY=开多, SELL=平多 ──
                if signal == BUY and not risk.position:
                    if time.time() < next_trade_time:
                        logger.info(f"⏳ 冷却中({int(next_trade_time - time.time())}s)")
                    else:
                        ok, reason = risk.can_trade()
                        if ok:
                            # 互斥检查: 有反向持仓则不开
                            existing_short = engine.get_position_size(CONTRACT_SYMBOL, "SHORT")
                            if existing_short > 0:
                                logger.warning(f"⛔ 已有反向空单 {existing_short:.4f} BTC，不开多")
                            else:
                                risk.open_position(price)
                                label = "🟢 合约开多(模拟)" if strategy.paper_trading else "🟢 合约开多"
                                pos_value = FIXED_ORDER_QTY * price
                                logger.info(f"{label} | {price:.0f} | 数量:{FIXED_ORDER_QTY}BTC | {LEVERAGE}x | 价值:{pos_value:.2f}U")
                                notifier.send(
                                    f"<b>{label}</b>\n"
                                    f"{CONTRACT_SYMBOL} @ {price:.0f}\n"
                                    f"数量: {FIXED_ORDER_QTY} BTC | {LEVERAGE}x\n"
                                    f"价值: {pos_value:.2f} USDT"
                                )
                                if not strategy.paper_trading:
                                    result = engine.limit_buy_open()
                                    save_real_order(result, CONTRACT_SYMBOL, "BUY", "LONG",
                                                    strategy.__class__.__name__, LEVERAGE, paper_trading=0)
                                    bo_id = result.get("info", result).get("orderId") or result.get("id")
                                    if bo_id:
                                        create_local_trade(CONTRACT_SYMBOL, "LONG", bo_id,
                                                           price, FIXED_ORDER_QTY, LEVERAGE,
                                                           strategy.__class__.__name__)
                                    engine.set_tp_sl_long(price)
                                else:
                                    save_sim_order(CONTRACT_SYMBOL, "BUY", "LONG", price,
                                               signal_type="strategy_signal", strategy_name=strategy.__class__.__name__,
                                               msg=f"开多 @ {price}")
                        else:
                            logger.warning(f"⛔ 风控拦截: {reason}")

                elif signal == SELL and risk.position:
                    engine.cancel_all_orders()
                    pnl = risk.calc_pnl(price)
                    risk.record_trade(pnl, exit_price=price)
                    next_trade_time = time.time() + POSITION_COOLDOWN_MINUTES * 60
                    label = "🔴 合约平多(模拟)" if strategy.paper_trading else "🔴 合约平多"
                    logger.info(f"{label} | {price:.0f} | 盈亏: {pnl:+.2f}")
                    notifier.send(
                        f"<b>{label}</b>\n"
                        f"{CONTRACT_SYMBOL} @ {price:.0f}\n"
                        f"盈亏: {pnl:+.2f} USDT ({LEVERAGE}x)\n"
                        f"统计: 今日{risk.trade_count}笔 / 盈亏{risk.daily_pnl:+.2f}"
                    )
                    if not strategy.paper_trading:
                        result = engine.market_sell(CONTRACT_SYMBOL, MAX_POSITION_USDT)
                        save_real_order(result, CONTRACT_SYMBOL, "SELL", "LONG",
                                        strategy.__class__.__name__, LEVERAGE, paper_trading=0, pnl=pnl)
                        bo_id = result.get("info", result).get("orderId") or result.get("id")
                        active = get_latest_active_trade("LONG")
                        if active and bo_id:
                            close_local_trade(active["id"], bo_id, price, pnl)
                    else:
                        save_sim_order(CONTRACT_SYMBOL, "SELL", "LONG", price,
                                       signal_type="strategy_signal", strategy_name=strategy.__class__.__name__,
                                       msg=f"平多 @ {price} | PnL:{pnl:+.2f}")

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
            rsi_values, macd_data, kdj_data, _ = _calc_indicators(engine, df)

            # 布林带（15m，周期20，标准差2）
            bb_15m = calc_bollinger_bands(df["close"], 20, 2)

            # 日志输出
            rsi_parts = [f"{tf} B:{rsi_values[tf]:.0f}" for tf in RSI_TIMEFRAMES]
            bb_parts = []
            if bb_15m:
                pct = f"{bb_15m['position']*100:.0f}%"
                bb_parts.append(f"15m U:{bb_15m['upper']:.0f} M:{bb_15m['middle']:.0f} L:{bb_15m['lower']:.0f}({pct})")
            logger.info(f"📈 {' | '.join(rsi_parts)} | {' | '.join(bb_parts)} | {_indicator_str(macd_data, kdj_data)}")

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
