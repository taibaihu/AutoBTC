# -*- coding: utf-8 -*-
"""策略配置管理 —— 从 DB 加载/保存策略参数"""
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from db_manager import fetch_one, fetch_all, execute, init_database, insert_strategy_defaults

logger = logging.getLogger(__name__)


@dataclass
class StrategyConfig:
    """策略配置对象，对应 strategies 表 + strategy_risk_params 表"""
    id: int = 0
    name: str = ""
    strategy_type: str = "ma_cross"
    symbol: str = "BTC/USDT"
    timeframe: str = "5m"
    params: dict = field(default_factory=lambda: {"short_window": 7, "long_window": 25})
    rsi_params: dict = field(default_factory=lambda: {
        "timeframes": ["5m", "1h", "2h"],
        "period": 14,
        "overbought": 80,
        "oversold": 20,
        "alert_cooldown": 300,
    })
    # 风控参数（独立表 strategy_risk_params，独立字段）
    max_position_usdt: float = 100.0
    daily_loss_limit: float = 50.0
    max_trades_per_day: int = 20
    min_profit_rate: float = 0.01
    max_loss_rate: float = 0.02
    leverage: int = 100
    user_id: str = "default"
    paper_trading: bool = True
    enabled: bool = True

    @classmethod
    def from_db_row(cls, row: dict) -> "StrategyConfig":
        return cls(
            id=row["id"],
            name=row["name"] or "",
            strategy_type=row["strategy_type"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            params=json.loads(row["params"]) if row.get("params") else {},
            rsi_params=json.loads(row["rsi_params"]) if row.get("rsi_params") else {},
            # 风控参数从 JOIN 结果中取
            max_position_usdt=float(row.get("max_position_usdt") or 100),
            daily_loss_limit=float(row.get("daily_loss_limit") or 50),
            max_trades_per_day=int(row.get("max_trades_per_day") or 20),
            min_profit_rate=float(row.get("min_profit_rate") or 0.01),
            max_loss_rate=float(row.get("max_loss_rate") or 0.02),
            leverage=int(row.get("leverage") or 100),
            user_id=row["user_id"],
            paper_trading=bool(row["paper_trading"]),
            enabled=bool(row["enabled"]),
        )


def load_strategy(user_id: str = "default") -> StrategyConfig:
    """加载用户启用的策略，不存在则创建默认策略"""
    init_database()
    insert_strategy_defaults(user_id)

    row = fetch_one(
        """SELECT s.*, r.max_position_usdt, r.daily_loss_limit, r.max_trades_per_day,
                  r.min_profit_rate, r.max_loss_rate, r.leverage
           FROM strategies s
           LEFT JOIN strategy_risk_params r ON r.strategy_id = s.id
           WHERE s.user_id = %s AND s.enabled = 1
           ORDER BY s.id DESC LIMIT 1""",
        (user_id,),
    )
    if not row:
        logger.warning(f"用户 '{user_id}' 无启用策略，使用硬编码默认值")
        return StrategyConfig(user_id=user_id)

    return StrategyConfig.from_db_row(row)


def save_strategy(cfg: StrategyConfig):
    """保存/更新策略配置（存在则更新，不存在则插入）"""
    if cfg.id:
        # 更新 strategies 表
        execute(
            """UPDATE strategies SET name=%s, strategy_type=%s, symbol=%s, timeframe=%s,
               params=%s, rsi_params=%s, paper_trading=%s, enabled=%s
               WHERE id=%s""",
            (
                cfg.name, cfg.strategy_type, cfg.symbol, cfg.timeframe,
                json.dumps(cfg.params), json.dumps(cfg.rsi_params),
                1 if cfg.paper_trading else 0, 1 if cfg.enabled else 0,
                cfg.id,
            ),
        )
        # 更新 strategy_risk_params（不存在则插入）
        execute(
            """INSERT INTO strategy_risk_params
               (strategy_id, max_position_usdt, daily_loss_limit, max_trades_per_day, min_profit_rate, max_loss_rate, leverage)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
               max_position_usdt=VALUES(max_position_usdt),
               daily_loss_limit=VALUES(daily_loss_limit),
               max_trades_per_day=VALUES(max_trades_per_day),
               min_profit_rate=VALUES(min_profit_rate),
               max_loss_rate=VALUES(max_loss_rate),
               leverage=VALUES(leverage)""",
            (
                cfg.id,
                cfg.max_position_usdt, cfg.daily_loss_limit, cfg.max_trades_per_day,
                cfg.min_profit_rate, cfg.max_loss_rate, cfg.leverage,
            ),
        )
        logger.info(f"策略 '{cfg.name}' (id={cfg.id}) 已更新")
    else:
        execute(
            """INSERT INTO strategies
               (name, strategy_type, symbol, timeframe, params, rsi_params, user_id, paper_trading, enabled)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                cfg.name, cfg.strategy_type, cfg.symbol, cfg.timeframe,
                json.dumps(cfg.params), json.dumps(cfg.rsi_params),
                cfg.user_id, 1 if cfg.paper_trading else 0, 1 if cfg.enabled else 0,
            ),
        )
        # 获取新 ID 后插入风险参数表
        row = fetch_one("SELECT id FROM strategies WHERE user_id=%s ORDER BY id DESC LIMIT 1", (cfg.user_id,))
        if row:
            execute(
                """INSERT INTO strategy_risk_params
                   (strategy_id, max_position_usdt, daily_loss_limit, max_trades_per_day, min_profit_rate, max_loss_rate, leverage)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (row["id"], cfg.max_position_usdt, cfg.daily_loss_limit, cfg.max_trades_per_day,
                 cfg.min_profit_rate, cfg.max_loss_rate, cfg.leverage),
            )
        logger.info(f"策略 '{cfg.name}' 已创建")


def list_strategies(enabled_only: bool = True) -> list[StrategyConfig]:
    """列出所有策略"""
    where = "WHERE s.enabled = 1" if enabled_only else ""
    rows = fetch_all(f"""
        SELECT s.*, r.max_position_usdt, r.daily_loss_limit, r.max_trades_per_day,
               r.min_profit_rate, r.max_loss_rate, r.leverage
        FROM strategies s
        LEFT JOIN strategy_risk_params r ON r.strategy_id = s.id
        {where}
        ORDER BY s.id
    """)
    return [StrategyConfig.from_db_row(r) for r in rows]


def apply_to_config(cfg: StrategyConfig):
    """将策略配置应用到 config 模块变量，使 main.py 直接读取"""
    import config as cmod

    cmod.SYMBOL = cfg.symbol
    cmod.TIMEFRAME = cfg.timeframe
    cmod.STRATEGY_NAME = cfg.strategy_type
    cmod.PAPER_TRADING = cfg.paper_trading

    # 策略参数 → STRATEGY_KWARGS
    strategy_kwargs = {}
    if cfg.strategy_type == "ma_cross":
        strategy_kwargs["short_window"] = cfg.params.get("short_window", 7)
        strategy_kwargs["long_window"] = cfg.params.get("long_window", 25)
        cmod.SHORT_MA = strategy_kwargs["short_window"]
        cmod.LONG_MA = strategy_kwargs["long_window"]
    elif cfg.strategy_type == "rsi_revert":
        strategy_kwargs["period"] = cfg.params.get("period", 14)
        strategy_kwargs["oversold"] = cfg.params.get("oversold", 20)
        strategy_kwargs["overbought"] = cfg.params.get("overbought", 80)
    elif cfg.strategy_type in ("fast_range", "fast_range_short"):
        for key in ("bb_period", "bb_std", "trend_ema_period", "adx_period",
                     "adx_threshold", "max_slope",
                     "buy_zone", "sell_zone", "shadow_body_ratio", "max_body_ratio",
                     "creep_lookback", "creep_threshold",
                     "sell_shadow_ratio", "sell_max_body_ratio"):
            if key in cfg.params:
                strategy_kwargs[key] = cfg.params[key]
    cmod.STRATEGY_KWARGS = strategy_kwargs
    cmod.LIMIT = cfg.params.get("limit", 100)

    # 风控参数（来自独立表字段）
    cmod.MAX_POSITION_USDT = cfg.max_position_usdt
    cmod.DAILY_LOSS_LIMIT = cfg.daily_loss_limit
    cmod.MAX_TRADES_PER_DAY = cfg.max_trades_per_day
    cmod.MIN_PROFIT_RATE = cfg.min_profit_rate
    cmod.MAX_LOSS_RATE = cfg.max_loss_rate
    cmod.LEVERAGE = cfg.leverage

    # RSI 参数
    rsi = cfg.rsi_params
    cmod.RSI_TIMEFRAMES = rsi.get("timeframes", ["5m", "1h", "2h"])
    cmod.RSI_PERIOD = rsi.get("period", 14)
    cmod.RSI_OVERBOUGHT = rsi.get("overbought", 80)
    cmod.RSI_OVERSOLD = rsi.get("oversold", 20)
    cmod.RSI_ALERT_COOLDOWN = rsi.get("alert_cooldown", 300)

    logger.info(f"策略配置已应用: {cfg.strategy_type} @ {cfg.symbol} {cfg.timeframe}")
