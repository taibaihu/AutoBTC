# BTC/USDT 量化交易框架

## 概述

基于技术指标的 BTC/USDT 量化交易系统，对接 Binance（主）+ OKX（辅助价格对比）实时行情，支持模拟交易、多周期指标监控、Telegram 推送预警。

## 架构

```
main.py              —— 主循环（5s 轮询）
├── engine.py        —— 行情获取 & 订单执行（BinanceEngine / OKXEngine）
├── strategy.py      —— 策略引擎（信号生成 + 指标计算 + 过滤逻辑）
├── risk_manager.py  —— 风控 & 仓位管理（MySQL 持久化）
├── config.py        —— 集中配置
├── notifier.py      —— Telegram 推送
└── backtest_alerts.py —— 历史扫描（回测信号检测）
```

## 交易策略

### 主策略：双均线交叉（MA Crossover）

当前默认的主信号策略，用于生成开平仓指令。

**参数**

| 参数 | 值 | 说明 |
|------|-----|------|
| SHORT_MA | 7 | 短期均线周期 |
| LONG_MA | 25 | 长期均线周期 |

**规则**

- **金叉**（MA7 上穿 MA25）→ 买入开仓
- **死叉**（MA7 下穿 MA25）→ 卖出平仓
- 其他情况 → 持仓不动（HOLD）

可通过 `config.py` 的 `STRATEGY_NAME` 切换为 RSI 均值回归策略（`rsi_revert`）。

---

### 辅助策略：方案7 五重过滤买入预警

独立于主策略运行，作为实时买入预警系统。每 5s 用 Binance 实时价格更新指标，**不直接下单，仅推送通知**。

> 历史回测（2026-04-30 ~ 2026-05-09）：**胜率 80%**（1%止盈/止损），日均信号 **2~3 次**

#### 基础条件（必须同时满足）

| 条件 | 规则 | 数学表达 |
|------|------|---------|
| **MACD 多头** | MACD 线位于信号线上方 | `macd > signal` |
| **KDJ 金叉** | K 线从下方向上穿越 D 线 | `K_prev ≤ D_prev 且 K_cur > D_cur` |

#### 五重过滤条件

任一过滤条件不满足则拒绝本次信号，并在日志中标注被拒原因。

##### F1：波动率过滤（剔除横盘）

- 计算布林带（20, 2）带宽比：`(上轨 - 下轨) / 中轨`
- 取过去 24 根 K 线的带宽均值
- **拒绝条件**：当前带宽 < 均值 × 0.5
- 目的：剔除波动率极低的横盘期，避免频繁交易磨损

##### F2：大周期趋势过滤

- 计算 EMA120（120 周期指数移动平均）
- **拒绝条件**：当前价格 < EMA120
- 目的：EMA120 下方不买入，避免逆大周期空头趋势

##### F3：超买区金叉过滤

| 指标 | 拒绝阈值 | 说明 |
|------|---------|------|
| K 值 | > 85 | K 值过高表示短期超买 |
| D 值 | > 85 | D 值过高同上 |
| J 值 | > 90 | J 值极端高位不追 |

- 目的：KDJ 高位金叉往往是强弩之末，胜率低

##### F4：成交量确认

- 计算过去 20 根 K 线的成交量均值
- **拒绝条件**：当前成交量 < 均值 × 0.8
- 目的：无量上涨缺乏持续性，需要成交量配合确认

##### F5：MACD 死叉复燃过滤

- 检查当前 K 线之前的 3 根 K 线的 MACD 柱状图（histogram）
- **拒绝条件**：3 根中有任意一根 histogram < 0
- 目的：MACD 刚刚死叉又立即金叉（复燃）是假突破信号，需等待稳定

#### 预警推送格式

```
🟢 买入预警
BTC/USDT @ 80228.04
买入预警: MACD多头+KDJ金叉
MACD:66.0 K:79.0 J:81.9
```

---

## 技术指标算法

所有指标计算与 TradingView / Binance 图表保持一致。

### RSI（相对强弱指标）

| 参数 | 值 |
|------|-----|
| 周期 | 14 |
| 超买阈值 | 80 |
| 超卖阈值 | 20 |
| 平滑方式 | Wilder's RMA（第一周期 SMA，之后 EMA 平滑） |

- 多周期监控：5m / 1h / 2h
- 实时价格注入最后一根 K 线的 close
- 所有周期均超买/超卖时触发 Telegram 告警（冷却 300s）

### MACD（指数平滑异同移动平均线）

| 参数 | 值 |
|------|-----|
| 快线(EMA) | 12 |
| 慢线(EMA) | 26 |
| 信号线 | 9 |

### KDJ（随机指标）

| 参数 | 值 |
|------|-----|
| RSV 周期 | 9 |
| K 平滑 | 3（EMA） |
| D 平滑 | 3（EMA） |

KDJ 的 high/low 使用实时价格更新（当前 K 线 high = max(实 high, 实价)，low = min(实 low, 实价)），确保实时金叉判断准确。

### 布林带（Bollinger Bands）

