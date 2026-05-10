#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略管理命令行工具"""
import argparse
import json
import sys
import logging

from strategy_manager import (
    StrategyConfig, load_strategy, save_strategy, list_strategies, apply_to_config,
)
from db_manager import execute, fetch_one, fetch_all, init_database, get_real_order, get_real_orders, get_real_order_stats

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.WARNING)
logger = logging.getLogger(__name__)


def cmd_list(args):
    strategies = list_strategies(enabled_only=False)
    if not strategies:
        print("暂无策略")
        return

    header = f"{'ID':<4} {'用户':<14} {'类型':<12} {'周期':<6} {'杠杆':<6} {'止盈':<6} {'止损':<6} {'仓位':<8} {'模拟':<5} {'状态':<5} {'名称'}"
    print(header)
    print("-" * 95)
    for s in strategies:
        lev = f"{s.leverage}x"
        tp = f"{s.min_profit_rate*100:.1f}%"
        sl = f"{s.max_loss_rate*100:.1f}%"
        pos = f"{s.max_position_usdt:.0f}U"
        paper = "模拟" if s.paper_trading else "实盘"
        status = "启用" if s.enabled else "禁用"
        print(f"{s.id:<4} {s.user_id:<14} {s.strategy_type:<12} {s.timeframe:<6} {lev:<6} {tp:<6} {sl:<6} {pos:<8} {paper:<5} {status:<5} {s.name}")


def cmd_view(args):
    cfg = load_strategy(args.user)
    print(json.dumps({
        "id": cfg.id,
        "name": cfg.name,
        "user_id": cfg.user_id,
        "strategy_type": cfg.strategy_type,
        "symbol": cfg.symbol,
        "timeframe": cfg.timeframe,
        "paper_trading": cfg.paper_trading,
        "enabled": cfg.enabled,
        "params": cfg.params,
        # 风控参数（独立字段）
        "leverage": cfg.leverage,
        "max_position_usdt": cfg.max_position_usdt,
        "daily_loss_limit": cfg.daily_loss_limit,
        "max_trades_per_day": cfg.max_trades_per_day,
        "min_profit_rate": cfg.min_profit_rate,
        "max_loss_rate": cfg.max_loss_rate,
        "rsi_params": cfg.rsi_params,
    }, ensure_ascii=False, indent=2))


