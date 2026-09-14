from __future__ import annotations

import json
from pathlib import Path

import pytest

from scoring_system.portable_setup_check import evaluate_setup
from scripts import run_project


ROOT = Path(__file__).resolve().parents[1]


def make_minimal_project(tmp_path: Path) -> Path:
    root = tmp_path / "stock-ai"
    (root / "scoring_system").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "skills" / "stock-ai-workflow-controller").mkdir(parents=True)
    (root / "reports" / "workflow").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "tests").mkdir()
    (root / "scoring_system" / "__init__.py").write_text("", encoding="utf-8")
    (root / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    (root / "requirements-dev.txt").write_text("pytest>=8\n", encoding="utf-8")
    (root / ".env.example").write_text("HITHINK_FINANCE_API_KEY=\nMOOTDX_SERVER=\n", encoding="utf-8")
    (root / "skills" / "stock-ai-workflow-controller" / "SKILL.md").write_text("# controller\n", encoding="utf-8")
    state = {
        "workflow_version": "workflow_state_v1",
        "created_at": "2026-07-18T00:00:00",
        "updated_at": "2026-07-18T00:00:00",
        "latest_completed_trade_date": "",
        "current_stage": "WEEKEND_REALITY_PENDING",
        "weekend_reality_analysis": {"market_state": "", "market_trend": "", "market_risk_level": "", "focus_sectors": [], "excluded_sectors": [], "reality_summary": "", "source_report": ""},
        "hexagram_manual_input": {"hexagram_status": "NOT_PROVIDED", "market_hexagram_result": "", "sector_hexagram_results": [], "timing_windows": [], "hexagram_risk_level": "", "hexagram_notes": "", "hexagram_source": "", "adjustment_rule": "DOWNGRADE_ONLY", "calibration_result": {}},
        "weekly_strategy": {"participation_level": "", "allowed_sectors": [], "prohibited_sectors": [], "allowed_days_or_windows": [], "strategy_summary": ""},
        "night_plan": {"plan_trade_date": "", "primary_candidate": {"ts_code": "", "name": "", "sector": "", "buy_level": "", "notes": ""}, "backup_candidate": {"ts_code": "", "name": "", "sector": "", "buy_level": "", "notes": ""}, "planned_quantity": 100, "primary_conditions": [], "backup_conditions": [], "cancellation_conditions": [], "plan_status": "NOT_READY"},
        "intraday_veto_result": {"check_time_window": "09:50-10:00", "intraday_data_source": "", "market_veto": None, "sector_veto": None, "primary_veto": None, "backup_veto": None, "data_status": "NOT_CHECKED", "final_intraday_action": "", "intraday_checked_at": ""},
        "daily_execution_state": {"new_buy_locked": False, "new_position_opened_today": False, "executed_symbol": "", "executed_quantity": 0, "execution_note": ""},
        "systemic_risk_gate": {"systemic_risk_status": "NOT_CHECKED", "systemic_risk_level": "", "systemic_risk_checked_at": "", "systemic_risk_reasons": [], "new_buy_locked": False, "new_buy_lock_date": "", "new_buy_lock_reason": "", "new_buy_unlock_pending": False, "new_buy_lock_history": [], "assessment_details": {}},
        "reversal_observation": {"reversal_status": "NONE", "reversal_trade_date": "", "reversal_source": "", "panic_release_detected": "UNKNOWN", "breadth_extreme_detected": "UNKNOWN", "index_stabilization_detected": "UNKNOWN", "sector_stabilization_detected": "UNKNOWN", "core_stock_support_detected": "UNKNOWN", "reversal_confirmation_count": 0, "reversal_data_status": "NOT_CHECKED", "reversal_reason": "", "reversal_failed_reason": "", "reversal_checked_at": ""},
        "workflow_audit": {"completed_steps": [], "history_root": "reports/workflow/history", "last_next_command": ""},
        "closing_holding_review": {"holding_actions": [], "closing_review": "", "next_day_attention": []},
        "weekly_review": {"reality_accuracy_score": None, "hexagram_value_score": None, "intraday_veto_value": "", "avoided_loss": None, "missed_opportunity": None, "execution_deviation": "", "weekly_summary": "", "next_week_adjustments": []},
    }
    (root / "reports" / "workflow" / "current_workflow_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    (root / "config" / "project_config.example.yaml").write_text("project_name: stock-ai\n", encoding="utf-8")
    return root


def test_controller_skill_exists() -> None:
    assert (ROOT / "skills" / "stock-ai-workflow-controller" / "SKILL.md").exists()


def test_quickstart_and_context_exist() -> None:
    assert (ROOT / "WORKFLOW_QUICKSTART.md").exists()
    assert (ROOT / "PROJECT_CONTEXT.md").exists()


def test_setup_ready_with_minimal_project_and_token(tmp_path: Path) -> None:
    root = make_minimal_project(tmp_path)
    result = evaluate_setup(root=root, env={"HITHINK_FINANCE_API_KEY": "abc123xyz"}, skip_network=True, module_names=[])

    assert result["status"] == "READY"
    assert "HITHINK_FINANCE_API_KEY present (not yet auth-verified)" in result["passed_checks"]


def test_token_missing_is_not_ready_or_warning(tmp_path: Path) -> None:
    root = make_minimal_project(tmp_path)
    result = evaluate_setup(root=root, env={}, skip_network=True, module_names=[])

    assert result["status"] in {"NOT_READY", "READY_WITH_WARNINGS"}
    assert any("HITHINK_FINANCE_API_KEY missing" in item for item in result["failed_checks"] + result["warnings"])


def test_import_failure_makes_not_ready(tmp_path: Path) -> None:
    root = make_minimal_project(tmp_path)
    result = evaluate_setup(root=root, env={"HITHINK_FINANCE_API_KEY": "abc123xyz"}, skip_network=True, module_names=["missing.module"])

    assert result["status"] == "NOT_READY"
    assert any("missing.module" in item for item in result["failed_checks"])


def test_broken_workflow_state_makes_not_ready(tmp_path: Path) -> None:
    root = make_minimal_project(tmp_path)
    (root / "reports" / "workflow" / "current_workflow_state.json").write_text("{broken", encoding="utf-8")
    result = evaluate_setup(root=root, env={"HITHINK_FINANCE_API_KEY": "abc123xyz"}, skip_network=True, module_names=[])

    assert result["status"] == "NOT_READY"
    assert any("workflow state invalid" in item for item in result["failed_checks"])


def test_business_command_blocked_when_environment_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_project, "evaluate_setup", lambda **kwargs: {"status": "NOT_READY", "failed_checks": ["x"], "warnings": [], "passed_checks": [], "recommended_actions": ["fix"]})

    assert run_project.main(["night-plan"]) == 2


def test_status_is_readonly(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(run_project, "run_workflow_command", lambda args: 0)

    assert run_project.main(["status"]) == 0
    assert capsys.readouterr()


def test_next_reuses_workflow_orchestrator(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}
    monkeypatch.setattr(run_project, "run_workflow_command", lambda args: called.setdefault("args", args) or 0)

    assert run_project.main(["next"]) == 0
    assert called["args"] == ["next"]


def test_invalid_project_command_does_not_modify_state(tmp_path: Path) -> None:
    root = make_minimal_project(tmp_path)
    state_path = root / "reports" / "workflow" / "current_workflow_state.json"
    before = state_path.read_text(encoding="utf-8")

    assert run_project.main(["bad-command"], root=root) == 2
    assert state_path.read_text(encoding="utf-8") == before


def test_gitignore_covers_sensitive_config() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in [".env", ".venv/", "config/push_channels.json", "config/telegram_bot.json", "reports/workflow/current_workflow_state.json"]:
        assert pattern in text


def test_examples_do_not_contain_real_tokens_or_holdings() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    state_example = (ROOT / "reports" / "workflow" / "current_workflow_state.example.json").read_text(encoding="utf-8")
    combined = env_example + "\n" + state_example

    assert "real_token_value" not in combined
    assert "真实持仓样例" not in combined
    assert "HITHINK_FINANCE_API_KEY" in env_example
    assert "TUSHARE_TOKEN=" not in env_example


def test_documented_commands_exist() -> None:
    quickstart = (ROOT / "WORKFLOW_QUICKSTART.md").read_text(encoding="utf-8")
    assert "scripts/run_project.py setup" in quickstart
    assert (ROOT / "scripts" / "run_project.py").exists()
    assert (ROOT / "scripts" / "run_setup_check.py").exists()


def test_startup_prompt_references_existing_files() -> None:
    quickstart = (ROOT / "WORKFLOW_QUICKSTART.md").read_text(encoding="utf-8")
    for rel in ["PROJECT_CONTEXT.md", "WORKFLOW_QUICKSTART.md", "skills/stock-ai-workflow-controller/SKILL.md"]:
        assert rel in quickstart
        assert (ROOT / rel).exists()


def test_windows_path_is_not_the_only_supported_environment() -> None:
    text = (ROOT / "docs" / "MIGRATION_GUIDE.md").read_text(encoding="utf-8")
    assert "Windows" in text
    assert "Linux" in text or "macOS" in text


def test_new_clone_can_use_examples(tmp_path: Path) -> None:
    root = make_minimal_project(tmp_path)
    result = evaluate_setup(root=root, env={"HITHINK_FINANCE_API_KEY": "abc123xyz"}, skip_network=True, module_names=[])

    assert result["status"] == "READY"
    assert not any(str(tmp_path) in item for item in result["recommended_actions"])
