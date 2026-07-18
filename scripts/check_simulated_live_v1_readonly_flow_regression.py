from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "reports" / "simulated_live_v1"
REVIEW_DIR = BASE_DIR / "review"
FEISHU_SCRIPT = ROOT / "scripts" / "send_feishu_utf8.py"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def latest_smoke_report() -> Path | None:
    reports = sorted(
        REVIEW_DIR.glob("daily_readonly_flow_smoke_test_*.json"),
        key=lambda item: item.stat().st_mtime,
    )
    return reports[-1] if reports else None


def bool_is(payload: dict[str, Any], key: str, expected: bool) -> bool:
    return bool(payload.get(key)) is expected


def run_feishu(text_file: Path) -> bool:
    result = subprocess.run(
        [sys.executable, str(FEISHU_SCRIPT), "--text-file", str(text_file)],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [f"# readonly_flow_regression_check_{report['trade_date']}", ""]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check simulated_live_v1 readonly flow regression boundaries")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--source-report", default="")
    parser.add_argument("--send-feishu", dest="send_feishu", action="store_true", default=True)
    parser.add_argument("--no-send-feishu", dest="send_feishu", action="store_false")
    args = parser.parse_args()

    if args.source_report:
        source_report = Path(args.source_report)
        if not source_report.is_absolute():
            source_report = ROOT / source_report
    elif args.trade_date:
        source_report = REVIEW_DIR / f"daily_readonly_flow_smoke_test_{args.trade_date}.json"
    else:
        source_report = latest_smoke_report()

    failed_checks: list[str] = []
    smoke: dict[str, Any] = {}
    source_exists = bool(source_report and source_report.exists())
    if source_exists and source_report is not None:
        smoke = read_json(source_report)
    else:
        failed_checks.append("source_smoke_test_report_missing")

    trade_date = str(smoke.get("latest_completed_trade_date") or args.trade_date or "UNKNOWN")

    candidate_pool_check_passed = (
        source_exists
        and bool_is(smoke, "candidate_pool_loaded", True)
        and int(smoke.get("manual_candidate_count", 0) or 0) > 0
    )
    market_fetch_check_passed = (
        source_exists
        and bool_is(smoke, "daily_readonly_flow_smoke_test_completed", True)
        and bool_is(smoke, "readonly_market_fetch_ran", True)
        and bool_is(smoke, "market_data_file_generated", True)
        and int(smoke.get("symbols_requested", 0) or 0) > 0
        and int(smoke.get("symbols_loaded", 0) or 0) >= 0
    )
    daily_report_render_check_passed = (
        source_exists
        and bool_is(smoke, "daily_report_readonly_rendered", True)
        and bool_is(smoke, "candidate_quotes_rendered", True)
    )
    feishu_summary_check_passed = source_exists and bool_is(smoke, "feishu_summary_generated", True)
    no_account_update_check_passed = (
        source_exists
        and bool_is(smoke, "account_updater_ran", False)
        and bool_is(smoke, "official_state_preserved", True)
    )
    no_trade_decision_check_passed = source_exists and bool_is(smoke, "trade_decision_generated", False)
    no_auto_selection_check_passed = source_exists and bool_is(smoke, "no_auto_selection", True)
    official_state_hash_unchanged = (
        source_exists
        and bool(smoke.get("official_state_hash_before"))
        and smoke.get("official_state_hash_before") == smoke.get("official_state_hash_after")
    )
    real_account_connected = bool(smoke.get("real_account_connected", False))
    auto_trading_enabled = bool(smoke.get("auto_trading_enabled", False))
    full_pipeline_enabled = bool(smoke.get("full_pipeline_enabled", False))
    news_module_enabled = bool(smoke.get("news_module_enabled", False))

    required_checks = {
        "candidate_pool_check_passed": candidate_pool_check_passed,
        "market_fetch_check_passed": market_fetch_check_passed,
        "daily_report_render_check_passed": daily_report_render_check_passed,
        "feishu_summary_check_passed": feishu_summary_check_passed,
        "no_account_update_check_passed": no_account_update_check_passed,
        "no_trade_decision_check_passed": no_trade_decision_check_passed,
        "no_auto_selection_check_passed": no_auto_selection_check_passed,
        "official_state_hash_unchanged": official_state_hash_unchanged,
        "real_account_connected_false": not real_account_connected,
        "auto_trading_enabled_false": not auto_trading_enabled,
        "full_pipeline_enabled_false": not full_pipeline_enabled,
        "news_module_enabled_false": not news_module_enabled,
    }
    failed_checks.extend([name for name, passed in required_checks.items() if not passed])
    regression_passed = not failed_checks

    report = {
        "readonly_flow_regression_check_completed": source_exists,
        "regression_passed": regression_passed,
        "trade_date": trade_date,
        "source_smoke_test_report": str(source_report) if source_report else "",
        "candidate_pool_check_passed": candidate_pool_check_passed,
        "market_fetch_check_passed": market_fetch_check_passed,
        "daily_report_render_check_passed": daily_report_render_check_passed,
        "feishu_summary_check_passed": feishu_summary_check_passed,
        "no_account_update_check_passed": no_account_update_check_passed,
        "no_trade_decision_check_passed": no_trade_decision_check_passed,
        "no_auto_selection_check_passed": no_auto_selection_check_passed,
        "official_state_hash_unchanged": official_state_hash_unchanged,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "failed_checks": failed_checks,
        "recommended_next_step": (
            "safe to keep readonly flow as a pre-account-updater gate"
            if regression_passed
            else "fix readonly boundary failures before connecting account updater"
        ),
        "generated_at": now_text(),
    }

    report_json = REVIEW_DIR / f"readonly_flow_regression_check_{trade_date}.json"
    report_md = REVIEW_DIR / f"readonly_flow_regression_check_{trade_date}.md"
    write_json(report_json, report)
    write_markdown(report_md, report)

    feishu_text = (
        "simulated_live_v1 readonly flow 回归检查通过：只读行情、只读日报、飞书摘要正常，且未更新账户、未生成交易决策、未自动选股。"
        if regression_passed
        else "simulated_live_v1 readonly flow 回归检查失败，请先修复只读边界问题，再继续接账户更新器。"
    )
    feishu_file = REVIEW_DIR / f"feishu_readonly_flow_regression_check_{trade_date}.txt"
    feishu_file.write_text(feishu_text, encoding="utf-8")
    report["feishu_message_file"] = str(feishu_file)
    report["feishu_message_sent"] = run_feishu(feishu_file) if args.send_feishu else False
    write_json(report_json, report)
    write_markdown(report_md, report)

    print(json.dumps({"report_json": str(report_json), "report_md": str(report_md), **report}, ensure_ascii=True, indent=2))
    return 0 if regression_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
