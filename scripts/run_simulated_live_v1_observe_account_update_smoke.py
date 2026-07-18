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
REGRESSION_SCRIPT = ROOT / "scripts" / "check_simulated_live_v1_readonly_flow_regression.py"
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


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [f"# observe_account_update_smoke_{report['trade_date']}", ""]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def latest_regression_report() -> Path | None:
    reports = sorted(REVIEW_DIR.glob("readonly_flow_regression_check_*.json"), key=lambda item: item.stat().st_mtime)
    return reports[-1] if reports else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simulated_live_v1 observe account update smoke test")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--test-mode", action="store_true", default=True)
    parser.add_argument("--use-official-state", action="store_true", default=False)
    parser.add_argument("--send-feishu", dest="send_feishu", action="store_true", default=True)
    parser.add_argument("--no-send-feishu", dest="send_feishu", action="store_false")
    args = parser.parse_args()

    regression_report_path = latest_regression_report() if not args.trade_date else REVIEW_DIR / f"readonly_flow_regression_check_{args.trade_date}.json"
    regression_report = read_json(regression_report_path) if regression_report_path and regression_report_path.exists() else {}
    readonly_regression_passed = bool(regression_report.get("regression_passed", False))
    trade_date = str(regression_report.get("trade_date") or args.trade_date or "UNKNOWN")

    report_json = REVIEW_DIR / f"observe_account_update_smoke_{trade_date}.json"
    report_md = REVIEW_DIR / f"observe_account_update_smoke_{trade_date}.md"

    if not readonly_regression_passed:
        blocked_report = {
            "observe_account_update_smoke_completed": False,
            "blocked_by_readonly_regression": True,
            "readonly_regression_passed": False,
            "trade_date": trade_date,
            "market_data_loaded": False,
            "candidate_pool_loaded": False,
            "account_state_loaded": False,
            "account_updater_ran": False,
            "test_mode": bool(args.test_mode),
            "official_state_preserved": sha256_file(OFFICIAL_STATE_FILE) == OFFICIAL_STATE_HASH,
            "final_user_action": "OBSERVE",
            "action_executed": "OBSERVE",
            "trade_decision_generated": False,
            "buy_sell_reduce_generated": False,
            "no_trade_executed": True,
            "cash_before": None,
            "cash_after": None,
            "total_equity_before": None,
            "total_equity_after": None,
            "positions_count_before": None,
            "positions_count_after": None,
            "daily_pnl": None,
            "cumulative_pnl": None,
            "real_account_connected": False,
            "auto_trading_enabled": False,
            "full_pipeline_enabled": False,
            "news_module_enabled": False,
            "recommended_next_step": "fix readonly regression before attempting observe account update smoke",
        }
        write_json(report_json, blocked_report)
        write_markdown(report_md, blocked_report)
        return 1

    if not args.trade_date:
        readonly_flow_result = run_command([sys.executable, str(READONLY_FLOW_SCRIPT), "--no-send-feishu"])
        if readonly_flow_result.returncode != 0:
            raise SystemExit(1)
        smoke_report = read_json(REVIEW_DIR / f"daily_readonly_flow_smoke_test_{trade_date}.json")
        trade_date = str(smoke_report.get("latest_completed_trade_date", trade_date))

    market_data_file = INPUT_DIR / "market_data" / f"market_data_{trade_date}.json"
    daily_report_file = DAILY_DIR / f"simulated_live_v1_daily_report_{trade_date}.json"
    candidate_pool_loaded = MANUAL_CANDIDATE_POOL_FILE.exists()
    market_data_loaded = market_data_file.exists()
    account_state_loaded = OFFICIAL_STATE_FILE.exists()

    test_run_dir = TEST_RUNS_DIR / "observe_account_update_smoke_001"
    test_state_dir = test_run_dir / "state"
    test_review_dir = test_run_dir / "review"
    test_state_dir.mkdir(parents=True, exist_ok=True)
    test_review_dir.mkdir(parents=True, exist_ok=True)

    official_hash_before = sha256_file(OFFICIAL_STATE_FILE)
    state_before = read_json(OFFICIAL_STATE_FILE)
    cash_before = float(state_before.get("cash", 0))
    total_equity_before = float(state_before.get("total_equity", 0))
    positions_count_before = len(state_before.get("positions", []))

    test_state_file = test_state_dir / f"simulated_account_state_{trade_date}_test.json"
    output_state_file = test_state_dir / f"simulated_account_state_{trade_date}_updated.json"
    test_snapshot_file = test_state_dir / f"simulated_account_state_{trade_date}_snapshot.json"
    test_trade_log_path = test_review_dir / f"simulated_trade_log_{trade_date}_test.json"
    test_update_review_path = test_review_dir / f"account_state_update_{trade_date}_test.json"
    test_update_review_md_path = test_review_dir / f"account_state_update_{trade_date}_test.md"
    shutil.copyfile(OFFICIAL_STATE_FILE, test_state_file)

    updater_result = run_command(
        [
            sys.executable,
            str(UPDATER_SCRIPT),
            "--trade-date",
            trade_date,
            "--dry-run",
            "--state-file",
            str(test_state_file if args.test_mode and not args.use_official_state else OFFICIAL_STATE_FILE),
            "--output-state-file",
            str(output_state_file if args.test_mode and not args.use_official_state else OFFICIAL_STATE_FILE),
            "--snapshot-file",
            str(test_snapshot_file if args.test_mode and not args.use_official_state else (STATE_DIR / "snapshots" / f"simulated_account_state_{trade_date}.json")),
            "--trade-log-file",
            str(test_trade_log_path if args.test_mode and not args.use_official_state else (STATE_DIR / "trade_logs" / f"simulated_trade_log_{trade_date}.json")),
            "--report-json-file",
            str(test_update_review_path if args.test_mode and not args.use_official_state else (REVIEW_DIR / f"account_state_update_{trade_date}.json")),
            "--report-md-file",
            str(test_update_review_md_path if args.test_mode and not args.use_official_state else (REVIEW_DIR / f"account_state_update_{trade_date}.md")),
        ]
    )
    account_updater_ran = updater_result.returncode == 0

    updated_state = read_json(output_state_file if args.test_mode and not args.use_official_state else OFFICIAL_STATE_FILE)
    trade_log_source = test_trade_log_path if args.test_mode and not args.use_official_state else (STATE_DIR / "trade_logs" / f"simulated_trade_log_{trade_date}.json")
    review_update_source = test_update_review_path if args.test_mode and not args.use_official_state else (REVIEW_DIR / f"account_state_update_{trade_date}.json")
    trade_log = read_json(trade_log_source) if trade_log_source.exists() else {}
    update_review = read_json(review_update_source) if review_update_source.exists() else {}

    official_hash_after = sha256_file(OFFICIAL_STATE_FILE)
    official_state_preserved = official_hash_before == official_hash_after == OFFICIAL_STATE_HASH

    report = {
        "observe_account_update_smoke_completed": bool(account_updater_ran),
        "blocked_by_readonly_regression": False,
        "readonly_regression_passed": True,
        "trade_date": trade_date,
        "market_data_loaded": market_data_loaded,
        "candidate_pool_loaded": candidate_pool_loaded,
        "account_state_loaded": account_state_loaded,
        "account_updater_ran": account_updater_ran,
        "test_mode": bool(args.test_mode and not args.use_official_state),
        "official_state_preserved": official_state_preserved,
        "final_user_action": str(update_review.get("final_user_action", "OBSERVE")),
        "action_executed": str(update_review.get("action_executed", "OBSERVE")),
        "trade_decision_generated": False,
        "buy_sell_reduce_generated": False,
        "no_trade_executed": int(trade_log.get("shares", 0) or 0) == 0 and str(trade_log.get("action_executed", "OBSERVE")) == "OBSERVE",
        "cash_before": cash_before,
        "cash_after": float(updated_state.get("cash", 0)),
        "total_equity_before": total_equity_before,
        "total_equity_after": float(updated_state.get("total_equity", 0)),
        "positions_count_before": positions_count_before,
        "positions_count_after": len(updated_state.get("positions", [])),
        "daily_pnl": float(updated_state.get("daily_pnl", 0)),
        "cumulative_pnl": float(updated_state.get("cumulative_pnl", 0)),
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "test_state_file": str(test_state_file),
        "output_state_file": str(output_state_file),
        "test_snapshot_file": str(test_snapshot_file),
        "test_trade_log_file": str(test_trade_log_path),
        "test_update_review_file": str(test_update_review_path),
        "recommended_next_step": "add a second smoke case with non-empty positions so HOLD mark-to-market can be verified on real readonly market data",
    }

    write_json(report_json, report)
    write_markdown(report_md, report)

    feishu_text = (
        "simulated_live_v1 真实行情 OBSERVE 账户更新 smoke test 已完成。当前仅用真实行情验证账户估值链路，未生成交易决策，未买卖，不接真实账户、不自动交易。"
    )
    feishu_file = REVIEW_DIR / f"feishu_observe_account_update_smoke_{trade_date}.txt"
    feishu_file.write_text(feishu_text, encoding="utf-8")
    if args.send_feishu:
        run_command([sys.executable, str(FEISHU_SCRIPT), "--text-file", str(feishu_file)])

    print(json.dumps({"report_json": str(report_json), "report_md": str(report_md), **report}, ensure_ascii=True, indent=2))
    return 0 if report["observe_account_update_smoke_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
