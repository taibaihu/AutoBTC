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

    # real_orders 表（实盘订单，与币安订单数据对齐）
    execute("""
        CREATE TABLE IF NOT EXISTS real_orders (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            binance_order_id  BIGINT NOT NULL COMMENT '币安订单号',
            client_order_id   VARCHAR(100) DEFAULT '' COMMENT '客户端订单ID',
            symbol            VARCHAR(20) NOT NULL COMMENT '交易对',
            side              VARCHAR(10) NOT NULL COMMENT 'BUY/SELL',
            position_side     VARCHAR(10) DEFAULT '' COMMENT 'LONG/SHORT',
            order_type        VARCHAR(20) NOT NULL DEFAULT 'MARKET' COMMENT '订单类型',
            status            VARCHAR(20) NOT NULL COMMENT 'NEW/PARTIALLY_FILLED/FILLED/CANCELED',
            price             DECIMAL(20, 8) DEFAULT NULL COMMENT '订单价格',
            avg_price         DECIMAL(20, 8) DEFAULT NULL COMMENT '成交均价',
            orig_qty          DECIMAL(20, 8) DEFAULT NULL COMMENT '原始数量',
            executed_qty      DECIMAL(20, 8) DEFAULT NULL COMMENT '已执行数量',
            cum_quote         DECIMAL(20, 8) DEFAULT NULL COMMENT '成交金额(USDT)',
            leverage          INT DEFAULT NULL COMMENT '杠杆倍数',
            strategy_name     VARCHAR(50) DEFAULT '' COMMENT '策略名称',
            paper_trading     TINYINT NOT NULL DEFAULT 0 COMMENT '0=实盘 1=模拟',
            pnl               DECIMAL(20, 8) DEFAULT NULL COMMENT '盈亏(平仓时填入)',
            binance_time      BIGINT DEFAULT NULL COMMENT '币安成交时间戳(ms)',
            created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at        DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_binance_order (binance_order_id),
            INDEX idx_status (status),
            INDEX idx_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='实盘订单表'
    """)

    # 实盘分析表（按策略+日期聚合）
    execute("""
        CREATE TABLE IF NOT EXISTS real_order_analysis (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            strategy_name   VARCHAR(50) NOT NULL COMMENT '策略名称',
            period          VARCHAR(10) NOT NULL COMMENT '周期: day',
            period_start    DATE NOT NULL COMMENT '周期起始日期',
            period_end      DATE NOT NULL COMMENT '周期结束日期',
            total_trades    INT NOT NULL DEFAULT 0,
            wins            INT NOT NULL DEFAULT 0,
            losses          INT NOT NULL DEFAULT 0,
            win_rate        DECIMAL(5, 2) DEFAULT 0.00,
            total_pnl       DECIMAL(20, 8) DEFAULT 0.00000000,
            avg_pnl         DECIMAL(20, 8) DEFAULT 0.00000000,
            max_win         DECIMAL(20, 8) DEFAULT 0.00000000,
            max_loss        DECIMAL(20, 8) DEFAULT 0.00000000,
            total_volume    DECIMAL(20, 8) DEFAULT 0.00000000,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_strategy_period (strategy_name, period, period_start),
            INDEX idx_strategy (strategy_name),
            INDEX idx_period (period_start DESC)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='实盘分析表(按日聚合)'
    """)

    # sim_orders 表（模拟交易/预警订单）
    execute("""
        CREATE TABLE IF NOT EXISTS sim_orders (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            symbol          VARCHAR(20) NOT NULL COMMENT '交易对',
            side            VARCHAR(10) NOT NULL COMMENT 'BUY/SELL',
            position_side   VARCHAR(10) DEFAULT '' COMMENT 'LONG/SHORT',
            price           DECIMAL(20, 8) DEFAULT NULL COMMENT '触发价格',
            signal_type     VARCHAR(50) DEFAULT '' COMMENT '信号类型: buy_alert/strategy_signal',
            strategy_name   VARCHAR(50) DEFAULT '' COMMENT '策略名称',
            indicators      TEXT DEFAULT NULL COMMENT '触发时的指标JSON',
            msg             TEXT DEFAULT NULL COMMENT '备注信息',
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_created (created_at),
            INDEX idx_signal_type (signal_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模拟交易记录表'
    """)

    # local_trades 表（本地订单号，开平仓一条记录）
    execute("""
        CREATE TABLE IF NOT EXISTS local_trades (
            id              INT AUTO_INCREMENT PRIMARY KEY COMMENT '本地订单号',
            symbol          VARCHAR(20) NOT NULL COMMENT '交易对',
            direction       VARCHAR(10) NOT NULL COMMENT 'LONG/SHORT',
            open_order_id   BIGINT COMMENT '币安开仓订单号',
            close_order_id  BIGINT COMMENT '币安平仓订单号',
            open_time       DATETIME COMMENT '开仓时间',
            close_time      DATETIME COMMENT '平仓时间',
            open_price      DECIMAL(20, 8) COMMENT '开仓价',
            close_price     DECIMAL(20, 8) COMMENT '平仓价',
            quantity        DECIMAL(20, 8) COMMENT '数量',
            leverage        INT DEFAULT 100 COMMENT '杠杆',
            pnl             DECIMAL(20, 8) COMMENT '盈亏',
            status          VARCHAR(20) DEFAULT '持仓中' COMMENT '持仓中/已平仓/部分平仓',
            strategy_name   VARCHAR(50) DEFAULT '' COMMENT '策略名称',
            paper_trading   TINYINT DEFAULT 0 COMMENT '0=实盘 1=模拟',
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_status (status),
            INDEX idx_direction (direction),
            INDEX idx_created (created_at DESC)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='本地订单表（开平一条记录）'
    """)

    logger.info("所有数据库表已就绪")

    # 回填历史订单
    backfill_local_trades()


