from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from scoring_system.env_loader import load_project_env
from scoring_system.output_formatter import compact_table, compact_trade_advice, limit_lines
from scoring_system.report_freshness import ensure_fresh_reports


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "push_channels.json"
CONFIG_EXAMPLE = ROOT / "config" / "push_channels.example.json"
REPORTS = ROOT / "reports"
PUSH_DIR = REPORTS / "push"
TUSHARE_STATUS_PATH = REPORTS / "tushare" / "latest_tushare_status.json"

load_project_env()


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


def tushare_status_line() -> str:
    if not TUSHARE_STATUS_PATH.exists():
        return "Tushare状态：未检测到最近探针结果。"
    try:
        payload = json.loads(TUSHARE_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return "Tushare状态：探针结果无法解析。"
    status = str(payload.get("status", "UNKNOWN"))
    endpoint = str(payload.get("endpoint", "-"))
    latest = str(payload.get("latest_trade_date", "-"))
    data_trade_date = str(payload.get("data_trade_date", "-"))
    message = str(payload.get("message", ""))
    if status != "PASS":
        return f"Tushare状态：异常/待确认，优先检查接口。status={status}；latest={latest}；data={data_trade_date}；endpoint={endpoint}；message={message}"
    return f"Tushare状态：正常。latest={latest}；data={data_trade_date}；endpoint={endpoint}"


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
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return {"ok": True, "status": getattr(resp, "status", None), "response": raw[:1000]}
    except urllib.error.URLError as exc:
        message = str(exc)
        if "SSLV3_ALERT_HANDSHAKE_FAILURE" in message or "handshake failure" in message:
            return post_json_powershell(url, payload, f"python_tls_failed: {message[:180]}")
        if "10061" not in message and "actively refused" not in message:
            raise
        proxy_keys = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
        old_proxy = {key: os.environ.get(key) for key in proxy_keys}
        for key in proxy_keys:
            os.environ.pop(key, None)
        try:
            direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with direct_opener.open(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        finally:
            for key, value in old_proxy.items():
                if value is not None:
                    os.environ[key] = value
        return {
            "ok": True,
            "status": getattr(resp, "status", None),
            "response": raw[:1000],
            "proxy_fallback": "direct_after_local_proxy_refused",
        }
    except urllib.error.URLError as exc:
        message = str(exc)
        if "SSLV3_ALERT_HANDSHAKE_FAILURE" not in message and "handshake failure" not in message:
            raise
        return post_json_powershell(url, payload, f"python_tls_failed: {message[:180]}")


def post_json_powershell(url: str, payload: dict[str, Any], reason: str) -> dict[str, Any]:
    script = r"""
$ErrorActionPreference = 'Stop'
$url = $env:FEISHU_POST_URL
$body = $env:FEISHU_POST_BODY
$resp = Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 20
$resp | ConvertTo-Json -Compress
"""
    env = os.environ.copy()
    env["FEISHU_POST_URL"] = url
    env["FEISHU_POST_BODY"] = json.dumps(payload, ensure_ascii=False)
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"PowerShell fallback failed: {proc.stderr.strip()[:500]}")
    return {
        "ok": True,
        "status": 200,
        "response": proc.stdout.strip()[:1000],
        "fallback": "powershell_invoke_restmethod",
        "fallback_reason": reason,
    }


def build_daily_brief(as_of: str) -> str:
    ensure_fresh_reports()
    main = clean_user_text(read_text(REPORTS / "latest_market_decision_report.md", 6000))
    enhanced = clean_user_text(read_text(REPORTS / "enhanced" / f"event_funds_state_{as_of}.md", 3000))
    alerts = clean_user_text(read_text(REPORTS / "alerts" / f"sector_alerts_{as_of}.md", 3000))
    weather = extract_lines(main, ["- 大盘天气评分", "- 上涨家数", "- 下跌家数", "- 今日成交"], 4)
    sectors = extract_lines(main, ["- 物流", "- 化妆品", "- 化学制药", "- 广告营销", "- 饲料"], 5)
    stocks = extract_lines(main, ["- 潮宏基", "- 拉芳家化", "- 百合花", "- 科伦药业", "- 温氏股份"], 5)
    market_proxy = extract_lines(enhanced, ["- 今日成交额", "- 较前一日成交额变化", "- 上涨家数", "- 下跌家数", "- 放量下跌数"], 5)
    alert_lines = extract_lines(alerts, ["## 元件", "## 电子化学品", "## 半导体", "## 计算机设备", "- 等级：HIGH"], 8)
    summary = compact_table(
        f"股票AI交易助手简报 {as_of}",
        [
            ("大盘", weather[0] if weather else "总报告缺失"),
            ("优势板块", sectors[0] if sectors else "优势板块缺失"),
            ("候选方向", stocks[0] if stocks else "个股候选缺失"),
            ("资金状态", market_proxy[0] if market_proxy else "资金代理报告缺失"),
            ("风险提示", alert_lines[0] if alert_lines else "暂无高风险预警"),
        ],
    )
    next_steps = limit_lines(kline_summary(as_of), 3)
    advice = compact_trade_advice(
        empty_action="轻仓买核心 / 先别买后排",
        holding_action="持有强的，转弱就轻减",
        add_action="只加核心，不追高",
        sell_action="破位先减，反抽再卖",
        buy_condition="板块继续强，核心回踩后承接确认就轻仓买。",
        reduce_condition="高位放量不修复或后排明显掉队就减仓。",
        stop_condition="跌破关键支撑且收不回，直接执行止损。",
        max_position="半仓以下",
        final_line="能买就轻仓买核心，不行就先别买，错了立刻止损。",
    )
    return "\n\n".join(
        [
            summary,
            tushare_status_line(),
            "下一步\n\n" + "\n".join(f"- {item.lstrip('- ').strip()}" for item in next_steps),
            advice,
        ]
    )


def build_test_message() -> str:
    return "\n".join(
        [
            "股票AI量化助手端口测试",
            f"发送时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "如果你能看到这条消息，说明飞书 webhook 通道已连通。",
        ]
    )


def build_question_message(question: str) -> str:
    ensure_fresh_reports()
    answer_path = REPORTS / "conversation" / "latest_answer.md"
    answer = read_text(answer_path, 2600)
    result_text = answer or "问答结果缺失，请先运行本地问答入口。"
    body = "\n".join(limit_lines(result_text.splitlines(), 18))
    return "\n".join(
        [
            f"问题：{question or '未填写'}",
            "",
            tushare_status_line(),
            "",
            body,
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
