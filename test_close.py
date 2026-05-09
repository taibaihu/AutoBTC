#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试平仓程序 —— 市价平掉当前所有持仓 + 撤销挂单"""
import logging

from engine import FuturesEngine
from config import LEVERAGE, CONTRACT_SYMBOL

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    engine = FuturesEngine(leverage=LEVERAGE)

    # 1. 查持仓
    pos = engine.get_position()
    if not pos:
        logger.info("当前无持仓，无需平仓")
        return

    size = pos["size"]
    entry = pos["entry_price"]
    price = engine.get_current_price(CONTRACT_SYMBOL)
    pnl = (price - entry) / entry * (1 * LEVERAGE)  # 1U 保证金
    logger.info(f"持仓: {size} BTC @ {entry:.2f} | 现价: {price:.2f} | 浮动盈亏: {pnl:+.2f}U")

    # 2. 撤销所有挂单
    engine.cancel_all_orders()

    # 3. 市价平仓
    logger.info(f"正在市价平仓 {size} BTC...")
    try:
        order = engine.exchange.create_market_sell_order(CONTRACT_SYMBOL, size, {"positionSide": "LONG"})
        logger.info(f"平仓成功 ✅ | 订单ID: {order.get('id', 'N/A')}")
    except Exception as e:
        logger.error(f"平仓失败: {e}")
        return

    # 4. 结果
    price_now = engine.get_current_price(CONTRACT_SYMBOL)
    pnl_real = (price_now - entry) / entry * (1 * LEVERAGE)
    logger.info(f"平仓价: {price_now:.2f} | 实际盈亏: {pnl_real:+.2f} USDT")


if __name__ == "__main__":
    main()