def cmd_set(args):
    cfg = load_strategy(args.user)

    if args.type:
        cfg.strategy_type = args.type
        if args.type == "ma_cross":
            cfg.params.setdefault("short_window", 7)
            cfg.params.setdefault("long_window", 25)
        elif args.type == "rsi_revert":
            cfg.params.setdefault("period", 14)
            cfg.params.setdefault("oversold", 20)
            cfg.params.setdefault("overbought", 80)

    if args.symbol:
        cfg.symbol = args.symbol
    if args.timeframe:
        cfg.timeframe = args.timeframe
    if args.paper is not None:
        cfg.paper_trading = args.paper == "1"
    if args.name:
        cfg.name = args.name

    try:
        save_strategy(cfg)
        print(f"策略已保存 (user={cfg.user_id}, type={cfg.strategy_type})")
    except Exception as e:
        print(f"保存失败: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_param(args):
    """修改策略的参数"""
    cfg = load_strategy(args.user)

    if args.group == "risk":
        # 修改风控参数（独立表独立字段）
        for kv in args.set:
            if "=" not in kv:
                print(f"格式错误: '{kv}'，需要 key=value 格式", file=sys.stderr)
                sys.exit(1)
            key, val = kv.split("=", 1)
            if key == "leverage":
                cfg.leverage = int(val)
            else:
                val = float(val)
                if key == "max_position_usdt":
                    cfg.max_position_usdt = val
                elif key == "daily_loss_limit":
                    cfg.daily_loss_limit = val
                elif key == "max_trades_per_day":
                    cfg.max_trades_per_day = int(val)
                elif key == "min_profit_rate":
                    cfg.min_profit_rate = val
                elif key == "max_loss_rate":
                    cfg.max_loss_rate = val
                else:
                    print(f"未知风控参数: {key}", file=sys.stderr)
                    sys.exit(1)
    elif args.group == "strategy":
        for kv in args.set:
            if "=" not in kv:
                print(f"格式错误: '{kv}'", file=sys.stderr)
                sys.exit(1)
            key, val = kv.split("=", 1)
            try:
                cfg.params[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                cfg.params[key] = val
    elif args.group == "rsi":
        for kv in args.set:
            if "=" not in kv:
                print(f"格式错误: '{kv}'", file=sys.stderr)
                sys.exit(1)
            key, val = kv.split("=", 1)
            try:
                cfg.rsi_params[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                cfg.rsi_params[key] = val
    else:
        print(f"未知参数组: {args.group}", file=sys.stderr)
        sys.exit(1)

    try:
        save_strategy(cfg)
        print(f"参数已更新")
    except Exception as e:
        print(f"保存失败: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_enable(args):
    row = fetch_one("SELECT id FROM strategies WHERE user_id = %s", (args.user,))
    if not row:
        print(f"用户 '{args.user}' 无策略", file=sys.stderr)
        sys.exit(1)
    execute("UPDATE strategies SET enabled = 1 WHERE id = %s", (row["id"],))
    print(f"用户 '{args.user}' 策略已启用")


def cmd_disable(args):
    row = fetch_one("SELECT id FROM strategies WHERE user_id = %s", (args.user,))
    if not row:
        print(f"用户 '{args.user}' 无策略", file=sys.stderr)
        sys.exit(1)
    execute("UPDATE strategies SET enabled = 0 WHERE id = %s", (row["id"],))
    print(f"用户 '{args.user}' 策略已禁用")


def cmd_apply(args):
    cfg = load_strategy(args.user)
    apply_to_config(cfg)
    from config import (
        SYMBOL, TIMEFRAME, STRATEGY_NAME, PAPER_TRADING,
        SHORT_MA, LONG_MA, MAX_POSITION_USDT,
        MIN_PROFIT_RATE, MAX_LOSS_RATE, LEVERAGE,
    )
    print(f"SYMBOL          = {SYMBOL}")
    print(f"TIMEFRAME        = {TIMEFRAME}")
    print(f"STRATEGY_NAME    = {STRATEGY_NAME}")
    print(f"PAPER_TRADING    = {PAPER_TRADING}")
    print(f"SHORT_MA         = {SHORT_MA}")
    print(f"LONG_MA          = {LONG_MA}")
    print(f"MAX_POSITION_USDT = {MAX_POSITION_USDT}")
    print(f"MIN_PROFIT_RATE  = {MIN_PROFIT_RATE}")
    print(f"MAX_LOSS_RATE    = {MAX_LOSS_RATE}")
    print(f"LEVERAGE          = {LEVERAGE}x")


# ── 实盘订单管理 ──────────────────────────────────────────────


def cmd_orders_list(args):
    orders = get_real_orders(
        symbol=args.symbol,
        status=args.status,
        side=args.side,
        paper_trading=None if args.all else 0,  # 默认仅实盘
        start=args.start,
        end=args.end,
        limit=args.limit,
    )
    if not orders:
        print("暂无订单记录")
        return

    header = f"{'ID':<6} {'时间':<20} {'交易对':<12} {'方向':<6} {'状态':<12} {'数量':<12} {'成交价':<12} {'金额(U)':<12} {'盈亏':<10} {'策略':<14} {'模式':<5}"
    print(header)
    print("-" * 125)
    for o in orders:
        oid = o["id"]
        t = o["created_at"].strftime("%m-%d %H:%M") if hasattr(o["created_at"], "strftime") else str(o["created_at"])
        sym = o["symbol"]
        side = o["side"]
        status = o["status"]
        qty = o["executed_qty"] or o["orig_qty"] or 0
        avg_p = o["avg_price"] or o["price"] or 0
        vol = o["cum_quote"] or 0
        pnl = o["pnl"]
        pnl_str = f"{pnl:+.2f}" if pnl is not None else "-"
        strat = o["strategy_name"] or "-"
        pt = "实盘" if not o["paper_trading"] else "模拟"
        print(f"{oid:<6} {t:<20} {sym:<12} {side:<6} {status:<12} {float(qty):<12.6f} {float(avg_p):<12.2f} {float(vol):<12.2f} {pnl_str:<10} {strat:<14} {pt:<5}")


def cmd_orders_view(args):
    o = get_real_order(args.order_id)
    if not o:
        print(f"订单 #{args.order_id} 不存在")
        return

    print(f"订单ID:      {o['id']}")
    print(f"币安单号:    {o['binance_order_id']}")
    print(f"客户端ID:    {o['client_order_id'] or '-'}")
    print(f"交易对:      {o['symbol']}")
    print(f"方向:        {o['side']} ({o['position_side'] or '-'})")
    print(f"类型:        {o['order_type']}")
    print(f"状态:        {o['status']}")
    print(f"价格:        {o['price'] or '-'}")
    print(f"成交均价:    {o['avg_price'] or '-'}")
    print(f"原始数量:    {o['orig_qty'] or '-'}")
    print(f"成交数量:    {o['executed_qty'] or '-'}")
    print(f"成交金额:    {o['cum_quote'] or '-'} USDT")
    print(f"杠杆:        {o['leverage'] or '-'}x")
    print(f"策略:        {o['strategy_name'] or '-'}")
    print(f"模式:        {'模拟' if o['paper_trading'] else '实盘'}")
    print(f"盈亏:        {o['pnl']:+.2f} USDT" if o['pnl'] is not None else "盈亏:        -")
    print(f"创建时间:    {o['created_at']}")
    print(f"更新时间:    {o['updated_at']}")


def cmd_orders_stats(args):
    stats = get_real_order_stats(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        paper_trading=None if args.all else 0,  # 默认仅实盘
    )
    print(f"总交易次数:  {stats['total_trades']}")
    print(f"盈利次数:    {stats['wins']}")
    print(f"亏损次数:    {stats['losses']}")
    print(f"保本次数:    {stats['breaks_even']}")
    print(f"胜率:        {stats['win_rate']}%")
    print(f"总盈亏:      {stats['total_pnl']:+.2f} USDT")
    print(f"平均盈亏:    {stats['avg_pnl']:+.2f} USDT")
    print(f"最大盈利:    {stats['max_win']:+.2f} USDT")
    print(f"最大亏损:    {stats['max_loss']:+.2f} USDT")
    print(f"总成交额:    {stats['total_volume']:.2f} USDT")


def main():
    parser = argparse.ArgumentParser(description="策略管理工具")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="列出所有策略")
    p_view = sub.add_parser("view", help="查看用户策略")
    p_view.add_argument("user", help="用户标识")

    p_set = sub.add_parser("set", help="设置用户策略")
    p_set.add_argument("user", help="用户标识")
    p_set.add_argument("--type", "-t", choices=["ma_cross", "rsi_revert"], help="策略类型")
    p_set.add_argument("--symbol", "-s", help="交易对")
    p_set.add_argument("--timeframe", "-tf", help="K线周期")
    p_set.add_argument("--paper", choices=["0", "1"], help="模拟模式 (1=模拟, 0=实盘)")
    p_set.add_argument("--name", "-n", help="策略名称")

    p_param = sub.add_parser("param", help="修改策略参数")
    p_param.add_argument("user", help="用户标识")
    p_param.add_argument("group", choices=["strategy", "risk", "rsi"], help="参数组")
    p_param.add_argument("set", nargs="+", metavar="key=value", help="参数键值对")

    p_enable = sub.add_parser("enable", help="启用用户策略")
    p_enable.add_argument("user", help="用户标识")
    p_disable = sub.add_parser("disable", help="禁用用户策略")
    p_disable.add_argument("user", help="用户标识")

    p_apply = sub.add_parser("apply", help="测试将策略应用到 config")
    p_apply.add_argument("user", default="default", nargs="?", help="用户标识")

    # ── orders 子命令集 ──
    p_orders = sub.add_parser("orders", help="实盘订单管理")
    orders_sub = p_orders.add_subparsers(dest="order_cmd")

    p_olist = orders_sub.add_parser("list", help="列出实盘订单")
    p_olist.add_argument("--symbol", "-s", help="交易对筛选")
    p_olist.add_argument("--status", choices=["NEW", "FILLED", "PARTIALLY_FILLED", "CANCELED"], help="订单状态")
    p_olist.add_argument("--side", choices=["BUY", "SELL"], help="买卖方向")
    p_olist.add_argument("--start", help="起始时间 (YYYY-MM-DD HH:MM:SS)")
    p_olist.add_argument("--end", help="截止时间")
    p_olist.add_argument("--limit", type=int, default=50, help="返回条数")
    p_olist.add_argument("--real", action="store_true", help="仅实盘")
    p_olist.add_argument("--all", action="store_true", help="包含模拟+实盘")

    p_oview = orders_sub.add_parser("view", help="查看订单详情")
    p_oview.add_argument("order_id", type=int, help="订单ID")

    p_ostats = orders_sub.add_parser("stats", help="交易统计")
    p_ostats.add_argument("--symbol", "-s", help="交易对")
    p_ostats.add_argument("--start", help="起始时间")
    p_ostats.add_argument("--end", help="截止时间")
    p_ostats.add_argument("--real", action="store_true", help="仅实盘")
    p_ostats.add_argument("--all", action="store_true", help="包含模拟+实盘")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    init_database()

    cmds = {
        "list": cmd_list,
        "view": cmd_view,
        "set": cmd_set,
        "param": cmd_param,
        "enable": cmd_enable,
        "disable": cmd_disable,
        "apply": cmd_apply,
    }

    if args.command == "orders":
        orders_cmds = {
            "list": cmd_orders_list,
            "view": cmd_orders_view,
            "stats": cmd_orders_stats,
        }
        if args.order_cmd is None:
            p_orders.print_help()
            return
        orders_cmds[args.order_cmd](args)
    else:
        cmds[args.command](args)


if __name__ == "__main__":
    main()
