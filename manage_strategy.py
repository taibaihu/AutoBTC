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
from db_manager import execute, fetch_one, init_database

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.WARNING)
logger = logging.getLogger(__name__)


def cmd_list(args):
    strategies = list_strategies(enabled_only=False)
    if not strategies:
        print("暂无策略")
        return

    print(f"{'ID':<4} {'用户':<16} {'类型':<14} {'交易对':<12} {'周期':<6} {'模拟':<6} {'状态':<6} {'名称'}")
    print("-" * 90)
    for s in strategies:
        paper = "模拟" if s.paper_trading else "实盘"
        status = "启用" if s.enabled else "禁用"
        print(f"{s.id:<4} {s.user_id:<16} {s.strategy_type:<14} {s.symbol:<12} {s.timeframe:<6} {paper:<6} {status:<6} {s.name}")


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
        "risk_params": cfg.risk_params,
        "rsi_params": cfg.rsi_params,
    }, ensure_ascii=False, indent=2))


def cmd_set(args):
    cfg = load_strategy(args.user)

    if args.type:
        cfg.strategy_type = args.type
        # 根据策略类型设置默认参数
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
        cfg.paper_trading = args.paper
    if args.name:
        cfg.name = args.name

    try:
        save_strategy(cfg)
        print(f"策略已保存 (user={cfg.user_id}, type={cfg.strategy_type})")
    except Exception as e:
        print(f"保存失败: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_param(args):
    """修改策略的 JSON 参数"""
    cfg = load_strategy(args.user)

    # 确定目标字典
    target_map = {
        "strategy": cfg.params,
        "risk": cfg.risk_params,
        "rsi": cfg.rsi_params,
    }
    target = target_map.get(args.group)
    if target is None:
        print(f"未知参数组: {args.group}，可选: strategy, risk, rsi", file=sys.stderr)
        sys.exit(1)

    # 解析 key=value
    for kv in args.set:
        if "=" not in kv:
            print(f"格式错误: '{kv}'，需要 key=value 格式", file=sys.stderr)
            sys.exit(1)
        key, val = kv.split("=", 1)
        # 尝试解析 JSON 类型
        try:
            parsed = json.loads(val)
            target[key] = parsed
        except (json.JSONDecodeError, TypeError):
            target[key] = val  # 保持字符串

    try:
        save_strategy(cfg)
        print(f"参数已更新: {', '.join(args.set)}")
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
    """测试将用户策略应用到 config 的效果"""
    cfg = load_strategy(args.user)
    apply_to_config(cfg)
    from config import (
        SYMBOL, TIMEFRAME, STRATEGY_NAME, PAPER_TRADING,
        SHORT_MA, LONG_MA, MAX_POSITION_USDT,
        MIN_PROFIT_RATE, MAX_LOSS_RATE,
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


def main():
    parser = argparse.ArgumentParser(description="策略管理工具")
    sub = parser.add_subparsers(dest="command")

    # list
    p_list = sub.add_parser("list", help="列出所有策略")

    # view
    p_view = sub.add_parser("view", help="查看用户策略")
    p_view.add_argument("user", help="用户标识")

    # set
    p_set = sub.add_parser("set", help="设置用户策略")
    p_set.add_argument("user", help="用户标识")
    p_set.add_argument("--type", "-t", choices=["ma_cross", "rsi_revert"], help="策略类型")
    p_set.add_argument("--symbol", "-s", help="交易对")
    p_set.add_argument("--timeframe", "-tf", help="K线周期")
    p_set.add_argument("--paper", choices=["0", "1"], help="模拟模式 (1=模拟, 0=实盘)")
    p_set.add_argument("--name", "-n", help="策略名称")

    # param
    p_param = sub.add_parser("param", help="修改策略参数 (JSON)")
    p_param.add_argument("user", help="用户标识")
    p_param.add_argument("group", choices=["strategy", "risk", "rsi"], help="参数组")
    p_param.add_argument("set", nargs="+", metavar="key=value", help="参数键值对")

    # enable / disable
    p_enable = sub.add_parser("enable", help="启用用户策略")
    p_enable.add_argument("user", help="用户标识")
    p_disable = sub.add_parser("disable", help="禁用用户策略")
    p_disable.add_argument("user", help="用户标识")

    # apply (test)
    p_apply = sub.add_parser("apply", help="测试将策略应用到 config")
    p_apply.add_argument("user", default="default", nargs="?", help="用户标识")

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
    cmds[args.command](args)


if __name__ == "__main__":
    main()
