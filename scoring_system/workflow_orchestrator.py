from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scoring_system.hexagram_calibration import calibrate_participation_level, write_hexagram_to_workflow_state
from scoring_system.systemic_risk_gate import SUSPENDED_STATUS, SYSTEMIC_ACTION
from scoring_system.workflow_state import (
    ROOT,
    STATE_JSON,
    load_state,
    save_state,
    update_section,
    validate_state,
)


HISTORY_ROOT = ROOT / "reports" / "workflow" / "history"

REVERSAL_STATES = {
    "NONE",
    "BOTTOMING_WATCH",
    "REVERSAL_WATCH",
    "REVERSAL_PROBE_ALLOWED",
    "REVERSAL_CONFIRMED",
    "REVERSAL_FAILED",
}

FINAL_INTRADAY_ACTIONS = {
    "BUY_PRIMARY_100",
    "BUY_BACKUP_100",
    "CAUTIOUS_PROBE_PRIMARY_100",
    "NO_NEW_BUY_SYSTEMIC_RISK",
    "NO_BUY_MARKET_VETO",
    "NO_BUY_SECTOR_VETO",
    "NO_BUY_STOCK_VETO",
    "NO_BUY_REVERSAL_UNCONFIRMED",
    "NO_BUY_DATA_UNRELIABLE",
}

REVERSAL_CONFIG = {
    "required_confirmation_count": 5,
    "required_signals": ("index_stabilization_detected",),
    "requires_one_of": ("sector_stabilization_detected", "core_stock_support_detected"),
    "confirmation_signals": (
        "panic_release_detected",
        "breadth_extreme_detected",
        "index_stabilization_detected",
        "sector_stabilization_detected",
        "core_stock_support_detected",
    ),
}


def _now(value: str | None = None) -> str:
    return value or datetime.now().isoformat(timespec="seconds")


def _trade_date_from_now(value: str) -> str:
    return value[:10].replace("-", "")


def _mark_completed(state: dict[str, Any], step: str) -> None:
    audit = state.setdefault("workflow_audit", {})
    completed = list(audit.get("completed_steps") or [])
    if step not in completed:
        completed.append(step)
    audit["completed_steps"] = completed


def _truth(value: Any) -> bool:
    return value is True or str(value).upper() == "TRUE"


def _unknown_if_missing(signals: dict[str, Any], key: str) -> Any:
    return signals[key] if key in signals else "UNKNOWN"


def _systemic_locked(state: dict[str, Any]) -> bool:
    gate = state.get("systemic_risk_gate") or {}
    execution = state.get("daily_execution_state") or {}
    return bool(gate.get("new_buy_locked") or execution.get("new_buy_locked"))


def _has_valid_hexagram(state: dict[str, Any]) -> bool:
    hexagram = state.get("hexagram_manual_input") or {}
    if hexagram.get("hexagram_status") != "PROVIDED":
        return False
    market = hexagram.get("market_hexagram_result")
    sectors = hexagram.get("sector_hexagram_results") or []
    items = []
    if isinstance(market, dict):
        items.append(market)
    items.extend(item for item in sectors if isinstance(item, dict))
    return any(item.get("validity_status") == "VALID" for item in items)


def decide_next_command(state: dict[str, Any], *, week_ended: bool = False) -> str:
    validate_state(state)
    stage = state["current_stage"]
    mapping = {
        "WEEKEND_REALITY_PENDING": "weekend",
        "WEEKEND_HEXAGRAM_PENDING": "hexagram",
        "WEEKLY_STRATEGY_READY": "weekly-strategy",
        "NIGHT_PLAN_READY": "night-plan",
        "INTRADAY_CHECK_PENDING": "intraday-check",
        "INTRADAY_CHECK_COMPLETED": "closing-review",
        "WEEKLY_REVIEW_COMPLETED": "weekend",
    }
    if stage == "CLOSING_REVIEW_COMPLETED":
        return "weekly-review" if week_ended else "night-plan"
    return mapping.get(stage, "validate")


