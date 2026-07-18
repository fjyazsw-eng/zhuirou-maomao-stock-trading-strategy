from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scoring_system.systemic_risk_gate import SYSTEMIC_ACTION
from scoring_system.workflow_state import load_state, save_state, update_section, validate_state


HEXAGRAM_DIRECTIONS = {"POSITIVE", "NEUTRAL", "CAUTIOUS", "NEGATIVE", "HIGH_RISK"}
PHASE_PATTERNS = {
    "STABLE_STRONG",
    "STRONG_THEN_WEAK",
    "WEAK_THEN_STABLE",
    "VOLATILE",
    "REVERSAL_RISK",
    "UNKNOWN",
}
CONFIDENCE_LEVELS = {"LOW", "MEDIUM", "HIGH"}
VALIDITY_STATUSES = {"VALID", "EXPIRED", "INVALIDATED"}
TARGET_TYPES = {"MARKET", "SECTOR"}
PARTICIPATION_LEVELS = ("NO_NEW_BUY", "CAUTIOUS_TRIAL", "NORMAL_TRIAL")
DOWNGRADE_RULE = "DOWNGRADE_ONLY"

CALIBRATION_CONFIG: dict[str, Any] = {
    "direction_map": {
        "NORMAL_TRIAL": {
            "POSITIVE": "NORMAL_TRIAL",
            "NEUTRAL": "NORMAL_TRIAL",
            "CAUTIOUS": "CAUTIOUS_TRIAL",
            "NEGATIVE": "NO_NEW_BUY",
            "HIGH_RISK": "NO_NEW_BUY",
        },
        "CAUTIOUS_TRIAL": {
            "POSITIVE": "CAUTIOUS_TRIAL",
            "NEUTRAL": "CAUTIOUS_TRIAL",
            "CAUTIOUS": "NO_NEW_BUY",
            "NEGATIVE": "NO_NEW_BUY",
            "HIGH_RISK": "NO_NEW_BUY",
        },
        "NO_NEW_BUY": {
            "POSITIVE": "NO_NEW_BUY",
            "NEUTRAL": "NO_NEW_BUY",
            "CAUTIOUS": "NO_NEW_BUY",
            "NEGATIVE": "NO_NEW_BUY",
            "HIGH_RISK": "NO_NEW_BUY",
        },
    },
    "risk_window_downgrade": {
        "NORMAL_TRIAL": "CAUTIOUS_TRIAL",
        "CAUTIOUS_TRIAL": "NO_NEW_BUY",
        "NO_NEW_BUY": "NO_NEW_BUY",
    },
}


class HexagramCalibrationError(ValueError):
    """Raised when manual hexagram input or calibration is invalid."""


def _now(value: str | None = None) -> str:
    return value or datetime.now().isoformat(timespec="seconds")


def _date_value(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10].replace("-", "")


def _rank(level: str) -> int:
    try:
        return PARTICIPATION_LEVELS.index(level)
    except ValueError as exc:
        raise HexagramCalibrationError(f"unknown participation level: {level}") from exc


def _min_level(a: str, b: str) -> str:
    return a if _rank(a) <= _rank(b) else b


def create_hexagram_template(
    *,
    target_type: str,
    target_name: str,
    question: str,
    input_time: str | None = None,
    observation_start_date: str = "",
    observation_end_date: str = "",
) -> dict[str, Any]:
    return {
        "input_time": _now(input_time),
        "question": question,
        "target_type": target_type,
        "target_name": target_name,
        "observation_start_date": observation_start_date,
        "observation_end_date": observation_end_date,
        "hexagram_direction": "NEUTRAL",
        "phase_pattern": "UNKNOWN",
        "risk_windows": [],
        "favorable_windows": [],
        "confidence_level": "LOW",
        "analyst_summary": "",
        "raw_notes": "",
        "validity_status": "VALID",
        "invalidation_reason": "",
        "source": "MANUAL",
    }


