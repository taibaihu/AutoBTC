# -*- coding: utf-8 -*-
"""配置文件 —— 所有可调参数集中管理"""
import os
from typing import Optional
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

# ===== 币安 API =====
API_KEY = os.getenv("BINANCE_API_KEY", "")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")

# ===== OKX API =====
OKX_API_KEY = os.getenv("OKX_API_KEY", "")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY", "")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE", "")

# ===== 交易对 & 参数 =====
SYMBOL = "BTC/USDT"          # 主交易对（现货）
CONTRACT_SYMBOL = "BTC/USDT:USDT"  # 合约交易对
TIMEFRAME = "15m"             # K线周期: 1m, 5m, 15m, 1h, 4h, 1d
LIMIT = 200                  # 获取K线根数
LEVERAGE = 100               # 合约杠杆倍数

# ===== 策略参数 =====
SHORT_MA = 7                 # 短期均线周期
LONG_MA = 25                 # 长期均线周期

# ===== 模拟交易模式（True=只算不买，False=实盘）=====
PAPER_TRADING = False

# ===== 风控 =====
FIXED_ORDER_QTY = 0.05        # 固定开仓数量 (BTC)
MAX_POSITION_USDT = 100      # 单次最大仓位 (USDT) — 旧参数，改用 FIXED_ORDER_QTY
DAILY_LOSS_LIMIT = 50        # 每日最大亏损 (USDT)
MAX_TRADES_PER_DAY = 20      # 每日最大交易次数
MIN_PROFIT_RATE = 0.015       # 最小止盈比例 (1.5%)
MAX_LOSS_RATE = 0.015         # 最大止损比例 (1.5%)

# ===== 策略选择 =====
STRATEGY_NAME = "fast_range"    # 策略名: ma_cross / rsi_revert / fast_range
STRATEGY_KWARGS = {"buy_zone": 0.20, "cooldown_bars": 2, "adx_threshold": 38, "max_slope": 0.02}

# KDJ 策略参数
KDJ_K_PERIOD = 9
KDJ_D_PERIOD = 3
KDJ_OVERSOLD_K = 30       # K<30 超卖区金叉才开多
KDJ_OVERBOUGHT_J = 100    # J>100 平多
# cooldown_bars: 平仓后等待多少根K线再入场 (15分钟K线, 冷却30分钟=2根)
# 如需自定义: STRATEGY_KWARGS = {"bb_period":20, "bb_std":2, "trend_ema_period":50}

# ===== 震荡模式：是否忽略EMA趋势过滤 =====
# True  = 震荡行情(ADX<threshold)下不看EMA方向，纯布林带高抛低吸
# False = 始终遵守EMA趋势过滤（旧逻辑）
RANGE_IGNORE_TREND_FILTER = True

# ===== 启动冷却（秒）：防止重启后立即开仓 =====
STARTUP_COOLDOWN = 120  # 重启后等待2分钟再交易
# ===== RSI 多周期预警 =====
RSI_TIMEFRAMES = ["15m", "1h", "2h"]   # 监控的时间周期
RSI_PERIOD = 14                       # RSI 计算周期
RSI_OVERBOUGHT = 80                   # 超买阈值
RSI_OVERSOLD = 20                     # 超卖阈值
RSI_ALERT_COOLDOWN = 300              # 重复告警冷却时间 (秒)
POSITION_COOLDOWN_MINUTES = 30        # 平仓后冷却时间（分钟）

# ===== 数据库 (阿里云 MySQL) =====
DB_HOST = os.getenv("DB_HOST", "")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "lianghua")

# ===== Telegram 推送 =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ===== 代理配置 (SOCKS5) =====
PROXY_ENABLED = os.getenv("PROXY_ENABLED", "false").lower() == "true"
PROXY_TYPE = os.getenv("PROXY_TYPE", "socks5h")
PROXY_HOST = os.getenv("PROXY_HOST", "")
PROXY_PORT = int(os.getenv("PROXY_PORT", "0"))
PROXY_USER = os.getenv("PROXY_USER", "")
PROXY_PASS = os.getenv("PROXY_PASS", "")


def get_proxy_config() -> Optional[dict]:
    """返回 ccxt 兼容的代理配置字典，无代理时返回 None"""
    if not PROXY_ENABLED or not PROXY_HOST:
        return None

    if PROXY_USER:
        proxy_url = f"{PROXY_TYPE}://{quote(PROXY_USER)}:{quote(PROXY_PASS)}@{PROXY_HOST}:{PROXY_PORT}"
    else:
        proxy_url = f"{PROXY_TYPE}://{PROXY_HOST}:{PROXY_PORT}"

    return {
        "http": proxy_url,
        "https": proxy_url,
    }
