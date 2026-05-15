#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书 / Telegram 机器人共享逻辑"""
import os, sys, logging, subprocess, re, time, collections
from pathlib import Path

logger = logging.getLogger("bot_common")

BASE_DIR = Path(__file__).parent
CLAUDE_CMD = os.getenv("CLAUDE_CMD", "claude")


def run_cmd(cmd: list, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=BASE_DIR)
        out = r.stdout.strip() or r.stderr.strip()
        return out or "(无输出)"
    except subprocess.TimeoutExpired:
        return f"(命令超时 {timeout}s)"
    except Exception as e:
        return f"(执行错误: {e})"


def quick_analysis() -> str:
    """快速分析日志，读取两个 bot 的最新行情"""
    logs = [("main.default.log", "LONG"), ("main.short.log", "SHORT")]
    parts = [f"📊 快速行情", f"━━━━━━━━━━━━━━━"]
    for log_name, direction in logs:
        log_path = BASE_DIR / log_name
        if not log_path.exists():
            parts.append(f"[{direction}] ⚠️ {log_name} 不存在")
            continue
        try:
            raw = subprocess.run(
                ["tail", "-40", str(log_path)],
                capture_output=True, text=True, timeout=5,
            ).stdout
        except Exception as e:
            parts.append(f"[{direction}] 读取失败: {e}")
            continue

        price = "?"
        signal = "?"
        for line in reversed(raw.splitlines()):
            m = re.search(r'📊 价格: (\d+)', line)
            if m and price == "?":
                price = m.group(1)
            m = re.search(r'信号: (⚪观望|🟢|🔴)', line)
            if m and signal == "?":
                signal = m.group(1)

        pos = "无持仓"
        for line in reversed(raw.splitlines()):
            m = re.search(r'📌 \[(short|default)\]\s+(.+)', line)
            if m:
                pos = m.group(2).strip()
                break

        # extract last indicator line
        ind = collections.Counter()
        for line in raw.splitlines():
            m = re.search(
                r'📈.*?B:(\S+).*?U:(\S+).*?M:(\S+).*?L:(\S+).*?MACD:(\S+).*?K:(\S+) D:(\S+) J:(\S+)',
                line,
            )
            if m:
                ind = {
                    "r15": m.group(1), "bbu": m.group(2),
                    "bbm": m.group(3), "bbl": m.group(4),
                    "macd": m.group(5), "k": m.group(6),
                    "d": m.group(7), "j": m.group(8),
                }
        bb_info = f"U:{ind.get('bbu','?')} M:{ind.get('bbm','?')} L:{ind.get('bbl','?')}" if ind else ""
        parts.append(f"[{direction}] {'🔴' if signal=='🔴' else '🟢' if signal=='🟢' else '⚪'}")
        parts.append(f"  价格:{price} 信号:{signal} | {bb_info}")
        parts.append(f"  RSI15:{ind.get('r15','?')} KDJ:{ind.get('k','?')}/{ind.get('d','?')}/{ind.get('j','?')}")
        parts.append(f"  持仓: {pos}")
    return "\n".join(parts)


def call_claude(instruction: str) -> str:
    try:
        r = subprocess.run(
            [CLAUDE_CMD, "-p", instruction, "--permission-mode", "dontAsk"],
            capture_output=True, text=True, timeout=120,
            cwd=BASE_DIR,
            env={**os.environ, "CLAUDE_CODE_HEADLESS": "1"},
        )
        out = r.stdout.strip() or r.stderr.strip()
        if not out:
            return "(Claude 无返回)"
        if len(out) > 3000:
            out = out[:3000] + "\n...(截断)"
        return out
    except FileNotFoundError:
        return "(错误: 未找到 claude 命令)"
    except subprocess.TimeoutExpired:
        return "(Claude 处理超时 120s)"
    except Exception as e:
        return f"(Claude 调用异常: {e})"