def validate_hexagram_input(item: dict[str, Any]) -> None:
    if not isinstance(item, dict):
        raise HexagramCalibrationError("hexagram input must be an object")
    required = [
        "input_time",
        "question",
        "target_type",
        "target_name",
        "observation_start_date",
        "observation_end_date",
        "hexagram_direction",
        "phase_pattern",
        "risk_windows",
        "favorable_windows",
        "confidence_level",
        "analyst_summary",
        "raw_notes",
        "validity_status",
        "invalidation_reason",
    ]
    for key in required:
        if key not in item:
            raise HexagramCalibrationError(f"missing hexagram field: {key}")
    if item["target_type"] not in TARGET_TYPES:
        raise HexagramCalibrationError("target_type must be MARKET or SECTOR")
    if item["hexagram_direction"] not in HEXAGRAM_DIRECTIONS:
        raise HexagramCalibrationError("hexagram_direction is invalid")
    if item["phase_pattern"] not in PHASE_PATTERNS:
        raise HexagramCalibrationError("phase_pattern is invalid")
    if item["confidence_level"] not in CONFIDENCE_LEVELS:
        raise HexagramCalibrationError("confidence_level is invalid")
    if item["validity_status"] not in VALIDITY_STATUSES:
        raise HexagramCalibrationError("validity_status is invalid")
    if item.get("source", "MANUAL") != "MANUAL":
        raise HexagramCalibrationError("hexagram source must be MANUAL")
    for key in ["risk_windows", "favorable_windows"]:
        if not isinstance(item.get(key), list):
            raise HexagramCalibrationError(f"{key} must be a list")
    if item["validity_status"] == "INVALIDATED" and not str(item.get("invalidation_reason") or "").strip():
        raise HexagramCalibrationError("invalidated hexagram requires invalidation_reason")


def _effective_status(item: dict[str, Any], as_of_date: str) -> str:
    status = str(item.get("validity_status") or "")
    if status != "VALID":
        return status
    end_date = _date_value(item.get("observation_end_date"))
    current = _date_value(as_of_date)
    if end_date and current and end_date < current:
        return "EXPIRED"
    return "VALID"


def _active_inputs(inputs: list[dict[str, Any]], as_of_date: str) -> tuple[list[dict[str, Any]], str]:
    statuses: list[str] = []
    active: list[dict[str, Any]] = []
    for item in inputs:
        validate_hexagram_input(item)
        status = _effective_status(item, as_of_date)
        statuses.append(status)
        if status == "VALID":
            active.append(item)
    if active:
        return active, "VALID"
    if "INVALIDATED" in statuses:
        return [], "INVALIDATED"
    if "EXPIRED" in statuses:
        return [], "EXPIRED"
    return [], "NOT_PROVIDED"


def _window_applies(window: Any, as_of_date: str) -> bool:
    text = str(window or "")
    compact = _date_value(as_of_date)
    dashed = f"{compact[:4]}-{compact[4:6]}-{compact[6:]}" if len(compact) == 8 else compact
    return compact in text.replace("-", "") or dashed in text


def _policy_text(level: str) -> str:
    if level == "NORMAL_TRIAL":
        return "保持原策略"
    if level == "CAUTIOUS_TRIAL":
        return "降为谨慎试错"
    return "禁止新买入"


def _systemic_locked(workflow_state: dict[str, Any] | None) -> bool:
    if not workflow_state:
        return False
    gate = workflow_state.get("systemic_risk_gate") or {}
    execution = workflow_state.get("daily_execution_state") or {}
    return bool(gate.get("new_buy_locked") or execution.get("new_buy_locked"))


