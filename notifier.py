# -*- coding: utf-8 -*-
"""Telegram 消息推送"""
import asyncio
import logging
from telegram import Bot
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class Notifier:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)

    async def _send(self, text: str):
        if not self.enabled:
            return
        try:
            bot = Bot(self.token)
            await bot.send_message(self.chat_id, text, parse_mode="HTML")
        except Exception as e:
            logging.getLogger(__name__).warning(f"Telegram推送失败: {e}")

    def send(self, text: str):
        if self.enabled:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._send(text))
            except RuntimeError:
                asyncio.run(self._send(text))

    def send_sync(self, text: str):
        """同步发送（适用于非异步上下文）"""
        if self.enabled:
            asyncio.run(self._send(text))
