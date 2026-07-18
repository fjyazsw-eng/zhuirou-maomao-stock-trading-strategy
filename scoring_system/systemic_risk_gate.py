from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from scoring_system.verified_market_snapshot import market_state as classify_market_state
from scoring_system.workflow_state import validate_state


RISK_LEVELS = {"NORMAL", "CAUTION", "HIGH", "SYSTEMIC"}
CORE_INDEX_CODES = ("000001.SH", "399001.SZ", "399006.SZ")

SYSTEMIC_RISK_CONFIG: dict[str, Any] = {
    "extreme_weak_up_ratio": 0.20,
    "core_index_sync_drop_pct": -1.50,
    "index_worsening_delta_pct": -0.20,
    "breadth_fast_decline_delta": -0.10,
    "high_signal_count": 3,
    "systemic_signal_count": 4,
    "systemic_pair": ("index_worsening", "strong_sector_selloff"),
}

ESCALATION_SIGNAL_KEYS = (
    "index_worsening",
    "strong_sector_selloff",
    "core_stocks_breakdown",
    "role_stack_weakening",
    "breadth_fast_decline",
    "defensive_divergence_with_market_risk",
)

RELIABLE_DATA_STATUSES = {"PASS", "OK"}
LOCKED_STATUS = "LOCKED"
SUSPENDED_STATUS = "SUSPENDED_BY_SYSTEMIC_RISK"
SYSTEMIC_ACTION = "NO_NEW_BUY_SYSTEMIC_RISK"


def _now(value: str | None = None) -> str:
    return value or datetime.now().isoformat(timespec="seconds")


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_from_time(value: str) -> str:
    return value[:10].replace("-", "")


def _snapshot_status(snapshot: dict[str, Any], explicit_status: str | None = None) -> dict[str, Any]:
    status = explicit_status or str(snapshot.get("snapshot_status") or snapshot.get("data_status") or "")
    if not status:
        status = "DATA_MISSING"
    reliable = status in RELIABLE_DATA_STATUSES
    if not isinstance(snapshot.get("market"), dict):
        reliable = False
        if status in RELIABLE_DATA_STATUSES:
            status = "DATA_MISSING"
    return {"status": status, "reliable": reliable}


def _market(snapshot: dict[str, Any]) -> dict[str, Any]:
    market = snapshot.get("market")
    return market if isinstance(market, dict) else {}


def _breadth_up_ratio(snapshot: dict[str, Any]) -> float | None:
    breadth = _market(snapshot).get("breadth")
    if isinstance(breadth, dict):
        return _as_float(breadth.get("up_ratio"))
    return None


def _core_index_pct_map(snapshot: dict[str, Any]) -> dict[str, float | None]:
    indexes = _market(snapshot).get("core_indexes")
    result: dict[str, float | None] = {code: None for code in CORE_INDEX_CODES}
    if not isinstance(indexes, list):
        return result
    for row in indexes:
        if not isinstance(row, dict):
            continue
        code = str(row.get("ts_code") or "")
        if code in result:
            result[code] = _as_float(row.get("pct_chg"))
    return result


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _market_state(snapshot: dict[str, Any]) -> str:
    market = _market(snapshot)
    explicit = str(market.get("state") or "")
    if explicit:
        return explicit
    pct_map = _core_index_pct_map(snapshot)
    pct_values = [value for value in pct_map.values() if value is not None]
    return classify_market_state(_avg(pct_values), _breadth_up_ratio(snapshot))


def _three_core_indexes_drop_together(snapshot: dict[str, Any]) -> tuple[str, str]:
    pct_map = _core_index_pct_map(snapshot)
    missing = [code for code, value in pct_map.items() if value is None]
    if missing:
        return "UNKNOWN", f"缺少核心指数涨跌幅：{','.join(missing)}"
    threshold = float(SYSTEMIC_RISK_CONFIG["core_index_sync_drop_pct"])
    dropped = [code for code, value in pct_map.items() if value is not None and value <= threshold]
    if len(dropped) == len(CORE_INDEX_CODES):
        return "TRUE", f"三大核心指数跌幅均 <= {threshold}%"
    return "FALSE", "三大核心指数未同步明显下跌"


