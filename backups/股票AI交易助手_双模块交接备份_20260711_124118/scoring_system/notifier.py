from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
PUSH_DIR = REPORTS / "push"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_brief(as_of: str) -> str:
    main = read_text(REPORTS / "latest_market_decision_report.md")
    enhanced = read_text(REPORTS / "enhanced" / f"event_funds_state_{as_of}.md")
    alerts = read_text(REPORTS / "alerts" / f"sector_alerts_{as_of}.md")
    lines = [
        f"# 股票AI量化助手简报 {as_of}",
        "",
        "## 总览",
        main[:1800] if main else "- 总报告缺失",
        "",
        "## 事件面与资金代理",
        enhanced[:1200] if enhanced else "- 事件资金报告缺失",
        "",
        "## 预警",
        alerts[:1200] if alerts else "- 预警报告缺失",
        "",
        "## 使用边界",
        "- 这是模型辅助分析，不替代最终交易决策。",
        "- 若数据日期不是最新完整交易日，应先更新数据再判断。",
    ]
    return "\n".join(lines)


def send_webhook(url: str, text: str, channel: str) -> dict[str, Any]:
    if channel == "feishu":
        body = {"msg_type": "text", "content": {"text": text}}
    else:
        body = {"msgtype": "text", "text": {"content": text}}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return {"ok": True, "status": getattr(resp, "status", None), "response": raw[:500]}


def write_preview(as_of: str, brief: str, result: dict[str, Any]) -> dict[str, str]:
    PUSH_DIR.mkdir(parents=True, exist_ok=True)
    md = PUSH_DIR / f"push_brief_{as_of}.md"
    js = PUSH_DIR / f"push_brief_{as_of}.json"
    md.write_text(brief, encoding="utf-8")
    js.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = PUSH_DIR / "latest_push_preview.md"
    latest.write_text(brief, encoding="utf-8")
    return {"markdown": str(md), "json": str(js), "latest": str(latest)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or send daily stock assistant brief")
    parser.add_argument("--as-of", default="20260702")
    parser.add_argument("--channel", choices=["preview", "feishu", "wecom"], default="preview")
    args = parser.parse_args(argv)

    brief = build_brief(args.as_of)
    result: dict[str, Any] = {"as_of_date": args.as_of, "channel": args.channel, "sent": False}
    if args.channel == "feishu":
        url = os.environ.get("FEISHU_WEBHOOK", "")
        result["webhook_configured"] = bool(url)
        if url:
            result.update(send_webhook(url, brief[:3500], "feishu"))
            result["sent"] = True
    elif args.channel == "wecom":
        url = os.environ.get("WECOM_WEBHOOK", "")
        result["webhook_configured"] = bool(url)
        if url:
            result.update(send_webhook(url, brief[:3500], "wecom"))
            result["sent"] = True
    else:
        result["webhook_configured"] = False
    paths = write_preview(args.as_of, brief, result)
    print(json.dumps({**result, **paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
