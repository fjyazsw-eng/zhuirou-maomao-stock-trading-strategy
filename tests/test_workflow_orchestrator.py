from __future__ import annotations

from pathlib import Path

from scoring_system.hexagram_calibration import create_hexagram_template, write_hexagram_to_workflow_state
from scoring_system.systemic_risk_gate import SYSTEMIC_ACTION
from scoring_system.workflow_orchestrator import (
    FINAL_INTRADAY_ACTIONS,
    REVERSAL_STATES,
    advance_after_closing_review,
    build_status,
    complete_closing_review,
    complete_weekend_reality,
    create_night_plan,
    decide_next_command,
    generate_weekly_strategy,
    record_history,
    run_intraday_check,
    run_reversal_check,
)
from scoring_system.workflow_state import create_blank_state, validate_state


def base_state() -> dict:
    return create_blank_state(now="2026-07-18T08:00:00", latest_completed_trade_date="20260717")


def ready_for_hexagram() -> dict:
    return complete_weekend_reality(
        base_state(),
        {
            "latest_completed_trade_date": "20260717",
            "market_state": "震荡",
            "market_trend": "稳定",
            "market_risk_level": "NORMAL",
            "focus_sectors": [{"name": "医药"}],
            "reality_summary": "现实分析完成。",
            "reality_participation_level": "CAUTIOUS_TRIAL",
        },
        now="2026-07-18T09:00:00",
    )


def ready_for_weekly_strategy() -> dict:
    item = create_hexagram_template(
        target_type="MARKET",
        target_name="全市场",
        question="下周A股整体参与风险如何？",
        input_time="2026-07-18T10:00:00",
        observation_start_date="20260720",
        observation_end_date="20260724",
    )
    item.update({"hexagram_direction": "NEUTRAL", "confidence_level": "MEDIUM", "analyst_summary": "人工中性。"})
    return write_hexagram_to_workflow_state(ready_for_hexagram(), item, now="2026-07-18T10:00:00")


def ready_for_night_plan() -> dict:
    return generate_weekly_strategy(
        ready_for_weekly_strategy(),
        {
            "allowed_sectors": [{"name": "医药"}],
            "prohibited_sectors": [],
            "allowed_days_or_windows": ["20260720 09:50-10:00"],
            "strategy_summary": "谨慎试错。",
        },
        now="2026-07-18T11:00:00",
    )


def night_plan_state() -> dict:
    return create_night_plan(
        ready_for_night_plan(),
        {
            "plan_trade_date": "20260720",
            "primary_candidate": {"ts_code": "600276.SH", "name": "恒瑞医药", "role": "趋势核心"},
            "backup_candidate": {"ts_code": "688235.SH", "name": "百济神州", "role": "中军"},
            "primary_conditions": ["站稳观察区"],
            "backup_conditions": ["首选否决后再看"],
            "cancellation_conditions": ["市场否决"],
            "systemic_risk_status": "CHECKED",
            "hexagram_risk_window_status": "NONE",
        },
        now="2026-07-19T20:00:00",
    )


def intraday_checked_state() -> dict:
    return run_intraday_check(
        night_plan_state(),
        {"data_status": "OK", "market_veto": False, "sector_veto": False, "primary_veto": False, "backup_veto": False},
        now="2026-07-20T09:55:00",
    )


def test_status_identifies_current_stage_and_next_step() -> None:
    status = build_status(base_state(), current_trade_date="20260720")

    assert status["current_stage"] == "WEEKEND_REALITY_PENDING"
    assert status["next_command"] == "weekend"
    assert "weekend_reality_analysis" in status["missing_steps"]


def test_next_does_not_skip_required_step() -> None:
    assert decide_next_command(base_state()) == "weekend"
    assert decide_next_command(ready_for_hexagram()) == "hexagram"


def test_weekend_reality_must_wait_for_hexagram_input() -> None:
    state = ready_for_hexagram()

    assert state["current_stage"] == "WEEKEND_HEXAGRAM_PENDING"
    assert decide_next_command(state) == "hexagram"


def test_hexagram_input_then_weekly_strategy_ready_for_generation() -> None:
    state = ready_for_weekly_strategy()

    assert state["current_stage"] == "WEEKLY_STRATEGY_READY"
    assert decide_next_command(state) == "weekly-strategy"


