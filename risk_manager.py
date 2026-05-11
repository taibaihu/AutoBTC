# -*- coding: utf-8 -*-
"""风险控制模块 —— 止盈止损、仓位管理、交易记录持久化（MySQL）"""
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from config import SYMBOL
from db_manager import execute, init_database

logger = logging.getLogger(__name__)


@dataclass
class RiskManager:
    max_position_usdt: float = 100.0
    order_qty: float = 0.05
    daily_loss_limit: float = 50.0
    max_trades_per_day: int = 20
    min_profit_rate: float = 0.01
    max_loss_rate: float = 0.02
    leverage: int = 100

    daily_pnl: float = 0.0
    trade_count: int = 0
    _position: bool = False
    _entry_price: float = 0.0
    _short_position: bool = False
    _short_entry_price: float = 0.0
    _reset_day: str = field(default_factory=lambda: time.strftime("%Y-%m-%d"))

    def __post_init__(self):
        init_database()

    def _check_day_reset(self):
        today = time.strftime("%Y-%m-%d")
        if today != self._reset_day:
            self.daily_pnl = 0.0
            self.trade_count = 0
            self._reset_day = today

    def _position_value(self) -> float:
        """仓位名义价值 = 持仓数量 × 入场价"""
        if self._position:
            return self.order_qty * self._entry_price
        if self._short_position:
            return self.order_qty * self._short_entry_price
        return 0.0

    def has_position(self) -> bool:
        """是否有任意方向持仓"""
        return self._position or self._short_position

    def position_side(self) -> Optional[str]:
        """返回当前持仓方向: LONG / SHORT / None"""
        if self._position:
            return "LONG"
        if self._short_position:
            return "SHORT"
        return None

    def can_trade(self) -> tuple[bool, str]:
        """返回 (是否可以交易, 原因)"""
        self._check_day_reset()

        if self.trade_count >= self.max_trades_per_day:
            return False, "已达每日最大交易次数"
        if self.daily_pnl <= -self.daily_loss_limit:
            return False, "已达每日亏损限额"
        return True, "OK"

    def calc_pnl(self, current_price: float) -> float:
        """多头盈亏计算（含杠杆）"""
        if not self._position:
            return 0.0
        return (current_price - self._entry_price) / self._entry_price * self._position_value()

    def calc_short_pnl(self, current_price: float) -> float:
        """空头盈亏计算（含杠杆），跌则赚"""
        if not self._short_position:
            return 0.0
        return (self._short_entry_price - current_price) / self._short_entry_price * self._position_value()

    def should_close_short(self, current_price: float) -> Optional[str]:
        """空头止盈/止损判断。空头: 跌=盈, 涨=亏"""
        if not self._short_position:
            return None
        change = (self._short_entry_price - current_price) / self._short_entry_price
        # change > 0 表示跌了，盈利；change < 0 表示涨了，亏损
        if change >= self.min_profit_rate:
            return f"空头止盈 (+{change:.2%})"
        if change <= -self.max_loss_rate:
            return f"空头止损 ({change:.2%})"
        return None

    def open_short(self, entry_price: float):
        """开空"""
        self._short_position = True
        self._short_entry_price = entry_price

    def close_short(self, pnl: float, exit_price: float = 0.0):
        """记录空头平仓盈亏"""
        self.daily_pnl += pnl
        self.trade_count += 1
        execute(
            "INSERT INTO trades (entry_price, exit_price, pnl, symbol) VALUES (%s, %s, %s, %s)",
            (self._short_entry_price, exit_price, round(pnl, 4), SYMBOL),
        )
        self._short_position = False

    def record_trade(self, pnl: float, exit_price: float = 0.0):
        """记录一笔成交盈亏，持久化到 MySQL"""
        self.daily_pnl += pnl
        self.trade_count += 1

        execute(
            "INSERT INTO trades (entry_price, exit_price, pnl, symbol) VALUES (%s, %s, %s, %s)",
            (self._entry_price, exit_price, round(pnl, 4), SYMBOL),
        )

        self._position = False

    def open_position(self, entry_price: float):
        self._position = True
        self._entry_price = entry_price

    def should_close(self, current_price: float) -> Optional[str]:
        """判断是否需要止盈/止损，返回原因或 None"""
        if not self._position:
            return None

        change = (current_price - self._entry_price) / self._entry_price

        if change >= self.min_profit_rate:
            return f"止盈 (+{change:.2%})"
        if change <= -self.max_loss_rate:
            return f"止损 ({change:.2%})"
        return None

    @property
    def position(self) -> bool:
        return self._position

    @property
    def short_position(self) -> bool:
        return self._short_position

    @property
    def summary(self) -> dict:
        self._check_day_reset()
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "trade_count": self.trade_count,
            "position": self._position,
            "short_position": self._short_position,
            "side": self.position_side(),
        }