def _derive_index_worsening(snapshot: dict[str, Any], previous: dict[str, Any] | None) -> tuple[str, str]:
    if previous is None:
        return "UNKNOWN", "缺少前一观察点"
    current = _core_index_pct_map(snapshot)
    prior = _core_index_pct_map(previous)
    missing = [
        code for code in CORE_INDEX_CODES
        if current.get(code) is None or prior.get(code) is None
    ]
    if missing:
        return "UNKNOWN", f"缺少指数前后观察值：{','.join(missing)}"
    delta_threshold = float(SYSTEMIC_RISK_CONFIG["index_worsening_delta_pct"])
    worsening = [
        code for code in CORE_INDEX_CODES
        if (current[code] - prior[code]) <= delta_threshold  # type: ignore[operator]
    ]
    if len(worsening) >= 2:
        return "TRUE", "至少两个核心指数较前一观察点继续扩大跌幅"
    return "FALSE", "未达到两个核心指数继续恶化"


def _derive_breadth_decline(snapshot: dict[str, Any], previous: dict[str, Any] | None) -> tuple[str, str]:
    if previous is None:
        return "UNKNOWN", "缺少前一观察点"
    current = _breadth_up_ratio(snapshot)
    prior = _breadth_up_ratio(previous)
    if current is None or prior is None:
        return "UNKNOWN", "缺少上涨占比前后观察值"
    delta_threshold = float(SYSTEMIC_RISK_CONFIG["breadth_fast_decline_delta"])
    if current - prior <= delta_threshold:
        return "TRUE", "全市场上涨占比较前一观察点快速下降"
    return "FALSE", "上涨占比未快速下降"


def _signal_from_input(
    key: str,
    supplied: dict[str, Any],
    snapshot: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, str]:
    if key in supplied:
        value = supplied.get(key)
        if value is True:
            return {"status": "TRUE", "reason": "上游信号明确成立"}
        if value is False:
            return {"status": "FALSE", "reason": "上游信号明确不成立"}
        return {"status": "UNKNOWN", "reason": "上游信号无法判断"}
    if key == "index_worsening":
        status, reason = _derive_index_worsening(snapshot, previous)
        return {"status": status, "reason": reason}
    if key == "breadth_fast_decline":
        status, reason = _derive_breadth_decline(snapshot, previous)
        return {"status": status, "reason": reason}
    return {"status": "UNKNOWN", "reason": "上游模块未提供该信号"}


def _workflow_locked_today(workflow_state: dict[str, Any] | None, trade_date: str) -> bool:
    if not workflow_state:
        return False
    gate = workflow_state.get("systemic_risk_gate") or {}
    execution = workflow_state.get("daily_execution_state") or {}
    locked = bool(gate.get("new_buy_locked") or execution.get("new_buy_locked"))
    return locked and str(gate.get("new_buy_lock_date") or "") == trade_date


