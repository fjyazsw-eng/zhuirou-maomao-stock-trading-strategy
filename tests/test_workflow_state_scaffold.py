from __future__ import annotations

import json
from pathlib import Path

import pytest

from scoring_system.workflow_state import (
    DEFAULT_PLANNED_QUANTITY,
    WorkflowStateError,
    create_blank_state,
    load_state,
    render_markdown,
    save_state,
    update_section,
    validate_state,
)


def test_create_blank_state_file(tmp_path: Path) -> None:
    state = create_blank_state(now="2026-07-18T15:00:00", latest_completed_trade_date="20260717")
    json_path = tmp_path / "current_workflow_state.json"
    md_path = tmp_path / "current_workflow_state.md"

    save_state(state, json_path=json_path, markdown_path=md_path)
    loaded = load_state(json_path)

    assert json_path.exists()
    assert md_path.exists()
    assert loaded["workflow_version"] == "workflow_state_v1"
    assert loaded["latest_completed_trade_date"] == "20260717"
    assert loaded["current_stage"] == "WEEKEND_REALITY_PENDING"
    assert loaded["night_plan"]["planned_quantity"] == DEFAULT_PLANNED_QUANTITY


def test_update_weekend_reality_limits_focus_sectors_to_two() -> None:
    state = create_blank_state(now="2026-07-18T15:00:00")

    updated = update_section(
        state,
        "weekend_reality_analysis",
        {
            "market_state": "极弱",
            "market_trend": "恶化",
            "market_risk_level": "HIGH",
            "focus_sectors": [{"name": "煤炭"}, {"name": "银行"}],
            "excluded_sectors": [{"name": "电子"}],
            "reality_summary": "只保存人工/报告结论，不自动计算。",
            "source_report": "reports/capability_boundary_audit_20260718.md",
        },
        next_stage="WEEKEND_HEXAGRAM_PENDING",
        now="2026-07-18T15:01:00",
    )

    assert updated["current_stage"] == "WEEKEND_HEXAGRAM_PENDING"
    assert updated["weekend_reality_analysis"]["focus_sectors"] == [{"name": "煤炭"}, {"name": "银行"}]
    validate_state(updated)

    with pytest.raises(WorkflowStateError, match="focus_sectors"):
        update_section(
            state,
            "weekend_reality_analysis",
            {"focus_sectors": [{"name": "煤炭"}, {"name": "银行"}, {"name": "传媒"}]},
            now="2026-07-18T15:01:00",
        )


def test_update_hexagram_manual_result() -> None:
    state = update_section(
        create_blank_state(now="2026-07-18T15:00:00"),
        "weekend_reality_analysis",
        {"market_state": "震荡"},
        next_stage="WEEKEND_HEXAGRAM_PENDING",
        now="2026-07-18T15:01:00",
    )

    updated = update_section(
        state,
        "hexagram_manual_input",
        {
            "hexagram_status": "PROVIDED",
            "market_hexagram_result": "偏防守",
            "sector_hexagram_results": [{"sector": "煤炭", "result": "只观察"}],
            "timing_windows": ["周二后再看"],
            "hexagram_risk_level": "HIGH",
            "hexagram_notes": "人工输入；不做自动断卦。",
        },
        next_stage="WEEKLY_STRATEGY_READY",
        now="2026-07-18T15:02:00",
    )

    assert updated["hexagram_manual_input"]["adjustment_rule"] == "DOWNGRADE_ONLY"
    assert updated["hexagram_manual_input"]["hexagram_status"] == "PROVIDED"
    assert updated["current_stage"] == "WEEKLY_STRATEGY_READY"


def test_update_night_plan_primary_and_backup() -> None:
    state = create_blank_state(now="2026-07-18T15:00:00")
    state = update_section(state, "weekend_reality_analysis", {}, next_stage="WEEKEND_HEXAGRAM_PENDING", now="2026-07-18T15:00:30")
    state = update_section(state, "hexagram_manual_input", {}, next_stage="WEEKLY_STRATEGY_READY", now="2026-07-18T15:00:45")
    state = update_section(
        state,
        "weekly_strategy",
        {
            "participation_level": "CAUTIOUS_TRIAL",
            "allowed_sectors": [{"name": "煤炭"}],
            "prohibited_sectors": [{"name": "电子"}],
            "allowed_days_or_windows": ["9:50-10:00"],
            "strategy_summary": "只允许小试。",
        },
        next_stage="NIGHT_PLAN_READY",
        now="2026-07-18T15:01:00",
    )

    updated = update_section(
        state,
        "night_plan",
        {
            "plan_trade_date": "20260720",
            "primary_candidate": {"ts_code": "601088.SH", "name": "中国神华"},
            "backup_candidate": {"ts_code": "601225.SH", "name": "陕西煤业"},
            "primary_conditions": ["不高开追涨"],
            "backup_conditions": ["第一优先否决后再看"],
            "cancellation_conditions": ["实时数据不足"],
            "plan_status": "READY",
        },
        now="2026-07-18T15:02:00",
    )

    assert updated["night_plan"]["planned_quantity"] == 100
    assert updated["night_plan"]["primary_candidate"]["ts_code"] == "601088.SH"
    assert updated["night_plan"]["backup_candidate"]["ts_code"] == "601225.SH"


