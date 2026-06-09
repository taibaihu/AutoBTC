# 项目操作红线（每条都踩过坑）

## 修改代码后重启流程
1. 先杀进程 → 清状态文件（orders/positions）→ 撤交易所旧单 → 再启动
2. 启动后看日志确认挂单成功，没有重复

## 改名/改逻辑时
1. 改的地方全部 `grep` 一遍确认没有遗漏引用
2. 不要让变量名不一致（如 `price_label` vs `label`）

## 入场价规则（改过多次，别再改错）
- 评分 ≥ 80 → 入场低限（低价挂）
- 评分 < 80 → 入场高限（高价挂）

## 每次上线一个机器人
- orders 一定要保持在机器人的上限内
- 状态文件必须干净，否则不挂单
- 撤单要撤两边：普通订单 + 条件单（TP/SL）

## 订单查询工具
- 脚本: `python3 tools/lookup_order.py <order_id_prefix>`
- 功能: 按订单ID前缀搜索本地状态文件（挂单/持仓/已平仓）+ 从交易所查询实时详情
- 同时支持 OKX 和 Binance 两个交易所
- 示例: `python3 tools/lookup_order.py 363513372560` → 查询 OKX WLD 挂单
- 示例: `python3 tools/lookup_order.py 801704125252` → 查询 Binance ZEC 挂单
