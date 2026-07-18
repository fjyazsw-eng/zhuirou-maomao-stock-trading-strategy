from __future__ import annotations

from copy import deepcopy

from scoring_system.systemic_risk_gate import (
    assess_systemic_risk,
    apply_systemic_risk_to_workflow_state,
    release_new_buy_lock_if_recovered,
)
from scoring_system.workflow_state import create_blank_state


def snapshot(
    *,
    state: str = "震荡",
    trade_date: str = "20260715",
    up_ratio: float = 0.45,
    index_pcts: dict[str, float] | None = None,
    status: str = "PASS",
) -> dict:
    index_pcts = index_pcts or {
        "000001.SH": -0.2,
        "399001.SZ": -0.1,
        "399006.SZ": 0.1,
    }
    return {
        "snapshot_status": status,
        "trade_date": trade_date,
        "data_source": "test_snapshot",
        "market": {
            "state": state,
            "breadth": {"up_ratio": up_ratio},
            "core_indexes": [
                {"ts_code": code, "pct_chg": pct}
                for code, pct in index_pcts.items()
            ],
        },
    }


def test_extremely_weak_market_opens_gate() -> None:
    result = assess_systemic_risk(
        snapshot(state="极弱", trade_date="20260717", up_ratio=0.087),
        assessment_time="2026-07-18T09:55:00",
    )

    assert result["risk_level"] == "SYSTEMIC"
    assert result["hard_veto_triggered"] is True
    assert result["new_buy_locked"] is True
    assert "MARKET_STATE_EXTREME_WEAK" in result["hard_veto_reasons"]


def test_three_core_indexes_falling_together_opens_gate() -> None:
    result = assess_systemic_risk(
        snapshot(
            state="弱",
            up_ratio=0.38,
            index_pcts={"000001.SH": -1.7, "399001.SZ": -2.0, "399006.SZ": -2.3},
        ),
        assessment_time="2026-07-15T09:55:00",
    )

    assert result["risk_level"] == "SYSTEMIC"
    assert result["new_buy_locked"] is True
    assert "THREE_CORE_INDEXES_DROP_TOGETHER" in result["hard_veto_reasons"]


def test_stale_or_unreliable_data_opens_gate() -> None:
    result = assess_systemic_risk(
        snapshot(status="DATA_STALE"),
        assessment_time="2026-07-15T09:55:00",
    )

    assert result["risk_level"] == "SYSTEMIC"
    assert result["data_status"]["status"] == "DATA_STALE"
    assert "DATA_UNRELIABLE" in result["hard_veto_reasons"]


def test_single_ordinary_worsening_signal_does_not_open_gate() -> None:
    result = assess_systemic_risk(
        snapshot(),
        assessment_time="2026-07-15T09:55:00",
        signals={"strong_sector_selloff": True},
    )

    assert result["risk_level"] == "CAUTION"
    assert result["hard_veto_triggered"] is False
    assert result["new_buy_locked"] is False


def test_three_worsening_signals_enter_high_without_lock() -> None:
    result = assess_systemic_risk(
        snapshot(),
        assessment_time="2026-07-15T09:55:00",
        signals={
            "strong_sector_selloff": True,
            "core_stocks_breakdown": True,
            "role_stack_weakening": True,
        },
    )

    assert result["risk_level"] == "HIGH"
    assert result["new_buy_locked"] is False
    assert result["escalation_score"] == 3


def test_systemic_combination_locks_new_buy() -> None:
    result = assess_systemic_risk(
        snapshot(),
        assessment_time="2026-07-15T09:55:00",
        signals={
            "index_worsening": True,
            "strong_sector_selloff": True,
            "core_stocks_breakdown": True,
        },
    )

    assert result["risk_level"] == "SYSTEMIC"
    assert result["new_buy_locked"] is True
    assert result["lock_scope"] == "NEW_BUY_ONLY"


def test_same_day_lock_cannot_auto_release() -> None:
    state = create_blank_state(now="2026-07-15T09:00:00", latest_completed_trade_date="20260715")
    locked = deepcopy(state)
    locked["daily_execution_state"]["new_buy_locked"] = True
    locked["systemic_risk_gate"] = {
        "systemic_risk_status": "LOCKED",
        "systemic_risk_level": "SYSTEMIC",
        "systemic_risk_checked_at": "2026-07-15T09:55:00",
        "systemic_risk_reasons": ["previous lock"],
        "new_buy_locked": True,
        "new_buy_lock_date": "20260715",
        "new_buy_lock_reason": "previous lock",
        "new_buy_unlock_pending": False,
        "new_buy_lock_history": [],
    }

    result = assess_systemic_risk(
        snapshot(trade_date="20260715", state="震荡", up_ratio=0.5),
        assessment_time="2026-07-15T10:30:00",
        workflow_state=locked,
    )

    assert result["risk_level"] == "SYSTEMIC"
    assert "WORKFLOW_ALREADY_LOCKED_TODAY" in result["hard_veto_reasons"]