def calibrate_participation_level(
    reality_participation_level: str,
    hexagram_inputs: list[dict[str, Any]],
    *,
    as_of_date: str,
    workflow_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if reality_participation_level not in PARTICIPATION_LEVELS:
        raise HexagramCalibrationError(f"unknown participation level: {reality_participation_level}")
    active, validity_status = _active_inputs(hexagram_inputs, as_of_date)
    blocked_by_systemic = _systemic_locked(workflow_state)
    directions = [str(item["hexagram_direction"]) for item in active]
    risk_windows: list[str] = []
    favorable_windows: list[str] = []
    calibrated = reality_participation_level
    reasons: list[str] = []

    if blocked_by_systemic:
        calibrated = "NO_NEW_BUY"
        reasons.append("系统性风险总闸已开启，六爻不得解除或升级。")
    else:
        for direction in directions:
            mapped = CALIBRATION_CONFIG["direction_map"][calibrated][direction]
            if _rank(mapped) < _rank(calibrated):
                reasons.append(f"人工六爻方向 {direction} 触发只降级映射。")
            calibrated = _min_level(calibrated, mapped)
        for item in active:
            risk_windows.extend(str(value) for value in item.get("risk_windows") or [])
            favorable_windows.extend(str(value) for value in item.get("favorable_windows") or [])
        if any(_window_applies(window, as_of_date) for window in risk_windows):
            mapped = CALIBRATION_CONFIG["risk_window_downgrade"][calibrated]
            if _rank(mapped) < _rank(calibrated):
                reasons.append("当前日期落入人工六爻风险窗口，只允许降级。")
            calibrated = _min_level(calibrated, mapped)

    downgrade_applied = _rank(calibrated) < _rank(reality_participation_level)
    hexagram_direction = "NONE"
    if "HIGH_RISK" in directions:
        hexagram_direction = "HIGH_RISK"
    elif "NEGATIVE" in directions:
        hexagram_direction = "NEGATIVE"
    elif "CAUTIOUS" in directions:
        hexagram_direction = "CAUTIOUS"
    elif "NEUTRAL" in directions:
        hexagram_direction = "NEUTRAL"
    elif "POSITIVE" in directions:
        hexagram_direction = "POSITIVE"
    return {
        "reality_participation_level": reality_participation_level,
        "hexagram_direction": hexagram_direction,
        "calibrated_participation_level": calibrated,
        "downgrade_applied": downgrade_applied,
        "downgrade_reason": "；".join(reasons),
        "blocked_by_systemic_risk": blocked_by_systemic,
        "risk_windows": risk_windows,
        "favorable_windows": favorable_windows,
        "validity_status": validity_status,
        "adjustment_rule": DOWNGRADE_RULE,
        "final_policy": _policy_text(calibrated),
        "final_intraday_action": SYSTEMIC_ACTION if blocked_by_systemic else "",
    }


def _hexagram_key(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(item.get("target_type") or ""),
        str(item.get("target_name") or ""),
        str(item.get("question") or ""),
        _date_value(item.get("observation_start_date")),
        _date_value(item.get("observation_end_date")),
    )


def _existing_hexagrams(section: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    market = section.get("market_hexagram_result")
    if isinstance(market, dict) and market:
        items.append(market)
    for item in section.get("sector_hexagram_results") or []:
        if isinstance(item, dict):
            items.append(item)
    return items


def _ensure_reality_ready(state: dict[str, Any]) -> None:
    reality = state.get("weekend_reality_analysis") or {}
    if not (reality.get("market_state") or reality.get("reality_summary") or reality.get("source_report")):
        raise HexagramCalibrationError("weekend reality analysis is required before hexagram calibration")


def _prevent_active_duplicate(section: dict[str, Any], item: dict[str, Any]) -> None:
    key = _hexagram_key(item)
    for existing in _existing_hexagrams(section):
        if _hexagram_key(existing) == key and str(existing.get("validity_status") or "") == "VALID":
            raise HexagramCalibrationError("active hexagram result already exists for the same question and window")


def write_hexagram_to_workflow_state(
    state: dict[str, Any],
    item: dict[str, Any],
    *,
    now: str | None = None,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    validate_state(state)
    validate_hexagram_input(item)
    _ensure_reality_ready(state)
    updated = copy.deepcopy(state)
    section = updated["hexagram_manual_input"]
    _prevent_active_duplicate(section, item)
    if state.get("current_stage") not in {"WEEKEND_HEXAGRAM_PENDING", "WEEKLY_STRATEGY_READY"}:
        raise HexagramCalibrationError("hexagram input requires WEEKEND_HEXAGRAM_PENDING or WEEKLY_STRATEGY_READY stage")
    if item["target_type"] == "MARKET":
        section["market_hexagram_result"] = copy.deepcopy(item)
    else:
        sectors = list(section.get("sector_hexagram_results") or [])
        active_sectors = [
            value for value in sectors
            if isinstance(value, dict) and value.get("validity_status") == "VALID"
        ]
        if len(active_sectors) >= 2:
            raise HexagramCalibrationError("sector hexagram results support at most two active sectors")
        sectors.append(copy.deepcopy(item))
        section["sector_hexagram_results"] = sectors
    section["hexagram_status"] = "PROVIDED"
    section["adjustment_rule"] = DOWNGRADE_RULE
    section["timing_windows"] = _combined_windows(section)
    section["hexagram_risk_level"] = _hexagram_risk_level(section)
    section["hexagram_notes"] = "人工六爻输入；系统只记录结构化结论并执行只降级校准，不自动解卦。"
    section["hexagram_source"] = "MANUAL"

    inputs = _existing_hexagrams(section)
    reality_level = updated["weekly_strategy"].get("participation_level") or "CAUTIOUS_TRIAL"
    calibration = calibrate_participation_level(
        reality_level,
        inputs,
        as_of_date=as_of_date or item["observation_start_date"],
        workflow_state=updated,
    )
    section["calibration_result"] = calibration
    updated["weekly_strategy"]["participation_level"] = calibration["calibrated_participation_level"]
    updated["weekly_strategy"]["strategy_summary"] = calibration["final_policy"]
    updated["current_stage"] = "WEEKLY_STRATEGY_READY"
    updated["updated_at"] = _now(now)
    validate_state(updated)
    return updated


def _combined_windows(section: dict[str, Any]) -> list[str]:
    windows: list[str] = []
    for item in _existing_hexagrams(section):
        windows.extend(str(value) for value in item.get("risk_windows") or [])
        windows.extend(str(value) for value in item.get("favorable_windows") or [])
    return list(dict.fromkeys(windows))


def _hexagram_risk_level(section: dict[str, Any]) -> str:
    directions = [str(item.get("hexagram_direction") or "") for item in _existing_hexagrams(section)]
    if "HIGH_RISK" in directions:
        return "HIGH"
    if "NEGATIVE" in directions or "CAUTIOUS" in directions:
        return "CAUTION"
    if directions:
        return "NORMAL"
    return ""


def invalidate_hexagram_result(
    state: dict[str, Any],
    *,
    target_type: str,
    target_name: str,
    question: str,
    reason: str,
    now: str | None = None,
) -> dict[str, Any]:
    validate_state(state)
    if not reason.strip():
        raise HexagramCalibrationError("invalidation reason is required")
    updated = copy.deepcopy(state)
    section = updated["hexagram_manual_input"]
    changed = False
    targets = []
    market = section.get("market_hexagram_result")
    if isinstance(market, dict):
        targets.append(market)
    targets.extend(item for item in section.get("sector_hexagram_results") or [] if isinstance(item, dict))
    for item in targets:
        if (
            item.get("target_type") == target_type
            and item.get("target_name") == target_name
            and item.get("question") == question
            and item.get("validity_status") == "VALID"
        ):
            item["validity_status"] = "INVALIDATED"
            item["invalidation_reason"] = reason
            item["invalidated_at"] = _now(now)
            changed = True
    if not changed:
        raise HexagramCalibrationError("no active hexagram result matched invalidation target")
    section["timing_windows"] = _combined_windows(section)
    updated["updated_at"] = _now(now)
    validate_state(updated)
    return updated


def _load_json_arg(value: str) -> dict[str, Any]:
    path = Path(value)
    text = path.read_text(encoding="utf-8") if path.exists() else value
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise HexagramCalibrationError("JSON input must be an object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual hexagram input and downgrade-only calibration.")
    sub = parser.add_subparsers(dest="command", required=True)

    template = sub.add_parser("template")
    template.add_argument("--target-type", choices=sorted(TARGET_TYPES), required=True)
    template.add_argument("--target-name", required=True)
    template.add_argument("--question", required=True)
    template.add_argument("--start-date", default="")
    template.add_argument("--end-date", default="")

    validate = sub.add_parser("validate")
    validate.add_argument("--input-json", required=True)

    write = sub.add_parser("write")
    write.add_argument("--input-json", required=True)
    write.add_argument("--as-of-date", default="")

    preview = sub.add_parser("preview")
    preview.add_argument("--input-json", required=True)
    preview.add_argument("--reality-participation-level", required=True)
    preview.add_argument("--as-of-date", required=True)

    invalidate = sub.add_parser("invalidate")
    invalidate.add_argument("--target-type", choices=sorted(TARGET_TYPES), required=True)
    invalidate.add_argument("--target-name", required=True)
    invalidate.add_argument("--question", required=True)
    invalidate.add_argument("--reason", required=True)

    args = parser.parse_args(argv)
    if args.command == "template":
        item = create_hexagram_template(
            target_type=args.target_type,
            target_name=args.target_name,
            question=args.question,
            observation_start_date=args.start_date,
            observation_end_date=args.end_date,
        )
        print(json.dumps(item, ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        validate_hexagram_input(_load_json_arg(args.input_json))
        print("hexagram_input_valid")
        return 0
    if args.command == "preview":
        item = _load_json_arg(args.input_json)
        result = calibrate_participation_level(
            args.reality_participation_level,
            [item],
            as_of_date=args.as_of_date,
            workflow_state=load_state(),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "write":
        item = _load_json_arg(args.input_json)
        state = write_hexagram_to_workflow_state(load_state(), item, as_of_date=args.as_of_date or None)
        paths = save_state(state)
        print(json.dumps(paths, ensure_ascii=False, indent=2))
        return 0
    if args.command == "invalidate":
        state = invalidate_hexagram_result(
            load_state(),
            target_type=args.target_type,
            target_name=args.target_name,
            question=args.question,
            reason=args.reason,
        )
        paths = save_state(state)
        print(json.dumps(paths, ensure_ascii=False, indent=2))
        return 0
    raise HexagramCalibrationError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
