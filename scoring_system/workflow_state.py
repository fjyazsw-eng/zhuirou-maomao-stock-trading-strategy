from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "reports" / "workflow"
STATE_JSON = WORKFLOW_DIR / "current_workflow_state.json"
STATE_MD = WORKFLOW_DIR / "current_workflow_state.md"

WORKFLOW_VERSION = "workflow_state_v1"
DEFAULT_PLANNED_QUANTITY = 100

STAGES = [
    "WEEKEND_REALITY_PENDING",
    "WEEKEND_HEXAGRAM_PENDING",
    "WEEKLY_STRATEGY_READY",
    "NIGHT_PLAN_READY",
    "INTRADAY_CHECK_PENDING",
    "INTRADAY_CHECK_COMPLETED",
    "CLOSING_REVIEW_COMPLETED",
    "WEEKLY_REVIEW_COMPLETED",
]

ALLOWED_STAGE_TRANSITIONS: dict[str, set[str]] = {
    "WEEKEND_REALITY_PENDING": {"WEEKEND_REALITY_PENDING", "WEEKEND_HEXAGRAM_PENDING"},
    "WEEKEND_HEXAGRAM_PENDING": {"WEEKEND_HEXAGRAM_PENDING", "WEEKLY_STRATEGY_READY"},
    "WEEKLY_STRATEGY_READY": {"WEEKLY_STRATEGY_READY", "NIGHT_PLAN_READY"},
    "NIGHT_PLAN_READY": {"NIGHT_PLAN_READY", "INTRADAY_CHECK_PENDING"},
    "INTRADAY_CHECK_PENDING": {"INTRADAY_CHECK_PENDING", "INTRADAY_CHECK_COMPLETED"},
    "INTRADAY_CHECK_COMPLETED": {"INTRADAY_CHECK_COMPLETED", "CLOSING_REVIEW_COMPLETED"},
    "CLOSING_REVIEW_COMPLETED": {"CLOSING_REVIEW_COMPLETED", "NIGHT_PLAN_READY", "WEEKLY_REVIEW_COMPLETED"},
    "WEEKLY_REVIEW_COMPLETED": {"WEEKLY_REVIEW_COMPLETED", "WEEKEND_REALITY_PENDING"},
}

SECTION_KEYS = {
    "weekend_reality_analysis",
    "hexagram_manual_input",
    "weekly_strategy",
    "night_plan",
    "intraday_veto_result",
    "daily_execution_state",
    "systemic_risk_gate",
    "reversal_observation",
    "workflow_audit",
    "closing_holding_review",
    "weekly_review",
}


class WorkflowStateError(ValueError):
    """Raised when workflow state structure or stage transition is invalid."""


def _now(value: str | None = None) -> str:
    return value or datetime.now().isoformat(timespec="seconds")


def _empty_candidate() -> dict[str, Any]:
    return {
        "ts_code": "",
        "name": "",
        "sector": "",
        "buy_level": "",
        "notes": "",
    }


def _empty_hexagram_calibration() -> dict[str, Any]:
    return {
        "reality_participation_level": "",
        "hexagram_direction": "",
        "calibrated_participation_level": "",
        "downgrade_applied": False,
        "downgrade_reason": "",
        "blocked_by_systemic_risk": False,
        "risk_windows": [],
        "favorable_windows": [],
        "validity_status": "NOT_PROVIDED",
        "adjustment_rule": "DOWNGRADE_ONLY",
        "final_policy": "",
        "final_intraday_action": "",
    }


