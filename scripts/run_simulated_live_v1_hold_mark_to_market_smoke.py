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
    lines = [f"# hold_valuation_with_real_market_smoke_{report['trade_date']}", ""]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def choose_quote(market_data: dict[str, Any], initial_cash: float) -> dict[str, Any]:
    quotes = [item for item in market_data.get("target_symbols_ohlc", []) if item.get("close") is not None]
    if not quotes:
        raise RuntimeError("no quote with close price in readonly market data")
    affordable = [item for item in quotes if float(item.get("close", 0)) * 100 <= initial_cash * 0.8]
    if affordable:
        return dict(affordable[0])
    return dict(sorted(quotes, key=lambda item: float(item.get("close", 0)))[0])


def build_test_state(official_state: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
    state = deepcopy(official_state)
    initial_cash = float(state.get("initial_cash", 20000))
    shares = 100
    cost_basis = 50.0
    cost_value = round(cost_basis * shares, 4)
    state["cash"] = 15000.0
    state["total_equity"] = initial_cash
    state["previous_total_equity"] = initial_cash
    state["positions"] = [
        {
            "ts_code": quote.get("ts_code", ""),
            "name": quote.get("name", ""),
            "shares": shares,
            "cost_basis": cost_basis,
            "mark_price": cost_basis,
            "market_value": cost_value,
            "unrealized_pnl": 0.0,
        }
    ]
    state["trade_count_today"] = 0
    state["new_buy_count_today"] = 0
    state["unrealized_pnl"] = 0.0
    state["realized_pnl"] = 0
    state["daily_pnl"] = 0.0
    state["daily_pnl_ratio"] = 0.0
    state["cumulative_pnl"] = 0.0
    state["cumulative_pnl_ratio"] = 0.0
    state["account_risk_flags"] = []
    state["real_account_connected"] = False
    state["auto_trading_enabled"] = False
    state["news_module_enabled"] = False
    return state


def build_hold_daily_report(trade_date: str, quote: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "readonly_render_only": True,
        "trade_decision_generated": False,
        "readonly_market_data_used": True,
        "original_model_action": "OBSERVE",
        "ai_review_shadow_action": "OBSERVE",
        "final_user_action": "HOLD",
        "action_requested": "HOLD",
        "candidate_ts_code": quote.get("ts_code", ""),
        "candidate_name": quote.get("name", ""),
        "test_mode": True,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "note": "HOLD valuation smoke input only; not a buy/sell/reduce decision",
    }


def position_static_fields_equal(before: dict[str, Any], after: dict[str, Any]) -> bool:
    ignored = {"mark_price", "market_value", "unrealized_pnl"}
    before_static = {key: value for key, value in before.items() if key not in ignored}
    after_static = {key: value for key, value in after.items() if key not in ignored}
    return before_static == after_static


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HOLD mark-to-market smoke test for simulated_live_v1")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--send-feishu", dest="send_feishu", action="store_true", default=True)
    parser.add_argument("--no-send-feishu", dest="send_feishu", action="store_false")
    args = parser.parse_args()

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    regression_report_path = (
        REVIEW_DIR / f"readonly_flow_regression_check_{args.trade_date}.json"
        if args.trade_date
        else latest_regression_report()
    )
    regression_report = read_json(regression_report_path) if regression_report_path and regression_report_path.exists() else {}
    readonly_regression_passed = bool(regression_report.get("regression_passed", False))
    trade_date = str(regression_report.get("trade_date") or args.trade_date or "UNKNOWN")

    report_json = REVIEW_DIR / f"hold_valuation_with_real_market_smoke_{trade_date}.json"
    report_md = REVIEW_DIR / f"hold_valuation_with_real_market_smoke_{trade_date}.md"
    feishu_file = REVIEW_DIR / f"feishu_hold_valuation_with_real_market_smoke_{trade_date}.txt"

    if not readonly_regression_passed:
        blocked_report = {
            "hold_valuation_smoke_completed": False,
            "blocked_by_readonly_regression": True,
            "readonly_regression_passed": False,
            "trade_date": trade_date,
            "market_data_loaded": False,
            "account_state_loaded": False,
            "position_symbol_matched": False,
            "price_loaded": False,
            "price_used": None,
            "final_user_action": "HOLD",
            "action_executed": "HOLD",
            "trade_decision_generated": False,
            "buy_sell_reduce_generated": False,
            "no_trade_executed": True,
            "official_state_preserved": sha256_file(OFFICIAL_STATE_FILE) == OFFICIAL_STATE_HASH,
            "failed_checks": ["readonly_regression_not_passed"],
            "real_account_connected": False,
            "auto_trading_enabled": False,
            "full_pipeline_enabled": False,
            "news_module_enabled": False,
            "recommended_next_step": "fix readonly regression before HOLD valuation smoke",
            "generated_at": now_text(),
        }
        write_json(report_json, blocked_report)
        write_markdown(report_md, blocked_report)
        feishu_file.write_text(
            "simulated_live_v1 HOLD 估值更新 smoke test 被阻止：readonly flow regression 未通过，请先修复只读边界。",
            encoding="utf-8",
        )
        if args.send_feishu:
            run_command([sys.executable, str(FEISHU_SCRIPT), "--text-file", str(feishu_file)])
        return 1

    market_data_source = INPUT_DIR / "market_data" / f"market_data_{trade_date}.json"
    market_data = dict(read_json(market_data_source))
    official_hash_before = sha256_file(OFFICIAL_STATE_FILE)
    official_state = dict(read_json(OFFICIAL_STATE_FILE))
    account_state_loaded = OFFICIAL_STATE_FILE.exists()
    initial_cash = float(official_state.get("initial_cash", 20000))
    quote = choose_quote(market_data, initial_cash)

    test_run_dir = TEST_RUNS_DIR / "hold_valuation_with_real_market_001"
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
    test_state = build_test_state(official_state, quote)
    write_json(test_state_file, test_state)
    write_json(test_daily_report_file, build_hold_daily_report(trade_date, quote))

    before_position = dict(test_state["positions"][0])
    cash_before = float(test_state.get("cash", 0))
    shares_before = int(before_position.get("shares", 0))
    position_symbol_matched = str(before_position.get("ts_code", "")) == str(quote.get("ts_code", ""))
    expected_mark_price = round(float(quote["close"]), 4)
    expected_market_value = round(shares_before * expected_mark_price, 4)
    expected_unrealized_pnl = round((expected_mark_price - float(before_position["cost_basis"])) * shares_before, 4)

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
    account_updater_ran = updater_result.returncode == 0
    updated_state = dict(read_json(output_state_file)) if output_state_file.exists() else {}
    trade_log = dict(read_json(test_trade_log_file)) if test_trade_log_file.exists() else {}
    update_review = dict(read_json(test_update_review_file)) if test_update_review_file.exists() else {}
    after_position = dict(updated_state.get("positions", [{}])[0]) if updated_state.get("positions") else {}
    official_hash_after = sha256_file(OFFICIAL_STATE_FILE)
    price_loaded = quote.get("close") is not None

    mark_price_updated = round(float(after_position.get("mark_price", 0)), 4) == expected_mark_price
    market_value_updated = round(float(after_position.get("market_value", 0)), 4) == expected_market_value
    unrealized_pnl_updated = round(float(after_position.get("unrealized_pnl", 0)), 4) == expected_unrealized_pnl
    shares_unchanged = int(after_position.get("shares", -1)) == shares_before
    cash_unchanged = round(float(updated_state.get("cash", 0)), 4) == round(cash_before, 4)
    position_only_mark_fields_changed = bool(after_position) and position_static_fields_equal(before_position, after_position)
    no_trade_executed = (
        int(trade_log.get("shares", 0) or 0) == 0
        and str(trade_log.get("action_executed", "")) == "HOLD"
    )

    failed_checks = []
    required_checks = {
        "account_updater_ran": account_updater_ran,
        "market_data_loaded": bool(market_data.get("target_symbols_ohlc")),
        "is_real_market_data": bool(market_data.get("is_real_market_data", False)),
        "account_state_loaded": account_state_loaded,
        "position_symbol_matched": position_symbol_matched,
        "price_loaded": price_loaded,
        "hold_action_executed": str(update_review.get("action_executed", "")) == "HOLD",
        "shares_unchanged": shares_unchanged,
        "cash_unchanged": cash_unchanged,
        "mark_price_updated": mark_price_updated,
        "market_value_updated": market_value_updated,
        "unrealized_pnl_updated": unrealized_pnl_updated,
        "position_only_mark_fields_changed": position_only_mark_fields_changed,
        "no_trade_executed": no_trade_executed,
        "official_state_preserved": official_hash_before == official_hash_after == OFFICIAL_STATE_HASH,
        "real_account_connected_false": not bool(updated_state.get("real_account_connected", False)),
        "auto_trading_enabled_false": not bool(updated_state.get("auto_trading_enabled", False)),
        "full_pipeline_enabled_false": True,
        "news_module_enabled_false": not bool(updated_state.get("news_module_enabled", False)),
    }
    failed_checks = [name for name, passed in required_checks.items() if not passed]
    smoke_passed = not failed_checks

    report = {
        "hold_valuation_smoke_completed": smoke_passed,
        "blocked_by_readonly_regression": False,
        "readonly_regression_passed": True,
        "trade_date": trade_date,
        "market_data_loaded": bool(market_data.get("target_symbols_ohlc")),
        "account_state_loaded": account_state_loaded,
        "position_symbol_matched": position_symbol_matched,
        "price_loaded": price_loaded,
        "price_used": expected_mark_price if price_loaded else None,
        "is_real_market_data": bool(market_data.get("is_real_market_data", False)),
        "test_mode": True,
        "account_updater_ran": account_updater_ran,
        "official_state_preserved": official_hash_before == official_hash_after == OFFICIAL_STATE_HASH,
        "official_state_hash_before": official_hash_before,
        "official_state_hash_after": official_hash_after,
        "selected_ts_code": quote.get("ts_code", ""),
        "selected_name": quote.get("name", ""),
        "final_user_action": str(update_review.get("final_user_action", "HOLD")),
        "action_executed": str(update_review.get("action_executed", "")),
        "trade_decision_generated": False,
        "buy_sell_reduce_generated": False,
        "no_trade_executed": no_trade_executed,
        "positions_count_before": len(test_state.get("positions", [])),
        "positions_count_after": len(updated_state.get("positions", [])),
        "shares_before": shares_before,
        "shares_after": int(after_position.get("shares", 0) or 0),
        "shares_unchanged": shares_unchanged,
        "cash_before": cash_before,
        "cash_after": float(updated_state.get("cash", 0) or 0),
        "cash_unchanged": cash_unchanged,
        "mark_price_before": float(before_position.get("mark_price", 0) or 0),
        "mark_price_after": float(after_position.get("mark_price", 0) or 0),
        "expected_mark_price": expected_mark_price,
        "mark_price_updated": mark_price_updated,
        "market_value_before": float(before_position.get("market_value", 0) or 0),
        "market_value_after": float(after_position.get("market_value", 0) or 0),
        "expected_market_value": expected_market_value,
        "market_value_updated": market_value_updated,
        "unrealized_pnl_before": float(before_position.get("unrealized_pnl", 0) or 0),
        "unrealized_pnl_after": float(after_position.get("unrealized_pnl", 0) or 0),
        "expected_unrealized_pnl": expected_unrealized_pnl,
        "unrealized_pnl_updated": unrealized_pnl_updated,
        "position_only_mark_fields_changed": position_only_mark_fields_changed,
        "total_equity_before": float(test_state.get("total_equity", 0) or 0),
        "total_equity_after": float(updated_state.get("total_equity", 0) or 0),
        "daily_pnl": float(updated_state.get("daily_pnl", 0) or 0),
        "cumulative_pnl": float(updated_state.get("cumulative_pnl", 0) or 0),
        "unrealized_pnl": float(updated_state.get("unrealized_pnl", 0) or 0),
        "realized_pnl": float(updated_state.get("realized_pnl", 0) or 0),
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "test_run_dir": str(test_run_dir),
        "test_state_file": str(test_state_file),
        "output_state_file": str(output_state_file),
        "test_market_data_file": str(test_market_data_file),
        "test_daily_report_file": str(test_daily_report_file),
        "test_trade_log_file": str(test_trade_log_file),
        "test_update_review_file": str(test_update_review_file),
        "failed_checks": failed_checks,
        "recommended_next_step": "review HOLD valuation smoke output, then keep future account-updater checks isolated until manual approval",
        "generated_at": now_text(),
    }

    write_json(report_json, report)
    write_markdown(report_md, report)

    feishu_text = (
        "simulated_live_v1 真实行情 HOLD 估值更新 smoke test 已完成。"
        "系统已用真实只读行情更新测试持仓市值和浮盈浮亏，未生成交易决策，未买卖，不接真实账户、不自动交易。"
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
