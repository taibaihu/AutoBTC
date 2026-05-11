#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 机器人 —— 通过 Telegram 远程给服务器发指令

使用方式：
  1. 在 @BotFather 创建机器人，拿到 token
  2. 将 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 填入 .env
  3. 运行: nohup python3 telegram_bot.py > telegram.log 2>&1 &

支持指令：
  - 行情/分析/开仓/信号 → 快速分析 main.log
  - 回测/backtest       → 运行 10 天回测
  - 重启/restart        → 重启交易机器人
  - 日志/log/进程/status → 查看状态
  - 其他任意文本         → 调用 Claude CLI 处理
"""
import os, sys, logging, asyncio

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters

from bot_common import process_message

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("telegram_bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


async def handle_message(update: Update, context):
    if not update.message or not update.message.text:
        return

    chat_id = str(update.effective_chat.id)
    if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
        await update.message.reply_text("⛔ 未授权的用户")
        logger.warning(f"拒绝未授权用户: {chat_id}")
        return

    text = update.message.text.strip()
    logger.info(f"收到消息: {text[:80]}")

    # 立即回复 "处理中"，避免 Telegram 超时
    await update.message.reply_text(f"🤖 收到，正在处理...\n> {text[:50]}")

    try:
        result = process_message(text)
        # Telegram 消息上限约 4096 字符
        if len(result) > 4000:
            result = result[:4000] + "\n\n...(截断)"
        await update.message.reply_text(result)
    except Exception as e:
        logger.error(f"处理消息异常: {e}")
        await update.message.reply_text(f"❌ 处理出错: {e}")


async def error_handler(update: Update, context):
    logger.error(f"Telegram 异常: {context.error}")


def main():
    if not TOKEN:
        print("=" * 60)
        print("❌ 未配置 Telegram Token!")
        print("请在 .env 中添加:")
        print("  TELEGRAM_BOT_TOKEN=你的Bot Token")
        print("  TELEGRAM_CHAT_ID=你的Chat ID")
        print("=" * 60)
        sys.exit(1)

    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    chat_info = f" (仅限 chat_id={ALLOWED_CHAT_ID})" if ALLOWED_CHAT_ID else " (无限制)"
    print(f"🤖 Telegram 机器人启动中...{chat_info}")
    logger.info(f"Telegram 机器人启动中...{chat_info}")

    app.run_polling(allowed_updates=Update.MESSAGE)


if __name__ == "__main__":
    main()
