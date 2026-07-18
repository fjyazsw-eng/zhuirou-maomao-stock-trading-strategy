from __future__ import annotations

import pytest

from scoring_system.hexagram_calibration import (
    HexagramCalibrationError,
    calibrate_participation_level,
    create_hexagram_template,
    invalidate_hexagram_result,
    write_hexagram_to_workflow_state,
)
from scoring_system.systemic_risk_gate import SYSTEMIC_ACTION
from scoring_system.workflow_state import create_blank_state


def reality_state(level: str = "NORMAL_TRIAL") -> dict:
    state = create_blank_state(now="2026-07-18T09:00:00", latest_completed_trade_date="20260717")
    state["current_stage"] = "WEEKEND_HEXAGRAM_PENDING"
    state["weekend_reality_analysis"]["market_state"] = "震荡"
    state["weekend_reality_analysis"]["reality_summary"] = "现实周末分析已完成。"
    state["weekly_strategy"]["participation_level"] = level
    return state


def market_hexagram(direction: str, **updates: object) -> dict:
    item = create_hexagram_template(
        target_type="MARKET",
        target_name="全市场",
        question="下周A股整体参与风险如何？",
        input_time="2026-07-18T10:00:00",
        observation_start_date="20260720",
        observation_end_date="20260724",
    )
    item.update(
        {
            "hexagram_direction": direction,
            "phase_pattern": "UNKNOWN",
            "confidence_level": "MEDIUM",
            "analyst_summary": "人工整理结论。",
            "raw_notes": "人工输入，不自动解卦。",
        }
    )
    item.update(updates)
    return item


def test_normal_reality_positive_hexagram_keeps_normal() -> None:
    result = calibrate_participation_level("NORMAL_TRIAL", [market_hexagram("POSITIVE")], as_of_date="20260720")

    assert result["calibrated_participation_level"] == "NORMAL_TRIAL"
    assert result["downgrade_applied"] is False
    assert result["final_policy"] == "保持原策略"


def test_normal_reality_cautious_hexagram_downgrades_to_cautious() -> None:
    result = calibrate_participation_level("NORMAL_TRIAL", [market_hexagram("CAUTIOUS")], as_of_date="20260720")

    assert result["calibrated_participation_level"] == "CAUTIOUS_TRIAL"
    assert result["downgrade_applied"] is True
    assert result["final_policy"] == "降为谨慎试错"


def test_normal_reality_high_risk_hexagram_blocks_new_buy() -> None:
    result = calibrate_participation_level("NORMAL_TRIAL", [market_hexagram("HIGH_RISK")], as_of_date="20260720")

    assert result["calibrated_participation_level"] == "NO_NEW_BUY"
    assert result["downgrade_applied"] is True
    assert result["final_policy"] == "禁止新买入"


def test_cautious_reality_positive_hexagram_does_not_upgrade() -> None:
    result = calibrate_participation_level("CAUTIOUS_TRIAL", [market_hexagram("POSITIVE")], as_of_date="20260720")

    assert result["calibrated_participation_level"] == "CAUTIOUS_TRIAL"
    assert result["downgrade_applied"] is False


def test_no_new_buy_reality_positive_hexagram_stays_blocked() -> None:
    result = calibrate_participation_level("NO_NEW_BUY", [market_hexagram("POSITIVE")], as_of_date="20260720")

    assert result["calibrated_participation_level"] == "NO_NEW_BUY"
    assert result["downgrade_applied"] is False
    assert result["final_policy"] == "禁止新买入"


def test_systemic_risk_positive_hexagram_still_blocks() -> None:
    state = reality_state("NORMAL_TRIAL")
    state["systemic_risk_gate"]["new_buy_locked"] = True
    state["systemic_risk_gate"]["systemic_risk_level"] = "SYSTEMIC"
    state["intraday_veto_result"]["final_intraday_action"] = SYSTEMIC_ACTION

    result = calibrate_participation_level(
        "NORMAL_TRIAL",
        [market_hexagram("POSITIVE", favorable_windows=["20260720上午"])],
        as_of_date="20260720",
        workflow_state=state,
    )

    assert result["blocked_by_systemic_risk"] is True
    assert result["calibrated_participation_level"] == "NO_NEW_BUY"
    assert result["final_intraday_action"] == SYSTEMIC_ACTION


