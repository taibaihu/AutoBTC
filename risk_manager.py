# -*- coding: utf-8 -*-
"""风险控制模块 —— 止盈止损、仓位管理、交易记录持久化（MySQL）"""
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import pymysql
from pymysql.constants import CLIENT

from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, SYMBOL

logger = logging.getLogger(__name__)


def _get_conn(database: str = None):
    """获取 MySQL 连接"""
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=database,
        connect_timeout=5,
        client_flag=CLIENT.MULTI_STATEMENTS,
    )


def _ensure_database_and_table():
    """自动创建数据库和 trades 表（幂等）"""
    try:
        # 先连接 MySQL（不指定库）创建数据库
        conn = _get_conn(database=None)
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` DEFAULT CHARSET utf8mb4")
        conn.close()

        # 再连到目标库创建表
        conn = _get_conn(database=DB_NAME)
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
                    entry_price DECIMAL(20, 8),
                    exit_price  DECIMAL(20, 8),
                    pnl         DECIMAL(20, 8),
                    symbol      VARCHAR(20)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
        conn.commit()
        conn.close()
        logger.info(f"数据库 `{DB_NAME}` 及 trades 表已就绪")
    except Exception as e:
        logger.warning(f"数据库初始化失败: {e}")
        raise


def _execute(sql: str, params: tuple = ()) -> Optional[pymysql.cursors.Cursor]:
    """执行 SQL 并自动提交"""
    try:
        conn = _get_conn(database=DB_NAME)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur
    except Exception as e:
        logger.warning(f"数据库操作失败: {e}")
        return None


@dataclass
class RiskManager:
    max_position_usdt: float = 100.0
    daily_loss_limit: float = 50.0
    max_trades_per_day: int = 20
    min_profit_rate: float = 0.01
    max_loss_rate: float = 0.02

    daily_pnl: float = 0.0
    trade_count: int = 0
    _position: bool = False
    _entry_price: float = 0.0
    _reset_day: str = field(default_factory=lambda: time.strftime("%Y-%m-%d"))

    def __post_init__(self):
        _ensure_database_and_table()

    def _check_day_reset(self):
        today = time.strftime("%Y-%m-%d")
        if today != self._reset_day:
            self.daily_pnl = 0.0
            self.trade_count = 0
            self._reset_day = today

    def can_trade(self) -> tuple[bool, str]:
        """返回 (是否可以交易, 原因)"""
        self._check_day_reset()

        if self.trade_count >= self.max_trades_per_day:
            return False, "已达每日最大交易次数"
        if self.daily_pnl <= -self.daily_loss_limit:
            return False, "已达每日亏损限额"
        return True, "OK"

    def calc_pnl(self, current_price: float) -> float:
        """统一盈亏计算，避免调用方重复手算"""
        if not self._position:
            return 0.0
        return (current_price - self._entry_price) / self._entry_price * self.max_position_usdt

    def record_trade(self, pnl: float, exit_price: float = 0.0):
        """记录一笔成交盈亏，持久化到 MySQL"""
        self.daily_pnl += pnl
        self.trade_count += 1

        _execute(
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
    def summary(self) -> dict:
        self._check_day_reset()
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "trade_count": self.trade_count,
            "position": self._position,
        }