def _get_bot_pids() -> list:
    try:
        r = subprocess.run(
            ["pgrep", "-f", "main.py --user"],
            capture_output=True, text=True, timeout=5,
        )
        return [int(p) for p in r.stdout.strip().split() if p]
    except:
        return []


def _start_bots() -> str:
    for user in ("default", "short"):
        subprocess.Popen(
            [sys.executable, "main.py", "--user", user],
            cwd=BASE_DIR,
            stdout=open(BASE_DIR / "main.log", "a"),
            stderr=subprocess.STDOUT,
        )
    time.sleep(3)
    pids = _get_bot_pids()
    if len(pids) >= 2:
        return f"✅ 已重启成功 (PID: {pids})"
    return f"⚠️ 启动中...当前进程: {pids}"



def _query_local_trades() -> str:
    """查询本地订单（开平一条记录）"""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from db_manager import get_local_trades, get_local_trade_stats
        stats = get_local_trade_stats()
        trades = get_local_trades(limit=10, status="\u6301\u4ed3\u4e2d")
        lines = [
            f"\U0001f4cb \u672c\u5730\u8ba2\u5355 ({stats['open_trades']}\u6301\u4ed3 / {stats['total_trades']}\u603b\u8ba1)",
            f"  \u603b\u76c8\u4e8f: {stats['total_pnl']:+.2f} | \u80dc\u7387: {stats['win_rate']}%",
            "\u2501" * 15,
        ]
        for t in trades:
            d = "\U0001f7e2\u591a" if t["direction"] == "LONG" else "\U0001f534\u7a7a"
            op = float(t["open_price"] or 0)
            q = float(t["quantity"] or 0)
            lines.append(f"#{t['id']} {d} \u5f00:{op:.0f} \u91cf:{q:.4f} | {t['status']}")
        if not trades:
            lines.append("\u6682\u65e0\u6301\u4ed3\u4e2d\u7684\u8ba2\u5355")
        return "\n".join(lines)
    except Exception as e:
        return f"(\u67e5\u8be2\u5931\u8d25: {e})"


CMDS = {
    "status":   lambda: run_cmd(["ps", "aux", "|", "grep", "main.py"]),
    "ps":       lambda: run_cmd(["ps", "aux", "|", "grep", "main.py"]),
    "进程":     lambda: run_cmd(["ps", "aux", "|", "grep", "main.py"]),

    "log":      lambda: run_cmd(["tail", "-20", str(BASE_DIR / "main.log")]),
    "日志":     lambda: run_cmd(["tail", "-20", str(BASE_DIR / "main.log")]),

    "回测":     lambda: run_cmd([sys.executable, "backtest_10d.py"], timeout=180),
    "backtest": lambda: run_cmd([sys.executable, "backtest_10d.py"], timeout=180),

    "持仓":     lambda: _query_local_trades(),
    "本地单":   lambda: _query_local_trades(),

    "restart":  lambda: (
        run_cmd(["kill"] + [str(p) for p in _get_bot_pids()]) + "\n" + _start_bots()
    ),
    "重启":     lambda: (
        run_cmd(["kill"] + [str(p) for p in _get_bot_pids()]) + "\n" + _start_bots()
    ),
}

FUZZY_CMDS = {
    "行情": quick_analysis, "适合开单": quick_analysis,
    "开仓": quick_analysis, "信号": quick_analysis,
    "大盘": quick_analysis, "盘面": quick_analysis,
    "市场": quick_analysis, "market": quick_analysis,
}


def process_message(text: str) -> str:
    text = text.strip()

    for keyword, handler in CMDS.items():
        if text == keyword:
            logger.info(f"执行快捷指令: {text}")
            return handler()

    for keyword, handler in FUZZY_CMDS.items():
        if keyword in text:
            logger.info(f"模糊匹配 [{keyword}] → 快速分析")
            return handler()

    logger.info(f"调用 Claude 处理指令: {text}")
    return call_claude(f"你是服务器上的 AI 助手。请处理以下指令（交易机器人安装在 /root/Exchange）：\n\n{text}")
