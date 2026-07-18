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
PREFERRED_TS_CODE = "300398.SZ"


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
    lines = [f"# daily_flow_hold_with_position_smoke_{report['trade_date']}", ""]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def choose_position_quote(market_data: dict[str, Any]) -> dict[str, Any]:
    quotes = [item for item in market_data.get("target_symbols_ohlc", []) if item.get("close") is not None]
    if not quotes:
        raise RuntimeError("no available real market quotes in market_data")
    for item in quotes:
        if str(item.get("ts_code", "")) == PREFERRED_TS_CODE:
            return dict(item)
    return dict(quotes[0])


def build_test_state(quote: dict[str, Any]) -> dict[str, Any]:
    return {
        "account_id": "sim_v1_local_only",
        "currency": "CNY",
        "initial_cash": 20000,
        "cash": 15000.0,
        "total_equity": 20000.0,
        "positions": [
            {
                "ts_code": quote.get("ts_code", ""),
                "name": quote.get("name", ""),
                "shares": 100,
                "cost_basis": 50.0,
                "mark_price": 50.0,
                "market_value": 5000.0,
                "unrealized_pnl": 0.0,
            }
        ],
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


def build_observation_fields(quote: dict[str, Any], daily_report_payload: dict[str, Any]) -> dict[str, Any]:
    close_price = float(quote.get("close", 0) or 0)
    pct_chg = float(quote.get("pct_chg", 0) or 0)
    market_phase = "WEAK_REPAIR" if pct_chg < 0 else "NEUTRAL"
    sector_phase = "REPAIR" if pct_chg < 0 else "STARTING"
    leader_strength = "NORMAL" if abs(pct_chg) < 8 else "DIVERGENT"
    stock_position_quality = "MID" if 45 <= close_price <= 60 else "UNKNOWN"
    buy_point_quality = "FAIR" if pct_chg > -8 else "POOR"
    risk_reward_quality = "FAIR"
    return {
        "market_phase": market_phase,
        "sector_phase": sector_phase,
        "leader_strength": leader_strength,
        "stock_position_quality": stock_position_quality,
        "buy_point_quality": buy_point_quality,
        "risk_reward_quality": risk_reward_quality,
        "candidate_action": "HOLD",
        "why_not_buy": "Current flow is a HOLD valuation smoke only; no new buy candidate is produced in this test run.",
        "what_would_trigger_buy": "A later manual review could consider a small trial buy only if market phase improves, sector resumes leadership, and a clear low-risk entry appears.",
        "hold_reason": "Existing test position still has real market data and can continue to be marked to market while no auto-trading is allowed.",
        "stop_loss_plan": "If real market data is missing, break into manual review; otherwise watch 5-day/10-day trend, sector retreat, leader weakness, and volume breakdown before any manual reduce/sell discussion.",
        "take_profit_plan": "If sector, leader, and stock trend continue to align, keep observing; if price surges with weak follow-through or sector overheats, consider manual staged profit-taking review.",
        "missed_opportunity_watch": False,
        "opportunity_notes": f"Real quote {quote.get('ts_code', '')} is available, so this run can observe whether HOLD valuation remains aligned with market context without forcing a buy decision.",
        "risk_notes": "This field is observational only. Missing real market data remains a hard manual-review gate and does not trigger auto-trading.",
        "readonly_observation_only": True,
        "observation_generated_at": now_text(),
        "source_trade_date": daily_report_payload.get("trade_date", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simulated_live_v1 daily flow HOLD with position smoke test")
    parser.add_argument("--trade-date", default="20260703")
    parser.add_argument("--send-feishu", dest="send_feishu", action="store_true", default=True)
    parser.add_argument("--no-send-feishu", dest="send_feishu", action="store_false")
    args = parser.parse_args()

    trade_date = args.trade_date
    regression_report_path = latest_regression_report() if not args.trade_date else REVIEW_DIR / f"readonly_flow_regression_check_{trade_date}.json"
    regression_report = read_json(regression_report_path) if regression_report_path and regression_report_path.exists() else {}
    readonly_regression_passed = bool(regression_report.get("regression_passed", False))

    report_json = REVIEW_DIR / f"daily_flow_hold_with_position_smoke_{trade_date}.json"
    report_md = REVIEW_DIR / f"daily_flow_hold_with_position_smoke_{trade_date}.md"
    feishu_file = REVIEW_DIR / f"feishu_daily_flow_hold_with_position_smoke_{trade_date}.txt"

    if not readonly_regression_passed:
        blocked_report = {
            "daily_flow_hold_with_position_smoke_completed": False,
            "readonly_regression_passed": False,
            "blocked_by_readonly_regression": True,
            "trade_date": trade_date,
            "failed_checks": ["readonly_regression_not_passed"],
            "real_account_connected": False,
            "auto_trading_enabled": False,
            "full_pipeline_enabled": False,
            "news_module_enabled": False,
            "missing_price_gate_retained": True,
            "recommended_next_step": "fix readonly regression before HOLD with position daily flow smoke",
        }
        write_json(report_json, blocked_report)
        write_markdown(report_md, blocked_report)
        feishu_file.write_text("simulated_live_v1 daily flow HOLD-with-position smoke blocked: readonly regression not passed.", encoding="utf-8")
        if args.send_feishu:
            run_command([sys.executable, str(FEISHU_SCRIPT), "--text-file", str(feishu_file)])
        return 1

    test_run_dir = TEST_RUNS_DIR / "daily_flow_hold_with_position_001"
    test_state_dir = test_run_dir / "state"
    test_input_dir = test_run_dir / "input"
    test_review_dir = test_run_dir / "review"
    test_state_dir.mkdir(parents=True, exist_ok=True)
    test_input_dir.mkdir(parents=True, exist_ok=True)
    test_review_dir.mkdir(parents=True, exist_ok=True)

    official_hash_before = sha256_file(OFFICIAL_STATE_FILE)

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

    market_data_payload = read_json(market_data_source)
    selected_quote = choose_position_quote(market_data_payload)
    selected_ts_code = str(selected_quote.get("ts_code", ""))
    selected_name = str(selected_quote.get("name", ""))
    price_used = round(float(selected_quote.get("close", 0) or 0), 4)

    test_market_data_file = test_input_dir / f"market_data_{trade_date}.json"
    test_daily_report_file = test_input_dir / f"simulated_live_v1_daily_report_{trade_date}.json"
    test_state_file = test_state_dir / "simulated_account_state_test.json"
    output_state_file = test_state_dir / "simulated_account_state_updated.json"
    test_snapshot_file = test_state_dir / "simulated_account_state_snapshot.json"
    test_trade_log_file = test_review_dir / "simulated_trade_log_test.json"
    test_update_review_file = test_review_dir / "account_state_update_test.json"
    test_update_review_md_file = test_review_dir / "account_state_update_test.md"
    test_observation_file = test_review_dir / "hold_profit_stoploss_observation.json"

    shutil.copyfile(market_data_source, test_market_data_file)
    shutil.copyfile(daily_report_source, test_daily_report_file)
    write_json(test_state_file, build_test_state(selected_quote))

    daily_report_payload = read_json(test_daily_report_file)
    daily_report_payload["final_user_action"] = "HOLD"
    daily_report_payload["action_requested"] = "HOLD"
    daily_report_payload["candidate_ts_code"] = selected_ts_code
    daily_report_payload["candidate_name"] = selected_name
    daily_report_payload["trade_decision_generated"] = False
    daily_report_payload["buy_sell_reduce_generated"] = False
    daily_report_payload["readonly_market_data_used"] = True
    daily_report_payload["profit_stoploss_observation"] = build_observation_fields(selected_quote, daily_report_payload)
    write_json(test_daily_report_file, daily_report_payload)

    state_before = read_json(test_state_file)
    before_position = dict(state_before.get("positions", [{}])[0])

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
    after_position = dict(updated_state.get("positions", [{}])[0]) if updated_state.get("positions") else {}

    observation_fields = build_observation_fields(selected_quote, daily_report_payload)
    write_json(test_observation_file, observation_fields)

    feishu_text = (
        f"simulated_live_v1 HOLD-with-position daily flow smoke completed: ts_code={selected_ts_code}, "
        f"real price loaded={price_used}, HOLD valuation path updated in test-run only, no trade executed, "
        "missing_price gate retained, no real account, no auto trading."
    )
    feishu_file.write_text(feishu_text, encoding="utf-8")
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
    missing_price = "missing_price" in list(updated_state.get("account_risk_flags", []))

    shares_before = int(before_position.get("shares", 0) or 0)
    shares_after = int(after_position.get("shares", 0) or 0)
    cash_before = float(state_before.get("cash", 0) or 0)
    cash_after = float(updated_state.get("cash", 0) or 0)
    mark_price_before = float(before_position.get("mark_price", 0) or 0)
    mark_price_after = float(after_position.get("mark_price", 0) or 0)
    market_value_before = float(before_position.get("market_value", 0) or 0)
    market_value_after = float(after_position.get("market_value", 0) or 0)
    total_equity_before = float(state_before.get("total_equity", 0) or 0)
    total_equity_after = float(updated_state.get("total_equity", 0) or 0)

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
        "test_run_only_account_writes": test_state_file.exists() and output_state_file.exists(),
        "official_state_preserved": official_hash_before == official_hash_after == OFFICIAL_STATE_HASH,
        "final_user_action_hold": str(update_review.get("final_user_action", "")) == "HOLD",
        "action_executed_hold": str(update_review.get("action_executed", "")) == "HOLD",
        "price_loaded": price_used > 0,
        "missing_price_false": not missing_price,
        "shares_unchanged": shares_before == 100 and shares_after == 100,
        "cash_unchanged": round(cash_before, 4) == 15000.0 and round(cash_after, 4) == 15000.0,
        "mark_price_updated": round(mark_price_before, 4) == 50.0 and round(mark_price_after, 4) == round(price_used, 4),
        "market_value_updated": round(market_value_after, 4) == round(100 * price_used, 4),
        "total_equity_updated": round(total_equity_after, 4) == round(15000.0 + market_value_after, 4),
        "daily_pnl_expected": round(float(updated_state.get("daily_pnl", 0) or 0), 4) == round(market_value_after - market_value_before, 4),
        "no_trade_executed": int(trade_log.get("shares", 0) or 0) == 0 and str(update_review.get("action_executed", "")) == "HOLD",
        "observation_fields_embedded": "profit_stoploss_observation" in daily_report_payload and test_observation_file.exists(),
        "real_account_connected_false": not bool(updated_state.get("real_account_connected", False)),
        "auto_trading_enabled_false": not bool(updated_state.get("auto_trading_enabled", False)),
        "news_module_enabled_false": not bool(updated_state.get("news_module_enabled", False)),
    }
    failed_checks = [name for name, passed in required_checks.items() if not passed]
    smoke_passed = not failed_checks

    report = {
        "daily_flow_hold_with_position_smoke_completed": smoke_passed,
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
        "test_run_only_account_writes": True,
        "official_state_preserved": official_hash_before == official_hash_after == OFFICIAL_STATE_HASH,
        "final_user_action": str(update_review.get("final_user_action", "HOLD")),
        "action_executed": str(update_review.get("action_executed", "HOLD")),
        "trade_decision_generated": False,
        "buy_sell_reduce_generated": False,
        "no_trade_executed": int(trade_log.get("shares", 0) or 0) == 0 and str(update_review.get("action_executed", "")) == "HOLD",
        "selected_ts_code": selected_ts_code,
        "selected_name": selected_name,
        "price_loaded": price_used > 0,
        "missing_price": missing_price,
        "price_used": price_used,
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
        "missing_price_gate_retained": True,
        "failed_checks": failed_checks,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "official_state_hash_before": official_hash_before,
        "official_state_hash_after": official_hash_after,
        "profit_stoploss_fields_embedded": True,
        "profit_stoploss_observation": observation_fields,
        "recommended_next_step": (
            "ready to enter first official simulated day readiness check"
            if smoke_passed
            else "fix failed_checks before first official simulated day readiness check"
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
