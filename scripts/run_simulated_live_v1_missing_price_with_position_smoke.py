from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "reports" / "simulated_live_v1"
STATE_DIR = BASE_DIR / "state"
INPUT_DIR = BASE_DIR / "input"
REVIEW_DIR = BASE_DIR / "review"
TEST_RUNS_DIR = BASE_DIR / "test_runs"

OFFICIAL_STATE_FILE = STATE_DIR / "simulated_account_state.json"
UPDATER_SCRIPT = ROOT / "scripts" / "update_simulated_account_state.py"
FEISHU_SCRIPT = ROOT / "scripts" / "send_feishu_utf8.py"

OFFICIAL_STATE_HASH = "2D545CDEC06244FEE96928207736D6A99964057413A34FBF9E3FD45465749454"
MISSING_SYMBOL = "999999.SZ"
MISSING_NAME = "missing_price_test_position"


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
    lines = [f"# missing_price_with_position_smoke_{report['trade_date']}", ""]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_test_state(official_state: dict[str, Any]) -> dict[str, Any]:
    state = deepcopy(official_state)
    state["initial_cash"] = 20000
    state["previous_total_equity"] = 20000
    state["cash"] = 15000.0
    state["positions"] = [
        {
            "ts_code": MISSING_SYMBOL,
            "name": MISSING_NAME,
            "shares": 100,
            "cost_basis": 50.0,
            "mark_price": 50.0,
            "market_value": 5000.0,
            "unrealized_pnl": 0.0,
        }
    ]
    state["total_equity"] = 20000.0
    state["realized_pnl"] = 0.0
    state["unrealized_pnl"] = 0.0
    state["daily_pnl"] = 0.0
    state["daily_pnl_ratio"] = 0.0
    state["cumulative_pnl"] = 0.0
    state["cumulative_pnl_ratio"] = 0.0
    state["trade_count_today"] = 0
    state["new_buy_count_today"] = 0
    state["account_risk_flags"] = []
    state["human_review_items"] = []
    state["real_account_connected"] = False
    state["auto_trading_enabled"] = False
    state["news_module_enabled"] = False
    return state