def test_risk_window_only_downgrades() -> None:
    result = calibrate_participation_level(
        "NORMAL_TRIAL",
        [market_hexagram("NEUTRAL", risk_windows=["20260721 09:50-10:00"])],
        as_of_date="20260721",
    )

    assert result["calibrated_participation_level"] == "CAUTIOUS_TRIAL"
    assert result["downgrade_applied"] is True
    assert result["risk_windows"] == ["20260721 09:50-10:00"]


def test_favorable_window_never_creates_buy_action() -> None:
    result = calibrate_participation_level(
        "CAUTIOUS_TRIAL",
        [market_hexagram("POSITIVE", favorable_windows=["20260722下午"])],
        as_of_date="20260722",
    )

    assert result["calibrated_participation_level"] == "CAUTIOUS_TRIAL"
    assert result["final_intraday_action"] == ""
    assert result["favorable_windows"] == ["20260722下午"]


def test_expired_hexagram_does_not_join_current_calibration() -> None:
    result = calibrate_participation_level(
        "NORMAL_TRIAL",
        [market_hexagram("HIGH_RISK", observation_end_date="20260719")],
        as_of_date="20260720",
    )

    assert result["calibrated_participation_level"] == "NORMAL_TRIAL"
    assert result["validity_status"] == "EXPIRED"
    assert result["downgrade_applied"] is False


def test_invalidated_hexagram_does_not_join_current_calibration() -> None:
    result = calibrate_participation_level(
        "NORMAL_TRIAL",
        [market_hexagram("HIGH_RISK", validity_status="INVALIDATED", invalidation_reason="人工作废")],
        as_of_date="20260720",
    )

    assert result["calibrated_participation_level"] == "NORMAL_TRIAL"
    assert result["validity_status"] == "INVALIDATED"


def test_same_active_question_cannot_be_overwritten() -> None:
    state = write_hexagram_to_workflow_state(
        reality_state(),
        market_hexagram("CAUTIOUS"),
        now="2026-07-18T10:00:00",
    )

    with pytest.raises(HexagramCalibrationError, match="active hexagram"):
        write_hexagram_to_workflow_state(
            state,
            market_hexagram("NEGATIVE"),
            now="2026-07-18T10:05:00",
        )


def test_workflow_stage_transition_after_hexagram_input() -> None:
    updated = write_hexagram_to_workflow_state(
        reality_state("NORMAL_TRIAL"),
        market_hexagram("CAUTIOUS"),
        now="2026-07-18T10:00:00",
    )

    assert updated["current_stage"] == "WEEKLY_STRATEGY_READY"
    assert updated["hexagram_manual_input"]["hexagram_status"] == "PROVIDED"
    assert updated["hexagram_manual_input"]["adjustment_rule"] == "DOWNGRADE_ONLY"
    assert updated["weekly_strategy"]["participation_level"] == "CAUTIOUS_TRIAL"


def test_mark_invalidated_allows_reentry_for_same_question() -> None:
    state = write_hexagram_to_workflow_state(reality_state(), market_hexagram("CAUTIOUS"), now="2026-07-18T10:00:00")
    invalidated = invalidate_hexagram_result(
        state,
        target_type="MARKET",
        target_name="全市场",
        question="下周A股整体参与风险如何？",
        reason="人工主动标记失效",
        now="2026-07-18T10:10:00",
    )
    updated = write_hexagram_to_workflow_state(
        invalidated,
        market_hexagram("NEUTRAL"),
        now="2026-07-18T10:15:00",
    )

    assert updated["hexagram_manual_input"]["market_hexagram_result"]["hexagram_direction"] == "NEUTRAL"
