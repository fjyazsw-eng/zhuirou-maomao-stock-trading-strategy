from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "push_channels.json"
CONFIG_EXAMPLE = ROOT / "config" / "push_channels.example.json"
REPORTS = ROOT / "reports"
PUSH_DIR = REPORTS / "push"


def read_text(path: Path, limit: int = 3200) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def clean_user_text(text: str) -> str:
    replacements = {
        "WAIT_PULLBACK_CORE": "等待回踩核心候选",
        "WAIT_CONFIRM": "等待确认",
        "WEAK_STRUCTURE": "结构偏弱",
        "READY_CORE": "核心机会",
        "READY_SECONDARY": "次级机会",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def extract_lines(text: str, prefixes: list[str], limit: int) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if any(line.startswith(prefix) for prefix in prefixes):
            lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def kline_summary(as_of: str) -> list[str]:
    path = REPORTS / "kline" / f"kline_analysis_{as_of}.json"
    if not path.exists():
        return ["K线报告缺失"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["K线报告无法解析"]
    rows = payload.get("items", [])[:8]
    result = [
        "说明：低吸分 70 以上才算承接较强；50-69 只观察；50 以下不适合空仓直接低吸。",
    ]
    for row in rows:
        score = row.get("low_absorb_score")
        state = str(row.get("state", ""))
        support = str(row.get("support_state", "承接待观察"))
        if isinstance(score, (int, float)) and score >= 70:
            action = "有承接，可重点观察低吸条件"
        elif isinstance(score, (int, float)) and score >= 50:
            action = "有修复迹象，先观察不急"
        elif "趋势延续" in state:
            action = "趋势还在，但不适合追高，等回踩"
        else:
            action = "承接不够，空仓不急着低吸"
        result.append(f"- {row.get('name')}：{action}；{support}；低吸分 {score if score is not None else '-'}")
    return result or ["K线样本为空"]


def load_config() -> dict[str, Any]:
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def channel_url(channel: str, cfg: dict[str, Any]) -> str:
    item = cfg.get(channel, {})
    env_name = item.get("webhook_env", "")
    env_url = os.environ.get(env_name, "") if env_name else ""
    return env_url or item.get("webhook_url", "")


def feishu_secret(cfg: dict[str, Any]) -> str:
    item = cfg.get("feishu", {})
    env_name = item.get("secret_env", "")
    return (os.environ.get(env_name, "") if env_name else "") or item.get("secret", "")


def feishu_sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def feishu_payload(text: str, secret: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {"msg_type": "text", "content": {"text": text}}
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = feishu_sign(secret, timestamp)
    return payload


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return {"ok": True, "status": getattr(resp, "status", None), "response": raw[:1000]}


def build_daily_brief(as_of: str) -> str:
    main = clean_user_text(read_text(REPORTS / "latest_market_decision_report.md", 6000))
    enhanced = clean_user_text(read_text(REPORTS / "enhanced" / f"event_funds_state_{as_of}.md", 3000))
    alerts = clean_user_text(read_text(REPORTS / "alerts" / f"sector_alerts_{as_of}.md", 3000))
    weather = extract_lines(main, ["- 大盘天气评分", "- 上涨家数", "- 下跌家数", "- 今日成交"], 4)
    sectors = extract_lines(main, ["- 物流", "- 化妆品", "- 化学制药", "- 广告营销", "- 饲料"], 5)
    stocks = extract_lines(main, ["- 潮宏基", "- 拉芳家化", "- 百合花", "- 科伦药业", "- 温氏股份"], 5)
    market_proxy = extract_lines(enhanced, ["- 今日成交额", "- 较前一日成交额变化", "- 上涨家数", "- 下跌家数", "- 放量下跌数"], 5)
    alert_lines = extract_lines(alerts, ["## 元件", "## 电子化学品", "## 半导体", "## 计算机设备", "- 等级：HIGH"], 8)
    parts = [
        f"股票AI量化助手简报 {as_of}",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "【天气】",
        *(weather or ["总报告缺失"]),
        "",
        "【强势街区】",
        *(sectors or ["优势板块缺失"]),
        "",
        "【候选店铺】",
        *(stocks or ["个股候选缺失"]),
        "",
        "【资金代理】",
        *(market_proxy or ["资金代理报告缺失"]),
        "",
        "【退潮预警】",
        *(alert_lines or ["暂无高风险预警"]),
        "",
        "【K线承接】",
        *kline_summary(as_of),
        "",
        "边界：仅作模型辅助分析，不自动交易，不替代最终决策。",
    ]
    return "\n".join(parts)


def build_test_message() -> str:
    return "\n".join(
        [
            "股票AI量化助手端口测试",
            f"发送时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "如果你能看到这条消息，说明飞书 webhook 通道已连通。",
        ]
    )


def build_question_message(question: str) -> str:
    answer_path = REPORTS / "conversation" / "latest_answer.md"
    answer = read_text(answer_path, 2600)
    return "\n".join(
        [
            "股票AI量化助手问答结果",
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"问题：{question or '未填写'}",
            "",
            "提问参考：空仓就说资金和周期；持仓就说代码、数量、成本；单票就说股票名或代码；板块就说板块名和你想问的方向。",
            "",
            answer or "问答结果缺失，请先运行本地问答入口。",
            "",
            "分数参考：大盘 70+ 可主动找机会；板块 75+ 才算强；个股执行 78+ 才算可参与；K线低吸 70+ 才算承接强。",
            "",
            "边界：仅作辅助分析，不自动交易。",
        ]
    )


def send(channel: str, text: str, dry_run: bool = False) -> dict[str, Any]:
    cfg = load_config()
    url = channel_url(channel, cfg)
    result: dict[str, Any] = {
        "channel": channel,
        "configured": bool(url),
        "dry_run": dry_run,
        "sent": False,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if not url:
        result["error"] = f"{channel} webhook 未配置"
        return result
    payload = feishu_payload(text, feishu_secret(cfg))
    result["payload_preview"] = payload
    if dry_run:
        return result
    try:
        result.update(post_json(url, payload))
        result["sent"] = True
    except Exception as exc:
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def write_result(kind: str, text: str, result: dict[str, Any]) -> dict[str, str]:
    PUSH_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md = PUSH_DIR / f"{kind}_feishu_{stamp}.md"
    js = PUSH_DIR / f"{kind}_feishu_{stamp}.json"
    md.write_text(text, encoding="utf-8")
    js.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = PUSH_DIR / f"latest_{kind}_feishu.md"
    latest.write_text(text, encoding="utf-8")
    return {"markdown": str(md), "json": str(js), "latest": str(latest)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="飞书推送端口")
    parser.add_argument("--channel", choices=["feishu"], default="feishu")
    parser.add_argument("--kind", choices=["test", "daily", "question"], default="test")
    parser.add_argument("--as-of", default="20260702")
    parser.add_argument("--question", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.kind == "daily":
        text = build_daily_brief(args.as_of)
    elif args.kind == "question":
        text = build_question_message(args.question)
    else:
        text = build_test_message()
    result = send(args.channel, text[:3500], dry_run=args.dry_run)
    paths = write_result(args.kind, text, result)
    print(json.dumps({**result, **paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
