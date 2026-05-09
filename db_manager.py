# -*- coding: utf-8 -*-
"""数据库初始化与连接管理"""
import json
import logging
from typing import Optional

import pymysql
from pymysql.constants import CLIENT

from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

logger = logging.getLogger(__name__)


def get_conn(database: Optional[str] = None):
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=database,
        connect_timeout=5,
        client_flag=CLIENT.MULTI_STATEMENTS,
    )


def execute(sql: str, params: tuple = (), db: Optional[str] = None) -> Optional[pymysql.cursors.Cursor]:
    """执行 SQL 并自动提交，返回 cursor"""
    try:
        conn = get_conn(database=db or DB_NAME)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur
    except Exception as e:
        logger.warning(f"数据库操作失败: {e}")
        return None


def fetch_one(sql: str, params: tuple = (), db: Optional[str] = None) -> Optional[dict]:
    """查询一条记录，返回字典"""
    try:
        conn = get_conn(database=db or DB_NAME)
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    except Exception as e:
        logger.warning(f"数据库查询失败: {e}")
        return None


def fetch_all(sql: str, params: tuple = (), db: Optional[str] = None) -> list[dict]:
    """查询多条记录，返回字典列表"""
    try:
        conn = get_conn(database=db or DB_NAME)
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as e:
        logger.warning(f"数据库查询失败: {e}")
        return []


def init_database():
    """自动创建数据库和所有需要的表（幂等）"""
    try:
        conn = get_conn(database=None)
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` DEFAULT CHARSET utf8mb4")
        conn.close()
        logger.info(f"数据库 `{DB_NAME}` 已就绪")
    except Exception as e:
        logger.warning(f"创建数据库失败: {e}")
        raise

    # trades 表
    execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
            entry_price DECIMAL(20, 8),
            exit_price  DECIMAL(20, 8),
            pnl         DECIMAL(20, 8),
            symbol      VARCHAR(20)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    # strategies 表
    execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            name            VARCHAR(100) NOT NULL COMMENT '策略名称',
            strategy_type   VARCHAR(50) NOT NULL COMMENT '策略类型: ma_cross, rsi_revert',
            symbol          VARCHAR(20) NOT NULL DEFAULT 'BTC/USDT',
            timeframe       VARCHAR(10) NOT NULL DEFAULT '5m',
            params          JSON COMMENT '策略专有参数',
            risk_params     JSON COMMENT '风控参数',
            rsi_params      JSON COMMENT 'RSI多周期监控参数',
            user_id         VARCHAR(100) NOT NULL DEFAULT '' COMMENT '用户标识',
            paper_trading   TINYINT NOT NULL DEFAULT 1 COMMENT '1=模拟, 0=实盘',
            enabled         TINYINT NOT NULL DEFAULT 1 COMMENT '1=启用, 0=禁用',
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_user (user_id),
            INDEX idx_enabled (enabled)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='策略配置表'
    """)

    logger.info("所有数据库表已就绪")


def insert_strategy_defaults(user_id: str = "default"):
    """为指定用户插入默认策略（如果不存在）"""
    existing = fetch_one(
        "SELECT id FROM strategies WHERE user_id = %s AND enabled = 1 LIMIT 1",
        (user_id,),
        db=DB_NAME,
    )
    if existing:
        return

    from config import (
        SHORT_MA, LONG_MA, SYMBOL, TIMEFRAME, LIMIT,
        MAX_POSITION_USDT, DAILY_LOSS_LIMIT, MAX_TRADES_PER_DAY,
        MIN_PROFIT_RATE, MAX_LOSS_RATE, PAPER_TRADING,
        STRATEGY_NAME,
        RSI_TIMEFRAMES, RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_ALERT_COOLDOWN,
    )

    execute(
        """INSERT INTO strategies
           (name, strategy_type, symbol, timeframe, params, risk_params, rsi_params, user_id, paper_trading)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            f"{user_id} 策略",
            STRATEGY_NAME,
            SYMBOL,
            TIMEFRAME,
            json.dumps({"short_window": SHORT_MA, "long_window": LONG_MA, "limit": LIMIT}),
            json.dumps({
                "max_position_usdt": MAX_POSITION_USDT,
                "daily_loss_limit": DAILY_LOSS_LIMIT,
                "max_trades_per_day": MAX_TRADES_PER_DAY,
                "min_profit_rate": MIN_PROFIT_RATE,
                "max_loss_rate": MAX_LOSS_RATE,
            }),
            json.dumps({
                "timeframes": RSI_TIMEFRAMES,
                "period": RSI_PERIOD,
                "overbought": RSI_OVERBOUGHT,
                "oversold": RSI_OVERSOLD,
                "alert_cooldown": RSI_ALERT_COOLDOWN,
            }),
            user_id,
            1 if PAPER_TRADING else 0,
        ),
        db=DB_NAME,
    )
    logger.info(f"已为用户 '{user_id}' 创建默认策略")
