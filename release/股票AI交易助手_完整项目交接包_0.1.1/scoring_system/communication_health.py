from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from scoring_system.env_loader import load_project_env


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "push_channels.json"
CONFIG_EXAMPLE = ROOT / "config" / "push_channels.example.json"
REPORT_DIR = ROOT / "reports" / "communication"
REPORT_JSON = REPORT_DIR / "latest_communication_health.json"
REPORT_MD = REPORT_DIR / "latest_communication_health.md"


def load_config() -> dict[str, Any]:
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def env_value(name: str) -> str:
    return os.environ.get(name, "")


def channel_value(cfg: dict[str, Any], name: str) -> str:
    item = cfg.get(name, {})
    env_name = item.get("webhook_env", "")
    if env_name:
        return env_value(env_name) or item.get("webhook_url", "")
    return item.get("webhook_url", "")


def post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return {"ok": True, "status": getattr(resp, "status", None), "response": raw[:500]}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:220]}"}


def probe_channel(name: str, url: str) -> dict[str, Any]:
    if not url:
        return {"configured": False, "ok": False, "sent": False, "error": "missing_webhook"}
    if name == "wecom":
        body = {"msgtype": "text", "text": {"content": "communication health check"}}
    else:
        body = {"msg_type": "text", "content": {"text": "communication health check"}}
    result = post_json(url, body)
    result.update({"configured": True, "sent": bool(result.get("ok"))})
    return result


def build_report() -> dict[str, Any]:
    load_project_env()
    cfg = load_config()
    telegram = cfg.get("telegram", {})
    llm = cfg.get("llm", {})
    feishu = channel_value(cfg, "feishu")
    wecom = channel_value(cfg, "wecom")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks": {
            "telegram": {
                "configured": bool(telegram.get("enabled") and telegram.get("bot_token")),
                "bot_token_present": bool(env_value(telegram.get("bot_token_env", "TELEGRAM_BOT_TOKEN")) or telegram.get("bot_token")),
                "allowed_chat_ids": list(telegram.get("allowed_chat_ids") or []),
            },
            "llm": {
                "configured": bool(llm.get("enabled") and llm.get("api_key")),
                "provider": llm.get("provider", ""),
                "model": llm.get("model", ""),
                "api_key_present": bool(env_value(llm.get("api_key_env", "OPENAI_API_KEY")) or llm.get("api_key")),
            },
            "feishu": probe_channel("feishu", feishu),
            "wecom": probe_channel("wecom", wecom),
        },
    }
    return report


def write_report(report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Communication Health Check",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Telegram: {'OK' if report['checks']['telegram']['configured'] else 'missing'}",
        f"- LLM: {'OK' if report['checks']['llm']['configured'] else 'missing'}",
        f"- Feishu: {'OK' if report['checks']['feishu'].get('sent') else 'missing'}",
        f"- WeCom: {'OK' if report['checks']['wecom'].get('sent') else 'missing'}",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    report = build_report()
    write_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