def create_blank_state(*, now: str | None = None, latest_completed_trade_date: str = "") -> dict[str, Any]:
    timestamp = _now(now)
    return {
        "workflow_version": WORKFLOW_VERSION,
        "created_at": timestamp,
        "updated_at": timestamp,
        "latest_completed_trade_date": latest_completed_trade_date,
        "current_stage": "WEEKEND_REALITY_PENDING",
        "weekend_reality_analysis": {
            "market_state": "",
            "market_trend": "",
            "market_risk_level": "",
            "focus_sectors": [],
            "excluded_sectors": [],
            "reality_summary": "",
            "source_report": "",
        },
        "hexagram_manual_input": {
            "hexagram_status": "NOT_PROVIDED",
            "market_hexagram_result": "",
            "sector_hexagram_results": [],
            "timing_windows": [],
            "hexagram_risk_level": "",
            "hexagram_notes": "",
            "hexagram_source": "",
            "adjustment_rule": "DOWNGRADE_ONLY",
            "calibration_result": _empty_hexagram_calibration(),
        },
        "weekly_strategy": {
            "participation_level": "",
            "allowed_sectors": [],
            "prohibited_sectors": [],
            "allowed_days_or_windows": [],
            "strategy_summary": "",
        },
        "night_plan": {
            "plan_trade_date": "",
            "primary_candidate": _empty_candidate(),
            "backup_candidate": _empty_candidate(),
            "planned_quantity": DEFAULT_PLANNED_QUANTITY,
            "primary_conditions": [],
            "backup_conditions": [],
            "cancellation_conditions": [],
            "plan_status": "NOT_READY",
        },
        "intraday_veto_result": {
            "check_time_window": "09:50-10:00",
            "intraday_data_source": "",
            "market_veto": None,
            "sector_veto": None,
            "primary_veto": None,
            "backup_veto": None,
            "data_status": "NOT_CHECKED",
            "final_intraday_action": "",
            "intraday_checked_at": "",
        },
        "daily_execution_state": {
            "new_buy_locked": False,
            "new_position_opened_today": False,
            "executed_symbol": "",
            "executed_quantity": 0,
            "execution_note": "",
        },
        "systemic_risk_gate": {
            "systemic_risk_status": "NOT_CHECKED",
            "systemic_risk_level": "",
            "systemic_risk_checked_at": "",
            "systemic_risk_reasons": [],
            "new_buy_locked": False,
            "new_buy_lock_date": "",
            "new_buy_lock_reason": "",
            "new_buy_unlock_pending": False,
            "new_buy_lock_history": [],
            "assessment_details": {},
        },
        "reversal_observation": {
            "reversal_status": "NONE",
            "reversal_trade_date": "",
            "reversal_source": "",
            "panic_release_detected": "UNKNOWN",
            "breadth_extreme_detected": "UNKNOWN",
            "index_stabilization_detected": "UNKNOWN",
            "sector_stabilization_detected": "UNKNOWN",
            "core_stock_support_detected": "UNKNOWN",
            "reversal_confirmation_count": 0,
            "reversal_data_status": "NOT_CHECKED",
            "reversal_reason": "",
            "reversal_failed_reason": "",
            "reversal_checked_at": "",
        },
        "workflow_audit": {
            "completed_steps": [],
            "history_root": "reports/workflow/history",
            "last_next_command": "",
        },
        "closing_holding_review": {
            "holding_actions": [],
            "closing_review": "",
            "next_day_attention": [],
        },
        "weekly_review": {
            "reality_accuracy_score": None,
            "hexagram_value_score": None,
            "intraday_veto_value": "",
            "avoided_loss": None,
            "missed_opportunity": None,
            "execution_deviation": "",
            "weekly_summary": "",
            "next_week_adjustments": [],
        },
    }


def validate_stage_transition(current_stage: str, next_stage: str) -> None:
    if current_stage not in STAGES:
        raise WorkflowStateError(f"Unknown current_stage: {current_stage}")
    if next_stage not in STAGES:
        raise WorkflowStateError(f"Unknown next_stage: {next_stage}")
    allowed = ALLOWED_STAGE_TRANSITIONS[current_stage]
    if next_stage not in allowed:
        raise WorkflowStateError(f"Illegal stage transition: {current_stage} -> {next_stage}")