def assess_systemic_risk(
    snapshot: dict[str, Any],
    *,
    previous_observation: dict[str, Any] | None = None,
    workflow_state: dict[str, Any] | None = None,
    assessment_time: str | None = None,
    data_status: str | None = None,
    signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one transparent object whose only decision is whether new buys are locked."""
    checked_at = _now(assessment_time)
    trade_date = str(snapshot.get("trade_date") or _date_from_time(checked_at))
    source = str(snapshot.get("data_source") or "UNKNOWN")
    status = _snapshot_status(snapshot, data_status)
    market = _market(snapshot)
    state = _market_state(snapshot)
    up_ratio = _breadth_up_ratio(snapshot)
    sync_status, sync_reason = _three_core_indexes_drop_together(snapshot)

    hard_reasons: list[str] = []
    if state == "极弱":
        hard_reasons.append("MARKET_STATE_EXTREME_WEAK")
    if sync_status == "TRUE":
        hard_reasons.append("THREE_CORE_INDEXES_DROP_TOGETHER")
    if up_ratio is not None and up_ratio <= float(SYSTEMIC_RISK_CONFIG["extreme_weak_up_ratio"]):
        hard_reasons.append("MARKET_BREADTH_EXTREME_WEAK")
    if not status["reliable"]:
        hard_reasons.append("DATA_UNRELIABLE")
    if _workflow_locked_today(workflow_state, trade_date):
        hard_reasons.append("WORKFLOW_ALREADY_LOCKED_TODAY")

    supplied_signals = signals or {}
    escalation_signals = {
        key: _signal_from_input(key, supplied_signals, snapshot, previous_observation)
        for key in ESCALATION_SIGNAL_KEYS
    }
    true_signals = [key for key, value in escalation_signals.items() if value["status"] == "TRUE"]
    escalation_score = len(true_signals)

    hard_veto = bool(hard_reasons)
    risk_level = "NORMAL"
    if hard_veto:
        risk_level = "SYSTEMIC"
    elif escalation_score >= int(SYSTEMIC_RISK_CONFIG["systemic_signal_count"]):
        risk_level = "SYSTEMIC"
    elif escalation_score >= int(SYSTEMIC_RISK_CONFIG["high_signal_count"]):
        pair = tuple(SYSTEMIC_RISK_CONFIG["systemic_pair"])
        if all(escalation_signals.get(key, {}).get("status") == "TRUE" for key in pair):
            risk_level = "SYSTEMIC"
        else:
            risk_level = "HIGH"
    elif escalation_score > 0:
        risk_level = "CAUTION"

    new_buy_locked = risk_level == "SYSTEMIC"
    lock_reason = "；".join(hard_reasons or true_signals) if new_buy_locked else ""
    return {
        "assessment_time": checked_at,
        "data_trade_date": trade_date,
        "data_source": source,
        "market_state": state,
        "risk_level": risk_level,
        "hard_veto_triggered": hard_veto,
        "hard_veto_reasons": hard_reasons,
        "escalation_score": escalation_score,
        "escalation_signals": escalation_signals,
        "new_buy_locked": new_buy_locked,
        "lock_reason": lock_reason,
        "lock_scope": "NEW_BUY_ONLY" if new_buy_locked else "",
        "assessment_details": {
            "core_index_pcts": _core_index_pct_map(snapshot),
            "three_core_indexes_drop_together": {"status": sync_status, "reason": sync_reason},
            "up_ratio": up_ratio,
            "candidate_checks_skipped": new_buy_locked,
            "holding_module_forced_action": "UNCHANGED",
            "source_market": market,
        },
        "data_status": status,
    }


def _ensure_systemic_section(state: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    if "systemic_risk_gate" not in updated or not isinstance(updated["systemic_risk_gate"], dict):
        updated["systemic_risk_gate"] = {}
    gate = updated["systemic_risk_gate"]
    gate.setdefault("systemic_risk_status", "NOT_CHECKED")
    gate.setdefault("systemic_risk_level", "")
    gate.setdefault("systemic_risk_checked_at", "")
    gate.setdefault("systemic_risk_reasons", [])
    gate.setdefault("new_buy_locked", False)
    gate.setdefault("new_buy_lock_date", "")
    gate.setdefault("new_buy_lock_reason", "")
    gate.setdefault("new_buy_unlock_pending", False)
    gate.setdefault("new_buy_lock_history", [])
    gate.setdefault("assessment_details", {})
    return updated


def apply_systemic_risk_to_workflow_state(
    state: dict[str, Any],
    result: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    updated = _ensure_systemic_section(state)
    checked_at = _now(now)
    locked = bool(result.get("new_buy_locked"))
    reasons = list(result.get("hard_veto_reasons") or [])
    if not reasons:
        reasons = [key for key, value in (result.get("escalation_signals") or {}).items() if value.get("status") == "TRUE"]

    gate = updated["systemic_risk_gate"]
    previous_reason = gate.get("new_buy_lock_reason")
    previous_date = gate.get("new_buy_lock_date")
    if locked and previous_reason:
        history = list(gate.get("new_buy_lock_history") or [])
        history.append({"date": previous_date, "reason": previous_reason})
        gate["new_buy_lock_history"] = history

    gate.update(
        {
            "systemic_risk_status": LOCKED_STATUS if locked else "CHECKED",
            "systemic_risk_level": str(result.get("risk_level") or ""),
            "systemic_risk_checked_at": checked_at,
            "systemic_risk_reasons": reasons,
            "new_buy_locked": locked or bool(gate.get("new_buy_locked")),
            "new_buy_lock_date": str(result.get("data_trade_date") or "") if locked else gate.get("new_buy_lock_date", ""),
            "new_buy_lock_reason": str(result.get("lock_reason") or "；".join(reasons)) if locked else gate.get("new_buy_lock_reason", ""),
            "new_buy_unlock_pending": False if locked else bool(gate.get("new_buy_unlock_pending")),
            "assessment_details": dict(result.get("assessment_details") or {}),
        }
    )
    if locked:
        updated["daily_execution_state"]["new_buy_locked"] = True
        updated["daily_execution_state"]["execution_note"] = gate["new_buy_lock_reason"]
        updated["night_plan"]["plan_status"] = SUSPENDED_STATUS
        for key in ["primary_candidate", "backup_candidate"]:
            candidate = updated["night_plan"].get(key)
            if isinstance(candidate, dict):
                candidate["status"] = SUSPENDED_STATUS
        updated["intraday_veto_result"]["market_veto"] = True
        updated["intraday_veto_result"]["primary_veto"] = True
        updated["intraday_veto_result"]["backup_veto"] = True
        updated["intraday_veto_result"]["data_status"] = result.get("data_status", {}).get("status", "OK")
        updated["intraday_veto_result"]["final_intraday_action"] = SYSTEMIC_ACTION
        updated["intraday_veto_result"]["intraday_checked_at"] = checked_at
    updated["updated_at"] = checked_at
    validate_state(updated)
    return updated


def release_new_buy_lock_if_recovered(
    state: dict[str, Any],
    recovery_result: dict[str, Any],
    *,
    now: str | None = None,
    next_stage: str = "INTRADAY_CHECK_PENDING",
) -> dict[str, Any]:
    updated = _ensure_systemic_section(state)
    checked_at = _now(now)
    gate = updated["systemic_risk_gate"]
    lock_date = str(gate.get("new_buy_lock_date") or "")
    recovery_date = str(recovery_result.get("data_trade_date") or "")
    can_release = (
        bool(gate.get("new_buy_locked"))
        and bool(recovery_date)
        and recovery_date != lock_date
        and recovery_result.get("risk_level") in {"NORMAL", "CAUTION"}
        and bool((recovery_result.get("data_status") or {}).get("reliable"))
        and recovery_result.get("market_state") != "极弱"
    )
    if can_release:
        history = list(gate.get("new_buy_lock_history") or [])
        history.append(
            {
                "date": lock_date,
                "reason": gate.get("new_buy_lock_reason", ""),
                "released_at": checked_at,
                "release_assessment_trade_date": recovery_date,
            }
        )
        gate.update(
            {
                "systemic_risk_status": "UNLOCKED_AFTER_REVIEW",
                "systemic_risk_level": str(recovery_result.get("risk_level") or ""),
                "systemic_risk_checked_at": checked_at,
                "systemic_risk_reasons": [],
                "new_buy_locked": False,
                "new_buy_lock_date": "",
                "new_buy_lock_reason": "",
                "new_buy_unlock_pending": False,
                "new_buy_lock_history": history,
                "assessment_details": dict(recovery_result.get("assessment_details") or {}),
            }
        )
        updated["daily_execution_state"]["new_buy_locked"] = False
        updated["daily_execution_state"]["execution_note"] = "系统性风险锁已由盘后/次日前复核解除；仍需进入盘中检查，不直接恢复为可买。"
        updated["current_stage"] = next_stage
    else:
        gate["new_buy_unlock_pending"] = recovery_date == lock_date and bool(gate.get("new_buy_locked"))
        gate["systemic_risk_checked_at"] = checked_at
        gate["systemic_risk_level"] = str(recovery_result.get("risk_level") or gate.get("systemic_risk_level") or "")
    updated["updated_at"] = checked_at
    validate_state(updated)
    return updated
