# -*- coding: utf-8 -*-
"""
FQYWX 注册码 Telegram 机器人（GitHub Actions 版）
每次被 Actions 唤醒时轮询一次 getUpdates，处理 /gen 命令并回码，然后退出。

环境变量（在 GitHub 仓库 Secrets 里配置）：
    TG_TOKEN   : BotFather 给的机器人 token（必填）
    ADMIN_ID   : 允许发码的 Telegram 数字 ID，多个用逗号/空格分隔（必填才可发码）
    REG_SECRET : 与模块一致的密钥，默认 "Fq!WxLoc#2026@SecretKey"

命令：
    /help            查看用法
    /id              查看自己的数字 ID / Chat ID（用于配置 ADMIN_ID）
    /gen <天数> [内容]  生成注册码；天数 0 = 永久；内容可选（≤255字节，仅作标识）
"""
import hashlib
import json
import os
import struct
import sys
import time
import urllib.request

SECRET = (os.environ.get("REG_SECRET") or "Fq!WxLoc#2026@SecretKey")
TOKEN = (os.environ.get("TG_TOKEN") or "").strip()

_raw_admin = (os.environ.get("ADMIN_ID") or "").replace(",", " ").replace(";", " ")
ADMIN_IDS = {int(x) for x in _raw_admin.split() if x.strip().isdigit()}

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

HELP = (
    "用法：\n"
    "/gen <天数> [内容] — 生成注册码\n"
    "  · 天数 0 = 永久；>0 = 该天数后到期\n"
    "  · 内容可选（≤255字节，最大255），仅作标识不解析\n"
    "  例：/gen 30        （30天随机码）\n"
    "  例：/gen 0 订单A01 （永久，内容=订单A01）\n"
    "/id — 查看自己的数字 ID\n"
    "/help — 本说明"
)


def build_code(payload: bytes, days: int = 0) -> str:
    if len(payload) > 255:
        raise ValueError("payload 过长(>255)")
    exp = int(time.time()) + int(days) * 86400 if days and days > 0 else 0
    data = bytes([1]) + struct.pack(">I", exp) + bytes([len(payload)]) + payload
    sig = hashlib.md5(SECRET.encode("utf-8") + data).digest()[:4]
    full = data + sig
    h = full.hex().upper()
    return "-".join(h[i:i + 4] for i in range(0, len(h), 4))


def api(method: str, params=None):
    url = "https://api.telegram.org/bot%s/%s" % (TOKEN, method)
    data = json.dumps(params).encode("utf-8") if params is not None else None
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def reply(chat_id, text: str):
    api("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})


def load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"offset": 0, "heartbeat": ""}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def handle(u: dict):
    m = u.get("message")
    if not m:
        return
    chat_id = m["chat"]["id"]
    uid = m["from"]["id"]
    text = (m.get("text") or "").strip()
    if not text.startswith("/"):
        return
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]

    if cmd in ("/start", "/help"):
        reply(chat_id, HELP)
    elif cmd in ("/id", "/whoami"):
        reply(chat_id, "你的数字 ID: %d\nChat ID: %d" % (uid, chat_id))
    elif cmd == "/gen":
        if not ADMIN_IDS:
            reply(chat_id, "未配置 ADMIN_ID，已禁用发码。请先用 /id 查到你的 ID 并配置后重试。")
            return
        if uid not in ADMIN_IDS:
            reply(chat_id, "无权限：仅管理员可发码。")
            return
        days = 0
        payload = os.urandom(4)
        if args:
            try:
                days = int(args[0])
            except ValueError:
                reply(chat_id, "天数须为整数，例如：/gen 30")
                return
        if len(args) >= 2:
            payload = " ".join(args[1:]).encode("utf-8")
            if len(payload) > 255:
                reply(chat_id, "自定义内容过长（>255字节），请缩短。")
                return
        code = build_code(payload, days)
        exp_txt = "永久" if days <= 0 else "%d 天" % days
        reply(chat_id, "注册码（时效：%s）：\n%s" % (exp_txt, code))
    else:
        reply(chat_id, "未知命令。发送 /help 查看用法。")


def main():
    if not TOKEN:
        print("[bot] 缺少 TG_TOKEN 环境变量")
        sys.exit(1)

    state = load_state()
    offset = int(state.get("offset", 0) or 0)

    params = {"timeout": 0, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset

    try:
        resp = api("getUpdates", params)
    except Exception as e:
        print("[bot] getUpdates 失败: %r" % (e,))
        sys.exit(1)

    if not resp.get("ok"):
        print("[bot] Telegram 返回错误: %s" % json.dumps(resp, ensure_ascii=False))
        sys.exit(1)

    updates = resp.get("result", [])
    print("[bot] 收到 %d 条更新" % len(updates))
    replied = 0
    for u in updates:
        offset = max(offset, int(u["update_id"]) + 1)
        try:
            handle(u)
            replied += 1
        except Exception as e:
            print("[bot] 处理更新出错: %r" % (e,))
    print("[bot] 处理 %d 条" % replied)

    new_state = {"offset": offset, "heartbeat": time.strftime("%Y-%m-%d", time.gmtime())}
    if new_state != state:
        save_state(new_state)
        print("[bot] 已更新 state.json")
    else:
        print("[bot] state 无变化")


if __name__ == "__main__":
    main()