def create_local_trade(symbol: str, direction: str, open_order_id: int,
                       open_price: float, quantity: float, leverage: int,
                       strategy_name: str, paper_trading: int = 0) -> Optional[int]:
    """开仓：创建一条本地订单记录，状态=持仓中"""
    cur = execute(
        """INSERT INTO local_trades
           (symbol, direction, open_order_id, open_time, open_price,
            quantity, leverage, strategy_name, paper_trading, status)
           VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, '持仓中')""",
        (symbol, direction, open_order_id, open_price,
         quantity, leverage, strategy_name, paper_trading),
        db=DB_NAME,
    )
    if cur and cur.lastrowid:
        return cur.lastrowid
    return None


def close_local_trade(trade_id: int, close_order_id: int,
                      close_price: float, pnl: float, status: str = '已平仓'):
    """平仓：更新本地订单记录，填入平仓信息"""
    execute(
        """UPDATE local_trades SET
           close_order_id = %s, close_time = NOW(), close_price = %s,
           pnl = %s, status = %s
           WHERE id = %s""",
        (close_order_id, close_price, pnl, status, trade_id),
        db=DB_NAME,
    )


def get_latest_active_trade(direction: str) -> Optional[dict]:
    """查询某个方向最新一笔持仓中的订单"""
    return fetch_one(
        "SELECT * FROM local_trades WHERE direction = %s AND status = '持仓中' ORDER BY id DESC LIMIT 1",
        (direction,), db=DB_NAME,
    )


def get_local_trades(limit: int = 50, offset: int = 0,
                     status: Optional[str] = None,
                     direction: Optional[str] = None) -> list[dict]:
    """查询本地订单列表"""
    conditions = []
    params = []
    if status:
        conditions.append("status = %s")
        params.append(status)
    if direction:
        conditions.append("direction = %s")
        params.append(direction)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT * FROM local_trades {where} ORDER BY id DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    return fetch_all(sql, tuple(params), db=DB_NAME)


def get_local_trade_stats() -> dict:
    """本地订单统计"""
    row = fetch_one("""
        SELECT
            COUNT(*)                                         AS total_trades,
            COUNT(CASE WHEN status = '持仓中' THEN 1 END)    AS open_trades,
            COUNT(CASE WHEN status = '已平仓' THEN 1 END)    AS closed_trades,
            COUNT(CASE WHEN pnl > 0 THEN 1 END)              AS wins,
            COUNT(CASE WHEN pnl < 0 THEN 1 END)              AS losses,
            COALESCE(SUM(pnl), 0)                            AS total_pnl
        FROM local_trades
    """, db=DB_NAME)
    if not row:
        return {"total_trades": 0, "open_trades": 0, "closed_trades": 0}
    total = row["total_trades"] or 0
    wins = row["wins"] or 0
    closed = row["closed_trades"] or 0
    return {
        "total_trades": total,
        "open_trades": row["open_trades"] or 0,
        "closed_trades": closed,
        "wins": wins,
        "losses": row["losses"] or 0,
        "win_rate": round(wins / closed * 100, 1) if closed > 0 else 0,
        "total_pnl": round(float(row["total_pnl"]), 2),
    }


