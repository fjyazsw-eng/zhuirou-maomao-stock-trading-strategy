from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.push_gateway import send as send_feishu
from scoring_system.telegram_gateway import KNOWN_CHATS_PATH, api_call, bot_token, telegram_config

REPORTS = ROOT / "reports"
PUSH = REPORTS / "push"


def read_text(path: Path, limit: int) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def telegram_send_message(token: str, chat_id: str, text: str) -> dict[str, Any]:
    return api_call(token, "sendMessage", {"chat_id": chat_id, "text": text})


def latest_chat_id(token: str) -> str:
    data = api_call(token, "getUpdates", {"limit": 20, "timeout": 1})
    updates = data.get("result", [])
    for item in reversed(updates):
        msg = item.get("message") or item.get("edited_message") or {}
        chat = msg.get("chat", {})
        if chat.get("id") is not None:
            return str(chat["id"])
    return ""


def known_chat_ids() -> list[str]:
    if not KNOWN_CHATS_PATH.exists():
        return []
    try:
        payload = json.loads(KNOWN_CHATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [str(x) for x in payload.get("chat_ids", []) if str(x).strip()]


def build_message(title: str, report_path: Path, text: str) -> str:
    return "\n".join(
        [
            title,
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"报告文件：{report_path}",
            "",
            text,
            "",
            "边界：封闭测试结果只用于模型复盘，不构成交易指令。",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Push a report file to Feishu and Telegram")
    parser.add_argument("--file", required=True)
    parser.add_argument("--title", default="股票AI量化助手报告")
    parser.add_argument("--limit", type=int, default=3200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    report_path = Path(args.file)
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    text = read_text(report_path, args.limit)
    message = build_message(args.title, report_path, text)

    results: dict[str, Any] = {"file": str(report_path), "title": args.title, "dry_run": args.dry_run}
    results["feishu"] = send_feishu("feishu", message[:3500], dry_run=args.dry_run)

    tg_cfg = telegram_config()
    token = bot_token(tg_cfg)
    tg_result: dict[str, Any] = {"configured": bool(token), "sent": False}
    if token and not args.dry_run:
        chat_ids = [str(x) for x in (tg_cfg.get("allowed_chat_ids") or [])]
        if not chat_ids:
            chat_ids = known_chat_ids()
        if not chat_ids:
            cid = latest_chat_id(token)
            chat_ids = [cid] if cid else []
        tg_result["chat_ids"] = chat_ids
        sent = []
        for cid in chat_ids:
            if not cid:
                continue
            sent.append(telegram_send_message(token, cid, message[:3900]))
        tg_result["sent"] = bool(sent)
        tg_result["responses"] = sent
    results["telegram"] = tg_result

    PUSH.mkdir(parents=True, exist_ok=True)
    out = PUSH / f"report_push_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**results, "log": str(out)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