def validate_state(state: dict[str, Any]) -> None:
    if not isinstance(state, dict):
        raise WorkflowStateError("Workflow state must be a JSON object")
    for key in ["workflow_version", "created_at", "updated_at", "latest_completed_trade_date", "current_stage"]:
        if key not in state:
            raise WorkflowStateError(f"Missing top-level field: {key}")
    if state["workflow_version"] != WORKFLOW_VERSION:
        raise WorkflowStateError(f"Unsupported workflow_version: {state['workflow_version']}")
    if state["current_stage"] not in STAGES:
        raise WorkflowStateError(f"Unsupported current_stage: {state['current_stage']}")
    for section in SECTION_KEYS:
        if section not in state or not isinstance(state[section], dict):
            raise WorkflowStateError(f"Missing section: {section}")

    focus = state["weekend_reality_analysis"].get("focus_sectors", [])
    if not isinstance(focus, list):
        raise WorkflowStateError("focus_sectors must be a list")
    if len(focus) > 2:
        raise WorkflowStateError("focus_sectors supports at most two sectors")

    hexagram = state["hexagram_manual_input"]
    if hexagram.get("hexagram_status") not in {"NOT_PROVIDED", "PROVIDED"}:
        raise WorkflowStateError("hexagram_status must be NOT_PROVIDED or PROVIDED")
    if hexagram.get("adjustment_rule") != "DOWNGRADE_ONLY":
        raise WorkflowStateError("adjustment_rule must remain DOWNGRADE_ONLY")
    sector_hexagrams = hexagram.get("sector_hexagram_results", [])
    if not isinstance(sector_hexagrams, list):
        raise WorkflowStateError("sector_hexagram_results must be a list")
    active_sector_hexagrams = [
        item for item in sector_hexagrams
        if isinstance(item, dict) and item.get("validity_status") == "VALID"
    ]
    if len(active_sector_hexagrams) > 2:
        raise WorkflowStateError("sector_hexagram_results supports at most two active sectors")
    if hexagram.get("hexagram_source", "") not in {"", "MANUAL"}:
        raise WorkflowStateError("hexagram_source must be MANUAL when provided")
    calibration = hexagram.get("calibration_result", {})
    if calibration and not isinstance(calibration, dict):
        raise WorkflowStateError("calibration_result must be an object")

    participation = state["weekly_strategy"].get("participation_level")
    if participation not in {"", "NORMAL_TRIAL", "CAUTIOUS_TRIAL", "NO_NEW_BUY"}:
        raise WorkflowStateError("participation_level is invalid")

    planned_quantity = state["night_plan"].get("planned_quantity")
    if planned_quantity != DEFAULT_PLANNED_QUANTITY:
        raise WorkflowStateError("planned_quantity must remain 100")

    if state["intraday_veto_result"].get("check_time_window") != "09:50-10:00":
        raise WorkflowStateError("check_time_window must remain 09:50-10:00")

    gate = state["systemic_risk_gate"]
    if gate.get("systemic_risk_level") not in {"", "NORMAL", "CAUTION", "HIGH", "SYSTEMIC"}:
        raise WorkflowStateError("systemic_risk_level is invalid")
    if not isinstance(gate.get("systemic_risk_reasons"), list):
        raise WorkflowStateError("systemic_risk_reasons must be a list")
    if not isinstance(gate.get("new_buy_locked"), bool):
        raise WorkflowStateError("systemic_risk_gate.new_buy_locked must be a boolean")
    if not isinstance(gate.get("new_buy_unlock_pending"), bool):
        raise WorkflowStateError("new_buy_unlock_pending must be a boolean")

    reversal = state["reversal_observation"]
    if reversal.get("reversal_status") not in {
        "NONE",
        "BOTTOMING_WATCH",
        "REVERSAL_WATCH",
        "REVERSAL_PROBE_ALLOWED",
        "REVERSAL_CONFIRMED",
        "REVERSAL_FAILED",
    }:
        raise WorkflowStateError("reversal_status is invalid")
    if not isinstance(reversal.get("reversal_confirmation_count"), int):
        raise WorkflowStateError("reversal_confirmation_count must be an integer")
    audit = state["workflow_audit"]
    if not isinstance(audit.get("completed_steps"), list):
        raise WorkflowStateError("workflow_audit.completed_steps must be a list")


