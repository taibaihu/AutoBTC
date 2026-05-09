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

    # strategy_risk_params 表（风控参数独立存放，每列清晰可见）
    execute("""
        CREATE TABLE IF NOT EXISTS strategy_risk_params (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            strategy_id         INT NOT NULL COMMENT '关联 strategies.id',
            max_position_usdt   DECIMAL(20, 2) NOT NULL DEFAULT 100.00,
            daily_loss_limit    DECIMAL(20, 2) NOT NULL DEFAULT 50.00,
            max_trades_per_day  INT NOT NULL DEFAULT 20,
            min_profit_rate     DECIMAL(10, 4) NOT NULL DEFAULT 0.0100,
            max_loss_rate       DECIMAL(10, 4) NOT NULL DEFAULT 0.0200,
            leverage            INT NOT NULL DEFAULT 100 COMMENT '合约杠杆倍数',
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_strategy (strategy_id),
            CONSTRAINT fk_risk_strategy FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='策略风控参数表'
    """)

    # 迁移：为已有表加 leverage 列 + 补默认值
    _add_column_if_not_exists("strategy_risk_params", "leverage", "INT NOT NULL DEFAULT 100 COMMENT '合约杠杆倍数' AFTER max_loss_rate")
    migrate_leverage_column()

    # 迁移旧数据：将 strategies.risk_params JSON 中的数据复制到新表（仅一次）
    migrate_risk_params()

    logger.info("所有数据库表已就绪")


def migrate_risk_params():
    """一次性迁移：将旧 strategies.risk_params JSON 数据导入 strategy_risk_params 表"""
    # 检查旧列是否存在
    col_check = fetch_one("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='strategies' AND COLUMN_NAME='risk_params'", (DB_NAME,), db=DB_NAME)
    if not col_check:
        return  # 旧列不存在，无需迁移

    # 查出所有还没有风控参数记录的 strategy
    rows = fetch_all("""
        SELECT s.id, s.risk_params
        FROM strategies s
        LEFT JOIN strategy_risk_params r ON r.strategy_id = s.id
        WHERE r.id IS NULL AND s.risk_params IS NOT NULL
    """, db=DB_NAME)
    if not rows:
        return

    for row in rows:
        try:
            rp = json.loads(row["risk_params"]) if isinstance(row["risk_params"], str) else (row["risk_params"] or {})
        except (json.JSONDecodeError, TypeError):
            rp = {}
        execute(
            """INSERT INTO strategy_risk_params
               (strategy_id, max_position_usdt, daily_loss_limit, max_trades_per_day, min_profit_rate, max_loss_rate, leverage)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                row["id"],
                rp.get("max_position_usdt", 100),
                rp.get("daily_loss_limit", 50),
                rp.get("max_trades_per_day", 20),
                rp.get("min_profit_rate", 0.01),
                rp.get("max_loss_rate", 0.02),
                rp.get("leverage", 100),
            ),
            db=DB_NAME,
        )
        logger.info(f"已迁移 {len(rows)} 条策略的风控参数到 strategy_risk_params 表")


def _add_column_if_not_exists(table: str, column: str, definition: str):
    """幂等地给表加列"""
    col_check = fetch_one(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (DB_NAME, table, column), db=DB_NAME,
    )
    if col_check:
        return
    try:
        execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}", db=DB_NAME)
        logger.info(f"表 {table} 已添加列 {column}")
    except Exception as e:
        logger.warning(f"添加列 {column} 失败: {e}")


def migrate_leverage_column():
    """为已有 strategy_risk_params 记录补全 leverage 字段（新增列时使用）"""
    col_check = fetch_one(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='strategy_risk_params' AND COLUMN_NAME='leverage'",
        (DB_NAME,), db=DB_NAME,
    )
    if not col_check:
        return  # 列还不存在，说明还没重建表
    execute("UPDATE strategy_risk_params SET leverage = 100 WHERE leverage IS NULL OR leverage = 0", db=DB_NAME)


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
        MIN_PROFIT_RATE, MAX_LOSS_RATE, LEVERAGE, PAPER_TRADING,
        STRATEGY_NAME,
        RSI_TIMEFRAMES, RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_ALERT_COOLDOWN,
    )

    # 插入 strategies 表
    execute(
        """INSERT INTO strategies
           (name, strategy_type, symbol, timeframe, params, rsi_params, user_id, paper_trading)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            f"{user_id} 策略",
            STRATEGY_NAME,
            SYMBOL,
            TIMEFRAME,
            json.dumps({"short_window": SHORT_MA, "long_window": LONG_MA, "limit": LIMIT}),
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

    # 获取新插入的策略 ID，插入 strategy_risk_params
    row = fetch_one(
        "SELECT id FROM strategies WHERE user_id = %s ORDER BY id DESC LIMIT 1",
        (user_id,),
        db=DB_NAME,
    )
    if row:
        execute(
            """INSERT INTO strategy_risk_params
               (strategy_id, max_position_usdt, daily_loss_limit, max_trades_per_day, min_profit_rate, max_loss_rate, leverage)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                row["id"],
                MAX_POSITION_USDT, DAILY_LOSS_LIMIT, MAX_TRADES_PER_DAY,
                MIN_PROFIT_RATE, MAX_LOSS_RATE, LEVERAGE,
            ),
            db=DB_NAME,
        )

    logger.info(f"已为用户 '{user_id}' 创建默认策略")