def build_hold_daily_report(trade_date: str) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "readonly_render_only": True,
        "readonly_market_data_used": True,
        "trade_decision_generated": False,
        "original_model_action": "OBSERVE",
        "ai_review_shadow_action": "OBSERVE",
        "final_user_action": "HOLD",
        "action_requested": "HOLD",
        "candidate_ts_code": MISSING_SYMBOL,
        "candidate_name": MISSING_NAME,
        "test_mode": True,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "note": "missing_price smoke input only; no buy/sell/reduce decision",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run missing_price with position smoke test for simulated_live_v1")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--send-feishu", dest="send_feishu", action="store_true", default=True)
    parser.add_argument("--no-send-feishu", dest="send_feishu", action="store_false")
    args = parser.parse_args()

    regression_report_path = (
        REVIEW_DIR / f"readonly_flow_regression_check_{args.trade_date}.json"
        if args.trade_date
        else latest_regression_report()
    )
    regression_report = read_json(regression_report_path) if regression_report_path and regression_report_path.exists() else {}
    readonly_regression_passed = bool(regression_report.get("regression_passed", False))
    trade_date = str(regression_report.get("trade_date") or args.trade_date or "UNKNOWN")

    report_json = REVIEW_DIR / f"missing_price_with_position_smoke_{trade_date}.json"
    report_md = REVIEW_DIR / f"missing_price_with_position_smoke_{trade_date}.md"
    feishu_file = REVIEW_DIR / f"feishu_missing_price_with_position_smoke_{trade_date}.txt"

    if not readonly_regression_passed:
        blocked_report = {
            "missing_price_smoke_completed": False,
            "blocked_by_readonly_regression": True,
            "readonly_regression_passed": False,
            "trade_date": trade_date,
            "test_mode": True,
            "market_data_loaded": False,
            "account_state_loaded": False,
            "selected_ts_code": MISSING_SYMBOL,
            "position_symbol_matched": False,
            "price_loaded": False,
            "missing_price": True,
            "missing_price_symbols": [MISSING_SYMBOL],
            "price_used": None,
            "final_user_action": "HOLD",
            "action_executed": "HOLD",
            "trade_decision_generated": False,
            "buy_sell_reduce_generated": False,
            "no_trade_executed": True,
            "human_review_items": [],
            "account_risk_flags": [],
            "official_state_preserved": sha256_file(OFFICIAL_STATE_FILE) == OFFICIAL_STATE_HASH,
            "real_account_connected": False,
            "auto_trading_enabled": False,
            "full_pipeline_enabled": False,
            "news_module_enabled": False,
            "failed_checks": ["readonly_regression_not_passed"],
            "recommended_next_step": "fix readonly regression before missing_price smoke",
        }
        write_json(report_json, blocked_report)
        write_markdown(report_md, blocked_report)
        feishu_file.write_text(
            "simulated_live_v1 missing_price smoke test failed: readonly flow regression not passed.",
            encoding="utf-8",
        )
        if args.send_feishu:
            run_command([sys.executable, str(FEISHU_SCRIPT), "--text-file", str(feishu_file)])
        return 1

    market_data_source = INPUT_DIR / "market_data" / f"market_data_{trade_date}.json"
    market_data = dict(read_json(market_data_source))
    official_hash_before = sha256_file(OFFICIAL_STATE_FILE)
    official_state = dict(read_json(OFFICIAL_STATE_FILE))

    test_run_dir = TEST_RUNS_DIR / "missing_price_with_position_001"
    test_state_dir = test_run_dir / "state"
    test_input_dir = test_run_dir / "input"
    test_review_dir = test_run_dir / "review"
    test_state_dir.mkdir(parents=True, exist_ok=True)
    test_input_dir.mkdir(parents=True, exist_ok=True)
    test_review_dir.mkdir(parents=True, exist_ok=True)

    test_market_data_file = test_input_dir / f"market_data_{trade_date}.json"
    test_daily_report_file = test_input_dir / f"simulated_live_v1_daily_report_{trade_date}.json"
    test_state_file = test_state_dir / "simulated_account_state_test.json"
    output_state_file = test_state_dir / "simulated_account_state_updated.json"
    test_snapshot_file = test_state_dir / "simulated_account_state_snapshot.json"
    test_trade_log_file = test_review_dir / "simulated_trade_log_test.json"
    test_update_review_file = test_review_dir / "account_state_update_test.json"
    test_update_review_md_file = test_review_dir / "account_state_update_test.md"

    shutil.copyfile(market_data_source, test_market_data_file)
    test_state = build_test_state(official_state)
    write_json(test_state_file, test_state)
    write_json(test_daily_report_file, build_hold_daily_report(trade_date))

    before_position = dict(test_state["positions"][0])
    cash_before = float(test_state.get("cash", 0))
    shares_before = int(before_position.get("shares", 0))

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

    updated_state = dict(read_json(output_state_file)) if output_state_file.exists() else {}
    trade_log = dict(read_json(test_trade_log_file)) if test_trade_log_file.exists() else {}
    update_review = dict(read_json(test_update_review_file)) if test_update_review_file.exists() else {}
    after_position = dict(updated_state.get("positions", [{}])[0]) if updated_state.get("positions") else {}
    official_hash_after = sha256_file(OFFICIAL_STATE_FILE)

    market_symbols = {str(item.get("ts_code", "")) for item in market_data.get("target_symbols_ohlc", [])}
    position_symbol_matched = MISSING_SYMBOL in market_symbols
    price_loaded = position_symbol_matched
    missing_price = not price_loaded
    missing_price_symbols = [MISSING_SYMBOL] if missing_price else []
    human_review_items = list(updated_state.get("human_review_items", []))
    account_risk_flags = list(updated_state.get("account_risk_flags", []))

    shares_after = int(after_position.get("shares", 0) or 0)
    cash_after = float(updated_state.get("cash", 0) or 0)
    mark_price_before = float(before_position.get("mark_price", 0) or 0)
    mark_price_after = float(after_position.get("mark_price", 0) or 0)
    market_value_before = float(before_position.get("market_value", 0) or 0)
    market_value_after = float(after_position.get("market_value", 0) or 0)
    total_equity_before = float(test_state.get("total_equity", 0) or 0)
    total_equity_after = float(updated_state.get("total_equity", 0) or 0)
    no_trade_executed = int(trade_log.get("shares", 0) or 0) == 0 and str(update_review.get("action_executed", "")) == "HOLD"

    required_checks = {
        "account_updater_ran": updater_result.returncode == 0,
        "market_data_loaded": bool(market_data.get("target_symbols_ohlc")),
        "account_state_loaded": OFFICIAL_STATE_FILE.exists(),
        "position_symbol_matched_false": not position_symbol_matched,
        "price_loaded_false": not price_loaded,
        "missing_price_true": missing_price,
        "price_used_empty": trade_log.get("price") is None,
        "shares_unchanged": shares_after == shares_before,
        "cash_unchanged": round(cash_after, 4) == round(cash_before, 4),
        "mark_price_unchanged": round(mark_price_after, 4) == round(mark_price_before, 4),
        "market_value_unchanged": round(market_value_after, 4) == round(market_value_before, 4),
        "total_equity_unchanged": round(total_equity_after, 4) == round(total_equity_before, 4),
        "human_review_items_written": any(MISSING_SYMBOL in item for item in human_review_items),
        "account_risk_flags_written": "missing_price" in account_risk_flags,
        "no_trade_executed": no_trade_executed,
        "no_trade_decision_generated": not bool(update_review.get("trade_decision_generated", False)),
        "official_state_preserved": official_hash_before == official_hash_after == OFFICIAL_STATE_HASH,
        "real_account_connected_false": not bool(updated_state.get("real_account_connected", False)),
        "auto_trading_enabled_false": not bool(updated_state.get("auto_trading_enabled", False)),
        "news_module_enabled_false": not bool(updated_state.get("news_module_enabled", False)),
    }
    failed_checks = [name for name, passed in required_checks.items() if not passed]
    smoke_passed = not failed_checks

    report = {
        "missing_price_smoke_completed": smoke_passed,
        "blocked_by_readonly_regression": False,
        "readonly_regression_passed": True,
        "trade_date": trade_date,
        "test_mode": True,
        "market_data_loaded": bool(market_data.get("target_symbols_ohlc")),
        "account_state_loaded": OFFICIAL_STATE_FILE.exists(),
        "selected_ts_code": MISSING_SYMBOL,
        "position_symbol_matched": position_symbol_matched,
        "price_loaded": price_loaded,
        "missing_price": missing_price,
        "missing_price_symbols": missing_price_symbols,
        "price_used": None,
        "final_user_action": str(update_review.get("final_user_action", "HOLD")),
        "action_executed": str(update_review.get("action_executed", "")),
        "trade_decision_generated": False,
        "buy_sell_reduce_generated": False,
        "no_trade_executed": no_trade_executed,
        "shares_before": shares_before,
        "shares_after": shares_after,
        "cash_before": cash_before,
        "cash_after": cash_after,
        "mark_price_before": mark_price_before,
        "mark_price_after": mark_price_after,
        "market_value_before": market_value_before,
        "market_value_after": market_value_after,
        "total_equity_before": total_equity_before,
        "total_equity_after": total_equity_after,
        "daily_pnl": float(updated_state.get("daily_pnl", 0) or 0),
        "cumulative_pnl": float(updated_state.get("cumulative_pnl", 0) or 0),
        "human_review_items": human_review_items,
        "account_risk_flags": account_risk_flags,
        "official_state_preserved": official_hash_before == official_hash_after == OFFICIAL_STATE_HASH,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "failed_checks": failed_checks,
        "recommended_next_step": "keep missing_price as a manual-review gate before any future valuation-dependent automation",
        "test_run_dir": str(test_run_dir),
        "test_state_file": str(test_state_file),
        "output_state_file": str(output_state_file),
        "test_market_data_file": str(test_market_data_file),
        "test_daily_report_file": str(test_daily_report_file),
        "test_trade_log_file": str(test_trade_log_file),
        "test_update_review_file": str(test_update_review_file),
        "generated_at": now_text(),
    }

    write_json(report_json, report)
    write_markdown(report_md, report)

    feishu_text = (
        "simulated_live_v1 missing_price smoke test 已完成：系统已识别测试持仓缺少真实行情，"
        "未编造价格，未执行交易，已写入人工复核/风险提示。不接真实账户、不自动交易。"
        if smoke_passed
        else "simulated_live_v1 missing_price smoke test 失败：请检查是否存在编造价格、错误估值或账户被误更新。"
    )
    feishu_file.write_text(feishu_text, encoding="utf-8")
    report["feishu_message_file"] = str(feishu_file)
    report["feishu_message_sent"] = False
    if args.send_feishu:
        feishu_result = run_command([sys.executable, str(FEISHU_SCRIPT), "--text-file", str(feishu_file)])
        report["feishu_message_sent"] = feishu_result.returncode == 0
        report["feishu_send_returncode"] = feishu_result.returncode
    write_json(report_json, report)
    write_markdown(report_md, report)

    print(json.dumps({"report_json": str(report_json), "report_md": str(report_md), **report}, ensure_ascii=True, indent=2))
    return 0 if smoke_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
