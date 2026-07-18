from __future__ import annotations

import json
from pathlib import Path

import pytest

from scoring_system.hexagram_calibration import (
    HexagramCalibrationError,
    create_hexagram_template,
    write_hexagram_to_workflow_state,
)
from scoring_system.workflow_orchestrator import record_history
from scoring_system.workflow_release_drill import (
    build_release_audit,
    run_cold_start_drill,
    run_fault_recovery_drills,
    run_release_drills,
    scan_release_security,
)
from scoring_system.workflow_state import create_blank_state, update_section, validate_state


ROOT = Path(__file__).resolve().parents[1]


def test_full_week_drill_archives_week_and_resets_next_week(tmp_path: Path) -> None:
    result = run_release_drills(output_root=tmp_path)
    scenario = result["scenarios"]["ordinary_choppy_week"]

    assert scenario["status"] == "PASS"
    assert scenario["final_stage"] == "WEEKEND_REALITY_PENDING"
    assert scenario["weekly_archive_exists"] is True
    assert scenario["history_consistent"] is True
    assert scenario["third_candidate_generated"] is False
    assert scenario["days_processed"] == ["20260720", "20260721", "20260722", "20260723", "20260724"]


def test_release_drill_covers_required_scenarios(tmp_path: Path) -> None:
    result = run_release_drills(output_root=tmp_path)

    assert set(result["scenarios"]) == {
        "ordinary_choppy_week",
        "systemic_risk_week",
        "reversal_confirmed_no_immediate_buy",
        "reversal_failed",
        "data_abnormal",
    }
    assert result["scenarios"]["systemic_risk_week"]["hexagram_unlocked_gate"] is False
    assert result["scenarios"]["systemic_risk_week"]["candidate_reselected"] is False
    assert result["scenarios"]["systemic_risk_week"]["holding_forced_sell_all"] is False
    assert result["scenarios"]["reversal_confirmed_no_immediate_buy"]["immediate_buy_after_reversal"] is False
    assert result["scenarios"]["reversal_failed"]["same_day_retry_allowed"] is False
    assert result["scenarios"]["data_abnormal"]["stopped_on_error"] is True


def test_record_history_keeps_repeat_records(tmp_path: Path) -> None:
    first = record_history("night_plan", "20260720", {"run": 1}, history_root=tmp_path, now="2026-07-19T20:00:00")
    second = record_history("night_plan", "20260720", {"run": 2}, history_root=tmp_path, now="2026-07-19T20:01:00")

    assert first != second
    assert first.exists()
    assert second.exists()
    assert len(list((tmp_path / "20260720").glob("night_plan*.json"))) == 2


def test_cold_start_drill_does_not_need_chat_history_or_real_paths(tmp_path: Path) -> None:
    result = run_cold_start_drill(output_root=tmp_path)

    assert result["status_after_missing_token"] == "NOT_READY"
    assert result["status_after_token_and_state"] == "READY"
    assert result["recognized_entry"] == "scripts/run_project.py"
    assert result["chat_history_required"] is False
    assert result["full_token_exposed"] is False
    assert result["absolute_path_dependency"] is False
    assert result["next_command"] == "weekend"


def test_fault_recovery_drills_report_without_overwriting(tmp_path: Path) -> None:
    result = run_fault_recovery_drills(output_root=tmp_path / "missing_parent")

    assert result["status"] == "PASS"
    assert result["workflow_state_json_broken"]["auto_overwritten"] is False
    assert result["invalid_stage"]["reported"] is True
    assert result["expired_hexagram"]["ignored_for_current_strategy"] is True
    assert result["duplicate_hexagram"]["reported"] is True
    assert result["intraday_without_night_plan"]["reported"] is True
    assert result["already_locked_today"]["risk_not_lowered"] is True
    assert result["history_not_writable"]["reported"] is True
    assert result["import_failure"]["status"] == "NOT_READY"
    assert result["token_missing"]["status"] == "NOT_READY"
    assert result["network_timeout"]["reported"] is True