def load_state(json_path: Path = STATE_JSON) -> dict[str, Any]:
    state = json.loads(json_path.read_text(encoding="utf-8"))
    validate_state(state)
    return state


def update_section(
    state: dict[str, Any],
    section: str,
    updates: dict[str, Any],
    *,
    next_stage: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    if section not in SECTION_KEYS:
        raise WorkflowStateError(f"Unknown section: {section}")
    if not isinstance(updates, dict):
        raise WorkflowStateError("updates must be a JSON object")
    validate_state(state)
    updated = copy.deepcopy(state)
    updated[section].update(updates)
    if section == "night_plan" and "planned_quantity" not in updates:
        updated[section]["planned_quantity"] = DEFAULT_PLANNED_QUANTITY
    if next_stage is not None:
        validate_stage_transition(str(updated["current_stage"]), next_stage)
        updated["current_stage"] = next_stage
    updated["updated_at"] = _now(now)
    validate_state(updated)
    return updated


def save_state(
    state: dict[str, Any],
    *,
    json_path: Path = STATE_JSON,
    markdown_path: Path = STATE_MD,
) -> dict[str, str]:
    validate_state(state)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(state), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def _list_text(items: Any) -> str:
    if not items:
        return "-"
    if isinstance(items, list):
        values: list[str] = []
        for item in items:
            if isinstance(item, dict):
                values.append(str(item.get("name") or item.get("ts_code") or item))
            else:
                values.append(str(item))
        return "、".join(values) if values else "-"
    return str(items)


def _candidate_text(candidate: dict[str, Any]) -> str:
    code = candidate.get("ts_code") or "-"
    name = candidate.get("name") or "-"
    sector = candidate.get("sector") or "-"
    return f"{name} {code}（{sector}）"


def _hexagram_text(value: Any) -> str:
    if not value:
        return "-"
    if not isinstance(value, dict):
        return str(value)
    target = value.get("target_name") or value.get("target_type") or "-"
    direction = value.get("hexagram_direction") or "-"
    status = value.get("validity_status") or "-"
    summary = value.get("analyst_summary") or "-"
    return f"{target}：{direction}（{status}），{summary}"


def render_markdown(state: dict[str, Any]) -> str:
    validate_state(state)
    reality = state["weekend_reality_analysis"]
    hexagram = state["hexagram_manual_input"]
    strategy = state["weekly_strategy"]
    plan = state["night_plan"]
    intraday = state["intraday_veto_result"]
    execution = state["daily_execution_state"]
    gate = state["systemic_risk_gate"]
    reversal = state["reversal_observation"]
    audit = state["workflow_audit"]
    closing = state["closing_holding_review"]
    weekly = state["weekly_review"]
    lines = [
        "# 工作流状态",
        "",
        "## 基础信息",
        f"- workflow_version：{state['workflow_version']}",
        f"- created_at：{state['created_at']}",
        f"- updated_at：{state['updated_at']}",
        f"- latest_completed_trade_date：{state['latest_completed_trade_date'] or '-'}",
        f"- current_stage：{state['current_stage']}",
        "",
        "## 周末现实分析",
        f"- market_state：{reality.get('market_state') or '-'}",
        f"- market_trend：{reality.get('market_trend') or '-'}",
        f"- market_risk_level：{reality.get('market_risk_level') or '-'}",
        f"- focus_sectors：{_list_text(reality.get('focus_sectors'))}",
        f"- excluded_sectors：{_list_text(reality.get('excluded_sectors'))}",
        f"- reality_summary：{reality.get('reality_summary') or '-'}",
        f"- source_report：{reality.get('source_report') or '-'}",
        "",
        "## 六爻人工输入",
        f"- hexagram_status：{hexagram.get('hexagram_status')}",
        f"- adjustment_rule：{hexagram.get('adjustment_rule')}",
        f"- hexagram_source：{hexagram.get('hexagram_source') or '-'}",
        f"- market_hexagram_result：{_hexagram_text(hexagram.get('market_hexagram_result'))}",
        f"- sector_hexagram_results：{_list_text([_hexagram_text(item) for item in hexagram.get('sector_hexagram_results') or []])}",
        f"- timing_windows：{_list_text(hexagram.get('timing_windows'))}",
        f"- hexagram_risk_level：{hexagram.get('hexagram_risk_level') or '-'}",
        f"- hexagram_notes：{hexagram.get('hexagram_notes') or '-'}",
        f"- calibrated_participation_level：{(hexagram.get('calibration_result') or {}).get('calibrated_participation_level') or '-'}",
        f"- downgrade_applied：{(hexagram.get('calibration_result') or {}).get('downgrade_applied')}",
        f"- final_policy：{(hexagram.get('calibration_result') or {}).get('final_policy') or '-'}",
        "",
        "## 最终周度策略",
        f"- participation_level：{strategy.get('participation_level') or '-'}",
        f"- allowed_sectors：{_list_text(strategy.get('allowed_sectors'))}",
        f"- prohibited_sectors：{_list_text(strategy.get('prohibited_sectors'))}",
        f"- allowed_days_or_windows：{_list_text(strategy.get('allowed_days_or_windows'))}",
        f"- strategy_summary：{strategy.get('strategy_summary') or '-'}",
        "",
        "## 前一晚计划",
        f"- plan_trade_date：{plan.get('plan_trade_date') or '-'}",
        f"- primary_candidate：{_candidate_text(plan.get('primary_candidate') or {})}",
        f"- backup_candidate：{_candidate_text(plan.get('backup_candidate') or {})}",
        f"- planned_quantity：{plan.get('planned_quantity')}",
        f"- primary_conditions：{_list_text(plan.get('primary_conditions'))}",
        f"- backup_conditions：{_list_text(plan.get('backup_conditions'))}",
        f"- cancellation_conditions：{_list_text(plan.get('cancellation_conditions'))}",
        f"- plan_status：{plan.get('plan_status')}",
        "",
        "## 盘中否决结果",
        f"- check_time_window：{intraday.get('check_time_window')}",
        f"- intraday_data_source：{intraday.get('intraday_data_source') or '-'}",
        f"- market_veto：{intraday.get('market_veto')}",
        f"- sector_veto：{intraday.get('sector_veto')}",
        f"- primary_veto：{intraday.get('primary_veto')}",
        f"- backup_veto：{intraday.get('backup_veto')}",
        f"- data_status：{intraday.get('data_status')}",
        f"- final_intraday_action：{intraday.get('final_intraday_action') or '-'}",
        f"- intraday_checked_at：{intraday.get('intraday_checked_at') or '-'}",
        "",
        "## 日内执行状态",
        f"- new_buy_locked：{execution.get('new_buy_locked')}",
        f"- new_position_opened_today：{execution.get('new_position_opened_today')}",
        f"- executed_symbol：{execution.get('executed_symbol') or '-'}",
        f"- executed_quantity：{execution.get('executed_quantity')}",
        f"- execution_note：{execution.get('execution_note') or '-'}",
        "",
        "## 系统性风险总闸",
        f"- systemic_risk_status：{gate.get('systemic_risk_status') or '-'}",
        f"- systemic_risk_level：{gate.get('systemic_risk_level') or '-'}",
        f"- systemic_risk_checked_at：{gate.get('systemic_risk_checked_at') or '-'}",
        f"- systemic_risk_reasons：{_list_text(gate.get('systemic_risk_reasons'))}",
        f"- new_buy_locked：{gate.get('new_buy_locked')}",
        f"- new_buy_lock_date：{gate.get('new_buy_lock_date') or '-'}",
        f"- new_buy_lock_reason：{gate.get('new_buy_lock_reason') or '-'}",
        f"- new_buy_unlock_pending：{gate.get('new_buy_unlock_pending')}",
        "",
        "## 反转观察",
        f"- reversal_status：{reversal.get('reversal_status')}",
        f"- reversal_trade_date：{reversal.get('reversal_trade_date') or '-'}",
        f"- reversal_source：{reversal.get('reversal_source') or '-'}",
        f"- panic_release_detected：{reversal.get('panic_release_detected')}",
        f"- breadth_extreme_detected：{reversal.get('breadth_extreme_detected')}",
        f"- index_stabilization_detected：{reversal.get('index_stabilization_detected')}",
        f"- sector_stabilization_detected：{reversal.get('sector_stabilization_detected')}",
        f"- core_stock_support_detected：{reversal.get('core_stock_support_detected')}",
        f"- reversal_confirmation_count：{reversal.get('reversal_confirmation_count')}",
        f"- reversal_data_status：{reversal.get('reversal_data_status')}",
        f"- reversal_reason：{reversal.get('reversal_reason') or '-'}",
        f"- reversal_failed_reason：{reversal.get('reversal_failed_reason') or '-'}",
        "",
        "## 工作流审计",
        f"- completed_steps：{_list_text(audit.get('completed_steps'))}",
        f"- history_root：{audit.get('history_root') or '-'}",
        f"- last_next_command：{audit.get('last_next_command') or '-'}",
        "",
        "## 收盘持仓复盘",
        f"- holding_actions：{_list_text(closing.get('holding_actions'))}",
        f"- closing_review：{closing.get('closing_review') or '-'}",
        f"- next_day_attention：{_list_text(closing.get('next_day_attention'))}",
        "",
        "## 周五复盘",
        f"- reality_accuracy_score：{weekly.get('reality_accuracy_score')}",
        f"- hexagram_value_score：{weekly.get('hexagram_value_score')}",
        f"- intraday_veto_value：{weekly.get('intraday_veto_value') or '-'}",
        f"- avoided_loss：{weekly.get('avoided_loss')}",
        f"- missed_opportunity：{weekly.get('missed_opportunity')}",
        f"- execution_deviation：{weekly.get('execution_deviation') or '-'}",
        f"- weekly_summary：{weekly.get('weekly_summary') or '-'}",
        f"- next_week_adjustments：{_list_text(weekly.get('next_week_adjustments'))}",
        "",
    ]
    return "\n".join(lines)


def _load_updates(value: str) -> dict[str, Any]:
    path = Path(value)
    text = path.read_text(encoding="utf-8") if path.exists() else value
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise WorkflowStateError("updates JSON must be an object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create, validate, read, update, and render workflow state.")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--latest-completed-trade-date", default="")

    sub.add_parser("read")
    sub.add_parser("validate")
    sub.add_parser("render")

    update = sub.add_parser("update-section")
    update.add_argument("--section", required=True)
    update.add_argument("--updates-json", required=True, help="JSON string or path to a JSON file")
    update.add_argument("--next-stage", default=None)

    args = parser.parse_args(argv)
    if args.command == "create":
        state = create_blank_state(latest_completed_trade_date=args.latest_completed_trade_date)
        paths = save_state(state)
        print(json.dumps(paths, ensure_ascii=False, indent=2))
        return 0
    if args.command == "read":
        print(json.dumps(load_state(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        validate_state(load_state())
        print("workflow_state_valid")
        return 0
    if args.command == "render":
        state = load_state()
        STATE_MD.write_text(render_markdown(state), encoding="utf-8")
        print(str(STATE_MD))
        return 0
    if args.command == "update-section":
        state = load_state()
        state = update_section(state, args.section, _load_updates(args.updates_json), next_stage=args.next_stage)
        paths = save_state(state)
        print(json.dumps(paths, ensure_ascii=False, indent=2))
        return 0
    raise WorkflowStateError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
