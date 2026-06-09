# AutoBTC — 加密货币量化交易策略

基于 KDJ 多空对称 + AI 评分的全自动量化交易系统，运行于 Binance 和 OKX 合约市场。

## 📊 策略一览

| 策略 | 交易所 | 标的 | 方式 | 预期年化 |
|:----|:------|:----|:----|:--------|
| **KDJ 多空对称** | Binance | BTC/USDC:USDC | KDJ 指标反转 | **+23.2%** |
| **Binance AI** | Binance | USDT 合约多币种 | AI 评分 + 趋势 | — |
| **OKX AI** | OKX | USDT 合约多币种 | AI 评分 + 趋势 | — |

---

## ⚙️ KDJ 多空对称策略（核心）

15 分钟 KDJ 均线回归，多空双向对称开仓。使用 EMA50 趋势过滤 + 波动率过滤，在 1 年回测中实现 **+23.2%** 年化收益。

### 入场条件

| 方向 | KDJ 条件 | 趋势过滤 | 波动率 | 挂单 |
|:---:|:---------|:--------|:------|:----:|
| 🟢 **多头** | 金叉 + K < 30 | 价 > EMA50 | 4h振幅 > 0.8% | 市价 **- $50** |
| 🔴 **空头** | 死叉 + K > 70 | 价 < EMA50 | 4h振幅 > 0.8% | 市价 **+ $50** |

### 出场条件

| 方式 | 规则 |
|:----|:------|
| **止盈** | **+1.5%** |
| **止损** | **-1.0%** |
| 盈亏比 | 1.5 : 1（需 40% 胜率即盈利） |
| 超时 | 持仓 **6h** 强制平仓 |
| 挂单超时 | **30min** 未成交自动撤单 |
| 冷却 | **30min** 平仓后冷却 |

### 关键参数

| 参数 | 值 | 说明 |
|:----|:---:|:------|
| k_period / d_period | **14** / 2 | KDJ 计算周期（平滑版） |
| oversold_k | **30** | K<30 超卖金叉开多 |
| overbought_k | **70** | K>70 超买死叉开空 |
| entry_offset | **±$50** | 限价单偏移 |
| **take_profit** | **1.5%** | 更大盈利空间 🚀 |
| **stop_loss** | **1.0%** | 不易被扫损 🚀 |
| **EMA period** | **50** | 趋势过滤（≈12.5h） |
| **vol_filter** | **0.8%** | 4h振幅 < 此值不开仓 |
| max_hold | **6h (24根)** | 超时强平 |
| cooldown | **30min (2根)** | 平仓后冷却 |
| order_timeout | **30min** | 挂单超时撤单 |
| position_size | 0.05 BTC | 每单大小 |
| check_interval | **60s** | 轮询间隔 |

### 回测表现（1年 15m精度）

| 指标 | 值 |
|:----|:----:|
| 总交易 | 184 笔/年 |
| 胜率 | **55.4%** |
| **总盈亏** | **+23.2%** |
| 盈亏比 | 1.5 : 1 |
| 最大回撤 | ~15% |
| 月均PnL | +1.93% |
| 正收益月 | **7/12** |
| 多/空占比 | 均匀分布 |

| 指标 | 值 |
|:----|:----:|
| 总交易 | ~1000 笔/年 |
| 胜率 | ~55% |
| 总盈亏 | **+34.85%** |
| 盈亏比 | 1:1 |
| 最大回撤 | ~12% |

---

## 🤖 Binance AI 策略

基于 Binance 多因子评分的自动开仓系统。

- **评分门槛**: ≥ 70 分
- **入场**: ≥80分低价挂，<80分高价挂
- **每单**: 200 USDT，1x 杠杆
- **最大持仓**: 5 个币种
- **止盈**: 条件单 5% / 持仓>2h盈利≥1%主动止盈
- **止损**: 条件单 3.5%
- **特色**: 孤儿条件单自动清理

---

## 🤖 OKX AI 策略

同 Binance AI，运行于 OKX 合约。

- **杠杆**: 20x 逐仓
- **每单**: 100 USDT
- **特色**: quantity 存币数量（非合约张数），金额显示正确

---

## 🌐 Web 监控面板

访问 `https://hellobtc.duckdns.org`

| 路径 | 功能 |
|:-----|:------|
| `/trend-convergence` | KDJ 多空对称监控 |
| `/binance-ai` | Binance AI 状态 |
| `/okx-ai` | OKX AI 状态 |
| `/okx-danger` | OKX 做多危险指数 |
| `/binance-danger` | Binance 做多危险指数 |

---

## 📁 项目结构

```
├── main_kdj_btcusdc.py       # KDJ 策略主程序
├── main_binance_ai.py        # Binance AI 启动器
├── main_okx_ai.py            # OKX AI 启动器
├── main.py                   # 原主策略入口
├── strategy.py               # 策略基类 / KDJReversalStrategy
├── strategy_binance_ai.py    # Binance AI 逻辑
├── strategy_okx_ai.py        # OKX AI 逻辑
├── config.py                 # 配置（从 .env 读取密钥）
├── engine.py                 # 行情获取与订单执行
├── web/
│   ├── app.py                # Flask 服务
│   └── static/               # 前端资源
├── backtests/
│   ├── backtest_kdj_1y.py    # 1年回测（旧版）
│   └── backtest_kdj_1y_v2.py # 1年回测（1m精度+多空对称）
├── deploy.sh                 # 一键部署
├── CLAUDE.md                 # 操作规范
└── README.md                 # 本文件
```

---

## 🚀 快速启动

```bash
# 配置密钥
cp .env.example .env      # 填入 BINANCE_API_KEY 等

# 启动 KDJ 策略
nohup python3 main_kdj_btcusdc.py > main_kdj_btcusdc.log 2>&1 &

# 启动 AI 策略
nohup python3 main_binance_ai.py > main_binance_ai.log 2>&1 &
nohup python3 main_okx_ai.py > main_okx_ai.log 2>&1 &

# 启动 Web 面板
cd web && gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

---

## ⚠️ 风险提示

加密货币交易存在高风险。回测不代表未来收益。建议先在小额资金验证后再追加投入。

---

*AutoBTC — Automated Bitcoin Trading*