def test_systemic_gate_suspends_primary_backup_and_skips_stock_checks() -> None:
    state = create_blank_state(now="2026-07-15T09:00:00", latest_completed_trade_date="20260715")
    state["night_plan"]["primary_candidate"] = {"ts_code": "600000.SH", "name": "测试首选"}
    state["night_plan"]["backup_candidate"] = {"ts_code": "000001.SZ", "name": "测试备选"}
    result = assess_systemic_risk(
        snapshot(state="极弱", trade_date="20260715", up_ratio=0.1),
        assessment_time="2026-07-15T09:55:00",
    )

    updated = apply_systemic_risk_to_workflow_state(state, result, now="2026-07-15T09:55:00")

    assert updated["night_plan"]["plan_status"] == "SUSPENDED_BY_SYSTEMIC_RISK"
    assert updated["night_plan"]["primary_candidate"]["status"] == "SUSPENDED_BY_SYSTEMIC_RISK"
    assert updated["night_plan"]["backup_candidate"]["status"] == "SUSPENDED_BY_SYSTEMIC_RISK"
    assert updated["intraday_veto_result"]["final_intraday_action"] == "NO_NEW_BUY_SYSTEMIC_RISK"
    assert updated["systemic_risk_gate"]["assessment_details"]["candidate_checks_skipped"] is True


def test_holding_review_is_not_forced_to_sell_all() -> None:
    state = create_blank_state(now="2026-07-15T09:00:00", latest_completed_trade_date="20260715")
    state["closing_holding_review"]["holding_actions"] = [
        {"ts_code": "300209.SZ", "action": "持有100股"}
    ]
    result = assess_systemic_risk(
        snapshot(state="极弱", trade_date="20260715", up_ratio=0.1),
        assessment_time="2026-07-15T09:55:00",
    )

    updated = apply_systemic_risk_to_workflow_state(state, result, now="2026-07-15T09:55:00")

    assert updated["closing_holding_review"]["holding_actions"] == [
        {"ts_code": "300209.SZ", "action": "持有100股"}
    ]


def test_next_trade_day_recovery_can_release_lock() -> None:
    state = create_blank_state(now="2026-07-15T09:00:00", latest_completed_trade_date="20260715")
    result = assess_systemic_risk(
        snapshot(state="极弱", trade_date="20260715", up_ratio=0.1),
        assessment_time="2026-07-15T09:55:00",
    )
    locked = apply_systemic_risk_to_workflow_state(state, result, now="2026-07-15T09:55:00")
    recovery = assess_systemic_risk(
        snapshot(
            state="震荡",
            trade_date="20260716",
            up_ratio=0.48,
            index_pcts={"000001.SH": 0.2, "399001.SZ": -0.1, "399006.SZ": 0.3},
        ),
        assessment_time="2026-07-16T08:50:00",
    )

    released = release_new_buy_lock_if_recovered(locked, recovery, now="2026-07-16T08:50:00")

    assert released["systemic_risk_gate"]["new_buy_locked"] is False
    assert released["daily_execution_state"]["new_buy_locked"] is False
    assert released["current_stage"] == "INTRADAY_CHECK_PENDING"
    assert released["intraday_veto_result"]["final_intraday_action"] != "买第一优先100股"


def test_unlock_same_day_keeps_lock_and_marks_pending() -> None:
    state = create_blank_state(now="2026-07-15T09:00:00", latest_completed_trade_date="20260715")
    result = assess_systemic_risk(
        snapshot(state="极弱", trade_date="20260715", up_ratio=0.1),
        assessment_time="2026-07-15T09:55:00",
    )
    locked = apply_systemic_risk_to_workflow_state(state, result, now="2026-07-15T09:55:00")
    recovery = assess_systemic_risk(
        snapshot(state="震荡", trade_date="20260715", up_ratio=0.48),
        assessment_time="2026-07-15T14:50:00",
    )

    still_locked = release_new_buy_lock_if_recovered(locked, recovery, now="2026-07-15T14:50:00")

    assert still_locked["systemic_risk_gate"]["new_buy_locked"] is True
    assert still_locked["systemic_risk_gate"]["new_buy_unlock_pending"] is True