def test_night_plan_cannot_bypass_systemic_risk() -> None:
    state = ready_for_night_plan()
    state["systemic_risk_gate"]["new_buy_locked"] = True
    state["systemic_risk_gate"]["systemic_risk_level"] = "SYSTEMIC"

    planned = create_night_plan(
        state,
        {"plan_trade_date": "20260720", "primary_candidate": {"ts_code": "600276.SH"}, "backup_candidate": {"ts_code": "688235.SH"}},
        now="2026-07-19T20:00:00",
    )

    assert planned["night_plan"]["plan_status"] == "SUSPENDED_BY_SYSTEMIC_RISK"
    assert planned["intraday_veto_result"]["final_intraday_action"] == SYSTEMIC_ACTION


def test_intraday_only_checks_primary_and_backup() -> None:
    checked = run_intraday_check(
        night_plan_state(),
        {"data_status": "OK", "market_veto": False, "sector_veto": False, "primary_veto": False, "backup_veto": False},
        now="2026-07-20T09:55:00",
    )

    assert checked["intraday_veto_result"]["checked_candidates"] == ["600276.SH", "688235.SH"]
    assert "third_candidate" not in checked["intraday_veto_result"]


def test_backup_can_be_checked_after_primary_fails() -> None:
    checked = run_intraday_check(
        night_plan_state(),
        {"data_status": "OK", "market_veto": False, "sector_veto": False, "primary_veto": True, "backup_veto": False},
        now="2026-07-20T09:55:00",
    )

    assert checked["intraday_veto_result"]["final_intraday_action"] == "BUY_BACKUP_100"


def test_no_third_candidate_when_primary_and_backup_fail() -> None:
    checked = run_intraday_check(
        night_plan_state(),
        {"data_status": "OK", "market_veto": False, "sector_veto": False, "primary_veto": True, "backup_veto": True},
        now="2026-07-20T09:55:00",
    )

    assert checked["intraday_veto_result"]["final_intraday_action"] == "NO_BUY_STOCK_VETO"
    assert checked["intraday_veto_result"]["checked_candidates"] == ["600276.SH", "688235.SH"]


def test_closing_review_loops_to_next_night_plan_on_non_friday() -> None:
    closed = complete_closing_review(intraday_checked_state(), {"closing_review": "收盘复盘。"}, trade_date="20260720", now="2026-07-20T15:30:00")
    next_state = advance_after_closing_review(closed, next_trade_date="20260721", week_ended=False, now="2026-07-20T16:00:00")

    assert next_state["current_stage"] == "NIGHT_PLAN_READY"
    assert next_state["night_plan"]["plan_trade_date"] == "20260721"


def test_friday_closing_moves_to_weekly_review() -> None:
    closed = complete_closing_review(intraday_checked_state(), {"closing_review": "周五收盘。"}, trade_date="20260724", now="2026-07-24T15:30:00")
    next_state = advance_after_closing_review(closed, next_trade_date="20260727", week_ended=True, now="2026-07-24T16:00:00")

    assert next_state["current_stage"] == "WEEKLY_REVIEW_COMPLETED"


def test_hexagram_reversal_hint_only_enters_reversal_watch() -> None:
    state = ready_for_weekly_strategy()
    state["hexagram_manual_input"]["market_hexagram_result"]["phase_pattern"] = "WEAK_THEN_STABLE"

    checked = run_reversal_check(state, {"reversal_data_status": "OK"}, now="2026-07-20T09:40:00")

    assert checked["reversal_observation"]["reversal_status"] == "REVERSAL_WATCH"


def test_hexagram_reversal_hint_cannot_directly_buy() -> None:
    state = ready_for_weekly_strategy()
    state["hexagram_manual_input"]["market_hexagram_result"]["phase_pattern"] = "WEAK_THEN_STABLE"

    checked = run_reversal_check(state, {"reversal_data_status": "OK"}, now="2026-07-20T09:40:00")

    assert checked["intraday_veto_result"]["final_intraday_action"] != "BUY_PRIMARY_100"


def test_insufficient_reality_signals_do_not_allow_probe() -> None:
    state = ready_for_weekly_strategy()
    state["reversal_observation"]["reversal_status"] = "REVERSAL_WATCH"

    checked = run_reversal_check(
        state,
        {"reversal_data_status": "OK", "index_stabilization_detected": True, "breadth_extreme_detected": True},
        now="2026-07-20T09:40:00",
    )

    assert checked["reversal_observation"]["reversal_status"] == "REVERSAL_WATCH"
    assert checked["intraday_veto_result"]["final_intraday_action"] == "NO_BUY_REVERSAL_UNCONFIRMED"


