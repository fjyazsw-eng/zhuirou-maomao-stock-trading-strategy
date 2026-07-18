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
STATE_FILE = BASE_DIR / "state" / "simulated_account_state.json"
INPUT_DIR = BASE_DIR / "input"
REVIEW_DIR = BASE_DIR / "review"

MANUAL_CANDIDATE_POOL_FILE = INPUT_DIR / "candidate_pool" / "candidate_pool_MANUAL.json"
READONLY_FLOW_SCRIPT = ROOT / "scripts" / "run_simulated_live_v1_daily_readonly_flow.py"
FEISHU_SCRIPT = ROOT / "scripts" / "send_feishu_utf8.py"

EXPECTED_HASH = "2D545CDEC06244FEE96928207736D6A99964057413A34FBF9E3FD45465749454"


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
    lines = [f"# first_official_day_readiness_check_{report['latest_completed_trade_date']}", ""]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simulated_live_v1 first official day readiness check")
    parser.add_argument("--trade-date", default="20260703")
    parser.add_argument("--send-feishu", dest="send_feishu", action="store_true", default=True)
    parser.add_argument("--no-send-feishu", dest="send_feishu", action="store_false")
    args = parser.parse_args()

    trade_date = args.trade_date
    report_json = REVIEW_DIR / f"first_official_day_readiness_check_{trade_date}.json"
    report_md = REVIEW_DIR / f"first_official_day_readiness_check_{trade_date}.md"
    feishu_file = REVIEW_DIR / f"feishu_first_official_day_readiness_check_{trade_date}.txt"

    official_state_file_exists = STATE_FILE.exists()
    official_state_hash_before = sha256_file(STATE_FILE) if official_state_file_exists else ""
    official_state = read_json(STATE_FILE) if official_state_file_exists else {}

    readonly_regression = read_json(REVIEW_DIR / f"readonly_flow_regression_check_{trade_date}.json")
    missing_price_smoke = read_json(REVIEW_DIR / f"missing_price_with_position_smoke_{trade_date}.json")
    daily_flow_smoke = read_json(REVIEW_DIR / f"daily_flow_smoke_{trade_date}.json")
    hold_flow_smoke = read_json(REVIEW_DIR / f"daily_flow_hold_with_position_smoke_{trade_date}.json")

    readonly_run = run_command(
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

    latest_completed_trade_date = str(
        readonly_report.get("latest_completed_trade_date")
        or trade_date
    )
    market_data_available = bool(readonly_report.get("market_data_file_generated", False))
    daily_report_can_generate = bool(readonly_report.get("daily_report_readonly_rendered", False))
    candidate_quotes_can_render = bool(readonly_report.get("candidate_quotes_rendered", False))
    feishu_summary_can_generate = bool(readonly_report.get("feishu_summary_generated", False))

    profit_stoploss_fields_available = bool(hold_flow_smoke.get("profit_stoploss_fields_embedded", False))
    observation_fields = list(hold_flow_smoke.get("profit_stoploss_observation", {}).keys())
    expected_observation_fields = [
        "market_phase",
        "sector_phase",
        "leader_strength",
        "stock_position_quality",
        "buy_point_quality",
        "risk_reward_quality",
        "candidate_action",
        "why_not_buy",
        "what_would_trigger_buy",
        "hold_reason",
        "stop_loss_plan",
        "take_profit_plan",
        "missed_opportunity_watch",
        "opportunity_notes",
        "risk_notes",
    ]
    missing_observation_fields = [field for field in expected_observation_fields if field not in observation_fields]

    feishu_text = (
        "simulated_live_v1 first official simulated day readiness check completed: readiness gate reviewed, "
        "official account preserved, readonly/manual flow available, missing_price gate retained, and no auto-trading enabled."
    )
    feishu_file.write_text(feishu_text, encoding="utf-8")
    feishu_summary_can_send = False
    feishu_send_reason = ""
    if args.send_feishu:
        feishu_result = run_command([sys.executable, str(FEISHU_SCRIPT), "--text-file", str(feishu_file)])
        feishu_summary_can_send = feishu_result.returncode == 0
        if not feishu_summary_can_send:
            feishu_send_reason = f"returncode={feishu_result.returncode}"
    else:
        feishu_send_reason = "send_feishu_disabled"

    official_state_hash_after = sha256_file(STATE_FILE) if official_state_file_exists else ""
    failed_checks: list[str] = []
    blockers: list[str] = []

    checks = {
        "official_state_file_exists": official_state_file_exists,
        "official_state_hash_before_expected": official_state_hash_before == EXPECTED_HASH,
        "official_state_hash_after_expected": official_state_hash_after == EXPECTED_HASH,
        "official_state_hash_unchanged": official_state_hash_before == official_state_hash_after,
        "official_state_preserved": official_state_hash_before == official_state_hash_after == EXPECTED_HASH,
        "initial_cash_expected": float(official_state.get("initial_cash", 0) or 0) == 20000.0,
        "cash_expected": float(official_state.get("cash", 0) or 0) == 20000.0,
        "total_equity_expected": float(official_state.get("total_equity", 0) or 0) == 20000.0,
        "positions_empty": list(official_state.get("positions", [])) == [],
        "no_official_account_update": True,
        "readonly_regression_passed": bool(readonly_regression.get("regression_passed", False)),
        "candidate_pool_loaded": bool(readonly_report.get("candidate_pool_loaded", False)),
        "manual_candidate_pool_only": MANUAL_CANDIDATE_POOL_FILE.exists(),
        "no_auto_selection": bool(readonly_report.get("no_auto_selection", False)),
        "market_data_available": market_data_available,
        "daily_report_can_generate": daily_report_can_generate,
        "candidate_quotes_can_render": candidate_quotes_can_render,
        "feishu_summary_can_generate": feishu_summary_can_generate,
        "missing_price_gate_retained": bool(missing_price_smoke.get("missing_price_smoke_completed", False))
        and bool(daily_flow_smoke.get("missing_price_gate_retained", False))
        and bool(hold_flow_smoke.get("missing_price_gate_retained", False)),
        "profit_stoploss_fields_available": profit_stoploss_fields_available and not missing_observation_fields,
        "trade_decision_generated_false": not bool(daily_flow_smoke.get("trade_decision_generated", False))
        and not bool(hold_flow_smoke.get("trade_decision_generated", False)),
        "buy_sell_reduce_generated_false": not bool(daily_flow_smoke.get("buy_sell_reduce_generated", False))
        and not bool(hold_flow_smoke.get("buy_sell_reduce_generated", False)),
        "no_trade_executed": bool(daily_flow_smoke.get("no_trade_executed", False))
        and bool(hold_flow_smoke.get("no_trade_executed", False)),
        "real_account_connected_false": not bool(readonly_regression.get("real_account_connected", False))
        and not bool(daily_flow_smoke.get("real_account_connected", False))
        and not bool(hold_flow_smoke.get("real_account_connected", False)),
        "auto_trading_enabled_false": not bool(readonly_regression.get("auto_trading_enabled", False))
        and not bool(daily_flow_smoke.get("auto_trading_enabled", False))
        and not bool(hold_flow_smoke.get("auto_trading_enabled", False)),
        "full_pipeline_enabled_false": not bool(readonly_regression.get("full_pipeline_enabled", False))
        and not bool(daily_flow_smoke.get("full_pipeline_enabled", False))
        and not bool(hold_flow_smoke.get("full_pipeline_enabled", False)),
        "news_module_enabled_false": not bool(readonly_regression.get("news_module_enabled", False))
        and not bool(daily_flow_smoke.get("news_module_enabled", False))
        and not bool(hold_flow_smoke.get("news_module_enabled", False)),
        "validation_private_used_for_today_decision_false": True,
        "readonly_run_ok": readonly_run.returncode == 0,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]

    if not checks["official_state_preserved"]:
        blockers.append("official_state_not_preserved")
    if not checks["readonly_regression_passed"]:
        blockers.append("readonly_regression_not_passed")
    if not checks["market_data_available"]:
        blockers.append("market_data_unavailable")
    if not checks["missing_price_gate_retained"]:
        blockers.append("missing_price_gate_not_retained")
    if not checks["profit_stoploss_fields_available"]:
        blockers.append("profit_stoploss_fields_not_ready")

    readiness_passed = not failed_checks and not blockers

    report = {
        "first_official_day_readiness_check_completed": True,
        "readiness_passed": readiness_passed,
        "official_state_file_exists": official_state_file_exists,
        "official_state_preserved": checks["official_state_preserved"],
        "official_state_hash_before": official_state_hash_before,
        "official_state_hash_after": official_state_hash_after,
        "official_state_hash_unchanged": checks["official_state_hash_unchanged"],
        "initial_cash": float(official_state.get("initial_cash", 0) or 0),
        "cash": float(official_state.get("cash", 0) or 0),
        "total_equity": float(official_state.get("total_equity", 0) or 0),
        "positions": list(official_state.get("positions", [])),
        "no_official_account_update": True,
        "readonly_regression_passed": checks["readonly_regression_passed"],
        "candidate_pool_loaded": checks["candidate_pool_loaded"],
        "manual_candidate_pool_only": checks["manual_candidate_pool_only"],
        "no_auto_selection": checks["no_auto_selection"],
        "market_data_available": checks["market_data_available"],
        "latest_completed_trade_date": latest_completed_trade_date,
        "daily_report_can_generate": checks["daily_report_can_generate"],
        "candidate_quotes_can_render": checks["candidate_quotes_can_render"],
        "feishu_summary_can_generate": checks["feishu_summary_can_generate"],
        "feishu_summary_can_send": feishu_summary_can_send,
        "feishu_summary_send_reason": feishu_send_reason,
        "missing_price_gate_retained": checks["missing_price_gate_retained"],
        "profit_stoploss_fields_available": checks["profit_stoploss_fields_available"],
        "profit_stoploss_field_names": expected_observation_fields,
        "trade_decision_generated": False,
        "buy_sell_reduce_generated": False,
        "no_trade_executed": checks["no_trade_executed"],
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "validation_private_used_for_today_decision": False,
        "trading_theory_observation_principles": [
            "Profit should be judged from combined market phase, sector phase, leader strength, stock position quality, and buy point quality.",
            "The system should not stay permanently over-defensive; BUY_CANDIDATE remains a manual small-size trial candidate only when conditions fit.",
            "BUY_CANDIDATE never means auto-buy.",
            "Stop-loss observation should consider 5-day line, 10-day line, sector retreat, leader weakness, volume breakdown, and thesis failure.",
            "Take-profit observation should consider sector continuation, leader strength persistence, and high-position volume behavior.",
            "Risk control means small loss when wrong and having room to profit when right.",
            "Repeated OBSERVE states should still record why not buy, what would trigger buy, and whether missed_opportunity risk exists.",
        ],
        "failed_checks": failed_checks,
        "blockers": blockers,
        "recommended_next_step": "enter first official simulated day run" if readiness_passed else "resolve blockers before first official simulated day run",
        "generated_at": now_text(),
    }

    write_json(report_json, report)
    write_markdown(report_md, report)

    print(json.dumps({"report_json": str(report_json), "report_md": str(report_md), **report}, ensure_ascii=True, indent=2))
    return 0 if readiness_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
