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
    """快速分析日志，毫秒级返回最新行情摘要"""
    log_path = BASE_DIR / "main.log"
    if not log_path.exists():
        return "⚠️ main.log 不存在"
    try:
        lines = subprocess.run(
            ["tail", "-80", str(log_path)],
            capture_output=True, text=True, timeout=5,
        ).stdout.splitlines()
    except Exception as e:
        return f"(读取日志失败: {e})"

    indicators = {}
    signals = collections.Counter()
    for line in lines:
        m = re.search(r'信号: (⚪观望|🟢开多|🔴开空|❌)', line)
        if m:
            signals[m.group(1)] += 1
        for key in ("价格", "bb_position", "adx", "uptrend_block", "cooldown",
                     "信号", "趋势ema", "成交量", "rsi", "macd", "kdj"):
            if key not in indicators:
                m2 = re.search(rf'{re.escape(key)}: (\S+)', line)
                if m2:
                    indicators[key] = m2.group(1)

    price = indicators.get("价格", "?")
    bb_pos = indicators.get("bb_position", "?")
    adx = indicators.get("adx", "?")
    uptrend_block = indicators.get("uptrend_block", "?")
    cooldown = indicators.get("cooldown", "?")
    trend_ema = indicators.get("趋势ema", "?")
    rsi_val = indicators.get("rsi", "?")
    macd_val = indicators.get("macd", "?")
    kdj_val = indicators.get("kdj", "?")

    if uptrend_block == "1":
        trend = "多头限制(不开多)"
    elif uptrend_block == "0" and adx != "?" and float(adx) < 25:
        trend = "震荡/低波动"
    else:
        trend = "正常"

    last_signal = ""
    for line in reversed(lines):
        m = re.search(r'信号: (⚪观望|🟢开多|🔴开空|❌)', line)
        if m:
            last_signal = m.group(1)
            break

    suggest = "等待机会"
    if last_signal == "🟢开多":
        suggest = "🟢 可开多"
    elif last_signal == "🔴开空":
        suggest = "🔴 可开空"
    elif last_signal == "❌":
        suggest = "❌ 禁止开仓"

    parts = [
        f"📊 实时行情分析",
        f"━━━━━━━━━━━━━━━",
        f"价格: {price}",
        f"信号: {last_signal}",
        f"趋势: {trend}",
        f"BB位置: {bb_pos} | ADX: {adx}",
    ]
    if rsi_val != "?":
        parts.append(f"RSI: {rsi_val}")
    if macd_val != "?":
        parts.append(f"MACD: {macd_val}")
    if kdj_val != "?":
        parts.append(f"KDJ: {kdj_val}")
    parts.extend([
        f"趋势EMA: {trend_ema}",
        f"冷却: {cooldown}",
        f"━━━━━━━━━━━━━━━",
        f"💡 建议: {suggest}",
    ])
    if signals:
        parts.append(f"近期信号: {dict(signals)}")
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


CMDS = {
    "status":   lambda: run_cmd(["ps", "aux", "|", "grep", "main.py"]),
    "ps":       lambda: run_cmd(["ps", "aux", "|", "grep", "main.py"]),
    "进程":     lambda: run_cmd(["ps", "aux", "|", "grep", "main.py"]),

    "log":      lambda: run_cmd(["tail", "-20", str(BASE_DIR / "main.log")]),
    "日志":     lambda: run_cmd(["tail", "-20", str(BASE_DIR / "main.log")]),

    "回测":     lambda: run_cmd([sys.executable, "backtest_10d.py"], timeout=180),
    "backtest": lambda: run_cmd([sys.executable, "backtest_10d.py"], timeout=180),

    "持仓":     lambda: "⚠️ 当前为模拟交易(100x)，查看 main.log 获取信号状态",

    "restart":  lambda: (
        run_cmd(["kill"] + [str(p) for p in _get_bot_pids()]) + "\n" + _start_bots()
    ),
    "重启":     lambda: (
        run_cmd(["kill"] + [str(p) for p in _get_bot_pids()]) + "\n" + _start_bots()
    ),
}

FUZZY_CMDS = {
    "行情": quick_analysis, "分析": quick_analysis, "适合开单": quick_analysis,
    "开仓": quick_analysis, "信号": quick_analysis, "当前": quick_analysis,
    "大盘": quick_analysis, "盘面": quick_analysis, "怎么样": quick_analysis,
    "怎样": quick_analysis, "如何": quick_analysis, "market": quick_analysis,
    "分析下": quick_analysis, "看看": quick_analysis, "什么情况": quick_analysis,
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