def build_status(state: dict[str, Any], *, current_trade_date: str = "", week_ended: bool = False) -> dict[str, Any]:
    validate_state(state)
    completed = list((state.get("workflow_audit") or {}).get("completed_steps") or [])
    missing = []
    if not (state["weekend_reality_analysis"].get("market_state") or state["weekend_reality_analysis"].get("reality_summary")):
        missing.append("weekend_reality_analysis")
    if not _has_valid_hexagram(state):
        missing.append("hexagram_manual_input")
    if not state["weekly_strategy"].get("participation_level"):
        missing.append("weekly_strategy")
    if not state["night_plan"].get("plan_trade_date"):
        missing.append("night_plan")
    return {
        "current_stage": state["current_stage"],
        "current_trade_date": current_trade_date or state.get("latest_completed_trade_date", ""),
        "completed_steps": completed,
        "missing_steps": missing,
        "systemic_risk_level": state["systemic_risk_gate"].get("systemic_risk_level") or "",
        "new_buy_locked": _systemic_locked(state),
        "hexagram_valid": _has_valid_hexagram(state),
        "reversal_status": state["reversal_observation"].get("reversal_status"),
        "next_command": decide_next_command(state, week_ended=week_ended),
    }


def record_history(
    kind: str,
    trade_date: str,
    payload: dict[str, Any],
    *,
    history_root: Path = HISTORY_ROOT,
    now: str | None = None,
) -> Path:
    folder = history_root / trade_date
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{kind}.json"
    if path.exists():
        suffix = _now(now).replace(":", "").replace("-", "").replace("T", "_")
        candidate = folder / f"{kind}_{suffix}.json"
        counter = 2
        while candidate.exists():
            candidate = folder / f"{kind}_{suffix}_{counter}.json"
            counter += 1
        path = candidate
    record = {"recorded_at": _now(now), "kind": kind, "trade_date": trade_date, "payload": payload}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def complete_weekend_reality(state: dict[str, Any], reality: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    updates = {
        "market_state": reality.get("market_state", ""),
        "market_trend": reality.get("market_trend", ""),
        "market_risk_level": reality.get("market_risk_level", ""),
        "focus_sectors": list(reality.get("focus_sectors") or [])[:2],
        "excluded_sectors": list(reality.get("excluded_sectors") or []),
        "reality_summary": reality.get("reality_summary", ""),
        "source_report": reality.get("source_report", ""),
    }
    updated = update_section(state, "weekend_reality_analysis", updates, next_stage="WEEKEND_HEXAGRAM_PENDING", now=now)
    if reality.get("latest_completed_trade_date"):
        updated["latest_completed_trade_date"] = str(reality["latest_completed_trade_date"])
    reality_level = str(reality.get("reality_participation_level") or "")
    if reality_level:
        updated["weekly_strategy"]["participation_level"] = reality_level
    _mark_completed(updated, "weekend_reality")
    updated["updated_at"] = _now(now)
    validate_state(updated)
    return updated


def apply_hexagram_input(state: dict[str, Any], item: dict[str, Any], *, now: str | None = None, as_of_date: str | None = None) -> dict[str, Any]:
    updated = write_hexagram_to_workflow_state(state, item, now=now, as_of_date=as_of_date)
    _mark_completed(updated, "hexagram")
    validate_state(updated)
    return updated


def generate_weekly_strategy(state: dict[str, Any], strategy: dict[str, Any] | None = None, *, now: str | None = None) -> dict[str, Any]:
    validate_state(state)
    if state["current_stage"] != "WEEKLY_STRATEGY_READY":
        raise ValueError("weekly strategy requires WEEKLY_STRATEGY_READY stage")
    updated = copy.deepcopy(state)
    strategy = strategy or {}
    participation = updated["weekly_strategy"].get("participation_level") or "CAUTIOUS_TRIAL"
    hexagram = updated.get("hexagram_manual_input") or {}
    if hexagram.get("calibration_result"):
        participation = hexagram["calibration_result"].get("calibrated_participation_level") or participation
    if _systemic_locked(updated):
        participation = "NO_NEW_BUY"
    weekly = updated["weekly_strategy"]
    weekly.update(
        {
            "participation_level": participation,
            "allowed_sectors": list(strategy.get("allowed_sectors") or weekly.get("allowed_sectors") or [])[:2],
            "prohibited_sectors": list(strategy.get("prohibited_sectors") or weekly.get("prohibited_sectors") or []),
            "allowed_days_or_windows": list(strategy.get("allowed_days_or_windows") or weekly.get("allowed_days_or_windows") or []),
            "strategy_summary": strategy.get("strategy_summary") or weekly.get("strategy_summary") or _strategy_summary(participation),
            "watch_sectors": list(strategy.get("watch_sectors") or []),
            "avoid_sectors": list(strategy.get("avoid_sectors") or []),
            "max_position": strategy.get("max_position") or ("0" if participation == "NO_NEW_BUY" else "100股试错"),
            "single_trial_quantity": 100,
            "cautious_dates": list(strategy.get("cautious_dates") or []),
            "observe_only_dates": list(strategy.get("observe_only_dates") or []),
            "strategy_invalidation_conditions": list(strategy.get("strategy_invalidation_conditions") or []),
        }
    )
    _mark_completed(updated, "weekly_strategy")
    updated["updated_at"] = _now(now)
    validate_state(updated)
    return updated


def _strategy_summary(level: str) -> str:
    if level == "NO_NEW_BUY":
        return "本周禁止新买入，只做观察和持仓管理。"
    if level == "CAUTIOUS_TRIAL":
        return "本周仅谨慎试错，不生成固定买入指令。"
    return "本周允许正常试错，但仍需通过前夜计划和盘中否决。"


def create_night_plan(state: dict[str, Any], plan: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    validate_state(state)
    updated = copy.deepcopy(state)
    plan_trade_date = str(plan.get("plan_trade_date") or updated["night_plan"].get("plan_trade_date") or "")
    updates = {
        "plan_trade_date": plan_trade_date,
        "primary_candidate": dict(plan.get("primary_candidate") or updated["night_plan"].get("primary_candidate") or {}),
        "backup_candidate": dict(plan.get("backup_candidate") or updated["night_plan"].get("backup_candidate") or {}),
        "planned_quantity": 100,
        "primary_conditions": list(plan.get("primary_conditions") or []),
        "backup_conditions": list(plan.get("backup_conditions") or []),
        "cancellation_conditions": list(plan.get("cancellation_conditions") or []),
        "market_conditions": list(plan.get("market_conditions") or []),
        "sector_cancellation_conditions": list(plan.get("sector_cancellation_conditions") or []),
        "stock_cancellation_conditions": list(plan.get("stock_cancellation_conditions") or []),
        "execution_time_window": plan.get("execution_time_window", "09:50-10:00"),
        "systemic_risk_status": plan.get("systemic_risk_status", updated["systemic_risk_gate"].get("systemic_risk_status")),
        "hexagram_risk_window_status": plan.get("hexagram_risk_window_status", "UNKNOWN"),
        "reversal_mode": updated["reversal_observation"].get("reversal_status") in {"BOTTOMING_WATCH", "REVERSAL_WATCH", "REVERSAL_CONFIRMED"},
        "plan_status": "READY",
    }
    updated["night_plan"].update(updates)
    if _systemic_locked(updated):
        updated["night_plan"]["plan_status"] = SUSPENDED_STATUS
        for key in ("primary_candidate", "backup_candidate"):
            if isinstance(updated["night_plan"].get(key), dict):
                updated["night_plan"][key]["status"] = SUSPENDED_STATUS
        updated["intraday_veto_result"]["final_intraday_action"] = SYSTEMIC_ACTION
    updated["current_stage"] = "INTRADAY_CHECK_PENDING"
    _mark_completed(updated, "night_plan")
    updated["updated_at"] = _now(now)
    validate_state(updated)
    return updated


def run_intraday_check(state: dict[str, Any], check: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    validate_state(state)
    updated = copy.deepcopy(state)
    action = ""
    data_status = str(check.get("data_status") or "NOT_CHECKED")
    primary_code = str((updated["night_plan"].get("primary_candidate") or {}).get("ts_code") or "")
    backup_code = str((updated["night_plan"].get("backup_candidate") or {}).get("ts_code") or "")
    checked_candidates = [code for code in [primary_code, backup_code] if code]
    if data_status not in {"OK", "PASS"}:
        action = "NO_BUY_DATA_UNRELIABLE"
    elif _systemic_locked(updated):
        action = SYSTEMIC_ACTION
    elif updated["reversal_observation"].get("reversal_status") in {"BOTTOMING_WATCH", "REVERSAL_WATCH", "REVERSAL_FAILED"}:
        action = "NO_BUY_REVERSAL_UNCONFIRMED"
    elif check.get("market_veto"):
        action = "NO_BUY_MARKET_VETO"
    elif check.get("sector_veto"):
        action = "NO_BUY_SECTOR_VETO"
    elif not check.get("primary_veto", True):
        action = "BUY_PRIMARY_100"
    elif not check.get("backup_veto", True):
        action = "BUY_BACKUP_100"
    else:
        action = "NO_BUY_STOCK_VETO"
    if action not in FINAL_INTRADAY_ACTIONS:
        raise ValueError(f"unsupported intraday action: {action}")
    updated["intraday_veto_result"].update(
        {
            "intraday_data_source": check.get("intraday_data_source", "MANUAL_OR_EXISTING_MODULE"),
            "market_veto": bool(check.get("market_veto")) or action in {"NO_BUY_MARKET_VETO", SYSTEMIC_ACTION},
            "sector_veto": bool(check.get("sector_veto")) or action == "NO_BUY_SECTOR_VETO",
            "primary_veto": bool(check.get("primary_veto")) or action in {"NO_BUY_STOCK_VETO", "NO_BUY_DATA_UNRELIABLE", SYSTEMIC_ACTION},
            "backup_veto": bool(check.get("backup_veto")) or action in {"NO_BUY_STOCK_VETO", "NO_BUY_DATA_UNRELIABLE", SYSTEMIC_ACTION},
            "data_status": data_status,
            "final_intraday_action": action,
            "intraday_checked_at": _now(now),
            "checked_candidates": checked_candidates,
        }
    )
    updated["current_stage"] = "INTRADAY_CHECK_COMPLETED"
    _mark_completed(updated, "intraday_check")
    updated["updated_at"] = _now(now)
    validate_state(updated)
    return updated


def complete_closing_review(state: dict[str, Any], review: dict[str, Any], *, trade_date: str, now: str | None = None) -> dict[str, Any]:
    updates = {
        "holding_actions": list(review.get("holding_actions") or []),
        "closing_review": review.get("closing_review", ""),
        "next_day_attention": list(review.get("next_day_attention") or []),
        "trade_date": trade_date,
        "market_result": review.get("market_result", ""),
        "sector_result": review.get("sector_result", ""),
        "candidate_result": review.get("candidate_result", ""),
        "veto_accuracy": review.get("veto_accuracy", ""),
        "systemic_risk_continues": review.get("systemic_risk_continues", ""),
        "hexagram_window_result": review.get("hexagram_window_result", ""),
        "reversal_next_step": review.get("reversal_next_step", ""),
    }
    updated = update_section(state, "closing_holding_review", updates, next_stage="CLOSING_REVIEW_COMPLETED", now=now)
    _mark_completed(updated, "closing_review")
    return updated


def advance_after_closing_review(
    state: dict[str, Any],
    *,
    next_trade_date: str,
    week_ended: bool,
    now: str | None = None,
) -> dict[str, Any]:
    validate_state(state)
    updated = copy.deepcopy(state)
    if updated["current_stage"] != "CLOSING_REVIEW_COMPLETED":
        raise ValueError("advance requires CLOSING_REVIEW_COMPLETED stage")
    if week_ended:
        updated["current_stage"] = "WEEKLY_REVIEW_COMPLETED"
        _mark_completed(updated, "weekly_review")
    else:
        updated["current_stage"] = "NIGHT_PLAN_READY"
        updated["night_plan"]["plan_trade_date"] = next_trade_date
        updated["night_plan"]["plan_status"] = "NOT_READY"
        updated["intraday_veto_result"]["final_intraday_action"] = ""
        updated["intraday_veto_result"]["data_status"] = "NOT_CHECKED"
    updated["updated_at"] = _now(now)
    validate_state(updated)
    return updated


def _hexagram_reversal_hint(state: dict[str, Any]) -> bool:
    section = state.get("hexagram_manual_input") or {}
    items = []
    market = section.get("market_hexagram_result")
    if isinstance(market, dict):
        items.append(market)
    items.extend(item for item in section.get("sector_hexagram_results") or [] if isinstance(item, dict))
    for item in items:
        summary = str(item.get("analyst_summary") or "")
        if item.get("phase_pattern") == "WEAK_THEN_STABLE":
            return True
        if "反弹观察" in summary or "反冲窗口" in summary:
            return True
    return False


def run_reversal_check(
    state: dict[str, Any],
    signals: dict[str, Any],
    *,
    trade_date: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    validate_state(state)
    updated = copy.deepcopy(state)
    checked_at = _now(now)
    trade_date = trade_date or _trade_date_from_now(checked_at)
    reversal = updated["reversal_observation"]
    if reversal.get("reversal_status") == "REVERSAL_FAILED" and reversal.get("reversal_trade_date") == trade_date:
        updated["updated_at"] = checked_at
        return updated

    data_status = str(signals.get("reversal_data_status") or "NOT_CHECKED")
    if data_status not in {"OK", "PASS"}:
        reversal.update(
            {
                "reversal_status": "REVERSAL_FAILED",
                "reversal_trade_date": trade_date,
                "reversal_data_status": data_status,
                "reversal_failed_reason": "反转观察数据不可靠。",
                "reversal_checked_at": checked_at,
            }
        )
        updated["intraday_veto_result"]["final_intraday_action"] = "NO_BUY_DATA_UNRELIABLE"
        updated["daily_execution_state"]["new_buy_locked"] = True
        updated["updated_at"] = checked_at
        validate_state(updated)
        return updated

    if _hexagram_reversal_hint(updated) and reversal.get("reversal_status") in {"NONE", "BOTTOMING_WATCH"}:
        reversal["reversal_status"] = "REVERSAL_WATCH"
        reversal["reversal_source"] = "HEXAGRAM_MANUAL_HINT"
        reversal["reversal_reason"] = "人工六爻提示反弹/企稳观察，仅进入观察，不触发买入。"

    for key in REVERSAL_CONFIG["confirmation_signals"]:
        reversal[key] = _unknown_if_missing(signals, key)
    count = sum(1 for key in REVERSAL_CONFIG["confirmation_signals"] if _truth(signals.get(key)))
    reversal["reversal_confirmation_count"] = count
    reversal["reversal_data_status"] = data_status
    reversal["reversal_trade_date"] = trade_date
    reversal["reversal_checked_at"] = checked_at

    failed = any(_truth(signals.get(key)) for key in [
        "indexes_drop_again",
        "break_observation_low",
        "breadth_repair_failed",
        "single_stock_spike_only",
        "core_fade_without_support",
        "probe_stock_breaks_invalidation",
    ])
    if failed:
        reversal["reversal_status"] = "REVERSAL_FAILED"
        reversal["reversal_failed_reason"] = "反冲失败或重新走弱。"
        updated["intraday_veto_result"]["final_intraday_action"] = "NO_BUY_REVERSAL_UNCONFIRMED"
        updated["daily_execution_state"]["new_buy_locked"] = True
    else:
        required_ok = all(_truth(signals.get(key)) for key in REVERSAL_CONFIG["required_signals"])
        one_of_ok = any(_truth(signals.get(key)) for key in REVERSAL_CONFIG["requires_one_of"])
        enough = count >= int(REVERSAL_CONFIG["required_confirmation_count"])
        if enough and required_ok and one_of_ok:
            reversal["reversal_status"] = "REVERSAL_CONFIRMED"
            reversal["reversal_reason"] = "现实反转确认信号达到阈值；总闸未解除前不允许实际买入。"
            if _systemic_locked(updated):
                updated["intraday_veto_result"]["final_intraday_action"] = SYSTEMIC_ACTION
                updated["daily_execution_state"]["new_buy_locked"] = True
        elif reversal.get("reversal_status") in {"REVERSAL_WATCH", "BOTTOMING_WATCH"}:
            updated["intraday_veto_result"]["final_intraday_action"] = "NO_BUY_REVERSAL_UNCONFIRMED"
    _mark_completed(updated, "reversal_check")
    updated["updated_at"] = checked_at
    validate_state(updated)
    return updated


def _load_json(value: str) -> dict[str, Any]:
    path = Path(value)
    text = path.read_text(encoding="utf-8") if path.exists() else value
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("JSON input must be an object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly workflow orchestrator.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("next")
    sub.add_parser("validate")
    for name in ["weekend", "hexagram", "weekly-strategy", "night-plan", "intraday-check", "closing-review", "weekly-review", "reversal-check"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("--input-json", default="{}")
        cmd.add_argument("--trade-date", default="")
        cmd.add_argument("--next-trade-date", default="")
        cmd.add_argument("--week-ended", action="store_true")
        cmd.add_argument("--as-of-date", default="")
    args = parser.parse_args(argv)

    state = load_state(STATE_JSON)
    if args.command == "status":
        print(json.dumps(build_status(state), ensure_ascii=False, indent=2))
        return 0
    if args.command == "next":
        command = decide_next_command(state)
        state.setdefault("workflow_audit", {})["last_next_command"] = command
        save_state(state)
        print(command)
        return 0
    if args.command == "validate":
        validate_state(state)
        print("workflow_orchestrator_valid")
        return 0

    payload = _load_json(args.input_json)
    if args.command == "weekend":
        state = complete_weekend_reality(state, payload)
        record_history("weekend_reality", state.get("latest_completed_trade_date", "unknown"), payload)
    elif args.command == "hexagram":
        state = apply_hexagram_input(state, payload, as_of_date=args.as_of_date or None)
        record_history("hexagram_input", payload.get("observation_start_date", "unknown"), payload)
    elif args.command == "weekly-strategy":
        state = generate_weekly_strategy(state, payload)
        record_history("weekly_strategy", state.get("latest_completed_trade_date", "unknown"), state["weekly_strategy"])
    elif args.command == "night-plan":
        state = create_night_plan(state, payload)
        record_history("night_plan", state["night_plan"].get("plan_trade_date", "unknown"), state["night_plan"])
    elif args.command == "intraday-check":
        state = run_intraday_check(state, payload)
        record_history("intraday_check", state["night_plan"].get("plan_trade_date", "unknown"), state["intraday_veto_result"])
    elif args.command == "closing-review":
        state = complete_closing_review(state, payload, trade_date=args.trade_date or state["night_plan"].get("plan_trade_date", "unknown"))
        record_history("closing_review", args.trade_date or state["night_plan"].get("plan_trade_date", "unknown"), state["closing_holding_review"])
    elif args.command == "weekly-review":
        state = advance_after_closing_review(state, next_trade_date=args.next_trade_date or "", week_ended=True)
        record_history("weekly_review", state.get("latest_completed_trade_date", "unknown"), state["weekly_review"])
    elif args.command == "reversal-check":
        state = run_reversal_check(state, payload, trade_date=args.trade_date or None)
        record_history("reversal_check", args.trade_date or state["night_plan"].get("plan_trade_date", "unknown"), state["reversal_observation"])
    save_state(state)
    print(json.dumps(build_status(state), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