def test_update_intraday_veto_result() -> None:
    state = create_blank_state(now="2026-07-18T15:00:00")
    state = update_section(state, "weekend_reality_analysis", {}, next_stage="WEEKEND_HEXAGRAM_PENDING", now="2026-07-18T15:00:30")
    state = update_section(state, "hexagram_manual_input", {}, next_stage="WEEKLY_STRATEGY_READY", now="2026-07-18T15:00:45")
    state = update_section(
        state,
        "weekly_strategy",
        {"participation_level": "CAUTIOUS_TRIAL"},
        next_stage="NIGHT_PLAN_READY",
        now="2026-07-18T15:01:00",
    )
    state = update_section(state, "intraday_veto_result", {}, next_stage="INTRADAY_CHECK_PENDING", now="2026-07-18T15:02:00")

    updated = update_section(
        state,
        "intraday_veto_result",
        {
            "intraday_data_source": "EASTMONEY_TEMPORARY",
            "market_veto": True,
            "sector_veto": True,
            "primary_veto": True,
            "backup_veto": True,
            "data_status": "OK",
            "final_intraday_action": "今天不买",
            "intraday_checked_at": "2026-07-20T09:58:00",
        },
        next_stage="INTRADAY_CHECK_COMPLETED",
        now="2026-07-20T09:58:00",
    )

    assert updated["intraday_veto_result"]["check_time_window"] == "09:50-10:00"
    assert updated["intraday_veto_result"]["final_intraday_action"] == "今天不买"
    assert updated["current_stage"] == "INTRADAY_CHECK_COMPLETED"


def test_update_closing_and_weekly_review() -> None:
    state = create_blank_state(now="2026-07-18T15:00:00")
    for next_stage in [
        "WEEKEND_HEXAGRAM_PENDING",
        "WEEKLY_STRATEGY_READY",
        "NIGHT_PLAN_READY",
        "INTRADAY_CHECK_PENDING",
        "INTRADAY_CHECK_COMPLETED",
    ]:
        state = update_section(state, "daily_execution_state", {}, next_stage=next_stage, now="2026-07-18T15:01:00")

    state = update_section(
        state,
        "closing_holding_review",
        {
            "holding_actions": [{"ts_code": "000988.SZ", "action": "持有不动"}],
            "closing_review": "收盘后人工复盘记录。",
            "next_day_attention": ["不补仓"],
        },
        next_stage="CLOSING_REVIEW_COMPLETED",
        now="2026-07-20T15:30:00",
    )
    updated = update_section(
        state,
        "weekly_review",
        {
            "reality_accuracy_score": 70,
            "hexagram_value_score": 0,
            "intraday_veto_value": "拦截无效计划",
            "avoided_loss": None,
            "missed_opportunity": None,
            "execution_deviation": "无",
            "weekly_summary": "本周仅记录骨架。",
            "next_week_adjustments": ["继续小样本验证"],
        },
        next_stage="WEEKLY_REVIEW_COMPLETED",
        now="2026-07-24T16:00:00",
    )

    assert updated["closing_holding_review"]["holding_actions"][0]["action"] == "持有不动"
    assert updated["weekly_review"]["weekly_summary"] == "本周仅记录骨架。"
    assert updated["current_stage"] == "WEEKLY_REVIEW_COMPLETED"


def test_illegal_stage_transition_raises() -> None:
    state = create_blank_state(now="2026-07-18T15:00:00")

    with pytest.raises(WorkflowStateError, match="Illegal stage transition"):
        update_section(state, "weekly_review", {}, next_stage="WEEKLY_REVIEW_COMPLETED", now="2026-07-18T15:01:00")


def test_markdown_renders_key_sections() -> None:
    state = update_section(
        create_blank_state(now="2026-07-18T15:00:00", latest_completed_trade_date="20260717"),
        "weekend_reality_analysis",
        {"market_state": "极弱", "focus_sectors": [{"name": "煤炭"}], "source_report": "reports/source.md"},
        next_stage="WEEKEND_HEXAGRAM_PENDING",
        now="2026-07-18T15:01:00",
    )

    markdown = render_markdown(state)

    assert "# 工作流状态" in markdown
    assert "20260717" in markdown
    assert "周末现实分析" in markdown
    assert "煤炭" in markdown
    assert "六爻人工输入" in markdown
    assert "DOWNGRADE_ONLY" in markdown


def test_saved_json_is_valid_structure(tmp_path: Path) -> None:
    json_path = tmp_path / "state.json"
    md_path = tmp_path / "state.md"
    state = create_blank_state(now="2026-07-18T15:00:00")

    save_state(state, json_path=json_path, markdown_path=md_path)
    raw = json.loads(json_path.read_text(encoding="utf-8"))

    assert validate_state(raw) is None
