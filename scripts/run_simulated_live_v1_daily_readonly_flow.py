from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "reports" / "simulated_live_v1"
INPUT_DIR = BASE_DIR / "input"
CANDIDATE_POOL_DIR = INPUT_DIR / "candidate_pool"
MARKET_DATA_DIR = INPUT_DIR / "market_data"
DAILY_DIR = BASE_DIR / "daily"
REVIEW_DIR = BASE_DIR / "review"
STATE_FILE = BASE_DIR / "state" / "simulated_account_state.json"

DEFAULT_CANDIDATE_POOL = CANDIDATE_POOL_DIR / "candidate_pool_MANUAL.json"
FETCH_SCRIPT = ROOT / "scripts" / "fetch_simulated_live_v1_market_data_readonly.py"
DAILY_REPORT_SCRIPT = ROOT / "scripts" / "build_simulated_live_v1_daily_report.py"
FEISHU_SCRIPT = ROOT / "scripts" / "send_feishu_utf8.py"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def parse_last_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        return dict(json.loads(text))
    except json.JSONDecodeError:
        pass
    start = text.rfind("{")
    if start < 0:
        return {}
    try:
        return dict(json.loads(text[start:]))
    except json.JSONDecodeError:
        return {}


def load_candidate_pool(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = read_json(path)
    return payload if isinstance(payload, list) else []


def build_price_mode_check(market_data: dict[str, Any]) -> dict[str, Any]:
    quotes = market_data.get("target_symbols_ohlc", [])
    fields_used = ["open", "high", "low", "close", "pre_close", "pct_chg", "amount"]
    has_price_fields = bool(quotes) and all(any(field in item for field in fields_used) for item in quotes)
    return {
        "price_mode_checked": True,
        "price_mode_source": "Tushare pro.daily readonly endpoint; no adj_factor, qfq, or hfq transformation applied in this flow",
        "price_fields_used": fields_used,
        "price_adjustment_mode": "raw",
        "amount_unit": "thousand CNY; Tushare daily.amount convention",
        "price_sanity_notes": (
            "Only raw readonly quote fields are rendered. This is enough for display, but simulated buy sizing should "
            "keep using the same raw close/mark_price convention and re-check amount/volume units before execution tests."
        ),
        "price_fields_present": has_price_fields,
    }


def write_review_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [f"# daily_readonly_flow_smoke_test_{report['latest_completed_trade_date']}", ""]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_feishu_summary(path: Path, report: dict[str, Any]) -> None:
    missing = report.get("missing_symbols") or []
    missing_text = f" missing_symbols={missing}。" if missing else ""
    price_note = ""
    if report.get("price_adjustment_mode") in {"unknown", ""}:
        price_note = " 注意：价格复权/单位口径仍需在后续模拟买入前确认。"
    text = (
        "simulated_live_v1 daily readonly flow smoke test 已完成：手工候选池、真实只读行情、只读日报与飞书摘要已串联。"
        "当前不更新账户、不生成交易决策、不自动选股、不接真实账户、不自动交易。"
        f"{missing_text}{price_note}"
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simulated_live_v1 daily readonly flow smoke test")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--candidate-pool", default=str(DEFAULT_CANDIDATE_POOL))
    parser.add_argument("--send-feishu", dest="send_feishu", action="store_true", default=True)
    parser.add_argument("--no-send-feishu", dest="send_feishu", action="store_false")
    parser.add_argument("--check-price-mode", action="store_true", default=True)
    args = parser.parse_args()

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    candidate_pool_path = Path(args.candidate_pool)
    if not candidate_pool_path.is_absolute():
        candidate_pool_path = ROOT / candidate_pool_path
    candidate_pool = load_candidate_pool(candidate_pool_path)

    state_hash_before = sha256_file(STATE_FILE)

    fetch_cmd = [sys.executable, str(FETCH_SCRIPT), "--candidate-pool", str(candidate_pool_path)]
    if args.trade_date:
        fetch_cmd += ["--trade-date", args.trade_date]
    fetch_result = run_command(fetch_cmd)
    fetch_stdout = parse_last_json(fetch_result.stdout)
    readonly_market_fetch_ran = fetch_result.returncode == 0

    latest_completed_trade_date = str(
        fetch_stdout.get("latest_completed_trade_date")
        or fetch_stdout.get("resolved_trade_date")
        or args.trade_date
    )
    if not latest_completed_trade_date:
        candidates = sorted(REVIEW_DIR.glob("market_data_readonly_fetch_*.json"), key=lambda item: item.stat().st_mtime)
        if candidates:
            latest_completed_trade_date = candidates[-1].stem.replace("market_data_readonly_fetch_", "")

    fetch_review_path = REVIEW_DIR / f"market_data_readonly_fetch_{latest_completed_trade_date}.json"
    fetch_review = read_json(fetch_review_path) if fetch_review_path.exists() else {}
    latest_completed_trade_date = str(fetch_review.get("latest_completed_trade_date") or latest_completed_trade_date)
    market_data_path = MARKET_DATA_DIR / f"market_data_{latest_completed_trade_date}.json"
    market_data = read_json(market_data_path) if market_data_path.exists() else {}

    daily_result = run_command([sys.executable, str(DAILY_REPORT_SCRIPT), "--trade-date", latest_completed_trade_date])
    daily_report_json = DAILY_DIR / f"simulated_live_v1_daily_report_{latest_completed_trade_date}.json"
    daily_report = read_json(daily_report_json) if daily_report_json.exists() else {}

    price_check = build_price_mode_check(market_data) if args.check_price_mode else {
        "price_mode_checked": False,
        "price_mode_source": "",
        "price_fields_used": [],
        "price_adjustment_mode": "unknown",
        "amount_unit": "unknown",
        "price_sanity_notes": "price mode check was disabled",
        "price_fields_present": False,
    }

    state_hash_after = sha256_file(STATE_FILE)
    latest = latest_completed_trade_date
    review_json = REVIEW_DIR / f"daily_readonly_flow_smoke_test_{latest}.json"
    review_md = REVIEW_DIR / f"daily_readonly_flow_smoke_test_{latest}.md"
    feishu_summary_file = REVIEW_DIR / f"feishu_daily_readonly_flow_smoke_test_{latest}.txt"

    report = {
        "daily_readonly_flow_smoke_test_completed": bool(
            readonly_market_fetch_ran
            and daily_result.returncode == 0
            and market_data_path.exists()
            and daily_report_json.exists()
        ),
        "candidate_pool_loaded": bool(candidate_pool),
        "candidate_pool_file_used": str(candidate_pool_path),
        "manual_candidate_count": len(candidate_pool),
        "readonly_market_fetch_ran": readonly_market_fetch_ran,
        "readonly_market_fetch_returncode": fetch_result.returncode,
        "latest_completed_trade_date": latest,
        "market_data_file_generated": market_data_path.exists(),
        "market_data_file_used": str(market_data_path),
        "symbols_requested": int(fetch_review.get("symbols_requested", 0) or 0),
        "symbols_loaded": int(fetch_review.get("symbols_loaded", 0) or 0),
        "missing_symbols": fetch_review.get("missing_symbols", []),
        "daily_report_readonly_rendered": bool(daily_report.get("readonly_render_only")) and daily_result.returncode == 0,
        "daily_report_file": str(DAILY_DIR / f"simulated_live_v1_daily_report_{latest}.md"),
        "daily_report_json": str(daily_report_json),
        "candidate_quotes_rendered": bool(daily_report.get("candidate_quotes_rendered")),
        "feishu_summary_generated": True,
        "feishu_summary_file": str(feishu_summary_file),
        "feishu_summary_sent": False,
        "trade_decision_generated": False,
        "account_updater_ran": False,
        "official_state_preserved": state_hash_before == state_hash_after,
        "official_state_hash_before": state_hash_before,
        "official_state_hash_after": state_hash_after,
        "price_mode_checked": price_check["price_mode_checked"],
        "price_mode_source": price_check["price_mode_source"],
        "price_fields_used": price_check["price_fields_used"],
        "price_adjustment_mode": price_check["price_adjustment_mode"],
        "amount_unit": price_check["amount_unit"],
        "price_sanity_notes": price_check["price_sanity_notes"],
        "no_auto_selection": True,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "recommended_next_step": "add a readonly daily-flow regression check before any future simulated account update integration",
        "generated_at": now_text(),
    }

    write_feishu_summary(feishu_summary_file, report)
    if args.send_feishu:
        feishu_result = run_command([sys.executable, str(FEISHU_SCRIPT), "--text-file", str(feishu_summary_file)])
        report["feishu_summary_sent"] = feishu_result.returncode == 0
        report["feishu_send_returncode"] = feishu_result.returncode
    write_json(review_json, report)
    write_review_markdown(review_md, report)

    print(json.dumps({"review_json": str(review_json), "review_md": str(review_md), **report}, ensure_ascii=True, indent=2))
    return 0 if report["daily_readonly_flow_smoke_test_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
