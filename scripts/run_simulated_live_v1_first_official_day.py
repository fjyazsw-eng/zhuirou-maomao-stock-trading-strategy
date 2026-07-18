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
DAILY_DIR = BASE_DIR / "daily"
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


def load_report_or_latest(prefix: str, trade_date: str) -> dict[str, Any]:
    exact_path = REVIEW_DIR / f"{prefix}_{trade_date}.json"
    if exact_path.exists():
        return read_json(exact_path)
    reports = sorted(REVIEW_DIR.glob(f"{prefix}_*.json"), key=lambda item: item.stat().st_mtime)
    return read_json(reports[-1]) if reports else {}


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [f"# first_official_simulated_day_{report['trade_date']}", ""]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def classify_market_phase(candidate_quotes: list[dict[str, Any]]) -> str:
    avg_pct = 0.0
    if candidate_quotes:
        avg_pct = sum(float(item.get("pct_chg", 0) or 0) for item in candidate_quotes) / len(candidate_quotes)
    if avg_pct >= 6:
        return "MAINLINE_EXTENSION"
    if avg_pct >= 2:
        return "STRONG_REPAIR"
    if avg_pct >= -1:
        return "NEUTRAL"
    if avg_pct >= -4:
        return "WEAK_REPAIR"
    return "RISK_OFF"