def backfill_local_trades():
    """从 real_orders 回填历史数据到 local_trades（幂等）"""
    existing = fetch_one("SELECT COUNT(*) AS cnt FROM local_trades", db=DB_NAME)
    if existing and existing["cnt"] > 0:
        logger.info("local_trades 已有数据，跳过回填")
        return

    orders = fetch_all(
        "SELECT * FROM real_orders WHERE status = 'FILLED' ORDER BY created_at ASC",
        db=DB_NAME,
    )
    if not orders:
        return

    # 按方向配对开平：开=单，平=按时间先后配对
    # LONG: 开=BUY/LONG, 平=SELL/LONG
    # SHORT: 开=SELL/SHORT, 平=BUY/SHORT
    opens = []
    closes = {"LONG": [], "SHORT": []}
    for o in orders:
        side = o["side"]
        pos_side = o["position_side"]
        if side == "BUY" and pos_side == "LONG":
            opens.append(o)
        elif side == "SELL" and pos_side == "SHORT":
            opens.append(o)
        elif side == "SELL" and pos_side == "LONG":
            closes["LONG"].append(o)
        elif side == "BUY" and pos_side == "SHORT":
            closes["SHORT"].append(o)

    # 为每个开仓单找平仓单（按时间顺序最先出现的同方向平仓单）
    used_closes = {"LONG": set(), "SHORT": set()}
    inserted = 0
    for o in opens:
        direction = o["position_side"]
        close = None
        for c in closes.get(direction, []):
            if c["id"] not in used_closes[direction] and c["created_at"] > o["created_at"]:
                close = c
                used_closes[direction].add(c["id"])
                break

        pnl = float(close["pnl"]) if close and close["pnl"] is not None else None
        status = "已平仓" if close else "持仓中"

        execute(
            """INSERT INTO local_trades
               (symbol, direction, open_order_id, close_order_id,
                open_time, close_time, open_price, close_price,
                quantity, leverage, pnl, status, strategy_name, paper_trading)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                o["symbol"], direction, o["binance_order_id"],
                close["binance_order_id"] if close else None,
                o["created_at"], close["created_at"] if close else None,
                float(o["avg_price"] or o["price"] or 0),
                float(close["avg_price"] or close["price"] or 0) if close else None,
                float(o["executed_qty"] or o["orig_qty"] or 0),
                o["leverage"] or 100, pnl, status,
                o["strategy_name"], o["paper_trading"],
            ), db=DB_NAME,
        )
        inserted += 1

    logger.info(f"回填完成: {inserted} 条本地订单")


def save_sim_order(symbol: str, side: str, position_side: str, price: float,
                   signal_type: str = "strategy_signal", strategy_name: str = "",
                   indicators: dict = None, msg: str = "") -> Optional[int]:
    """将模拟交易/预警记录写入 sim_orders 表"""
    import json
    cur = execute(
        """INSERT INTO sim_orders
           (symbol, side, position_side, price, signal_type, strategy_name, indicators, msg)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (symbol, side, position_side, price, signal_type, strategy_name,
         json.dumps(indicators, ensure_ascii=False) if indicators else None, msg),
    )
    if cur and cur.lastrowid:
        return cur.lastrowid
    return None


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


def save_real_order(order_result: dict, symbol: str, side: str, position_side: str,
                     strategy_name: str, leverage: int, paper_trading: int = 0,
                     pnl: Optional[float] = None) -> Optional[int]:
    """
    将实盘订单写入 real_orders 表，幂等（按 binance_order_id 去重更新）。

    order_result: ccxt exchange.create_market_buy/sell_order() 返回的字典
    """
    info = order_result.get("info", order_result)
    binance_order_id = info.get("orderId")
    if not binance_order_id:
        logger.warning("save_real_order: 缺少 orderId, 跳过入库")
        return None

    client_order_id = info.get("clientOrderId") or order_result.get("id", "")
    raw_status = info.get("status", order_result.get("status", "unknown"))
    # 归一化状态: Binance 原始值 vs ccxt 转译值
    status_map = {"open": "NEW", "closed": "FILLED", "canceled": "CANCELED"}
    status = status_map.get(raw_status, raw_status)

    order_type = (info.get("type") or order_result.get("type", "MARKET")).upper()
    price = info.get("price") or order_result.get("price")
    avg_price = info.get("avgPrice") or info.get("average")
    orig_qty = info.get("origQty") or order_result.get("amount")
    executed_qty = info.get("executedQty") or order_result.get("filled")
    cum_quote = info.get("cumQuote") or order_result.get("cost")
    binance_time = info.get("updateTime") or info.get("transactTime")

    insert_sql = """
        INSERT INTO real_orders
            (binance_order_id, client_order_id, symbol, side, position_side,
             order_type, status, price, avg_price, orig_qty, executed_qty,
             cum_quote, leverage, strategy_name, paper_trading, pnl, binance_time)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            status          = VALUES(status),
            avg_price       = VALUES(avg_price),
            executed_qty    = VALUES(executed_qty),
            cum_quote       = VALUES(cum_quote),
            pnl             = COALESCE(VALUES(pnl), pnl),
            updated_at      = CURRENT_TIMESTAMP
    """

    cur = execute(insert_sql, (
        binance_order_id, client_order_id, symbol, side, position_side,
        order_type, status, price, avg_price, orig_qty, executed_qty,
        cum_quote, leverage, strategy_name, paper_trading, pnl, binance_time,
    ), db=DB_NAME)

    if cur and cur.lastrowid:
        return cur.lastrowid

    # ON DUPLICATE KEY 不返回 lastrowid，按 binance_order_id 反查
    row = fetch_one(
        "SELECT id FROM real_orders WHERE binance_order_id = %s",
        (binance_order_id,), db=DB_NAME,
    )
    return row["id"] if row else None