def test_expired_and_duplicate_hexagram_rules_are_exercised() -> None:
    state = create_blank_state(now="2026-07-18T09:00:00", latest_completed_trade_date="20260717")
    state = update_section(
        state,
        "weekend_reality_analysis",
        {"market_state": "震荡", "reality_summary": "允许谨慎试错"},
        next_stage="WEEKEND_HEXAGRAM_PENDING",
        now="2026-07-18T09:01:00",
    )
    state["weekly_strategy"]["participation_level"] = "NORMAL_TRIAL"
    item = create_hexagram_template(
        target_type="MARKET",
        target_name="全市场",
        question="下周市场节奏",
        input_time="2026-07-18T09:02:00",
        observation_start_date="20260714",
        observation_end_date="20260715",
    )
    state = write_hexagram_to_workflow_state(state, item, as_of_date="20260718")
    assert state["hexagram_manual_input"]["calibration_result"]["validity_status"] == "EXPIRED"

    state = create_blank_state(now="2026-07-18T09:00:00", latest_completed_trade_date="20260717")
    state = update_section(
        state,
        "weekend_reality_analysis",
        {"market_state": "震荡", "reality_summary": "允许谨慎试错"},
        next_stage="WEEKEND_HEXAGRAM_PENDING",
        now="2026-07-18T09:01:00",
    )
    state["weekly_strategy"]["participation_level"] = "NORMAL_TRIAL"
    active = create_hexagram_template(
        target_type="MARKET",
        target_name="全市场",
        question="下周市场节奏",
        input_time="2026-07-18T09:02:00",
        observation_start_date="20260720",
        observation_end_date="20260724",
    )
    state = write_hexagram_to_workflow_state(state, active, as_of_date="20260720")
    with pytest.raises(HexagramCalibrationError):
        write_hexagram_to_workflow_state(state, active, as_of_date="20260720")


def test_release_audit_and_security_scan(tmp_path: Path) -> None:
    audit = build_release_audit(root=ROOT)
    security = scan_release_security(root=ROOT)

    assert audit["formal_entry"] == "scripts/run_project.py"
    assert "scripts/run_workflow.py" in audit["compatibility_entries"]
    assert "scripts/run_daily_workflow.py" in audit["deprecated_keep"]
    assert "reports/workflow/tmp_snapshot_probe" in audit["safe_delete_candidates"]
    assert "reports/workflow/current_workflow_state.json" in security["ignored_sensitive_files"]
    assert "manual_review_required" in security
    assert not any("real_token_value" in json.dumps(item, ensure_ascii=False) for item in security["safe_to_commit_files"])


def test_release_files_and_documented_commands_exist() -> None:
    for rel in [
        "docs/WORKFLOW_ARCHITECTURE.md",
        "docs/RELEASE_CHECKLIST.md",
        "CHANGELOG.md",
        "VERSION",
    ]:
        assert (ROOT / rel).exists()

    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.0.0-rc1"
    quickstart = (ROOT / "WORKFLOW_QUICKSTART.md").read_text(encoding="utf-8")
    for command in ["setup", "status", "next", "validate", "intraday-check"]:
        assert f"scripts/run_project.py {command}" in quickstart


def test_examples_remain_sanitized_and_valid() -> None:
    state = json.loads((ROOT / "reports" / "workflow" / "current_workflow_state.example.json").read_text(encoding="utf-8"))
    validate_state(state)
    combined = "\n".join(
        [
            (ROOT / ".env.example").read_text(encoding="utf-8"),
            (ROOT / "config" / "project_config.example.yaml").read_text(encoding="utf-8"),
            json.dumps(state, ensure_ascii=False),
        ]
    )
    for forbidden in ["real_token_value", "真实持仓样例", "C:\\Users\\HUAWEI"]:
        assert forbidden not in combined