| 参数 | 值 |
|------|-----|
| 周期 | 20 |
| 标准差倍数 | 2 |

---

## 风控系统（RiskManager）

### 参数

| 参数 | 值 | 说明 |
|------|-----|------|
| MAX_POSITION_USDT | 100 | 单次最大仓位（USDT） |
| DAILY_LOSS_LIMIT | 50 | 每日最大亏损限额 |
| MAX_TRADES_PER_DAY | 20 | 每日最大交易次数 |
| MIN_PROFIT_RATE | 1% | 止盈触发比例 |
| MAX_LOSS_RATE | 2% | 止损触发比例 |

### 止盈/止损逻辑

每 5s 轮询持仓，计算当前价格的涨跌幅：

- **止盈**：涨幅 ≥ +1% → 平仓获利
- **止损**：跌幅 ≤ -2% → 平仓止损
- 平仓后记录交易到 MySQL `trades` 表

### 日重置

每日 0 点自动重置交易次数和累计盈亏。

### 开仓前置检查

| 检查项 | 拒绝条件 |
|--------|---------|
| 每日交易次数 | 已达 `MAX_TRADES_PER_DAY` |
| 每日亏损限额 | 累计亏损 ≤ `-DAILY_LOSS_LIMIT` |

---

## 交易模式

| 模式 | 说明 |
|------|------|
| **模拟交易**（默认） | `PAPER_TRADING = True`，只算盈亏不下单 |
| **实盘交易** | `PAPER_TRADING = False`，执行真实 Binance 市价单 |

---

## 实时价格注入

每 5s 获取两个交易所的实时价格：

1. **Binance**：`get_current_price()` + `fetch_ohlcv()`
2. **OKX**：`get_current_price()`（仅现货价格对比）

实时价格会替换最后一根 K 线的 close/high/low 值，参与 RSI、MACD、KDJ 的实时计算，确保信号反映最新市场状态。

日志格式：`🔥 实时价 B:80379.78  O:80383.40  Δ:-3.62`

---

## 数据存储（MySQL）

### trades 表（交易记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键自增 |
| timestamp | DATETIME | 创建时间 |
| entry_price | DECIMAL(20,8) | 入场价格 |
| exit_price | DECIMAL(20,8) | 出场价格 |
| pnl | DECIMAL(20,8) | 盈亏（USDT） |
| symbol | VARCHAR(20) | 交易对 |

### buy_signals 表（买入预警记录）

用于 backtest_alerts.py 历史扫描，记录每个符合条件的信号点及其全部指标值：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键自增 |
| signal_time | DATETIME | 信号时间（北京时间） |
| price | DECIMAL(20,8) | 信号价格 |
| rsi_5m / rsi_1h / rsi_2h | DECIMAL(10,4) | 多周期 RSI |
| macd / macd_signal / macd_hist | DECIMAL(20,8) | MACD 三值 |
| k_val / d_val / j_val | DECIMAL(10,4) | KDJ 三值 |
| bb_width | DECIMAL(10,6) | 布林带宽 |
| ema120 | DECIMAL(20,8) | EMA120 值 |
| volume / vol_mean_20 | DECIMAL(20,4) | 成交量 |
| filter_detail | VARCHAR(500) | 通过/拒绝详情 |

---

## 回测结果（方案7）

扫描范围：2026-04-30 ~ 2026-05-09，5m K 线，1% 止盈 / 1% 止损

| 指标 | 值 |
|------|-----|
| 扫描天数 | 10 天 |
| 总信号数 | 19 个 |
| 日均信号 | ~2.1 个 |
| 已完结交易 | 15 笔 |
| 止盈 | 12 笔 |
| 止损 | 3 笔 |
| 胜率（已完结） | 80% |
| 平均每笔收益 | +0.6% |
| 未完结（超时） | 4 笔 |

---

## 项目文件说明

| 文件 | 说明 |
|------|------|
| `main.py` | 主入口，5s 循环：行情→主策略→风控→方案7预警 |
| `strategy.py` | 指标计算（RSI/MACD/KDJ/BB）、方案7过滤、策略类 |
| `engine.py` | Binance/OKX 行情获取及订单执行（ccxt） |
| `risk_manager.py` | 仓位管理、止盈止损、交易记录（MySQL） |
| `config.py` | 所有可调参数集中管理 |
| `notifier.py` | Telegram Bot 推送封装 |
| `backtest_alerts.py` | 历史数据扫描 + 信号入库 |

---

## 配置

通过 `.env` 文件加载敏感信息，所有交易参数在 `config.py` 中调整。

```env
BINANCE_API_KEY=xxx
BINANCE_SECRET_KEY=xxx
DB_HOST=rm-xxx.mysql.rds.aliyuncs.com
DB_PORT=3306
DB_USER=xxx
DB_PASSWORD=xxx
DB_NAME=lianghua
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
```

---

## 启动

```bash
# 安装依赖
pip install -r requirements.txt

# 模拟交易模式（默认）
python3 main.py

# 后台运行
nohup python3 main.py > main.log 2>&1 &

# 历史信号回测
python3 backtest_alerts.py
```
