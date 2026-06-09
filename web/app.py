#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 服务 —— 订单/策略/统计查询"""
import json
import os
import sys
import time
from datetime import datetime, date

# 将项目根目录加入 path, 复用 db_manager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory


class BeijingEncoder(json.JSONEncoder):
    """自定义 JSON 编码：datetime 统一输出北京时间 +08:00"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        if isinstance(obj, date):
            return obj.isoformat()
        if hasattr(obj, "__float__"):
            return float(obj)
        if hasattr(obj, "__int__"):
            return int(obj)
        return super().default(obj)


# ── 简单内存缓存（减少币安 API 调用频率） ──
_cache = {}

def cached(ttl: int):
    """缓存装饰器，ttl 秒内直接返回缓存（内存+文件回退，gunicorn多worker共享）"""
    import functools, json, time as _time
    _CACHE_DIR = Path(__file__).parent / "api_cache"
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = func.__name__
            now = _time.time()

            # 内存缓存（flask Response 对象可直接复用）
            if key in _cache and now - _cache[key]["time"] < ttl:
                return _cache[key]["data"]

            # 文件缓存（跨worker共享，存 response.data 反序列化后重建）
            fpath = _CACHE_DIR / f"{key}.json"
            try:
                if fpath.exists():
                    fc = json.loads(fpath.read_text(encoding="utf-8"))
                    if now - fc["time"] < ttl:
                        resp_data = fc["data"]
                        _cache[key] = {"data": json_ok(resp_data), "time": fc["time"]}
                        return _cache[key]["data"]
            except Exception:
                pass

            # 实际调用 → 得到 Flask Response
            result = func(*args, **kwargs)

            # 从 Response 对象中提取 json 数据体
            try:
                body = json.loads(result.data.decode("utf-8"))
                _cache[key] = {"data": result, "time": now}
                # 写入文件缓存（只存 data 部分，不存整个 Response）
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                fpath.write_text(
                    json.dumps({"data": body.get("data"), "time": now}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                _cache[key] = {"data": result, "time": now}

            return result
        return wrapper
    return decorator

from db_manager import (
    init_database,
    get_real_order,
    get_real_orders,
    get_real_order_stats,
    get_local_trades,
    get_local_trade_stats,
    fetch_one,
    fetch_all,
    execute,
    run_analysis,
    get_analysis,
    get_analysis_summary,
    get_polymarket_stats,
    get_polymarket_trades,
    get_trend_history,
    # removed ai_entry
    get_binance_ai_data,
    get_binance_ai_times,
    get_okx_ai_data,
    get_okx_ai_times,
    get_binance_tradfi_data,
    get_binance_tradfi_times,
)
from strategy_manager import list_strategies, load_strategy

import subprocess, re, ccxt
from pathlib import Path

app = Flask(__name__)
app.json_encoder = BeijingEncoder

# 确保数据库和表已创建（gunicorn 模式下不会自动执行 main()）
try:
    init_database()
except Exception as e:
    print(f"[WARN] init_database: {e}")

# Polymarket 本金
POLYMARKET_INITIAL_BALANCE = float(os.getenv("POLYMARKET_INITIAL_BALANCE", "50"))


# ── 工具 ────────────────────────────────────────────────────


def json_ok(data=None, msg="ok"):
    return app.response_class(
        response=json.dumps({"code": 0, "msg": msg, "data": data}, cls=BeijingEncoder, ensure_ascii=False),
        status=200,
        mimetype="application/json",
    )


def json_ok_data(data):
    """同 json_ok，固定 msg=ok"""
    return json_ok(data)


def json_err(msg: str, code: int = 1, http_status: int = 400):
    return jsonify({"code": code, "msg": msg, "data": None}), http_status


# ── 策略说明生成 ─────────────────────────────────────────────


def describe_strategy(row: dict) -> dict:
    """根据策略类型和参数生成结构化说明"""
    stype = row.get("strategy_type", "")
    raw = row.get("params")
    if isinstance(raw, str):
        try:
            params = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            params = {}
    else:
        params = raw or {}

    if stype == "fast_range":
        buy_zone = params.get("buy_zone", 0.10)
        sell_zone = params.get("sell_zone", 0.95)
        bb_period = params.get("bb_period", 20)
        bb_std = params.get("bb_std", 2.0)
        adx_threshold = params.get("adx_threshold", 30)
        trend_ema = params.get("trend_ema_period", 50)
        shadow_ratio = params.get("shadow_body_ratio", 1.2)
        max_body = params.get("max_body_ratio", 0.6)
        creep = params.get("creep_lookback", 3)
        return {
            "title": "FastRange 震荡快速买卖策略",
            "summary": "专用于震荡行情的低买高卖策略。在 ADX < 30 的震荡市中，价格触及布林下轨时买入，触及上轨时卖出。",
            "conditions": [
                {
                    "group": "震荡判定（同时满足才交易）",
                    "items": [
                        f"ADX < {adx_threshold} — 无强趋势",
                        f"布林带宽在历史均值 0.3~2.0 倍内 — 不过分剧烈",
                        "7周期均线斜率 < 0.5% — 方向不明",
                    ],
                },
                {
                    "group": "买入条件（价格触及下轨 + K线确认）",
                    "items": [
                        f"布林位置 ≤ {buy_zone*100:.0f}%（触及下轨）",
                        f"前一根K线长下影线（下影线 > 实体×{shadow_ratio}）或小阳线（实体占比 < {max_body*100:.0f}%）",
                        f"拒绝条件：连续 {creep} 根K线收盘低于下轨（贴轨阴跌不抄底）",
                    ],
                },
                {
                    "group": "卖出条件",
                    "items": [
                        f"布林位置 ≥ {sell_zone*100:.0f}%（触及上轨）即平多",
                    ],
                },
                {
                    "group": "大方向过滤",
                    "items": [
                        f"{trend_ema}周期EMA下方不买入（不逆大趋势抄底）",
                    ],
                },
            ],
            "params_desc": {
                f"布林带周期/标准差": f"{bb_period}/{bb_std}",
                "ADX阈值": f"{adx_threshold}",
                "趋势EMA": f"{trend_ema}",
                "买入区": f"≤{buy_zone*100:.0f}%",
                "卖出区": f"≥{sell_zone*100:.0f}%",
                "K线确认": f"下影线>{shadow_ratio}倍实体 或 小阳线<{max_body*100:.0f}%",
            },
        }

    elif stype == "ma_cross":
        short = params.get("short_window", 7)
        long = params.get("long_window", 25)
        return {
            "title": "MA Crossover 双均线交叉策略",
            "summary": f"经典趋势跟踪策略。短期均线({short}期)上穿长期均线({long}期)时买入，下穿时卖出。",
            "conditions": [
                {
                    "group": "买入条件",
                    "items": [f"{short}期MA上穿{long}期MA（金叉）"],
                },
                {
                    "group": "卖出条件",
                    "items": [f"{short}期MA下穿{long}期MA（死叉）"],
                },
            ],
            "params_desc": {f"短期均线": f"{short}", f"长期均线": f"{long}"},
        }

    elif stype == "rsi_revert":
        period = params.get("period", 14)
        oversold = params.get("oversold", 20)
        overbought = params.get("overbought", 80)
        return {
            "title": "RSI 均值回归策略",
            "summary": f"RSI({period})进入超卖区时买入，进入超买区时卖出，押注价格回归均值。",
            "conditions": [
                {"group": "买入条件", "items": [f"RSI < {oversold}（超卖）"]},
                {"group": "卖出条件", "items": [f"RSI > {overbought}（超买）"]},
            ],
            "params_desc": {f"RSI周期": f"{period}", f"超卖": f"{oversold}", f"超买": f"{overbought}"},
        }

    elif stype == "fast_range_short":
        return {
            "title": "FastRange Short 震荡做空策略",
            "summary": "FastRange的做空版本。震荡市中触及上轨开空，下轨平空。",
            "conditions": [
                {"group": "开空条件", "items": ["前一根高点触及布林上轨 + 长上影线或小阴线确认"]},
                {"group": "平空条件", "items": ["价格触及布林下轨"]},
            ],
            "params_desc": {},
        }

    return {"title": stype, "summary": "", "conditions": [], "params_desc": {}}


# ── 健康检查 ────────────────────────────────────────────────


@app.route("/health")
def health():
    return json_ok({"status": "running", "time": datetime.now().isoformat()})


# ── 订单查询 ────────────────────────────────────────────────


@app.route("/api/orders")
def api_orders():
    try:
        orders = get_real_orders(
            symbol=request.args.get("symbol"),
            status=request.args.get("status"),
            side=request.args.get("side"),
            paper_trading=int(request.args["paper_trading"]) if "paper_trading" in request.args else None,
            start=request.args.get("start"),
            end=request.args.get("end"),
            limit=int(request.args.get("limit", 50)),
            offset=int(request.args.get("offset", 0)),
        )
        return json_ok(orders)
    except Exception as e:
        return json_err(str(e))


@app.route("/api/orders/stats")
def api_orders_stats():
    try:
        stats = get_real_order_stats(
            symbol=request.args.get("symbol"),
            start=request.args.get("start"),
            end=request.args.get("end"),
            paper_trading=int(request.args["paper_trading"]) if "paper_trading" in request.args else None,
        )
        return json_ok(stats)
    except Exception as e:
        return json_err(str(e))


@app.route("/api/orders/<int:order_id>")
def api_order_detail(order_id):
    o = get_real_order(order_id)
    if not o:
        return json_err("订单不存在", http_status=404)
    return json_ok(o)


@app.route("/api/local-trades")
@cached(5)
def api_local_trades():
    """本地订单列表（开平一条记录），持仓中自动计算未实现盈亏"""
    try:
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        status = request.args.get("status") or None
        direction = request.args.get("direction") or None
        trades = get_local_trades(limit=limit, offset=offset, status=status, direction=direction)
        stats = get_local_trade_stats()

        # 获取当前合约价格（从 cache 读取，不再调币安 API）
        current_price = None
        try:
            cache_path = Path(__file__).parent.parent / "cache" / "market.json"
            if cache_path.exists():
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if "error" not in cached and cached.get("contract_price"):
                    current_price = float(cached["contract_price"])
        except:
            pass

        if current_price:
            for t in trades:
                if t["status"] == "持仓中" and t["open_price"] and float(t["open_price"]) > 0:
                    entry = float(t["open_price"])
                    qty = float(t["quantity"] or 0)
                    if t["direction"] == "LONG":
                        upnl = round((current_price - entry) * qty, 2)
                    else:
                        upnl = round((entry - current_price) * qty, 2)
                    t["current_price"] = current_price
                    t["unrealized_pnl"] = upnl

        return json_ok({"trades": trades, "stats": stats, "current_price": current_price})
    except Exception as e:
        return json_err(str(e))


# ── 策略查询 ────────────────────────────────────────────────


@app.route("/api/strategies")
def api_strategies():
    try:
        enabled_only = request.args.get("enabled", "true").lower() == "true"
        strategies = list_strategies(enabled_only=enabled_only)
        data = [
            {
                "id": s.id,
                "name": s.name,
                "user_id": s.user_id,
                "strategy_type": s.strategy_type,
                "symbol": s.symbol,
                "timeframe": s.timeframe,
                "paper_trading": s.paper_trading,
                "enabled": s.enabled,
                "params": s.params,
                "leverage": s.leverage,
                "max_position_usdt": s.max_position_usdt,
                "daily_loss_limit": s.daily_loss_limit,
                "max_trades_per_day": s.max_trades_per_day,
                "min_profit_rate": s.min_profit_rate,
                "max_loss_rate": s.max_loss_rate,
            }
            for s in strategies
        ]
        return json_ok(data)
    except Exception as e:
        return json_err(str(e))


@app.route("/api/strategies/<int:strategy_id>")
def api_strategy_detail(strategy_id):
    row = fetch_one(
        """SELECT s.*, r.max_position_usdt, r.daily_loss_limit, r.max_trades_per_day,
                  r.min_profit_rate, r.max_loss_rate, r.leverage
           FROM strategies s
           LEFT JOIN strategy_risk_params r ON r.strategy_id = s.id
           WHERE s.id = %s""",
        (strategy_id,),
    )
    if not row:
        return json_err("策略不存在", http_status=404)
    row["description"] = describe_strategy(row)
    return json_ok_data(row)


@app.route("/api/strategies/<int:strategy_id>/orders")
def api_strategy_orders(strategy_id):
    """查询某策略产生的所有订单"""
    row = fetch_one("SELECT id, strategy_type, name FROM strategies WHERE id = %s", (strategy_id,))
    if not row:
        return json_err("策略不存在", http_status=404)

    try:
        orders = fetch_all(
            """SELECT * FROM real_orders
               WHERE strategy_name = (SELECT strategy_type FROM strategies WHERE id = %s)
               ORDER BY created_at DESC
               LIMIT 200""",
            (strategy_id,),
        )
        return json_ok_data({
            "strategy": row,
            "orders": orders,
            "total": len(orders),
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/api/strategy-status")
def api_strategy_status():
    """所有策略运行状态：注册表 + 进程 + 日志"""
    try:
        # 1. 所有已注册策略
        from strategy import STRATEGIES as REGISTERED
        all_strategies = list(REGISTERED.keys())

        # 2. DB 配置
        db_strats = {}
        for s in list_strategies(enabled_only=False):
            db_strats[s.strategy_type] = {
                "id": s.id, "name": s.name, "strategy_type": s.strategy_type,
                "symbol": s.symbol, "timeframe": s.timeframe, "user_id": s.user_id,
                "enabled": s.enabled, "paper_trading": s.paper_trading,
                "leverage": s.leverage, "max_position_usdt": s.max_position_usdt,
                "daily_loss_limit": s.daily_loss_limit,
                "max_trades_per_day": s.max_trades_per_day,
                "min_profit_rate": s.min_profit_rate,
                "max_loss_rate": s.max_loss_rate,
            }

        # 3. 运行进程
        import os as _os
        proc_info = {}
        try:
            out = _os.popen("ps aux | grep 'python.*main' | grep -v grep | grep -v 'web/app.py' | grep -v 'market_watcher'").read()
            for line in out.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 11:
                    continue
                pid = parts[1]
                start_col = parts[8] if len(parts) > 8 else ""
                cmd = " ".join(parts[10:])
                # 提取 --user 参数
                user_id = "default"
                for i, p in enumerate(parts):
                    if p == "--user" and i + 1 < len(parts):
                        user_id = parts[i + 1]
                    elif p == "--mode" and i + 1 < len(parts):
                        user_id = "tc_" + parts[i + 1]
                if "main_ai_entry" in cmd:
                    user_id = "ai_entry"
                if "main_binance_ai" in cmd:
                    user_id = "binance_ai"
                if "main_okx_ai" in cmd:
                    user_id = "okx_ai"
                proc_info[user_id] = {"pid": pid, "start": start_col, "cmd": cmd[:120]}
        except Exception:
            pass

        # 4. 日志文件信息
        from pathlib import Path as _Path
        log_dir = _Path(__file__).parent.parent
        log_info = {}
        log_patterns = {
            "fast_range": "main.default.log*",
            "fast_range_short": "main.short.log*",
            "tc_long": "trend_convergence_long.log*",
            "tc_short": "trend_convergence_short.log*",
            "ai_entry": "main_ai_entry.log*",
            "binance_ai": "main_binance_ai.log*",
            "okx_ai": "main_okx_ai.log*",
        }
        for key, pat in log_patterns.items():
            files = sorted(log_dir.glob(pat), key=lambda f: _os.path.getmtime(f), reverse=True)
            if files:
                latest = files[0]
                mtime = _os.path.getmtime(latest)
                # 读最后一行日志
                last_line = ""
                try:
                    with open(latest, "r") as f:
                        lines = f.readlines()
                        for l in reversed(lines):
                            l = l.strip()
                            if l and ("[" in l or "信号" in l or "持仓" in l):
                                last_line = l[:200]
                                break
                        if not last_line and lines:
                            last_line = lines[-1].strip()[:200]
                except Exception:
                    pass
                log_info[key] = {
                    "file": latest.name,
                    "size": latest.stat().st_size,
                    "mtime": mtime,
                    "last_line": last_line,
                }

        # 5. 组装结果
        result = []
        for st in all_strategies:
            db = db_strats.get(st, {})
            # 映射 user_id
            uid = {"fast_range": "default", "fast_range_short": "short"}.get(st, st)
            running = uid in proc_info
            log_key = uid if uid in log_info else st if st in log_info else None

            result.append({
                "key": st,
                "name": db.get("name", ""),
                "description": getattr(REGISTERED[st], "__doc__", "").strip().split("\n")[0] if REGISTERED[st].__doc__ else "",
                "enabled": bool(db.get("enabled", False)),
                "paper_trading": bool(db.get("paper_trading", True)),
                "symbol": db.get("symbol", "BTC/USDT"),
                "timeframe": db.get("timeframe", ""),
                "leverage": db.get("leverage", 0),
                "running": running,
                "pid": proc_info[uid]["pid"] if running else None,
                "start_time": proc_info[uid]["start"] if running else None,
                "log": log_info.get(log_key) if log_key else None,
            })

        # 也包含 tc_long / tc_short
        for tc_mode in ["tc_long", "tc_short"]:
            running = tc_mode in proc_info
            label = "趋势收敛 做多" if tc_mode == "tc_long" else "趋势收敛 做空"
            log_key = tc_mode if tc_mode in log_info else None
            result.append({
                "key": tc_mode,
                "name": label,
                "description": "5m/15m/1h趋势打分穿越",
                "enabled": True,
                "paper_trading": False,
                "symbol": "BTC/USDC:USDC",
                "timeframe": "多周期",
                "leverage": 1,
                "running": running,
                "pid": proc_info[tc_mode]["pid"] if running else None,
                "start_time": proc_info[tc_mode]["start"] if running else None,
                "log": log_info.get(log_key) if log_key else None,
            })

        # AI 入场策略
        ai_running = "ai_entry" in proc_info or "tc_ai_entry" in proc_info
        result.append({
            "key": "ai_entry",
            "name": "AI入场策略",
            "description": "基于评分数据多币种合约挂单",
            "enabled": True,
            "paper_trading": False,
            "symbol": "多币种",
            "timeframe": "60s轮询",
            "leverage": 1,
            "running": ai_running,
            "pid": proc_info.get("ai_entry", {}).get("pid") or proc_info.get("tc_ai_entry", {}).get("pid"),
            "start_time": proc_info.get("ai_entry", {}).get("start") or proc_info.get("tc_ai_entry", {}).get("start"),
            "log": log_info.get("ai_entry"),
        })

        # OKX AI 策略
        okx_running = "okx_ai" in proc_info
        result.append({
            "key": "okx_ai",
            "name": "OKX AI策略",
            "description": "基于okx_top_value OKX USDT合约挂单 20x杠杆",
            "enabled": True,
            "paper_trading": False,
            "symbol": "多币种USDT",
            "timeframe": "60s轮询",
            "leverage": 20,
            "running": okx_running,
            "pid": proc_info.get("okx_ai", {}).get("pid"),
            "start_time": proc_info.get("okx_ai", {}).get("start"),
            "log": log_info.get("okx_ai"),
        })

        # Binance AI 策略
        ba_running = "binance_ai" in proc_info
        result.append({
            "key": "binance_ai",
            "name": "Binance AI策略",
            "description": "基于Binance_top_value 币安USDT合约挂单",
            "enabled": True,
            "paper_trading": False,
            "symbol": "多币种USDT",
            "timeframe": "60s轮询",
            "leverage": 1,
            "running": ba_running,
            "pid": proc_info.get("binance_ai", {}).get("pid"),
            "start_time": proc_info.get("binance_ai", {}).get("start"),
            "log": log_info.get("binance_ai"),
        })

        return json_ok_data(result)
    except Exception as e:
        import traceback
        return json_err(str(e) + "\n" + traceback.format_exc())


# ── 实盘分析 ────────────────────────────────────────────────


@app.route("/api/analysis/<strategy_name>")
def api_analysis(strategy_name):
    """查询+自动汇总某策略的实盘分析"""
    try:
        run_analysis(strategy_name=strategy_name)
        daily = get_analysis(strategy_name)
        summary = get_analysis_summary(strategy_name)
        return json_ok_data({"summary": summary, "daily": daily})
    except Exception as e:
        return json_err(str(e))


# ── 交易记录 (trades 表，RiskManager 写入的历史盈亏) ──────────


@app.route("/api/trades")
def api_trades():
    try:
        limit = int(request.args.get("limit", 100))
        rows = fetch_all(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT %s", (limit,)
        )
        return json_ok_data(rows)
    except Exception as e:
        return json_err(str(e))


# ── 买入信号 (backtest_alerts 写入) ──────────────────────────


@app.route("/api/buy-signals")
def api_buy_signals():
    try:
        limit = int(request.args.get("limit", 50))
        rows = fetch_all(
            "SELECT * FROM buy_signals ORDER BY signal_time DESC LIMIT %s", (limit,)
        )
        return json_ok_data(rows)
    except Exception as e:
        return json_err(str(e))


# ── 模拟交易记录 ────────────────────────────────────────────


@app.route("/api/sim-orders")
def api_sim_orders():
    try:
        limit = int(request.args.get("limit", 50))
        signal_type = request.args.get("signal_type")
        if signal_type:
            rows = fetch_all(
                "SELECT * FROM sim_orders WHERE signal_type = %s ORDER BY created_at DESC LIMIT %s",
                (signal_type, limit),
            )
        else:
            rows = fetch_all(
                "SELECT * FROM sim_orders ORDER BY created_at DESC LIMIT %s", (limit,)
            )
        return json_ok_data(rows)
    except Exception as e:
        return json_err(str(e))


# ── Polymarket 预测交易 ─────────────────────────────────────


@app.route("/api/polymarket/stats")
def api_polymarket_stats():
    """Polymarket 交易统计 + 最近记录 + 当前余额"""
    try:
        stats = get_polymarket_stats()
        trades = get_polymarket_trades(limit=50)

        # Read current balance from bot log
        balance = None
        try:
            log_path = "/root/polymarket-trading-bot/bot.log"
            if os.path.exists(log_path):
                result = subprocess.run(
                    ["tail", "-200", log_path],
                    capture_output=True, text=True, timeout=5,
                )
                for line in reversed(result.stdout.splitlines()):
                    m = re.search(r'USD:\s*\$?([\d.]+)', line)
                    if m:
                        balance = float(m.group(1))
                        break
        except Exception:
            pass

        profit = round(balance - POLYMARKET_INITIAL_BALANCE, 2) if balance is not None else None
        return json_ok_data({
            "stats": stats,
            "trades": trades,
            "balance": balance,
            "initial_balance": POLYMARKET_INITIAL_BALANCE,
            "profit": profit,
        })
    except Exception as e:
        return json_err(str(e))


# ── USDC 策略数据 ────────────────────────────────────────────


@app.route("/api/usdc")
def api_usdc():
    """USDC永续合约策略状态 + 交易记录（从JSON文件读取）"""
    try:
        json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "usdc_data.json")
        if not os.path.exists(json_path):
            return json_ok({"state": {"trend": "NONE", "position": "NONE"}, "trades": [], "last_update": None})
        with open(json_path) as f:
            data = json.load(f)
        return json_ok(data)
    except Exception as e:
        return json_err(str(e))


@app.route("/api/sd-only")
def api_sd_only():
    """SDOnlyStrategy 策略状态 + 交易记录"""
    try:
        json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sd_only_data.json")
        if not os.path.exists(json_path):
            return json_ok({"state": {"position": "NONE"}, "trades": [], "last_update": None})
        with open(json_path) as f:
            data = json.load(f)
        return json_ok(data)
    except Exception as e:
        return json_err(str(e))


@app.route("/api/trend-score")
def api_trend_score():
    """多周期趋势打分 0-100 — 从 market_watcher 缓存读取"""
    try:
        cache_path = Path(__file__).parent.parent / "cache" / "trend_score.json"
        if cache_path.exists():
            return json_ok(json.loads(cache_path.read_text(encoding="utf-8")))
        return json_ok({"time": None, "timeframes": {}})
    except Exception as e:
        return json_err(str(e))


@app.route("/api/trend-history")
def api_trend_history():
    """趋势打分历史记录（近12小时，每分钟一个点）"""
    try:
        data = get_trend_history(720)
        return json_ok(data)
    except Exception as e:
        return json_err(str(e))


# ── AI 入场数据 ────────────────────────────────────────────────


@app.route("/api/binance-ai")
@cached(300)
def api_binance_ai():
    """Binance AI 评分数据（Binance_top_value），按分钟聚合"""
    try:
        limit = int(request.args.get("limit", 50))
        analysis_time = request.args.get("analysis_time") or None
        data = get_binance_ai_data(limit, analysis_time)
        # 最新分钟
        latest = fetch_one(
            """SELECT DATE_FORMAT(analysis_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time
               FROM Binance_top_value
               WHERE analysis_time >= NOW() - INTERVAL 48 HOUR
               GROUP BY minute_time
               HAVING COUNT(*) >= 5
               ORDER BY minute_time DESC
               LIMIT 1""",
            db="ll_test",
        )
        if not latest:
            latest = fetch_one(
                "SELECT DATE_FORMAT(analysis_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time FROM Binance_top_value WHERE analysis_time >= NOW() - INTERVAL 48 HOUR ORDER BY analysis_time DESC LIMIT 1",
                db="ll_test",
            )
        now_time = latest["minute_time"] if latest else None
        return json_ok({
            "records": data,
            "total": len(data),
            "analysis_time": now_time,
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/api/binance-ai/times")
@cached(120)
def api_binance_ai_times():
    """Binance AI 可选时间点（分钟级）"""
    try:
        times = get_binance_ai_times()
        return json_ok({
            "times": [{"time": t["minute_time"], "cnt": t["cnt"]} for t in times],
            "total": len(times),
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/okx-ai")
def okx_ai_page():
    return send_from_directory("static", "index.html")


@app.route("/api/okx-ai")
@cached(300)
def api_okx_ai():
    """OKX AI 评分数据（okx_top_value）"""
    try:
        limit = int(request.args.get("limit", 50))
        analysis_time = request.args.get("analysis_time") or None
        data = get_okx_ai_data(limit, analysis_time)
        latest = fetch_one(
            """SELECT DATE_FORMAT(analysis_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time
               FROM okx_top_value
               WHERE analysis_time >= NOW() - INTERVAL 48 HOUR
               GROUP BY minute_time
               HAVING COUNT(*) >= 5
               ORDER BY minute_time DESC
               LIMIT 1""",
            db="ll_test",
        )
        if not latest:
            latest = fetch_one(
                "SELECT DATE_FORMAT(analysis_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time FROM okx_top_value WHERE analysis_time >= NOW() - INTERVAL 48 HOUR ORDER BY analysis_time DESC LIMIT 1",
                db="ll_test",
            )
        now_time = latest["minute_time"] if latest else None
        return json_ok({
            "records": data,
            "total": len(data),
            "analysis_time": now_time,
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/api/okx-ai/times")
@cached(120)
def api_okx_ai_times():
    """OKX AI 可选时间点"""
    try:
        times = get_okx_ai_times()
        return json_ok({
            "times": [{"time": t["minute_time"], "cnt": t["cnt"]} for t in times],
            "total": len(times),
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/api/okx-ai/orders")
def api_okx_ai_orders():
    """OKX AI策略的订单&amp;持仓状态"""
    try:
        state_path = Path(__file__).parent.parent / "okx_ai_state.json"
        if not state_path.exists():
            return json_ok({"orders": {}, "positions": {}, "filled_today": {}})
        state = json.loads(state_path.read_text(encoding="utf-8"))
        now = time.time()
        for coin, o in state.get("orders", {}).items():
            o["age_hours"] = round((now - o["placed_at"]) / 3600, 1)
            o["placed_at_str"] = datetime.fromtimestamp(o["placed_at"]).strftime("%m-%d %H:%M")
        for coin, p in state.get("positions", {}).items():
            p["filled_at_str"] = datetime.fromtimestamp(p["filled_at"]).strftime("%m-%d %H:%M") if p.get("filled_at") else "-"
        return json_ok(state)
    except Exception as e:
        return json_err(str(e))


@app.route("/binance-ai")
def binance_ai_page():
    return send_from_directory("static", "index.html")


@app.route("/api/binance-ai/orders")
def api_binance_ai_orders():
    """Binance AI策略的订单&amp;持仓状态"""
    try:
        state_path = Path(__file__).parent.parent / "binance_ai_state.json"
        if not state_path.exists():
            return json_ok({"orders": {}, "positions": {}, "filled_today": {}})
        state = json.loads(state_path.read_text(encoding="utf-8"))
        now = time.time()
        for coin, o in state.get("orders", {}).items():
            o["age_hours"] = round((now - o["placed_at"]) / 3600, 1)
            o["placed_at_str"] = datetime.fromtimestamp(o["placed_at"]).strftime("%m-%d %H:%M")
        for coin, p in state.get("positions", {}).items():
            p["filled_at_str"] = datetime.fromtimestamp(p["filled_at"]).strftime("%m-%d %H:%M") if p.get("filled_at") else "-"
        return json_ok(state)
    except Exception as e:
        return json_err(str(e))


# ── TradFi 分析页面 ──────────────────────────────────────────────


@app.route("/tradfi-ai")
def tradfi_ai_page():
    return send_from_directory("static", "index.html")


@app.route("/api/tradfi-ai")
@cached(30)
def api_tradfi_ai():
    """TradFi 评分数据（Binance_tradfi_top_value）"""
    try:
        limit = int(request.args.get("limit", 50))
        analysis_time = request.args.get("analysis_time") or None
        data = get_binance_tradfi_data(limit, analysis_time)
        latest = fetch_one(
            """SELECT DATE_FORMAT(analysis_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time
               FROM Binance_tradfi_top_value
               GROUP BY minute_time
               HAVING COUNT(*) >= 5
               ORDER BY minute_time DESC
               LIMIT 1""",
            db="ll_test",
        )
        if not latest:
            latest = fetch_one(
                "SELECT DATE_FORMAT(analysis_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time FROM Binance_tradfi_top_value ORDER BY analysis_time DESC LIMIT 1",
                db="ll_test",
            )
        now_time = latest["minute_time"] if latest else None
        return json_ok({
            "records": data,
            "total": len(data),
            "analysis_time": now_time,
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/api/tradfi-ai/times")
def api_tradfi_ai_times():
    """TradFi 可选时间点（分钟级）"""
    try:
        times = get_binance_tradfi_times()
        return json_ok({
            "times": [{"time": t["minute_time"], "cnt": t["cnt"]} for t in times],
            "total": len(times),
        })
    except Exception as e:
        return json_err(str(e))


# ── OKX 做多危险指数 ────────────────────────────────────────


@app.route("/okx-danger")
def okx_danger_page():
    return send_from_directory("static", "index.html")


@app.route("/api/okx-danger")
def api_okx_danger():
    """OKX 做多危险指数评分（long_danger_rank_30）"""
    try:
        from db_manager import fetch_one
        limit = int(request.args.get("limit", 30))
        analysis_time = request.args.get("analysis_time") or None

        if not analysis_time:
            latest = fetch_one(
                """SELECT DATE_FORMAT(record_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time
                   FROM long_danger_rank_30
                   GROUP BY minute_time
                   HAVING COUNT(*) >= 5
                   ORDER BY minute_time DESC
                   LIMIT 1""",
                db="ll_test",
            )
            if not latest:
                latest = fetch_one(
                    "SELECT DATE_FORMAT(record_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time FROM long_danger_rank_30 ORDER BY record_time DESC LIMIT 1",
                    db="ll_test",
                )
            if latest:
                analysis_time = latest["minute_time"]

        if analysis_time and len(analysis_time) == 16:
            start_time = analysis_time + ":00"
            from datetime import datetime, timedelta
            dt = datetime.strptime(analysis_time, "%Y-%m-%d %H:%M")
            end_dt = dt + timedelta(minutes=1)
            end_time = end_dt.strftime("%Y-%m-%d %H:%M:%S")
            records = fetch_all(
                """SELECT t1.* FROM long_danger_rank_30 t1
                   INNER JOIN (
                       SELECT coin_name, MAX(record_time) AS max_time
                       FROM long_danger_rank_30
                       WHERE record_time >= %s AND record_time < %s
                       GROUP BY coin_name
                   ) t2 ON t1.coin_name = t2.coin_name AND t1.record_time = t2.max_time
                   ORDER BY t1.total_score DESC
                   LIMIT %s""",
                (start_time, end_time, limit),
                db="ll_test",
            )
        else:
            records = fetch_all(
                """SELECT * FROM long_danger_rank_30
                   WHERE record_time = %s
                   ORDER BY total_score DESC
                   LIMIT %s""",
                (analysis_time, limit),
                db="ll_test",
            )

        # 获取时间点列表
        times = fetch_all(
            """SELECT DATE_FORMAT(record_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time,
                      COUNT(*) AS cnt
               FROM long_danger_rank_30
               GROUP BY minute_time
               ORDER BY minute_time DESC
               LIMIT 100""",
            db="ll_test",
        )

        # 布林带数据由后台定时任务计算并写入DB，此处不再实时计算

        return json_ok({
            "records": records,
            "total": len(records),
            "analysis_time": analysis_time,
            "times": [{"time": t["minute_time"], "cnt": t["cnt"]} for t in times],
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/api/okx-danger/analysis")
def api_okx_danger_analysis():
    """OKX 做多危险指数 AI 分析（重点关注最高/最低分币种）"""
    try:
        from db_manager import fetch_all
        latest = fetch_one(
            """SELECT DATE_FORMAT(record_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time
               FROM long_danger_rank_30
               GROUP BY minute_time
               HAVING COUNT(*) >= 5
               ORDER BY minute_time DESC LIMIT 1""",
            db="ll_test",
        )
        if not latest:
            return json_ok({"analysis": "暂无数据"})
        at = latest["minute_time"]
        start_t = at + ":00"
        from datetime import datetime, timedelta
        dt = datetime.strptime(at, "%Y-%m-%d %H:%M")
        end_t = (dt + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")

        rows = fetch_all(
            """SELECT t1.* FROM long_danger_rank_30 t1
               INNER JOIN (
                   SELECT coin_name, MAX(record_time) AS max_time
                   FROM long_danger_rank_30
                   WHERE record_time >= %s AND record_time < %s
                   GROUP BY coin_name
               ) t2 ON t1.coin_name = t2.coin_name AND t1.record_time = t2.max_time
               ORDER BY t1.total_score DESC
               LIMIT 30""",
            (start_t, end_t),
            db="ll_test",
        )
        if not rows:
            return json_ok({"analysis": "暂无数据"})

        def okx_link(coin):
            name = coin.lower().replace(" ", "").replace("/", "")
            return f'<a href="https://www.okx.com/zh-hans/trade-swap/{name}-usdt-swap" target="_blank" style="color:#58a6ff;text-decoration:none">{coin} ↗</a>'

        # 构建分析文本
        lines = []
        top3 = rows[:3]
        bottom3 = rows[-3:] if len(rows) >= 3 else rows

        # 总体概览
        avg = sum(r["total_score"] for r in rows) / len(rows)
        critical = [r for r in rows if r["total_score"] >= 75]
        high = [r for r in rows if 65 <= r["total_score"] < 75]
        medium = [r for r in rows if 45 <= r["total_score"] < 65]
        safe = [r for r in rows if r["total_score"] < 45]
        lines.append(f"本轮{len(rows)}个币种平均分{avg:.0f}分。最高危{len(critical)}个、高度危险{len(high)}个、中等{len(medium)}个、安全{len(safe)}个。")

        # 高危前三分析
        lines.append(f"\n🔥 重点回避（做多危险前三）：")
        for r in top3:
            factors = []
            if r["score_ema"] >= 15: factors.append("趋势转空")
            if r["score_funding"] >= 15: factors.append("资金费率高")
            if r["score_momentum"] >= 10: factors.append("短期下跌动能强")
            if r["score_position"] >= 12: factors.append("高位")
            if r["score_rsi"] >= 8: factors.append("RSI超买")
            if r["score_dispersion"] >= 8: factors.append("偏离均线远")
            lines.append(f"  {okx_link(r['coin_name'])}（{r['total_score']}分）：{', '.join(factors)}。{r.get('trade_signal','观望')}。")

        # 安全前三分析
        lines.append(f"\n✅ 相对安全（做多优先）：")
        for r in bottom3:
            factors = []
            if r["score_ema"] < 10: factors.append("趋势偏多")
            if r["score_funding"] < 8: factors.append("资金费率低/负")
            if r["score_momentum"] < 7: factors.append("短期企稳")
            if r["score_position"] < 8: factors.append("低位")
            if r["score_rsi"] < 5: factors.append("RSI超卖")
            lines.append(f"  {okx_link(r['coin_name'])}（{r['total_score']}分）：{', '.join(factors)}。")

        # 总结
        if critical:
            lines.append(f"\n💡 建议：当前{len(critical)}个币种高危（{', '.join(okx_link(r['coin_name']) for r in critical)}），做多风险极高，优先考虑做空或观望。")
        else:
            lines.append(f"\n💡 建议：整体风险可控，可精选低分币种做多。")

        return json_ok({"analysis": "\n".join(lines), "analysis_time": at})
    except Exception as e:
        return json_err(str(e))


@app.route("/binance-danger")
def binance_danger_page():
    return send_from_directory("static", "index.html")


@app.route("/api/binance-danger")
def api_binance_danger():
    """币安做多危险指数评分（binance_danger_rank_30）"""
    try:
        from db_manager import fetch_all, fetch_one
        limit = int(request.args.get("limit", 30))
        analysis_time = request.args.get("analysis_time") or None

        if not analysis_time:
            latest = fetch_one(
                """SELECT DATE_FORMAT(record_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time
                   FROM binance_danger_rank_30
                   GROUP BY minute_time
                   HAVING COUNT(*) >= 5
                   ORDER BY minute_time DESC LIMIT 1""",
                db="ll_test",
            )
            if not latest:
                latest = fetch_one(
                    "SELECT DATE_FORMAT(record_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time FROM binance_danger_rank_30 ORDER BY record_time DESC LIMIT 1",
                    db="ll_test",
                )
            if latest:
                analysis_time = latest["minute_time"]

        if analysis_time and len(analysis_time) == 16:
            start_time = analysis_time + ":00"
            from datetime import datetime, timedelta
            dt = datetime.strptime(analysis_time, "%Y-%m-%d %H:%M")
            end_dt = dt + timedelta(minutes=1)
            end_time = end_dt.strftime("%Y-%m-%d %H:%M:%S")
            records = fetch_all(
                """SELECT t1.* FROM binance_danger_rank_30 t1
                   INNER JOIN (
                       SELECT coin_name, MAX(record_time) AS max_time
                       FROM binance_danger_rank_30
                       WHERE record_time >= %s AND record_time < %s
                       GROUP BY coin_name
                   ) t2 ON t1.coin_name = t2.coin_name AND t1.record_time = t2.max_time
                   ORDER BY t1.total_score DESC
                   LIMIT %s""",
                (start_time, end_time, limit),
                db="ll_test",
            )
        else:
            records = fetch_all(
                """SELECT * FROM binance_danger_rank_30
                   WHERE record_time = %s
                   ORDER BY total_score DESC
                   LIMIT %s""",
                (analysis_time, limit),
                db="ll_test",
            )

        times = fetch_all(
            """SELECT DATE_FORMAT(record_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time,
                      COUNT(*) AS cnt
               FROM binance_danger_rank_30
               GROUP BY minute_time
               ORDER BY minute_time DESC
               LIMIT 100""",
            db="ll_test",
        )

        return json_ok({
            "records": records,
            "total": len(records),
            "analysis_time": analysis_time,
            "times": [{"time": t["minute_time"], "cnt": t["cnt"]} for t in times],
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/api/binance-danger/analysis")
def api_binance_danger_analysis():
    """币安做多危险指数 AI 分析"""
    try:
        from db_manager import fetch_all, fetch_one
        latest = fetch_one(
            """SELECT DATE_FORMAT(record_time, '%%Y-%%m-%%d %%H:%%i') AS minute_time
               FROM binance_danger_rank_30
               GROUP BY minute_time
               HAVING COUNT(*) >= 5
               ORDER BY minute_time DESC LIMIT 1""",
            db="ll_test",
        )
        if not latest:
            return json_ok({"analysis": "暂无数据"})
        at = latest["minute_time"]
        start_t = at + ":00"
        from datetime import datetime, timedelta
        dt = datetime.strptime(at, "%Y-%m-%d %H:%M")
        end_t = (dt + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")

        rows = fetch_all(
            """SELECT t1.* FROM binance_danger_rank_30 t1
               INNER JOIN (
                   SELECT coin_name, MAX(record_time) AS max_time
                   FROM binance_danger_rank_30
                   WHERE record_time >= %s AND record_time < %s
                   GROUP BY coin_name
               ) t2 ON t1.coin_name = t2.coin_name AND t1.record_time = t2.max_time
               ORDER BY t1.total_score DESC LIMIT 30""",
            (start_t, end_t), db="ll_test",
        )
        if not rows:
            return json_ok({"analysis": "暂无数据"})

        def okx_link(coin):
            name = coin.lower().replace(" ", "").replace("/", "")
            return f'<a href="https://www.okx.com/zh-hans/trade-swap/{name}-usdt-swap" target="_blank" style="color:#58a6ff;text-decoration:none">{coin} ↗</a>'

        lines = []
        top3 = rows[:3]
        bottom3 = rows[-3:] if len(rows) >= 3 else rows
        avg = sum(r["total_score"] for r in rows) / len(rows)
        critical = [r for r in rows if r["total_score"] >= 75]
        high = [r for r in rows if 65 <= r["total_score"] < 75]
        medium = [r for r in rows if 45 <= r["total_score"] < 65]
        safe = [r for r in rows if r["total_score"] < 45]
        lines.append(f"本轮{len(rows)}个币种平均分{avg:.0f}分。最高危{len(critical)}个、高度危险{len(high)}个、中等{len(medium)}个、安全{len(safe)}个。")
        lines.append(f"\n🔥 重点回避（做多危险前三）：")
        for r in top3:
            factors = []
            if r["score_ema"] >= 15: factors.append("趋势转空")
            if r["score_funding"] >= 15: factors.append("资金费率高")
            if r["score_momentum"] >= 10: factors.append("短期下跌动能强")
            if r["score_position"] >= 12: factors.append("高位")
            if r["score_rsi"] >= 8: factors.append("RSI超买")
            if r["score_dispersion"] >= 8: factors.append("偏离均线远")
            lines.append(f"  {okx_link(r['coin_name'])}（{r['total_score']}分）：{', '.join(factors)}。{r.get('trade_signal','观望')}。")
        lines.append(f"\n✅ 相对安全（做多优先）：")
        for r in bottom3:
            factors = []
            if r["score_ema"] < 10: factors.append("趋势偏多")
            if r["score_funding"] < 8: factors.append("资金费率低/负")
            if r["score_momentum"] < 7: factors.append("短期企稳")
            if r["score_position"] < 8: factors.append("低位")
            if r["score_rsi"] < 5: factors.append("RSI超卖")
            lines.append(f"  {okx_link(r['coin_name'])}（{r['total_score']}分）：{', '.join(factors)}。")
        if critical:
            lines.append(f"\n💡 建议：当前{len(critical)}个币种高危（{', '.join(okx_link(r['coin_name']) for r in critical)}），做多风险极高。")
        else:
            lines.append(f"\n💡 建议：整体风险可控。")
        return json_ok({"analysis": "\n".join(lines), "analysis_time": at})
    except Exception as e:
        return json_err(str(e))


# ── 前端页面 ────────────────────────────────────────────────


@app.route("/api/market")
def api_market():
    """实时行情 — 从 market_watcher 缓存读取"""
    try:
        cache_path = Path(__file__).parent.parent / "cache" / "market.json"
        data = {"price": None, "contract_price": None, "change_24h": 0}
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if "error" not in cached:
                data = cached

        # 从 main.log 解析指标（仍然实时解析）
        log_path = Path(__file__).parent.parent / "main.log"
        indicators = {}
        last_signal = ""
        if log_path.exists():
            lines = subprocess.run(["tail", "-80", str(log_path)], capture_output=True, text=True, timeout=5).stdout.splitlines()
            for line in lines:
                m = re.search(r'信号: (⚪观望|🟢开多|🔴开空|❌)', line)
                if m:
                    last_signal = m.group(1)
                for key in ("价格", "bb_position", "adx", "uptrend_block", "cooldown", "趋势ema"):
                    if key not in indicators:
                        m2 = re.search(rf'{re.escape(key)}: (\S+)', line)
                        if m2:
                            indicators[key] = m2.group(1)

        # 持仓信息从 account cache 取
        pos_info = {}
        acct_path = Path(__file__).parent.parent / "cache" / "account.json"
        if acct_path.exists():
            acct = json.loads(acct_path.read_text(encoding="utf-8"))
            if "error" not in acct and acct.get("positions"):
                p = acct["positions"][0]
                pos_info = {
                    "side": p.get("side"),
                    "size": p.get("size", 0),
                    "entry_price": p.get("entry_price", 0),
                    "unrealized_pnl": p.get("unrealized_pnl", 0),
                    "mark_price": p.get("mark_price", 0),
                }

        return json_ok_data({
            "price": data.get("price"),
            "contract_price": data.get("contract_price"),
            "change_24h": data.get("change_24h", 0),
            "signal": last_signal or "未知",
            "indicators": indicators,
            "position": pos_info,
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/api/account")
def api_account():
    """币安账户余额和持仓摘要 — 从 market_watcher 缓存读取"""
    try:
        cache_path = Path(__file__).parent.parent / "cache" / "account.json"
        if cache_path.exists():
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if "error" not in data:
                # 清理 timestamp 等内部字段
                result = {k: data[k] for k in ("total_wallet", "unrealized_pnl", "total_equity", "assets", "positions") if k in data}
                return json_ok_data(result)

        return json_ok_data({
            "total_wallet": 0, "unrealized_pnl": 0, "total_equity": 0,
            "assets": [], "positions": [],
        })
    except Exception as e:
        return json_err(str(e))


# ── OKX 多账户管理 ────────────────────────────────────────────


def _okx_exchange(cfg, sandbox=False):
    """创建 OKX ccxt 实例"""
    ex = ccxt.okx({
        "apiKey": cfg["apiKey"].strip(),
        "secret": cfg["secret"].strip(),
        "password": cfg["password"].strip(),
        "enableRateLimit": True,
        "options": {"defaultType": "swap", "sandboxMode": sandbox},
    })
    if sandbox:
        ex.urls["api"] = ex.urls["test"]
    return ex


@app.route("/api/okx/balance", methods=["POST"])
def api_okx_balance():
    """查询多账户余额"""
    try:
        req = request.get_json()
        accounts = req.get("accounts", [])
        sandbox = req.get("sandbox", False)
        results = []
        for acc in accounts:
            # 校验必填字段
            ak = (acc.get("apiKey") or "").strip()
            sk = (acc.get("secret") or "").strip()
            pw = (acc.get("password") or "").strip()
            if not ak or not sk or not pw:
                results.append({"name": acc.get("name", "?"), "ok": False, "error": "API Key / Secret / Passphrase 不能为空"})
                continue
            try:
                ex = _okx_exchange(acc, sandbox)
                ex.load_markets()
                bal = ex.fetch_balance()
                # USDT
                usdt = bal.get("USDT", {})
                usdt_total = float(usdt.get("total", 0))
                usdt_free = float(usdt.get("free", 0))
                usdt_used = float(usdt.get("used", 0))
                # 持仓
                positions = []
                total_upnl = 0.0
                try:
                    pos_list = ex.fetch_positions()
                    for p in pos_list:
                        sz = float(p.get("contracts", 0) or p.get("size", 0))
                        if sz != 0:
                            upnl = float(p.get("unrealizedPnl", 0))
                            total_upnl += upnl
                            positions.append({
                                "symbol": p.get("symbol"),
                                "side": p.get("side"),
                                "size": sz,
                                "entryPrice": float(p.get("entryPrice", 0)),
                                "markPrice": float(p.get("markPrice", 0)),
                                "unrealizedPnl": upnl,
                                "margin": float(p.get("initialMargin", 0)),
                            })
                except Exception:
                    pass
                total_equity = usdt_total + total_upnl
                results.append({
                    "name": acc.get("name", "?"),
                    "ok": True,
                    "usdt_total": round(usdt_total, 2),
                    "usdt_free": round(usdt_free, 2),
                    "usdt_used": round(usdt_used, 2),
                    "total_equity": round(total_equity, 2),
                    "unrealized_pnl": round(total_upnl, 2),
                    "positions": positions,
                })
            except Exception as e:
                err_msg = str(e)
                # 提取 OKX JSON 错误信息
                if "{" in err_msg and "msg" in err_msg:
                    try:
                        import re as _re
                        m = _re.search(r'"msg":"([^"]+)"', err_msg)
                        if m:
                            err_msg = m.group(1)
                    except Exception:
                        pass
                results.append({
                    "name": acc.get("name", "?"),
                    "ok": False,
                    "error": err_msg,
                })
        return json_ok(results)
    except Exception as e:
        return json_err(str(e))


@app.route("/api/okx/open-position", methods=["POST"])
def api_okx_open_position():
    """开仓"""
    try:
        req = request.get_json()
        acc = req.get("account", {})
        ak = (acc.get("apiKey") or "").strip()
        sk = (acc.get("secret") or "").strip()
        pw = (acc.get("password") or "").strip()
        if not ak or not sk or not pw:
            return json_err("API Key / Secret / Passphrase 不能为空")
        symbol = req.get("symbol", "BTC/USDT:USDT")
        side = req.get("side", "buy")          # buy=开多, sell=开空
        amount = float(req.get("amount", 0.01))
        order_type = req.get("order_type", "market")
        leverage = int(req.get("leverage", 1))
        margin_mode = req.get("margin_mode", "isolated")
        sandbox = req.get("sandbox", False)

        ex = _okx_exchange(acc, sandbox)
        ex.load_markets()

        if symbol not in ex.markets:
            return json_err(f"合约 {symbol} 不存在")

        # 设置杠杆
        try:
            ex.set_leverage(leverage, symbol)
        except Exception:
            pass
        try:
            ex.set_margin_mode(margin_mode, symbol)
        except Exception:
            pass

        # 获取当前价格
        ticker = ex.fetch_ticker(symbol)
        current_price = ticker["last"]

        # 下单
        if order_type == "market":
            order = ex.create_market_order(symbol, side, amount)
        else:
            order = ex.create_limit_order(symbol, side, amount, current_price)

        # 查成交
        time.sleep(0.5)
        order_id = order.get("id", "")
        if order_id:
            try:
                order = ex.fetch_order(order_id, symbol)
            except Exception:
                pass

        filled = float(order.get("filled", 0))
        avg_price = float(order.get("average", 0) or order.get("price", 0) or 0)

        return json_ok({
            "order_id": order.get("id"),
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "filled": filled,
            "avg_price": round(avg_price, 1),
            "status": order.get("status"),
            "current_price": current_price,
            "message": f"{'开多' if side == 'buy' else '开空'} {filled}/{amount} 张 @ ${avg_price:.1f}" if filled > 0 else "订单已提交但未成交",
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/api/okx/close-all", methods=["POST"])
def api_okx_close_all():
    """一键平仓 — 平掉该账户下所有合约持仓"""
    try:
        req = request.get_json()
        acc = req.get("account", {})
        ak = (acc.get("apiKey") or "").strip()
        sk = (acc.get("secret") or "").strip()
        pw = (acc.get("password") or "").strip()
        if not ak or not sk or not pw:
            return json_err("API Key / Secret / Passphrase 不能为空")
        sandbox = req.get("sandbox", False)

        ex = _okx_exchange(acc, sandbox)
        ex.load_markets()

        positions = ex.fetch_positions()
        closed = []
        for pos in positions:
            sz = float(pos.get("contracts", 0) or pos.get("size", 0))
            if sz == 0:
                continue
            symbol = pos.get("symbol", "")
            pos_side = pos.get("side", "")  # 'long' or 'short'
            if not symbol or not pos_side:
                continue

            # 平仓：多仓卖，空仓买
            close_side = "sell" if pos_side == "long" else "buy"
            try:
                order = ex.create_market_order(symbol, close_side, sz)
                time.sleep(0.3)
                order_id = order.get("id", "")
                if order_id:
                    try:
                        order = ex.fetch_order(order_id, symbol)
                    except Exception:
                        pass
                filled = float(order.get("filled", 0))
                closed.append({
                    "symbol": symbol,
                    "side": pos_side,
                    "size": sz,
                    "filled": filled,
                    "status": order.get("status"),
                })
            except Exception as e:
                closed.append({
                    "symbol": symbol,
                    "side": pos_side,
                    "size": sz,
                    "error": str(e),
                })

        return json_ok({
            "closed": closed,
            "total": len(closed),
            "message": f"已处理 {len(closed)} 个持仓",
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/api/okx/orders", methods=["POST"])
def api_okx_orders():
    """查询最近订单"""
    try:
        req = request.get_json()
        acc = req.get("account", {})
        ak = (acc.get("apiKey") or "").strip()
        sk = (acc.get("secret") or "").strip()
        pw = (acc.get("password") or "").strip()
        if not ak or not sk or not pw:
            return json_err("API Key / Secret / Passphrase 不能为空")
        symbol = req.get("symbol", "BTC/USDT:USDT")
        limit = int(req.get("limit", 20))
        sandbox = req.get("sandbox", False)

        ex = _okx_exchange(acc, sandbox)
        ex.load_markets()
        orders = ex.fetch_orders(symbol, limit=limit)

        result = []
        for o in orders:
            result.append({
                "id": o.get("id"),
                "datetime": o.get("datetime"),
                "side": o.get("side"),
                "type": o.get("type"),
                "price": o.get("price"),
                "amount": o.get("amount"),
                "filled": o.get("filled"),
                "cost": o.get("cost"),
                "status": o.get("status"),
                "fee": o.get("fee"),
            })
        return json_ok(result)
    except Exception as e:
        return json_err(str(e))


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/orders")
def orders_page():
    return send_from_directory("static", "index.html")


@app.route("/polymarket")
def polymarket_page():
    return send_from_directory("static", "index.html")

@app.route("/sim-orders")
def sim_orders_page():
    return send_from_directory("static", "index.html")


@app.route("/strategies")
def strategies_page():
    return send_from_directory("static", "index.html")

@app.route("/usdc")
def usdc_page():
    return send_from_directory("static", "index.html")


@app.route("/sd-only")
def sd_only_page():
    return send_from_directory("static", "index.html")


@app.route("/api/btc-trend")
@cached(300)
def api_btc_trend():
    """BTC 六因子量化评分（每5分钟刷新）"""
    import subprocess, re, json as _json
    try:
        script = Path(__file__).parent.parent / "btc_analysis.py"
        result = subprocess.run(["python3", str(script)], capture_output=True, text=True, timeout=30)
        out = result.stdout

        def grab(pattern, default="?"):
            m = re.search(pattern, out)
            return m.group(1).strip() if m else default

        price = float(grab(r"当前价格:\s*\$?([\d,]+)", "0").replace(",", ""))
        score = int(grab(r"总分:\s*(\d+)/100"))
        verdict = grab(r"→ (.+)")
        ema7 = float(grab(r"EMA7:\s*\$?([\d,]+)", "0").replace(",", ""))
        ema25 = float(grab(r"EMA25:\s*\$?([\d,]+)", "0").replace(",", ""))
        ema99 = grab(r"EMA99:\s*\$?([\d,]+)")
        ema99 = float(ema99.replace(",", "")) if ema99 != "?" else None
        rsi_val = grab(r"RSI\(14\):\s*([\d.]+)")
        m24 = re.search(r"当前vs均价:\s*([+-]?\d+\.?\d*)%", out)
        chg_24h = float(m24.group(1)) if m24 else 0
        # 震荡幅度
        amp = grab(r"24h振幅:\s*([\d.]+)%")
        # 各因子分数
        s1 = int(grab(r"\[短期趋势\s*(\d+)/30"))
        s2 = int(grab(r"\[中期位置\s*(\d+)/20"))
        s3 = int(grab(r"\[波动健康\s*(\d+)/15"))
        s4 = int(grab(r"\[成交量支撑\s*(\d+)/10"))
        s5 = int(grab(r"\[动量强度\s*(\d+)/15"))
        s6 = int(grab(r"\[风险调整\s*(\d+)/10"))

        # 因子详细描述
        s1_desc = grab(r"\[短期趋势\s*\d+/30\]\s*(.+)")
        s2_desc = grab(r"\[中期位置\s*\d+/20\]\s*(.+)")
        s3_desc = grab(r"\[波动健康\s*\d+/15\]\s*(.+)")
        s4_desc = grab(r"\[成交量支撑\s*\d+/10\]\s*(.+)")
        s5_desc = grab(r"\[动量强度\s*\d+/15\]\s*(.+)")
        s6_desc = grab(r"\[风险调整\s*\d+/10\]\s*(.+)")

        # V型反弹
        recovery = grab(r"反弹幅度:\s*([\d.]+)%")
        candle_lines = [l.strip() for l in out.split("\n") if "⚠️" in l or "✅" in l]
        candle_trend = candle_lines[-1] if candle_lines else ""

        # 关键价位（去逗号转数字）
        support = grab(r"强支撑:\s*\$?([\d,]+)")
        resistance = grab(r"强阻力:\s*\$?([\d,]+)")
        weak_resistance = grab(r"弱阻力:\s*\$?([\d,]+)")
        try:
            support = float(support.replace(",", "")) if support != "?" else None
        except:
            support = None
        try:
            resistance = float(resistance.replace(",", "")) if resistance != "?" else None
        except:
            resistance = None
        try:
            weak_resistance = float(weak_resistance.replace(",", "")) if weak_resistance != "?" else None
        except:
            weak_resistance = None

        total = s1 + s2 + s3 + s4 + s5 + s6
        trend = "多头" if total >= 60 else "空头"

        # ── 生成详细交易策略分析 ──
        ema7_s = f"${ema7:,.0f}" if ema7 else "?"
        ema25_s = f"${ema25:,.0f}" if ema25 else "?"
        sup_s = f"${support:,.0f}" if support else "?"
        res_s = f"${resistance:,.0f}" if resistance else "?"
        wr_s = f"${weak_resistance:,.0f}" if weak_resistance else "?"

        long_ok = s1 > 15 and s5 > 7 and total >= 60
        short_ok = s1 < 10 and s5 < 5 and total < 50
        if total >= 70:
            desc = f"当前总分{total}/100，属「大概率盈利」区间。短期趋势{s1}/30强势，动量{s5}/15配合，多头排列清晰。"
            analysis = (
                f"趋势方向明确，多头占优，以回调做多为主。"
                f"如果要操作，等待价格回踩EMA7({ema7_s})附近企稳后轻仓试多。"
                f"买入信号: RSI({rsi_val})未超买，MACD零轴上15m金叉即可入场。"
                f"关注点: 放量突破{res_s}则打开上行空间。"
            )
            suggest = "✅ 评分≥70，大盘强势，可以正常开多"
        elif total >= 60:
            desc = f"当前总分{total}/100，踩在保本线。短期趋势{s1}/30中性，RSI({rsi_val})，方向不明。"
            analysis = (
                f"多空平衡区，观望为主，当前位置可上可下直接入场盈亏比差。"
                f"如果要操作，等待回踩支撑{sup_s}企稳试多或反弹{res_s}受阻试空。"
                f"买入信号: 价格站稳EMA7且15m MACD零轴上金叉。"
                f"卖出信号: 价格跌破{sup_s}且放量。"
                f"关注点: 突破{res_s}偏多，跌破{sup_s}偏空。"
            )
            suggest = "🟡 评分≥60，保本区域，谨慎开多"
        elif total >= 50:
            desc = f"当前总分{total}/100，偏弱区域。短期趋势{s1}/30偏空，RSI({rsi_val})偏低。"
            analysis = (
                f"偏弱震荡，以反弹做空为主，谨慎抄底。"
                f"如果要操作，反弹至弱阻力{wr_s}附近遇阻试空。"
                f"买入信号: 暂时没有，需等价格放量站上EMA7。"
                f"关注点: 若再次测试{sup_s}关注是否放量破位。"
            )
            suggest = "⏸ 评分<60，偏弱区域，暂不建议开多"
        else:
            ct = f"，近3K {candle_trend}" if candle_trend else ""
            desc = f"当前总分{total}/100，属于「大概率亏损」区间。短期趋势{s1}/30极弱，RSI({rsi_val}){ct}。"
            analysis = (
                f"观望为主，等待二次确认。当前位置既不在支撑也不在阻力，盈亏比最差。"
                f"如果要操作，等待反弹至{wr_s}区域遇阻确认后小仓位试空。"
                f"买入信号: 需要价格站稳EMA7({ema7_s})且15m金叉形成，目前均不满足。"
                f"关注点: 若再次测试{sup_s}前低，关注是否放量破位——破位则进一步看{round(support * 0.95) if support else '?'}。"
            )
            suggest = "🔴 评分<50，大概率亏损，暂停开多"

        return json_ok({
            "price": price,
            "score": total,
            "verdict": verdict,
            "trend": trend,
            "factors": {
                "短期趋势": {"score": s1, "max": 30, "desc": s1_desc},
                "中期位置": {"score": s2, "max": 20, "desc": s2_desc},
                "波动健康": {"score": s3, "max": 15, "desc": s3_desc},
                "成交量支撑": {"score": s4, "max": 10, "desc": s4_desc},
                "动量强度": {"score": s5, "max": 15, "desc": s5_desc},
                "风险调整": {"score": s6, "max": 10, "desc": s6_desc},
            },
            "ema7": ema7,
            "ema25": ema25,
            "ema99": ema99,
            "rsi": float(rsi_val) if rsi_val != "?" else 0,
            "change_24h": round(chg_24h, 2),
            "amplitude": amp,
            "recovery": recovery,
            "support": support,
            "resistance": resistance,
            "weak_resistance": weak_resistance,
            "candle_trend": candle_trend,
            "desc": desc,
            "analysis": analysis,
            "suggest": suggest,
            "updated_at": datetime.now().strftime("%H:%M"),
        })
    except Exception as e:
        import traceback
        return json_ok({"price": 0, "score": 0, "trend": "未知", "desc": f"获取失败: {e}", "suggest": ""})


@app.route("/api/kdj-monitor")
def api_kdj_monitor():
    """KDJ金叉策略实时监控"""
    try:
        import ccxt, numpy as np
        ex = ccxt.binance({"enableRateLimit": True})
        ohlcv15 = ex.fetch_ohlcv("BTC/USDT", "15m", since=int(time.time()-86400)*1000, limit=100)
        close15 = [c[4] for c in ohlcv15]
        high15 = [c[2] for c in ohlcv15]
        low15 = [c[3] for c in ohlcv15]

        k15, d15 = [50], [50]
        for i in range(1, len(close15)):
            l = min(low15[max(0,i-8):i+1]); h = max(high15[max(0,i-8):i+1])
            rsv = (close15[i]-l)/(h-l)*100 if h!=l else 50
            k = k15[-1]*2/3+rsv/3; d = d15[-1]*2/3+k/3
            k15.append(k); d15.append(d)
        j15 = [3*k15[i]-2*d15[i] for i in range(len(k15))]
        ck, cd, cj = k15[-1], d15[-1], j15[-1]
        pk, pd = k15[-2], d15[-2]
        golden = pk <= pd and ck > cd
        death = pk >= pd and ck < cd

        cur_price = float(close15[-1])
        ema20 = sum(close15[-20:]) / 20
        above_ema = (cur_price / ema20 - 1) * 100

        s14 = close15[-14:]; m14 = sum(s14)/14
        bb_up14 = m14 + 2 * (sum((x-m14)**2 for x in s14)/14)**0.5

        cond_golden = {"value": bool(golden), "label": "KDJ金叉", "ok": golden}
        cond_k = {"value": round(ck, 1), "label": "K<30", "ok": ck < 30}
        cond_ema = {"value": round(above_ema, 2), "label": "不远离EMA20", "ok": above_ema <= 2}
        conditions = {"kdj_golden": cond_golden, "k_under_30": cond_k, "not_far_ema": cond_ema}
        can_buy = golden and ck < 30 and above_ema <= 2

        return json_ok({
            "price": round(cur_price, 1), "time": datetime.now().strftime("%H:%M:%S"),
            "k": round(ck, 1), "d": round(cd, 1), "j": round(cj, 1),
            "bb_up14": round(bb_up14, 1),
            "ema20": round(ema20, 1), "above_ema_pct": round(above_ema, 2),
            "golden_cross": golden, "death_cross": death,
            "can_buy": can_buy,
            "conditions": conditions,
            "state": "条件满足，可开仓" if can_buy else "等待开仓条件",
        })
    except Exception as e:
        import traceback
        return json_ok({"error": str(e), "trace": traceback.format_exc()})

@app.route("/trend-chart")
def trend_chart_page():
    return send_from_directory("static", "trend-chart.html")


@app.route("/trend-convergence")
def trend_convergence_page():
    return send_from_directory("static", "index.html")


@app.route("/api/trend-convergence")
def api_trend_convergence():
    """KDJ金叉策略状态：参数/持仓/挂单/历史"""
    try:
        from pathlib import Path as _P
        base = _P(__file__).parent.parent

        # KDJ 状态
        state = {"orders": {}, "positions": {}, "filled_today": {}, "closed_positions": []}
        state_path = base / "kdj_btcusdc_state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except:
                pass

        # KDJ 策略参数 — 从bot源码读当前配置
        _params = {
            "k_period": 7, "d_period": 2, "oversold_k": 25, "cooldown_bars": 2,
            "max_hold_candles": 8, "stop_loss_pct": 0.8,
            "take_profit_pct": 0.3, "overbought_k": 70, "entry_offset": -50,
            "order_qty": 0.05, "symbol": "BTC/USDC:USDC", "leverage": 1,
        }
        try:
            bot_src = (base / "main_kdj_btcusdc.py").read_text()
            import re as _re2
            for _key in ["k_period", "d_period", "oversold_k", "cooldown_bars",
                          "max_hold_candles", "stop_loss_pct", "take_profit_pct",
                          "OVERBOUGHT_K", "ENTRY_OFFSET"]:
                _mo = _re2.search(rf"{_key}\s*=\s*([\d.]+)", bot_src)
                if _mo:
                    _v = _mo.group(1)
                    _params[_key.lower().replace("overbought_k","overbought_k").replace("entry_offset","entry_offset")] = float(_v) if "." in _v else int(_v)
            # 补上overbought_k字段名
            if "OVERBOUGHT_K" in bot_src:
                _mo = _re2.search(r"OVERBOUGHT_K\s*=\s*(\d+)", bot_src)
                if _mo: _params["overbought_k"] = int(_mo.group(1))
        except: pass

        params = _params

        # 入场条件说明
        position_side = state.get("position")  # "long" / "short" / None
        conditions_long = [
            {"label": "KDJ金叉 (K上穿D)", "check": "前根K≤D 且 当前K>D"},
            {"label": f"K < {params['oversold_k']}（超卖区）", "check": f"当前K值 < {params['oversold_k']}"},
            {"label": "限价-$50挂买单", "check": f"低于市价{abs(params['entry_offset'])}U等待成交"},
            {"label": f"止盈 +{params['take_profit_pct']}%", "check": "达到目标价自动平"},
            {"label": f"止损 -{params['stop_loss_pct']}%", "check": "亏损达标自动平"},
            {"label": f"最长持有 {params['max_hold_candles']}根 ({params['max_hold_candles']*15//60}h)", "check": "超时市价平仓"},
        ]
        conditions_short = [
            {"label": "KDJ死叉 (K下穿D)", "check": "前根K≥D 且 当前K<D"},
            {"label": f"K > {params['overbought_k']}（超买区）", "check": f"当前K值 > {params['overbought_k']}"},
            {"label": "限价+$50挂卖单", "check": f"高于市价{abs(params['entry_offset'])}U等待成交"},
            {"label": f"止盈 +{params['take_profit_pct']}%（跌）", "check": "价格下跌达标自动平"},
            {"label": f"止损 +{params['stop_loss_pct']}%（涨）", "check": "价格上涨达标自动平"},
            {"label": f"最长持有 {params['max_hold_candles']}根 ({params['max_hold_candles']*15//60}h)", "check": "超时市价平仓"},
        ]

        # 当前 KDJ 值（从bot最新日志取）
        import subprocess, re as _re
        kdj_values = {"K": None, "D": None, "J": None}
        try:
            log_path = base / "main_kdj_btcusdc.log"
            if log_path.exists():
                out = subprocess.run(["tail", "-20", str(log_path)], capture_output=True, text=True, timeout=5).stdout
                for line in reversed(out.splitlines()):
                    m = _re.search(r"K=([\d.]+).*D=([\d.]+).*J=([\d.]+)", line)
                    if m:
                        kdj_values = {"K": float(m.group(1)), "D": float(m.group(2)), "J": float(m.group(3))}
                        break
        except:
            pass

        # 币安标准 KDJ(9,3) BTC/USDT — 供对比
        kdj_standard = {"K": None, "D": None, "J": None}
        try:
            import ccxt as _ccxt, pandas as _pd, numpy as _np
            _ex = _ccxt.binance({"enableRateLimit": True})
            _o = _ex.fetch_ohlcv("BTC/USDT", "15m", limit=250)
            _df = _pd.DataFrame(_o, columns=["t","o","h","l","c","v"])
            _c, _h, _l = _df["c"], _df["h"], _df["l"]
            _ll = _l.rolling(9).min(); _hh = _h.rolling(9).max()
            _rsv = (_c - _ll) / (_hh - _ll) * 100; _rsv = _rsv.fillna(50)
            _k = _rsv.ewm(alpha=1/3, adjust=False).mean()
            _d = _k.ewm(alpha=1/3, adjust=False).mean()
            _j = 3*_k - 2*_d
            kdj_standard = {"K": round(float(_k.iloc[-1]), 1), "D": round(float(_d.iloc[-1]), 1), "J": round(float(_j.iloc[-1]), 1)}
        except:
            pass

        # ── enrichment: 给 orders/positions 补充前端需要的字段 ──
        now_ts = time.time()

        # 获取实时价格用于未实现盈亏计算（避免状态文件价格过期导致盈亏错误）
        live_price = None
        try:
            import ccxt as _ccxt2
            _ex2 = _ccxt2.binance({"enableRateLimit": True})
            _ticker = _ex2.fetch_ticker("BTC/USDC:USDC")
            live_price = float(_ticker["last"])
        except:
            pass

        for coin, o in state.get("orders", {}).items():
            if o.get("placed_at"):
                o["age_hours"] = round((now_ts - o["placed_at"]) / 3600, 1)
                o["placed_at_str"] = datetime.fromtimestamp(o["placed_at"]).strftime("%m-%d %H:%M")
            else:
                o["age_hours"] = 0
                o["placed_at_str"] = "-"
        for coin, p in state.get("positions", {}).items():
            if p.get("filled_at"):
                p["filled_at_str"] = datetime.fromtimestamp(p["filled_at"]).strftime("%m-%d %H:%M")
            else:
                p["filled_at_str"] = "-"
            # 未实现盈亏（使用实时价格）— 区分多空方向
            price = live_price if live_price else p.get("current_price")
            pos_side = p.get("side", "long")  # 'long' or 'short'
            if p.get("entry_price") and price:
                qty = p.get("quantity", 0.05)
                if pos_side == "long":
                    p["unrealized_pnl"] = round((price - p["entry_price"]) * qty, 2)
                else:
                    p["unrealized_pnl"] = round((p["entry_price"] - price) * qty, 2)
                p["current_price"] = price

        return json_ok({
            "params": params,
            "position_side": position_side,
            "conditions_long": conditions_long,
            "conditions_short": conditions_short,
            "kdj": kdj_values,
            "kdj_standard": kdj_standard,
            "orders": state.get("orders", {}),
            "positions": state.get("positions", {}),
            "closed_positions": state.get("closed_positions", []),
            "filled_today": state.get("filled_today", {}),
        })
    except Exception as e:
        import traceback
        return json_err(str(e) + "\n" + traceback.format_exc())


@app.route("/local-orders")
def local_orders_page():
    return send_from_directory("static", "index.html")


@app.route("/okx")
def okx_page():
    return send_from_directory("static", "index.html")


@app.route("/strategy/<int:strategy_id>")
def strategy_detail_page(strategy_id):
    return send_from_directory("static", "index.html")


@app.route("/order/<int:order_id>")
def order_detail_page(order_id):
    return send_from_directory("static", "index.html")


# ── 仪表盘聚合 ──────────────────────────────────────────────


@app.route("/api/dashboard")
@cached(5)
def api_dashboard():
    """返回概览面板数据：策略数、订单数、最新盈亏、交易记录"""
    try:
        now = datetime.now().isoformat()

        # 策略统计
        strat_count = fetch_one("SELECT COUNT(*) cnt FROM strategies WHERE enabled = 1")
        strategies = list_strategies(enabled_only=True)
        active_strats = [
            {
                "id": s.id, "name": s.name,
                "strategy_type": s.strategy_type, "symbol": s.symbol, "timeframe": s.timeframe,
                "paper_trading": s.paper_trading, "enabled": s.enabled,
                "leverage": s.leverage, "max_position_usdt": s.max_position_usdt,
                "min_profit_rate": s.min_profit_rate, "max_loss_rate": s.max_loss_rate,
            }
            for s in strategies
        ]

        # 订单汇总
        today = date.today().isoformat()
        stats = get_real_order_stats()
        today_stats = get_real_order_stats(start=today)

        # 近期订单
        recent = fetch_all(
            "SELECT id, symbol, side, status, cum_quote, pnl, created_at, strategy_name, paper_trading "
            "FROM real_orders ORDER BY created_at DESC LIMIT 20"
        )

        # ── AI 策略运行状态 ──
        import os as _os
        import json as _json

        ai_strategies = []
        proc_out = _os.popen("ps aux | grep -E 'main_ai_entry|main_binance_ai|main_okx_ai' | grep -v grep").read()

        # 检查 binance AI
        ba_running = "main_binance_ai" in proc_out
        ba_state = {}
        ba_path = Path(__file__).parent.parent / "binance_ai_state.json"
        if ba_path.exists():
            try:
                ba_state = _json.loads(ba_path.read_text(encoding="utf-8"))
            except:
                ba_state = {}
        ba_orders = len(ba_state.get("orders", {}))
        ba_positions = len(ba_state.get("positions", {}))
        ba_closed = len(ba_state.get("closed_positions", []))
        ba_pnl = sum(p.get("pnl", 0) for p in ba_state.get("closed_positions", []))

        ai_strategies.append({
            "key": "binance_ai",
            "name": "Binance AI策略",
            "description": "基于Binance_top_value 币安USDT合约挂单",
            "running": ba_running,
            "orders_count": ba_orders,
            "positions_count": ba_positions,
            "closed_count": ba_closed,
            "pnl": round(ba_pnl, 2),
        })

        # 检查 OKX AI
        okx_running = "main_okx_ai" in proc_out
        okx_state = {}
        okx_path = Path(__file__).parent.parent / "okx_ai_state.json"
        if okx_path.exists():
            try:
                okx_state = _json.loads(okx_path.read_text(encoding="utf-8"))
            except:
                okx_state = {}
        okx_orders = len(okx_state.get("orders", {}))
        okx_positions = len(okx_state.get("positions", {}))
        okx_closed = len(okx_state.get("closed_positions", []))
        okx_pnl = sum(p.get("pnl", 0) for p in okx_state.get("closed_positions", []))

        ai_strategies.append({
            "key": "okx_ai",
            "name": "OKX AI策略",
            "description": "基于okx_top_value OKX USDT合约挂单",
            "running": okx_running,
            "orders_count": okx_orders,
            "positions_count": okx_positions,
            "closed_count": okx_closed,
            "pnl": round(okx_pnl, 2),
        })

        return json_ok_data({
            "time": now,
            "strategies": {
                "total_enabled": (strat_count["cnt"] if strat_count else 0) + (1 if ba_running else 0) + (1 if okx_running else 0),
                "list": active_strats,
                "ai_strategies": ai_strategies,
            },
            "orders": {
                "all_time": stats,
                "today": today_stats,
                "recent": recent,
            },
        })
    except Exception as e:
        return json_err(str(e))


# ── 入口 ────────────────────────────────────────────────────


def main():
    init_database()

    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "5000"))
    debug = os.getenv("WEB_DEBUG", "false").lower() == "true"

    print(f"🌐 Web 服务启动: http://{host}:{port}")
    print(f"   健康检查: http://{host}:{port}/health")
    print(f"   仪表盘:   http://{host}:{port}/api/dashboard")
    print(f"   订单列表: http://{host}:{port}/api/orders")
    print(f"   策略列表: http://{host}:{port}/api/strategies")

    app.run(host=host, port=port, debug=debug)


@app.route("/<path:filename>")
def web_root_files(filename):
    """提供前端SPA路由 或 Web 根目录下的 .txt 文件"""
    # /api/* 不存在则返回 404（不丢给 SPA）
    if filename.startswith("api/") or filename.startswith("api\\"):
        return jsonify({"code": 404, "msg": "Not Found"}), 404
    # SPA 路由（无扩展名）返回 index.html 让前端处理
    if "." not in filename:
        return send_from_directory("static", "index.html")
    if not filename.endswith(".txt"):
        return jsonify({"code": 404, "msg": "Not Found"}), 404
    import os
    web_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(web_dir, filename)
    # 防止路径穿越
    if os.path.realpath(file_path).startswith(os.path.realpath(web_dir)) and os.path.isfile(file_path):
        return send_from_directory(web_dir, filename)
    return jsonify({"code": 404, "msg": "Not Found"}), 404


if __name__ == "__main__":
    main()
