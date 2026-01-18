from __future__ import annotations

import argparse
import time

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a test inbound event to the bot")
    parser.add_argument("--url", default="http://127.0.0.1:8000/wechat/event")
    parser.add_argument("--secret", default="CHANGE_ME")
    parser.add_argument("--chat-id", default="demo-chat")
    parser.add_argument("--chat-type", default="direct", choices=["direct", "group"])
    parser.add_argument("--sender-id", default="user-1")
    parser.add_argument("--text", default="hello")
    parser.add_argument("--mention", action="store_true")
    args = parser.parse_args()

    payload = {
        "chat_id": args.chat_id,
        "chat_type": args.chat_type,
        "sender_id": args.sender_id,
        "timestamp": int(time.time()),
        "text": args.text,
        "is_mention": bool(args.mention),
    }

    headers = {"X-BOT-SECRET": args.secret}
    resp = httpx.post(args.url, json=payload, headers=headers, timeout=10.0)
    print(resp.status_code, resp.text)


if __name__ == "__main__":
    main()
