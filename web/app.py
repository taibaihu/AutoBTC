#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 服务 —— 订单/策略/统计查询"""
import json
import os
import sys
from datetime import datetime, date

# 将项目根目录加入 path, 复用 db_manager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory

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
)
from strategy_manager import list_strategies, load_strategy

import subprocess, re
from pathlib import Path
import ccxt
from config import get_proxy_config, CONTRACT_SYMBOL, SYMBOL

app = Flask(__name__)

# Polymarket 本金
POLYMARKET_INITIAL_BALANCE = float(os.getenv("POLYMARKET_INITIAL_BALANCE", "50"))


# ── 工具 ────────────────────────────────────────────────────


def json_serial(obj):
    """JSON 序列化辅助：处理 datetime/date/Decimal"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "__float__"):
        return float(obj)
    if hasattr(obj, "__int__"):
        return int(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def json_ok(data=None, msg="ok"):
    return jsonify({"code": 0, "msg": msg, "data": data})


def json_ok_data(data):
    """返回 data 并自动处理不可序列化类型"""
    return app.response_class(
        response=json.dumps({"code": 0, "msg": "ok", "data": data}, default=json_serial, ensure_ascii=False),
        status=200,
        mimetype="application/json",
    )


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
def api_local_trades():
    """本地订单列表（开平一条记录），持仓中自动计算未实现盈亏"""
    try:
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        status = request.args.get("status") or None
        direction = request.args.get("direction") or None
        trades = get_local_trades(limit=limit, offset=offset, status=status, direction=direction)
        stats = get_local_trade_stats()

        # 获取当前合约价格，为持仓中的订单计算未实现盈亏
        current_price = None
        try:
            proxies = get_proxy_config()
            ex = ccxt.binance({"enableRateLimit": True, "proxies": proxies})
            ticker = ex.fetch_ticker(CONTRACT_SYMBOL)
            current_price = float(ticker["last"])
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


# ── 前端页面 ────────────────────────────────────────────────


@app.route("/api/market")
def api_market():
    """实时行情 + 最新策略指标"""
    try:
        proxies = get_proxy_config()
        exchange = ccxt.binance({"enableRateLimit": True, "proxies": proxies})
        ticker = exchange.fetch_ticker(SYMBOL)
        contract_ticker = exchange.fetch_ticker(CONTRACT_SYMBOL)
        price = ticker["last"]
        contract_price = contract_ticker["last"]
        change_24h = ticker.get("percentage", 0)

        # 从 main.log 解析指标
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

        # 最新持仓状态
        pos_info = {}
        try:
            positions = exchange.fetch_positions([CONTRACT_SYMBOL])
            for p in positions:
                if float(p.get("contracts", 0) or 0) > 0:
                    pos_info = {
                        "side": p.get("positionSide"),
                        "size": float(p.get("contracts", 0)),
                        "entry_price": float(p.get("entryPrice", 0)),
                        "unrealized_pnl": float(p.get("unrealizedPnl", 0)),
                        "mark_price": float(p.get("markPrice", 0)),
                    }
                    break
        except:
            pass

        return json_ok_data({
            "price": price,
            "contract_price": contract_price,
            "change_24h": round(change_24h, 2) if change_24h else 0,
            "signal": last_signal or "未知",
            "indicators": indicators,
            "position": pos_info,
        })
    except Exception as e:
        return json_err(str(e))


@app.route("/api/account")
def api_account():
    """币安账户余额和持仓摘要"""
    try:
        proxies = get_proxy_config()
        exchange = ccxt.binance({
            "apiKey": os.getenv("BINANCE_API_KEY"),
            "secret": os.getenv("BINANCE_SECRET_KEY"),
            "enableRateLimit": True,
            "proxies": proxies,
            "options": {"defaultType": "future"},
        })
        balance = exchange.fetch_balance()
        info = balance.get("info", {})
        assets = []
        for asset in info.get("assets", []):
            wallet = asset.get("walletBalance", "0")
            upnl = asset.get("unrealizedProfit", "0")
            if float(wallet) > 0 or float(upnl) != 0:
                assets.append({
                    "asset": asset.get("asset"),
                    "wallet": float(wallet),
                    "unrealized_pnl": float(upnl),
                    "total": float(wallet) + float(upnl),
                })

        positions = []
        try:
            pos_data = exchange.fetch_positions([CONTRACT_SYMBOL])
            for p in pos_data:
                amt = float(p.get("contracts", 0) or 0)
                if amt > 0:
                    side = p.get("info", {}).get("positionSide", "LONG")
                    wallet = max(float(p.get("initialMargin", 0) or 0), 1)
                    positions.append({
                        "symbol": p.get("symbol"),
                        "side": side,
                        "size": amt,
                        "entry_price": float(p.get("entryPrice", 0)),
                        "mark_price": float(p.get("markPrice", 0)),
                        "unrealized_pnl": round(float(p.get("unrealizedPnl", 0)), 2),
                        "pnl_pct": round(float(p.get("unrealizedPnl", 0)) / wallet * 100, 2),
                    })
        except:
            for p in info.get("positions", []):
                if float(p.get("positionAmt", "0")) != 0:
                    positions.append({
                        "symbol": p.get("symbol"),
                        "side": p.get("positionSide"),
                        "size": float(p.get("positionAmt", 0)),
                        "entry_price": float(p.get("entryPrice", 0)),
                        "mark_price": float(p.get("markPrice", 0)),
                        "unrealized_pnl": float(p.get("unrealizedPnl", 0)),
                        "pnl_pct": 0,
                    })

        main_asset = next((a for a in assets if a["asset"] == "USDT"), {"wallet": 0, "unrealized_pnl": 0, "total": 0})
        return json_ok_data({
            "total_wallet": main_asset["wallet"],
            "unrealized_pnl": main_asset["unrealized_pnl"],
            "total_equity": main_asset["total"],
            "assets": assets,
            "positions": positions,
        })
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


@app.route("/local-orders")
def local_orders_page():
    return send_from_directory("static", "index.html")


@app.route("/strategy/<int:strategy_id>")
def strategy_detail_page(strategy_id):
    return send_from_directory("static", "index.html")


@app.route("/order/<int:order_id>")
def order_detail_page(order_id):
    return send_from_directory("static", "index.html")


# ── 仪表盘聚合 ──────────────────────────────────────────────


@app.route("/api/dashboard")
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

        return json_ok_data({
            "time": now,
            "strategies": {
                "total_enabled": strat_count["cnt"] if strat_count else 0,
                "list": active_strats,
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


if __name__ == "__main__":
    main()
