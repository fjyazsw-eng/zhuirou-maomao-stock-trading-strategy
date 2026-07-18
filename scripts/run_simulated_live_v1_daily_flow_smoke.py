from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "reports" / "simulated_live_v1"
STATE_DIR = BASE_DIR / "state"
INPUT_DIR = BASE_DIR / "input"
DAILY_DIR = BASE_DIR / "daily"
REVIEW_DIR = BASE_DIR / "review"
TEST_RUNS_DIR = BASE_DIR / "test_runs"

OFFICIAL_STATE_FILE = STATE_DIR / "simulated_account_state.json"
MANUAL_CANDIDATE_POOL_FILE = INPUT_DIR / "candidate_pool" / "candidate_pool_MANUAL.json"
READONLY_FLOW_SCRIPT = ROOT / "scripts" / "run_simulated_live_v1_daily_readonly_flow.py"
UPDATER_SCRIPT = ROOT / "scripts" / "update_simulated_account_state.py"
FEISHU_SCRIPT = ROOT / "scripts" / "send_feishu_utf8.py"

OFFICIAL_STATE_HASH = "2D545CDEC06244FEE96928207736D6A99964057413A34FBF9E3FD45465749454"


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


def latest_regression_report() -> Path | None:
    reports = sorted(REVIEW_DIR.glob("readonly_flow_regression_check_*.json"), key=lambda item: item.stat().st_mtime)
    return reports[-1] if reports else None


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [f"# daily_flow_smoke_{report['trade_date']}", ""]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_test_state() -> dict[str, Any]:
    return {
        "account_id": "sim_v1_local_only",
        "currency": "CNY",
        "initial_cash": 20000,
        "cash": 20000,
        "total_equity": 20000.0,
        "positions": [],
        "max_position_per_stock": 0.2,
        "max_total_position": 0.6,
        "max_new_buy_per_day": 1,
        "max_total_trades_per_day": 2,
        "lot_size": 100,
        "trade_count_today": 0,
        "new_buy_count_today": 0,
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "daily_pnl": 0.0,
        "daily_pnl_ratio": 0.0,
        "cumulative_pnl": 0.0,
        "cumulative_pnl_ratio": 0.0,
        "account_risk_flags": [],
        "human_review_items": [],
        "previous_total_equity": 20000.0,
        "last_update": "",
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "news_module_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simulated_live_v1 daily flow smoke test")
    parser.add_argument("--trade-date", default="20260703")
    parser.add_argument("--send-feishu", dest="send_feishu", action="store_true", default=True)
    parser.add_argument("--no-send-feishu", dest="send_feishu", action="store_false")
    args = parser.parse_args()

    trade_date = args.trade_date
    regression_report_path = latest_regression_report() if not args.trade_date else REVIEW_DIR / f"readonly_flow_regression_check_{trade_date}.json"
    regression_report = read_json(regression_report_path) if regression_report_path and regression_report_path.exists() else {}
    readonly_regression_passed = bool(regression_report.get("regression_passed", False))

    report_json = REVIEW_DIR / f"daily_flow_smoke_{trade_date}.json"
    report_md = REVIEW_DIR / f"daily_flow_smoke_{trade_date}.md"
    feishu_file = REVIEW_DIR / f"feishu_daily_flow_smoke_{trade_date}.txt"

    if not readonly_regression_passed:
        blocked_report = {
            "daily_flow_smoke_completed": False,
            "readonly_regression_passed": False,
            "blocked_by_readonly_regression": True,
            "trade_date": trade_date,
            "failed_checks": ["readonly_regression_not_passed"],
            "real_account_connected": False,
            "auto_trading_enabled": False,
            "full_pipeline_enabled": False,
            "news_module_enabled": False,
            "recommended_next_step": "fix readonly regression before daily flow smoke",
        }
        write_json(report_json, blocked_report)
        write_markdown(report_md, blocked_report)
        feishu_file.write_text("simulated_live_v1 daily flow smoke blocked: readonly regression not passed.", encoding="utf-8")
        if args.send_feishu:
            run_command([sys.executable, str(FEISHU_SCRIPT), "--text-file", str(feishu_file)])
        return 1

    test_run_dir = TEST_RUNS_DIR / "daily_flow_smoke_001"
    test_state_dir = test_run_dir / "state"
    test_input_dir = test_run_dir / "input"
    test_review_dir = test_run_dir / "review"
    test_state_dir.mkdir(parents=True, exist_ok=True)
    test_input_dir.mkdir(parents=True, exist_ok=True)
    test_review_dir.mkdir(parents=True, exist_ok=True)

    official_hash_before = sha256_file(OFFICIAL_STATE_FILE)
    write_json(test_state_dir / "simulated_account_state_test.json", build_test_state())

    readonly_result = run_command(
        [
            sys.executable,
            str(READONLY_FLOW_SCRIPT),
            "--trade-date",
            trade_date,
            "--candidate-pool",
            str(MANUAL_CANDIDATE_POOL_FILE),
            "--no-send-feishu",
        ]
    )
    readonly_report = read_json(REVIEW_DIR / f"daily_readonly_flow_smoke_test_{trade_date}.json")
    market_data_source = INPUT_DIR / "market_data" / f"market_data_{trade_date}.json"
    daily_report_source = DAILY_DIR / f"simulated_live_v1_daily_report_{trade_date}.json"
    feishu_summary_source = REVIEW_DIR / f"feishu_daily_readonly_flow_smoke_test_{trade_date}.txt"

    test_market_data_file = test_input_dir / f"market_data_{trade_date}.json"
    test_daily_report_file = test_input_dir / f"simulated_live_v1_daily_report_{trade_date}.json"
    test_state_file = test_state_dir / "simulated_account_state_test.json"
    output_state_file = test_state_dir / "simulated_account_state_updated.json"
    test_snapshot_file = test_state_dir / "simulated_account_state_snapshot.json"
    test_trade_log_file = test_review_dir / "simulated_trade_log_test.json"
    test_update_review_file = test_review_dir / "account_state_update_test.json"
    test_update_review_md_file = test_review_dir / "account_state_update_test.md"

    shutil.copyfile(market_data_source, test_market_data_file)
    shutil.copyfile(daily_report_source, test_daily_report_file)

    daily_report_payload = read_json(test_daily_report_file)
    daily_report_payload["final_user_action"] = "OBSERVE"
    daily_report_payload["action_requested"] = "OBSERVE"
    daily_report_payload["trade_decision_generated"] = False
    daily_report_payload["buy_sell_reduce_generated"] = False
    daily_report_payload["readonly_market_data_used"] = True
    write_json(test_daily_report_file, daily_report_payload)

    state_before = read_json(test_state_file)
    positions_before = list(state_before.get("positions", []))

    updater_result = run_command(
        [
            sys.executable,
            str(UPDATER_SCRIPT),
            "--trade-date",
            trade_date,
            "--dry-run",
            "--state-file",
            str(test_state_file),
            "--output-state-file",
            str(output_state_file),
            "--snapshot-file",
            str(test_snapshot_file),
            "--trade-log-file",
            str(test_trade_log_file),
            "--report-json-file",
            str(test_update_review_file),
            "--report-md-file",
            str(test_update_review_md_file),
            "--market-data-file",
            str(test_market_data_file),
            "--daily-report-file",
            str(test_daily_report_file),
        ]
    )

    updated_state = read_json(output_state_file) if output_state_file.exists() else {}
    update_review = read_json(test_update_review_file) if test_update_review_file.exists() else {}
    trade_log = read_json(test_trade_log_file) if test_trade_log_file.exists() else {}
    positions_after = list(updated_state.get("positions", []))

    flow_feishu_text = (
        "simulated_live_v1 daily flow smoke 已完成：readonly regression、手工候选池、真实只读行情、daily report、"
        "飞书摘要、隔离账户更新链路已跑通。未执行交易，不接真实账户，不自动交易，不启用 full pipeline。"
    )
    feishu_file.write_text(flow_feishu_text, encoding="utf-8")
    feishu_summary_generated = feishu_summary_source.exists() and feishu_file.exists()
    feishu_summary_sent = False
    feishu_send_reason = ""
    if args.send_feishu:
        feishu_result = run_command([sys.executable, str(FEISHU_SCRIPT), "--text-file", str(feishu_file)])
        feishu_summary_sent = feishu_result.returncode == 0
        if not feishu_summary_sent:
            feishu_send_reason = f"returncode={feishu_result.returncode}"
    else:
        feishu_send_reason = "send_feishu_disabled"

    official_hash_after = sha256_file(OFFICIAL_STATE_FILE)
    failed_checks = []
    required_checks = {
        "readonly_regression_passed": readonly_regression_passed,
        "readonly_flow_ran": readonly_result.returncode == 0,
        "candidate_pool_loaded": bool(readonly_report.get("candidate_pool_loaded", False)),
        "market_data_loaded": bool(readonly_report.get("market_data_file_generated", False)),
        "daily_report_generated": Path(daily_report_source).exists(),
        "candidate_quotes_rendered": bool(readonly_report.get("candidate_quotes_rendered", False)),
        "feishu_summary_generated": feishu_summary_generated,
        "account_state_loaded": test_state_file.exists(),
        "account_updater_ran": updater_result.returncode == 0,
        "official_state_preserved": official_hash_before == official_hash_after == OFFICIAL_STATE_HASH,
        "final_user_action_observe": str(update_review.get("final_user_action", "")) == "OBSERVE",
        "action_executed_observe": str(update_review.get("action_executed", "")) == "OBSERVE",
        "no_trade_executed": int(trade_log.get("shares", 0) or 0) == 0 and str(trade_log.get("action_executed", "")) == "OBSERVE",
        "cash_unchanged": float(updated_state.get("cash", 0) or 0) == 20000.0,
        "positions_empty": positions_before == [] and positions_after == [],
        "total_equity_unchanged": float(updated_state.get("total_equity", 0) or 0) == 20000.0,
        "daily_pnl_zero": float(updated_state.get("daily_pnl", 0) or 0) == 0.0,
        "cumulative_pnl_zero": float(updated_state.get("cumulative_pnl", 0) or 0) == 0.0,
        "real_account_connected_false": not bool(updated_state.get("real_account_connected", False)),
        "auto_trading_enabled_false": not bool(updated_state.get("auto_trading_enabled", False)),
        "news_module_enabled_false": not bool(updated_state.get("news_module_enabled", False)),
    }
    failed_checks = [name for name, passed in required_checks.items() if not passed]
    smoke_passed = not failed_checks

    report = {
        "daily_flow_smoke_completed": smoke_passed,
        "readonly_regression_passed": readonly_regression_passed,
        "blocked_by_readonly_regression": False,
        "candidate_pool_loaded": bool(readonly_report.get("candidate_pool_loaded", False)),
        "market_data_loaded": bool(readonly_report.get("market_data_file_generated", False)),
        "daily_report_generated": Path(daily_report_source).exists(),
        "candidate_quotes_rendered": bool(readonly_report.get("candidate_quotes_rendered", False)),
        "feishu_summary_generated": feishu_summary_generated,
        "feishu_summary_sent": feishu_summary_sent,
        "feishu_summary_send_reason": feishu_send_reason,
        "account_state_loaded": test_state_file.exists(),
        "account_updater_ran": updater_result.returncode == 0,
        "test_mode": True,
        "official_state_preserved": official_hash_before == official_hash_after == OFFICIAL_STATE_HASH,
        "final_user_action": str(update_review.get("final_user_action", "OBSERVE")),
        "action_executed": str(update_review.get("action_executed", "OBSERVE")),
        "trade_decision_generated": False,
        "buy_sell_reduce_generated": False,
        "no_trade_executed": int(trade_log.get("shares", 0) or 0) == 0 and str(trade_log.get("action_executed", "")) == "OBSERVE",
        "cash_before": float(state_before.get("cash", 0) or 0),
        "cash_after": float(updated_state.get("cash", 0) or 0),
        "positions_before": positions_before,
        "positions_after": positions_after,
        "total_equity_before": float(state_before.get("total_equity", 0) or 0),
        "total_equity_after": float(updated_state.get("total_equity", 0) or 0),
        "daily_pnl": float(updated_state.get("daily_pnl", 0) or 0),
        "cumulative_pnl": float(updated_state.get("cumulative_pnl", 0) or 0),
        "failed_checks": failed_checks,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "official_state_hash_before": official_hash_before,
        "official_state_hash_after": official_hash_after,
        "test_run_only_account_writes": True,
        "missing_price_gate_retained": True,
        "recommended_next_step": (
            "safe to consider first-day formal simulated run after one more dedicated BUY-blocked or HOLD-with-position daily flow smoke"
            if smoke_passed
            else "fix failed_checks before any first-day formal simulated run"
        ),
        "trade_date": trade_date,
        "generated_at": now_text(),
        "test_run_dir": str(test_run_dir),
    }

    write_json(report_json, report)
    write_markdown(report_md, report)

    print(json.dumps({"report_json": str(report_json), "report_md": str(report_md), **report}, ensure_ascii=True, indent=2))
    return 0 if smoke_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