# ── real_orders 查询 ──────────────────────────────────────────────


def get_real_order(order_id: int) -> Optional[dict]:
    """按 ID 查询单笔实盘订单"""
    return fetch_one("SELECT * FROM real_orders WHERE id = %s", (order_id,), db=DB_NAME)


def get_real_orders(symbol: Optional[str] = None,
                    status: Optional[str] = None,
                    side: Optional[str] = None,
                    paper_trading: Optional[int] = None,
                    start: Optional[str] = None,
                    end: Optional[str] = None,
                    limit: int = 50,
                    offset: int = 0) -> list[dict]:
    """
    查询实盘订单列表，支持多条件筛选。
    默认按创建时间倒序。
    """
    conditions = []
    params = []

    if symbol:
        conditions.append("symbol = %s")
        params.append(symbol)
    if status:
        conditions.append("status = %s")
        params.append(status)
    if side:
        conditions.append("side = %s")
        params.append(side)
    if paper_trading is not None:
        conditions.append("paper_trading = %s")
        params.append(paper_trading)
    if start:
        conditions.append("created_at >= %s")
        params.append(start)
    if end:
        conditions.append("created_at <= %s")
        params.append(end)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT * FROM real_orders {where} ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    return fetch_all(sql, tuple(params), db=DB_NAME)