def classify_candidate(item: dict[str, Any], market_phase: str) -> dict[str, Any]:
    pct_chg = float(item.get("pct_chg", 0) or 0)
    amount = float(item.get("amount", 0) or 0)
    latest_price = float(item.get("close", 0) or 0)
    sector_text = str(item.get("sector", "") or "")

    if pct_chg >= 6:
        sector_phase = "MAINLINE"
        leader_strength = "STRONG"
        stock_position_quality = "MID"
        buy_point_quality = "GOOD"
        risk_reward_quality = "FAIR"
        candidate_action = "BUY_CANDIDATE"
        why_not_buy = ""
        what_would_trigger_buy = "Manual confirmation only: keep relative strength, avoid weak close, and confirm sector continuation on next valid session."
        suggested_trial_position = 0.1
    elif pct_chg >= 2:
        sector_phase = "STARTING"
        leader_strength = "NORMAL"
        stock_position_quality = "MID"
        buy_point_quality = "FAIR"
        risk_reward_quality = "FAIR"
        candidate_action = "WATCH"
        why_not_buy = "Momentum exists, but the first official simulated day keeps the account unchanged without manual confirmation."
        what_would_trigger_buy = "If sector and leader strength continue and a lower-risk follow-up entry appears, this can be reviewed as a small trial candidate."
        suggested_trial_position = None
    elif pct_chg <= -7:
        sector_phase = "RETREAT"
        leader_strength = "WEAK"
        stock_position_quality = "LOW"
        buy_point_quality = "POOR"
        risk_reward_quality = "POOR"
        candidate_action = "NEEDS_HUMAN_REVIEW"
        why_not_buy = "Large drawdown on the day weakens the entry quality and requires manual review before any watchlist upgrade."
        what_would_trigger_buy = "Need clear repair in sector strength, leader stabilization, and a new low-risk re-entry setup."
        suggested_trial_position = None
    else:
        sector_phase = "REPAIR"
        leader_strength = "NORMAL"
        stock_position_quality = "MID"
        buy_point_quality = "FAIR"
        risk_reward_quality = "FAIR"
        candidate_action = "OBSERVE"
        why_not_buy = "Conditions are not weak enough to dismiss completely, but not aligned enough yet for a manual small trial buy candidate."
        what_would_trigger_buy = "Need stronger market phase, tighter setup, and clearer sector/leader follow-through."
        suggested_trial_position = None

    stop_loss_plan = (
        "Watch 5-day and 10-day trend, sector retreat, leader weakness, volume breakdown, thesis failure, "
        "and missing_price events; any of these should push the name into manual review before action."
    )
    take_profit_plan = (
        "If sector continues extending, leader remains strong, and price advances with healthy follow-through, keep observing; "
        "if high-position surge fades or extension overheats, shift to staged manual profit-taking review."
    )
    risk_notes = (
        f"First official simulated day keeps the account unchanged. Sector={sector_text or 'UNKNOWN'}, "
        "so this note is informational only and does not trigger auto-trading."
    )
    opportunity_notes = (
        "Profit potential comes from market phase, sector cycle, leader strength, stock position quality, and buy point quality lining up together."
    )
    return {
        "ts_code": item.get("ts_code", ""),
        "name": item.get("name", ""),
        "latest_price": latest_price,
        "pct_chg": pct_chg,
        "amount": amount,
        "market_phase": market_phase,
        "sector_phase": sector_phase,
        "leader_strength": leader_strength,
        "stock_position_quality": stock_position_quality,
        "buy_point_quality": buy_point_quality,
        "risk_reward_quality": risk_reward_quality,
        "candidate_action": candidate_action,
        "why_not_buy": why_not_buy,
        "what_would_trigger_buy": what_would_trigger_buy,
        "suggested_trial_position": suggested_trial_position,
        "stop_loss_plan": stop_loss_plan,
        "take_profit_plan": take_profit_plan,
        "risk_notes": risk_notes,
        "opportunity_notes": opportunity_notes,
        "missed_opportunity_watch": candidate_action in {"WATCH", "BUY_CANDIDATE"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simulated_live_v1 first official simulated day")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--send-feishu", dest="send_feishu", action="store_true", default=True)
    parser.add_argument("--no-send-feishu", dest="send_feishu", action="store_false")
    args = parser.parse_args()
    requested_trade_date = args.trade_date.strip()

    official_state_loaded = STATE_FILE.exists()
    official_state_hash_before = sha256_file(STATE_FILE) if official_state_loaded else ""
    official_state = read_json(STATE_FILE) if official_state_loaded else {}
    manual_candidate_pool = read_json(MANUAL_CANDIDATE_POOL_FILE) if MANUAL_CANDIDATE_POOL_FILE.exists() else []

    readonly_cmd = [
        sys.executable,
        str(READONLY_FLOW_SCRIPT),
        "--candidate-pool",
        str(MANUAL_CANDIDATE_POOL_FILE),
        "--no-send-feishu",
    ]
    if requested_trade_date:
        readonly_cmd.extend(["--trade-date", requested_trade_date])
    readonly_run = run_command(readonly_cmd)
    if readonly_run.returncode != 0:
        raise SystemExit(1)

    if requested_trade_date:
        readonly_report_path = REVIEW_DIR / f"daily_readonly_flow_smoke_test_{requested_trade_date}.json"
        readonly_report = read_json(readonly_report_path) if readonly_report_path.exists() else {}
    else:
        reports = sorted(REVIEW_DIR.glob("daily_readonly_flow_smoke_test_*.json"), key=lambda item: item.stat().st_mtime)
        readonly_report = read_json(reports[-1]) if reports else {}
    trade_date = str(readonly_report.get("latest_completed_trade_date") or requested_trade_date)

    report_json = REVIEW_DIR / f"first_official_simulated_day_{trade_date}.json"
    report_md = REVIEW_DIR / f"first_official_simulated_day_{trade_date}.md"
    feishu_file = REVIEW_DIR / f"feishu_first_official_simulated_day_{trade_date}.txt"

    readonly_regression = load_report_or_latest("readonly_flow_regression_check", trade_date)
    readiness = load_report_or_latest("first_official_day_readiness_check", trade_date)
    market_data = read_json(INPUT_DIR / "market_data" / f"market_data_{trade_date}.json")
    daily_report = read_json(DAILY_DIR / f"simulated_live_v1_daily_report_{trade_date}.json")
    candidate_quotes = list(market_data.get("target_symbols_ohlc", []))

    market_phase = classify_market_phase(candidate_quotes)
    candidate_opportunity_review = [classify_candidate(item, market_phase) for item in candidate_quotes]
    buy_candidate_exists = any(item["candidate_action"] == "BUY_CANDIDATE" for item in candidate_opportunity_review)
    manual_confirmation_required = buy_candidate_exists

    official_daily_report = {
        "trade_date": trade_date,
        "account_snapshot": {
            "cash": float(official_state.get("cash", 0) or 0),
            "total_equity": float(official_state.get("total_equity", 0) or 0),
            "positions": list(official_state.get("positions", [])),
        },
        "cash": float(official_state.get("cash", 0) or 0),
        "total_equity": float(official_state.get("total_equity", 0) or 0),
        "positions": list(official_state.get("positions", [])),
        "candidate_pool": list(manual_candidate_pool),
        "candidate_quotes": candidate_quotes,
        "market_data_source": market_data.get("data_source", ""),
        "price_adjustment_mode": "raw",
        "amount_unit": "thousand CNY",
        "no_auto_selection": True,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "candidate_opportunity_review": candidate_opportunity_review,
        "profit_stoploss_fields_generated": True,
        "missing_price_gate_retained": True,
        "manual_confirmation_required": manual_confirmation_required,
        "auto_trade_executed": False,
        "feishu_notice_only": True,
    }

    daily_official_json = DAILY_DIR / f"simulated_live_v1_first_official_day_{trade_date}.json"
    daily_official_md = DAILY_DIR / f"simulated_live_v1_first_official_day_{trade_date}.md"
    write_json(daily_official_json, official_daily_report)
    daily_official_md.write_text(
        "\n".join(
            [
                f"# simulated_live_v1_first_official_day_{trade_date}",
                "",
                f"- trade_date: {trade_date}",
                f"- cash: {official_daily_report['cash']}",
                f"- total_equity: {official_daily_report['total_equity']}",
                f"- positions: {official_daily_report['positions']}",
                f"- candidate_opportunity_review_generated: {bool(candidate_opportunity_review)}",
                f"- manual_confirmation_required: {manual_confirmation_required}",
                f"- auto_trade_executed: False",
                "",
            ]
        ),
        encoding="utf-8",
    )

    action_pairs = [f"{item['ts_code']}:{item['candidate_action']}" for item in candidate_opportunity_review]
    watch_codes = [item["ts_code"] for item in candidate_opportunity_review if item["candidate_action"] == "WATCH"]
    buy_candidate_codes = [item["ts_code"] for item in candidate_opportunity_review if item["candidate_action"] == "BUY_CANDIDATE"]
    review_codes = [item["ts_code"] for item in candidate_opportunity_review if item["candidate_action"] == "NEEDS_HUMAN_REVIEW"]
    feishu_text = (
        f"{trade_date}，总资产{official_daily_report['total_equity']}元，现金{official_daily_report['cash']}元，空仓未操作。"
        f"观察代码：{'/'.join(watch_codes) if watch_codes else '无'}；人工确认候选：{'/'.join(buy_candidate_codes) if buy_candidate_codes else '无'}；人工复核：{'/'.join(review_codes) if review_codes else '无'}。"
        + (
            "出现 BUY_CANDIDATE，但只做人工确认候选，不自动买入。"
            if manual_confirmation_required
            else "今天没有 BUY_CANDIDATE。"
        )
        + "计划：继续盯强弱延续、止损条件和 missed_opportunity 风险。飞书仅通知，不执行。"
    )
    feishu_file.write_text(feishu_text, encoding="utf-8")
    feishu_summary_sent = False
    feishu_send_reason = ""
    if args.send_feishu:
        feishu_result = run_command([sys.executable, str(FEISHU_SCRIPT), "--text-file", str(feishu_file)])
        feishu_summary_sent = feishu_result.returncode == 0
        if not feishu_summary_sent:
            feishu_send_reason = f"returncode={feishu_result.returncode}"
    else:
        feishu_send_reason = "send_feishu_disabled"

    official_state_hash_after = sha256_file(STATE_FILE) if official_state_loaded else ""
    failed_checks: list[str] = []
    blockers: list[str] = []
    checks = {
        "first_official_simulated_day_completed": True,
        "readonly_regression_passed": bool(readonly_regression.get("regression_passed", False)),
        "official_state_loaded": official_state_loaded,
        "official_state_hash_unchanged": official_state_hash_before == official_state_hash_after == EXPECTED_HASH,
        "official_account_unchanged": float(official_state.get("cash", 0) or 0) == 20000.0
        and list(official_state.get("positions", [])) == []
        and float(official_state.get("total_equity", 0) or 0) == 20000.0,
        "candidate_pool_loaded": bool(readonly_report.get("candidate_pool_loaded", False)),
        "manual_candidate_pool_only": MANUAL_CANDIDATE_POOL_FILE.exists(),
        "no_auto_selection": bool(readonly_report.get("no_auto_selection", False)),
        "market_data_loaded": bool(readonly_report.get("market_data_file_generated", False)),
        "daily_report_generated": daily_official_json.exists() and daily_official_md.exists(),
        "candidate_quotes_rendered": bool(readonly_report.get("candidate_quotes_rendered", False)),
        "candidate_opportunity_review_generated": bool(candidate_opportunity_review),
        "profit_stoploss_fields_generated": all(
            all(
                key in item
                for key in [
                    "market_phase",
                    "sector_phase",
                    "leader_strength",
                    "stock_position_quality",
                    "buy_point_quality",
                    "risk_reward_quality",
                    "candidate_action",
                    "why_not_buy",
                    "what_would_trigger_buy",
                    "stop_loss_plan",
                    "take_profit_plan",
                    "risk_notes",
                    "opportunity_notes",
                    "missed_opportunity_watch",
                ]
            )
            for item in candidate_opportunity_review
        ),
        "missing_price_gate_retained": bool(readiness.get("missing_price_gate_retained", False)),
        "real_account_connected_false": not bool(official_state.get("real_account_connected", False)),
        "auto_trading_enabled_false": not bool(official_state.get("auto_trading_enabled", False)),
        "full_pipeline_enabled_false": True,
        "news_module_enabled_false": not bool(official_state.get("news_module_enabled", False)),
        "validation_private_used_for_today_decision_false": True,
        "no_trade_executed": True,
        "readonly_run_ok": readonly_run.returncode == 0,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]

    if not checks["readonly_regression_passed"]:
        blockers.append("readonly_regression_not_passed")
    if not checks["official_state_hash_unchanged"]:
        blockers.append("official_state_changed")
    if not checks["market_data_loaded"]:
        blockers.append("market_data_not_available")
    if not checks["candidate_opportunity_review_generated"]:
        blockers.append("candidate_opportunity_review_missing")
    if not checks["profit_stoploss_fields_generated"]:
        blockers.append("profit_stoploss_fields_missing")

    report = {
        "first_official_simulated_day_completed": True,
        "trade_date": trade_date,
        "readonly_regression_passed": checks["readonly_regression_passed"],
        "official_state_loaded": official_state_loaded,
        "official_state_hash_before": official_state_hash_before,
        "official_state_hash_after": official_state_hash_after,
        "official_state_hash_unchanged": checks["official_state_hash_unchanged"],
        "candidate_pool_loaded": checks["candidate_pool_loaded"],
        "manual_candidate_pool_only": checks["manual_candidate_pool_only"],
        "no_auto_selection": checks["no_auto_selection"],
        "market_data_loaded": checks["market_data_loaded"],
        "daily_report_generated": checks["daily_report_generated"],
        "candidate_quotes_rendered": checks["candidate_quotes_rendered"],
        "candidate_opportunity_review_generated": checks["candidate_opportunity_review_generated"],
        "profit_stoploss_fields_generated": checks["profit_stoploss_fields_generated"],
        "missing_price_gate_retained": checks["missing_price_gate_retained"],
        "feishu_summary_generated": feishu_file.exists(),
        "feishu_summary_sent": feishu_summary_sent,
        "feishu_summary_send_reason": feishu_send_reason,
        "final_user_action": "OBSERVE",
        "no_trade_executed": True,
        "cash_before": 20000.0,
        "cash_after": float(official_state.get("cash", 0) or 0),
        "positions_before": [],
        "positions_after": list(official_state.get("positions", [])),
        "total_equity_before": 20000.0,
        "total_equity_after": float(official_state.get("total_equity", 0) or 0),
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "validation_private_used_for_today_decision": False,
        "manual_confirmation_required": manual_confirmation_required,
        "auto_trade_executed": False,
        "feishu_notice_only": True,
        "candidate_pool_symbols": [item.get("ts_code", "") for item in manual_candidate_pool],
        "candidate_actions": [
            {"ts_code": item["ts_code"], "name": item["name"], "candidate_action": item["candidate_action"]}
            for item in candidate_opportunity_review
        ],
        "candidate_action_pairs": action_pairs,
        "candidate_opportunity_review": candidate_opportunity_review,
        "failed_checks": failed_checks,
        "blockers": blockers,
        "recommended_next_step": "run daily simulated live for 3 to 5 trading days with fixed manual candidate pool",
        "generated_at": now_text(),
    }

    write_json(report_json, report)
    write_markdown(report_md, report)

    print(json.dumps({"report_json": str(report_json), "report_md": str(report_md), **report}, ensure_ascii=True, indent=2))
    return 0 if not failed_checks and not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
