#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书机器人 Webhook 服务 —— 通过飞书远程给 Claude/服务器发指令

使用方式：
  1. 在 https://open.feishu.cn 创建应用 → 开启机器人能力
  2. 事件与回调 → 订阅方式 → 回调URL: http://47.83.127.250:9090/webhook
  3. 添加事件: im.message.receive_v1
  4. 权限管理 → 添加 im:message / im:message:send_as_bot
  5. 将 FEISHU_APP_ID / FEISHU_APP_SECRET 填入 .env
  6. 运行: nohup python3 feishu_bot.py > feishu.log 2>&1 &

飞书发消息 → 本服务接收 → 执行指令 → 飞书回复
"""
import os, sys, json, logging, threading, re, time
from pathlib import Path

from dotenv import load_dotenv
import requests
from flask import Flask, request, jsonify

from bot_common import process_message

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("feishu_bot")

# ── 飞书配置 ──
APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
BOT_NAME = os.getenv("FEISHU_BOT_NAME", "交易助手")
VERIFY_TOKEN = os.getenv("FEISHU_VERIFY_TOKEN", "")

app = Flask(__name__)

# Token 缓存
_feishu_token = {"token": "", "expires": 0}


def _get_tenant_token() -> str:
    if time.time() < _feishu_token["expires"] - 60:
        return _feishu_token["token"]
    try:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": APP_ID, "app_secret": APP_SECRET},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") == 0:
            _feishu_token["token"] = data["tenant_access_token"]
            _feishu_token["expires"] = time.time() + data.get("expire", 7200)
            return _feishu_token["token"]
        else:
            logger.error(f"获取 token 失败: {data}")
            return ""
    except Exception as e:
        logger.error(f"获取 token 异常: {e}")
        return ""


def reply_message(message_id: str, content: str):
    token = _get_tenant_token()
    if not token:
        return
    try:
        resp = requests.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"content": json.dumps({"text": content}), "msg_type": "text"},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.warning(f"回复消息失败: {data}")
    except Exception as e:
        logger.warning(f"回复消息异常: {e}")


def send_message(open_id: str, text: str):
    token = _get_tenant_token()
    if not token:
        return
    try:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "receive_id": open_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.warning(f"发送消息失败: {data}")
    except Exception as e:
        logger.warning(f"发送消息异常: {e}")


# ── Webhook 路由 ──

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    logger.info(f"飞书事件: keys={list(data.keys())}")

    if data.get("type") in ("url_verification", "callback_challenge"):
        return jsonify({"challenge": data.get("challenge", "")})

    event, message_id, sender_id, msg_type, content_str = {}, "", "", "", "{}"

    if data.get("schema") == "2.0" and "header" in data:
        event = data.get("event", {})
        logger.info(f"新格式事件: {data['header'].get('event_type')}")
    elif "event" in data:
        event = data.get("event", {})
    else:
        logger.warning(f"未识别格式: {json.dumps(data, ensure_ascii=False)[:200]}")
        return jsonify({"code": 0})

    msg = event.get("message") or {}
    message_id = msg.get("message_id", "")
    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id", {}).get("open_id", "") if sender.get("sender_id") else ""
    msg_type = msg.get("message_type", "") or msg.get("msg_type", "")
    content_str = msg.get("content", "{}")

    if message_id and msg_type == "text":
        try:
            content = json.loads(content_str)
            user_text = content.get("text", "").strip()
        except:
            user_text = content_str.strip()
        user_text = re.sub(r"@_internal_|@.*?\s", "", user_text).strip()
        logger.info(f"消息: {user_text[:80]}")

        threading.Thread(
            target=_handle_message_async,
            args=(message_id, user_text),
            daemon=True,
        ).start()

    return jsonify({"code": 0})


def _handle_message_async(message_id: str, user_text: str):
    try:
        reply_message(message_id, f"🤖 收到，正在处理...\n> {user_text[:50]}")
        result = process_message(user_text)
        reply_message(message_id, result)
    except Exception as e:
        logger.error(f"异步处理异常: {e}")


@app.route("/", methods=["GET"])
def index():
    return "飞书机器人运行中 ✅"


if __name__ == "__main__":
    if not APP_ID or not APP_SECRET:
        print("=" * 60)
        print("❌ 未配置飞书凭证!")
        print("请在 .env 中添加:")
        print("  FEISHU_APP_ID=你的应用ID")
        print("  FEISHU_APP_SECRET=你的应用Secret")
        print("=" * 60)
        sys.exit(1)
    port = int(os.getenv("FEISHU_PORT", "9090"))
    print(f"🤖 飞书机器人启动 @ :{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