def test_sufficient_reality_signals_enter_confirmed_flow() -> None:
    state = ready_for_weekly_strategy()
    state["reversal_observation"]["reversal_status"] = "REVERSAL_WATCH"

    checked = run_reversal_check(
        state,
        {
            "reversal_data_status": "OK",
            "index_stabilization_detected": True,
            "breadth_extreme_detected": True,
            "panic_release_detected": True,
            "sector_stabilization_detected": True,
            "core_stock_support_detected": True,
        },
        now="2026-07-20T09:40:00",
    )

    assert checked["reversal_observation"]["reversal_status"] == "REVERSAL_CONFIRMED"
    assert checked["intraday_veto_result"]["final_intraday_action"] != "BUY_PRIMARY_100"


def test_systemic_lock_prevents_reversal_buy_execution() -> None:
    state = ready_for_weekly_strategy()
    state["systemic_risk_gate"]["new_buy_locked"] = True
    state["systemic_risk_gate"]["systemic_risk_level"] = "SYSTEMIC"
    state["reversal_observation"]["reversal_status"] = "REVERSAL_WATCH"

    checked = run_reversal_check(
        state,
        {
            "reversal_data_status": "OK",
            "index_stabilization_detected": True,
            "breadth_extreme_detected": True,
            "panic_release_detected": True,
            "sector_stabilization_detected": True,
            "core_stock_support_detected": True,
        },
        now="2026-07-20T09:40:00",
    )

    assert checked["reversal_observation"]["reversal_status"] == "REVERSAL_CONFIRMED"
    assert checked["daily_execution_state"]["new_buy_locked"] is True
    assert checked["intraday_veto_result"]["final_intraday_action"] == SYSTEMIC_ACTION


def test_reversal_failed_cannot_retry_same_day() -> None:
    state = ready_for_weekly_strategy()
    state["reversal_observation"]["reversal_status"] = "REVERSAL_FAILED"
    state["reversal_observation"]["reversal_trade_date"] = "20260720"

    checked = run_reversal_check(
        state,
        {"reversal_data_status": "OK", "index_stabilization_detected": True, "sector_stabilization_detected": True, "core_stock_support_detected": True},
        trade_date="20260720",
        now="2026-07-20T10:00:00",
    )

    assert checked["reversal_observation"]["reversal_status"] == "REVERSAL_FAILED"


def test_reversal_confirmed_does_not_directly_generate_buy() -> None:
    state = ready_for_weekly_strategy()
    state["reversal_observation"]["reversal_status"] = "REVERSAL_CONFIRMED"

    checked = run_reversal_check(state, {"reversal_data_status": "OK"}, now="2026-07-20T09:40:00")

    assert checked["intraday_veto_result"]["final_intraday_action"] != "BUY_PRIMARY_100"


def test_unreliable_reversal_data_fails() -> None:
    state = ready_for_weekly_strategy()
    state["reversal_observation"]["reversal_status"] = "REVERSAL_WATCH"

    checked = run_reversal_check(state, {"reversal_data_status": "DATA_STALE"}, now="2026-07-20T09:40:00")

    assert checked["reversal_observation"]["reversal_status"] == "REVERSAL_FAILED"
    assert checked["intraday_veto_result"]["final_intraday_action"] == "NO_BUY_DATA_UNRELIABLE"


def test_daily_history_records_do_not_overwrite(tmp_path: Path) -> None:
    first = record_history("night_plan", "20260720", {"id": 1}, history_root=tmp_path, now="2026-07-20T20:00:00")
    second = record_history("night_plan", "20260721", {"id": 2}, history_root=tmp_path, now="2026-07-21T20:00:00")

    assert first != second
    assert first.exists()
    assert second.exists()
    assert (tmp_path / "20260720" / "night_plan.json").exists()
    assert (tmp_path / "20260721" / "night_plan.json").exists()


def test_reversal_states_and_actions_are_fixed_enums() -> None:
    assert {"NONE", "BOTTOMING_WATCH", "REVERSAL_WATCH", "REVERSAL_PROBE_ALLOWED", "REVERSAL_CONFIRMED", "REVERSAL_FAILED"} <= REVERSAL_STATES
    assert {"BUY_PRIMARY_100", "BUY_BACKUP_100", "NO_NEW_BUY_SYSTEMIC_RISK", "NO_BUY_REVERSAL_UNCONFIRMED"} <= FINAL_INTRADAY_ACTIONS
    validate_state(base_state())
