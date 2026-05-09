#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试下单程序 —— 开多 1U 保证金，设置 1% 止盈止损"""
import sys
import time
import logging

from engine import FuturesEngine
from config import LEVERAGE, CONTRACT_SYMBOL

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

MARGIN = 1        # 1 USDT 保证金
TP_PCT = 0.01     # 1% 止盈
SL_PCT = 0.01     # 1% 止损


def main():
    engine = FuturesEngine(leverage=LEVERAGE)
    engine.set_leverage()

    # 1. 查余额
    balance = engine.get_balance("USDT")
    logger.info(f"合约账户余额: {balance:.2f} USDT")
    if balance < MARGIN:
        logger.error("余额不足，无法下单")
        sys.exit(1)

    # 2. 获取当前价格
    price = engine.get_current_price(CONTRACT_SYMBOL)
    if not price or price == 0:
        logger.error("获取价格失败")
        sys.exit(1)
    logger.info(f"当前价格: {price:.2f} USDT")

    # 3. 计算数量
    quantity = engine.calc_contract_amount(MARGIN, price)
    nominal = MARGIN * LEVERAGE
    logger.info(f"下单参数: 保证金={MARGIN}U | 杠杆={LEVERAGE}x | 名义价值={nominal:.2f}U")
    logger.info(f"合约数量: {quantity} BTC")

    # 4. 确认
    print(f"\n{'='*50}")
    print(f"即将实盘开多: {CONTRACT_SYMBOL}")
    print(f"  价格: {price:.2f}")
    print(f"  数量: {quantity} BTC")
    print(f"  名义价值: {nominal:.2f} USDT")
    print(f"  保证金: {MARGIN} USDT")
    print(f"  止盈价: {price * (1 + TP_PCT):.2f} (+1%)")
    print(f"  止损价: {price * (1 - SL_PCT):.2f} (-1%)")
    print(f"{'='*50}")
    confirm = input("\n确认下单? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("已取消")
        return

    # 5. 开多
    logger.info("正在开多...")
    try:
        order = engine.market_buy(CONTRACT_SYMBOL, MARGIN)
        logger.info(f"开多成功: {order.get('id', 'N/A')}")
        logger.info(f"成交均价: {order.get('price', '市价')}")
        logger.info(f"成交数量: {order.get('filled', quantity)}")
    except Exception as e:
        logger.error(f"开多失败: {e}")
        sys.exit(1)

    # 6. 查询持仓（等订单成交）
    time.sleep(4)
    pos = engine.get_position()
    if pos:
        entry = pos["entry_price"]
        size = pos["size"]
        logger.info(f"当前持仓: {size} BTC @ {entry:.2f}")
    else:
        logger.warning("未查到持仓，可能已全部成交或已被强平")
        entry = price
        size = quantity

    # 7. 设置止盈止损（市价触发单）
    tp_price = round(entry * (1 + TP_PCT), 1)
    sl_price = round(entry * (1 - SL_PCT), 1)

    try:
        logger.info(f"设置止盈: {tp_price:.1f}")
        engine.exchange.create_order(
            CONTRACT_SYMBOL, "TAKE_PROFIT_MARKET", "sell", size,
            params={"stopPrice": tp_price, "reduceOnly": True, "positionSide": "LONG"},
        )
        logger.info(f"止盈单已提交 ✅")
    except Exception as e:
        logger.warning(f"止盈单失败: {e}")

    try:
        logger.info(f"设置止损: {sl_price:.1f}")
        engine.exchange.create_order(
            CONTRACT_SYMBOL, "STOP_MARKET", "sell", size,
            params={"stopPrice": sl_price, "reduceOnly": True, "positionSide": "LONG"},
        )
        logger.info(f"止损单已提交 ✅")
    except Exception as e:
        logger.warning(f"止损单失败: {e}")

    # 8. 汇总
    print(f"\n{'='*50}")
    print(f"✅ 测试单完成")
    print(f"  开仓价: {entry:.2f}")
    print(f"  数量: {size} BTC")
    print(f"  止盈: {tp_price:.1f} (+1% = +{nominal*TP_PCT:.2f}U)")
    print(f"  止损: {sl_price:.1f} (-1% = -{nominal*SL_PCT:.2f}U)")
    print(f"  保证金: {MARGIN} USDT | {LEVERAGE}x")
    print(f"{'='*50}")
    print("⚠️ 请在币安合约页面核对订单，手动测试完后平仓")
    print("   或运行: python3 test_close.py")


if __name__ == "__main__":
    main()