def get_real_order_stats(symbol: Optional[str] = None,
                         start: Optional[str] = None,
                         end: Optional[str] = None,
                         paper_trading: Optional[int] = 0) -> dict:
    """
    实盘交易统计：总盈亏、胜率、交易次数。

    默认只统计实盘订单 (paper_trading=0)，
    传 paper_trading=None 则合并模拟+实盘。
    """
    conditions = ["pnl IS NOT NULL"]
    params = []
    if symbol:
        conditions.append("symbol = %s")
        params.append(symbol)
    if paper_trading is not None:
        conditions.append("paper_trading = %s")
        params.append(paper_trading)
    if start:
        conditions.append("created_at >= %s")
        params.append(start)
    if end:
        conditions.append("created_at <= %s")
        params.append(end)

    where = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT
            COUNT(*)                                         AS total_trades,
            COUNT(CASE WHEN pnl > 0 THEN 1 END)              AS wins,
            COUNT(CASE WHEN pnl < 0 THEN 1 END)              AS losses,
            COUNT(CASE WHEN pnl = 0 THEN 1 END)              AS breaks_even,
            COALESCE(SUM(pnl), 0)                            AS total_pnl,
            COALESCE(AVG(pnl), 0)                            AS avg_pnl,
            COALESCE(MAX(pnl), 0)                            AS max_win,
            COALESCE(MIN(pnl), 0)                            AS max_loss,
            COALESCE(SUM(cum_quote), 0)                      AS total_volume
        FROM real_orders
        {where}
    """
    row = fetch_one(sql, tuple(params), db=DB_NAME)
    if not row:
        return {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0}

    total = row["total_trades"] or 0
    wins = row["wins"] or 0
    return {
        "total_trades": total,
        "wins": wins,
        "losses": row["losses"] or 0,
        "breaks_even": row["breaks_even"] or 0,
        "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
        "total_pnl": round(float(row["total_pnl"]), 2),
        "avg_pnl": round(float(row["avg_pnl"]), 2),
        "max_win": round(float(row["max_win"]), 2),
        "max_loss": round(float(row["max_loss"]), 2),
        "total_volume": round(float(row["total_volume"]), 2),
    }


# ── 实盘分析 ────────────────────────────────────────────────


def run_analysis(strategy_name: Optional[str] = None, force: bool = False) -> int:
    """
    从 real_orders 汇总数据到 real_order_analysis（按日聚合）。

    只统计已成交 (FILLED) 且有 pnl 的订单。
    返回写入/更新的行数。
    """
    where = "WHERE o.status = 'FILLED' AND o.pnl IS NOT NULL"
    params = []
    if strategy_name:
        where += " AND o.strategy_name = %s"
        params.append(strategy_name)

    rows = fetch_all(
        f"""SELECT o.strategy_name,
                   DATE(o.created_at) AS day,
                   COUNT(*)           AS total_trades,
                   SUM(o.pnl > 0)     AS wins,
                   SUM(o.pnl < 0)     AS losses,
                   ROUND(AVG(o.pnl), 8) AS avg_pnl,
                   ROUND(SUM(o.pnl), 8) AS total_pnl,
                   ROUND(MAX(o.pnl), 8) AS max_win,
                   ROUND(MIN(o.pnl), 8) AS max_loss,
                   ROUND(SUM(o.cum_quote), 8) AS total_volume
            FROM real_orders o
            {where}
            GROUP BY o.strategy_name, DATE(o.created_at)
            ORDER BY o.strategy_name, day""",
        tuple(params), db=DB_NAME,
    )

    if not rows:
        logger.info("分析: 无数据需要汇总")
        return 0

    inserted = 0
    for r in rows:
        day = r["day"]
        if hasattr(day, "isoformat"):
            day_str = day.isoformat()
        else:
            day_str = str(day)

        total = int(r["total_trades"])
        wins = int(r["wins"])
        losses = int(r["losses"])
        win_rate = round(wins / total * 100, 2) if total > 0 else 0

        execute(
            """INSERT INTO real_order_analysis
               (strategy_name, period, period_start, period_end,
                total_trades, wins, losses, win_rate,
                total_pnl, avg_pnl, max_win, max_loss, total_volume)
               VALUES (%s, 'day', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                total_trades = VALUES(total_trades),
                wins         = VALUES(wins),
                losses       = VALUES(losses),
                win_rate     = VALUES(win_rate),
                total_pnl    = VALUES(total_pnl),
                avg_pnl      = VALUES(avg_pnl),
                max_win      = VALUES(max_win),
                max_loss     = VALUES(max_loss),
                total_volume = VALUES(total_volume),
                updated_at   = CURRENT_TIMESTAMP""",
            (
                r["strategy_name"], day_str, day_str,
                total, wins, losses, win_rate,
                r["total_pnl"], r["avg_pnl"], r["max_win"], r["max_loss"], r["total_volume"],
            ), db=DB_NAME,
        )
        inserted += 1

    logger.info(f"分析完成: {inserted} 条记录已写入")
    return inserted


def get_analysis(strategy_name: str, limit: int = 30) -> list[dict]:
    """获取某策略的逐日分析数据，按日期倒序"""
    return fetch_all(
        """SELECT * FROM real_order_analysis
           WHERE strategy_name = %s
           ORDER BY period_start DESC
           LIMIT %s""",
        (strategy_name, limit), db=DB_NAME,
    )


def get_analysis_summary(strategy_name: str) -> dict:
    """获取策略的累计分析摘要"""
    row = fetch_one(
        """SELECT
               COUNT(DISTINCT period_start) AS days_active,
               COALESCE(SUM(total_trades), 0)    AS total_trades,
               COALESCE(SUM(wins), 0)             AS total_wins,
               COALESCE(SUM(losses), 0)           AS total_losses,
               COALESCE(SUM(total_pnl), 0)        AS total_pnl,
               COALESCE(SUM(total_volume), 0)     AS total_volume
           FROM real_order_analysis
           WHERE strategy_name = %s""",
        (strategy_name,), db=DB_NAME,
    )
    if not row:
        return {"days_active": 0, "total_trades": 0, "total_pnl": 0}

    total = int(row["total_trades"])
    wins = int(row["total_wins"])
    return {
        "days_active": int(row["days_active"]),
        "total_trades": total,
        "total_wins": wins,
        "total_losses": int(row["total_losses"]),
        "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
        "total_pnl": round(float(row["total_pnl"]), 2),
        "total_volume": round(float(row["total_volume"]), 2),
    }


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
