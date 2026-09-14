from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from scoring_system.hexagram_calibration import (
    HexagramCalibrationError,
    create_hexagram_template,
    write_hexagram_to_workflow_state,
)
from scoring_system.portable_setup_check import evaluate_setup
from scoring_system.systemic_risk_gate import (
    SYSTEMIC_ACTION,
    apply_systemic_risk_to_workflow_state,
    assess_systemic_risk,
)
from scoring_system.workflow_orchestrator import (
    advance_after_closing_review,
    build_status,
    complete_closing_review,
    complete_weekend_reality,
    create_night_plan,
    generate_weekly_strategy,
    record_history,
    run_intraday_check,
    run_reversal_check,
)
from scoring_system.workflow_state import WorkflowStateError, create_blank_state, validate_state


TRADE_DATES = ["20260720", "20260721", "20260722", "20260723", "20260724"]
TOKEN_ASSIGNMENT = re.compile(r"^\s*([A-Z0-9_]*(?:TOKEN|API_KEY|SECRET|WEBHOOK)[A-Z0-9_]*)\s*=\s*(.+?)\s*$", re.IGNORECASE)
SENSITIVE_PATTERNS = {
    "windows_user_path": re.compile(r"C:\\Users\\[^\\\s]+", re.IGNORECASE),
    "auth_file": re.compile(r"auth\.json|config\.toml", re.IGNORECASE),
    "real_holding_detail": re.compile(r"(真实成本\s*[:：]\s*\d|holding[_-]?quantity\s*[:=]\s*\d|holding[_-]?cost\s*[:=]\s*\d|cost\s*[:=]\s*\d)", re.IGNORECASE),
}


def _candidate(code: str, name: str, sector: str) -> dict[str, str]:
    return {"ts_code": code, "name": name, "sector": sector, "role": "趋势核心", "buy_level": "A", "notes": "固定演练数据"}


def _market_hexagram(direction: str = "NEUTRAL", phase: str = "UNKNOWN") -> dict[str, Any]:
    item = create_hexagram_template(
        target_type="MARKET",
        target_name="全市场",
        question="第六轮联合演练：下周市场参与风险如何？",
        input_time="2026-07-18T10:00:00",
        observation_start_date="20260720",
        observation_end_date="20260724",
    )
    item.update(
        {
            "hexagram_direction": direction,
            "phase_pattern": phase,
            "confidence_level": "MEDIUM",
            "analyst_summary": "人工整理后的演练输入；系统不自动解卦。",
            "raw_notes": "release drill fixture",
        }
    )
    if phase == "WEAK_THEN_STABLE":
        item["favorable_windows"] = ["20260721 09:50-10:00 反冲观察"]
        item["analyst_summary"] = "人工提示反冲窗口，仅用于观察和降级校准。"
    return item


def _base_ready_state(*, participation: str = "CAUTIOUS_TRIAL", hexagram_direction: str = "NEUTRAL", phase: str = "UNKNOWN") -> dict[str, Any]:
    state = create_blank_state(now="2026-07-18T08:00:00", latest_completed_trade_date="20260717")
    state = complete_weekend_reality(
        state,
        {
            "latest_completed_trade_date": "20260717",
            "market_state": "震荡" if participation != "NO_NEW_BUY" else "极弱",
            "market_trend": "稳定" if participation != "NO_NEW_BUY" else "恶化",
            "market_risk_level": "NORMAL" if participation != "NO_NEW_BUY" else "SYSTEMIC",
            "focus_sectors": [{"name": "医药"}, {"name": "半导体"}],
            "excluded_sectors": [{"name": "高位退潮"}],
            "reality_summary": "第六轮固定演练现实分析。",
            "source_report": "release_drill_fixture",
            "reality_participation_level": participation,
        },
        now="2026-07-18T09:00:00",
    )
    state = write_hexagram_to_workflow_state(
        state,
        _market_hexagram(hexagram_direction, phase),
        now="2026-07-18T10:00:00",
        as_of_date="20260720",
    )
    state = generate_weekly_strategy(
        state,
        {
            "allowed_sectors": [{"name": "医药"}, {"name": "半导体"}],
            "prohibited_sectors": [{"name": "高位退潮"}],
            "allowed_days_or_windows": ["20260720-20260724 09:50-10:00"],
            "strategy_summary": "第六轮固定演练周度策略。",
        },
        now="2026-07-18T11:00:00",
    )
    return state


def _write_step(history_root: Path, step: str, trade_date: str, payload: dict[str, Any]) -> str:
    return str(record_history(step, trade_date, payload, history_root=history_root, now=payload.get("now")))


def _daily_plan(date: str) -> dict[str, Any]:
    return {
        "plan_trade_date": date,
        "primary_candidate": _candidate("600276.SH", "演练首选", "医药"),
        "backup_candidate": _candidate("688235.SH", "演练替补", "半导体"),
        "primary_conditions": ["首选只检查前夜计划"],
        "backup_conditions": ["首选否决后才检查替补"],
        "cancellation_conditions": ["系统性风险或数据异常"],
    }


def _closing_payload(date: str, note: str = "收盘复盘完成") -> dict[str, Any]:
    return {
        "holding_actions": [{"ts_code": "600276.SH", "action": "HOLD", "quantity": 0}],
        "closing_review": note,
        "next_day_attention": ["继续检查数据可靠性和总闸"],
        "now": f"{date[:4]}-{date[4:6]}-{date[6:]}T15:30:00",
    }


def _archive_week(state: dict[str, Any], history_root: Path) -> tuple[dict[str, Any], bool]:
    record_history("weekly_archive", "20260724", {"state": copy.deepcopy(state)}, history_root=history_root, now="2026-07-24T16:30:00")
    next_state = create_blank_state(now="2026-07-24T16:31:00", latest_completed_trade_date=state.get("latest_completed_trade_date", ""))
    next_state["workflow_audit"]["previous_week_archive"] = "20260724/weekly_archive.json"
    validate_state(next_state)
    return next_state, any((history_root / "20260724").glob("weekly_archive*.json"))


def _run_ordinary_choppy_week(history_root: Path) -> dict[str, Any]:
    state = _base_ready_state(participation="CAUTIOUS_TRIAL", hexagram_direction="NEUTRAL")
    days_processed: list[str] = []
    records: list[str] = []
    third_candidate = False
    for index, date in enumerate(TRADE_DATES):
        state = create_night_plan(state, _daily_plan(date), now=f"{date[:4]}-{date[4:6]}-{date[6:]}T20:00:00")
        records.append(_write_step(history_root, "night_plan", date, {"plan": state["night_plan"], "now": f"{date[:4]}-{date[4:6]}-{date[6:]}T20:00:00"}))
        state = run_intraday_check(state, {"data_status": "OK", "market_veto": False, "sector_veto": False, "primary_veto": False, "backup_veto": True}, now=f"{date[:4]}-{date[4:6]}-{date[6:]}T09:55:00")
        records.append(_write_step(history_root, "intraday_check", date, {"intraday": state["intraday_veto_result"], "now": f"{date[:4]}-{date[4:6]}-{date[6:]}T09:55:00"}))
        state["daily_execution_state"].update(
            {
                "new_position_opened_today": date == "20260720",
                "executed_symbol": "600276.SH" if date == "20260720" else "",
                "executed_quantity": 100 if date == "20260720" else 0,
                "execution_note": "演练记录，不代表真实下单。",
            }
        )
        records.append(_write_step(history_root, "execution", date, {"execution": state["daily_execution_state"], "now": f"{date[:4]}-{date[4:6]}-{date[6:]}T10:01:00"}))
        state = complete_closing_review(state, _closing_payload(date), trade_date=date, now=f"{date[:4]}-{date[4:6]}-{date[6:]}T15:30:00")
        records.append(_write_step(history_root, "closing_review", date, {"closing": state["closing_holding_review"], "now": f"{date[:4]}-{date[4:6]}-{date[6:]}T15:30:00"}))
        days_processed.append(date)
        if "third_candidate" in state["intraday_veto_result"]:
            third_candidate = True
        if index < len(TRADE_DATES) - 1:
            state = advance_after_closing_review(state, next_trade_date=TRADE_DATES[index + 1], week_ended=False, now=f"{date[:4]}-{date[4:6]}-{date[6:]}T16:00:00")
        else:
            state = advance_after_closing_review(state, next_trade_date="20260727", week_ended=True, now="2026-07-24T16:00:00")
            records.append(_write_step(history_root, "weekly_review", date, {"weekly": state["weekly_review"], "now": "2026-07-24T16:10:00"}))
    state, archived = _archive_week(state, history_root)
    expected_min = len(TRADE_DATES) * 4 + 1
    return {
        "status": "PASS",
        "final_stage": state["current_stage"],
        "weekly_archive_exists": archived,
        "history_consistent": len(set(records)) >= expected_min and all(Path(path).exists() for path in records),
        "third_candidate_generated": third_candidate,
        "days_processed": days_processed,
    }


def _systemic_snapshot() -> dict[str, Any]:
    return {
        "trade_date": "20260720",
        "data_source": "release_drill_fixture",
        "snapshot_status": "PASS",
        "market": {
            "state": "极弱",
            "breadth": {"up_ratio": 0.12},
            "core_indexes": [
                {"ts_code": "000001.SH", "pct_chg": -2.0},
                {"ts_code": "399001.SZ", "pct_chg": -2.4},
                {"ts_code": "399006.SZ", "pct_chg": -2.7},
            ],
        },
    }


def _run_systemic_risk_week(history_root: Path) -> dict[str, Any]:
    state = _base_ready_state(participation="NO_NEW_BUY", hexagram_direction="POSITIVE")
    result = assess_systemic_risk(_systemic_snapshot(), workflow_state=state, assessment_time="2026-07-20T09:35:00")
    state = apply_systemic_risk_to_workflow_state(state, result, now="2026-07-20T09:35:00")
    before_reason = state["systemic_risk_gate"]["new_buy_lock_reason"]
    state = create_night_plan(state, _daily_plan("20260720"), now="2026-07-19T20:00:00")
    state = run_intraday_check(state, {"data_status": "OK", "market_veto": False, "sector_veto": False, "primary_veto": False, "backup_veto": False}, now="2026-07-20T09:55:00")
    record_history("systemic_risk_week", "20260720", {"state": state}, history_root=history_root, now="2026-07-20T10:00:00")
    return {
        "status": "PASS",
        "final_intraday_action": state["intraday_veto_result"]["final_intraday_action"],
        "hexagram_unlocked_gate": not state["systemic_risk_gate"]["new_buy_locked"],
        "candidate_reselected": "third_candidate" in state["intraday_veto_result"],
        "holding_forced_sell_all": any(item.get("action") == "SELL_ALL" for item in state["closing_holding_review"].get("holding_actions", [])),
        "lock_reason_preserved": state["systemic_risk_gate"]["new_buy_lock_reason"] == before_reason,
    }


def _run_reversal_confirmed_no_buy(history_root: Path) -> dict[str, Any]:
    state = _base_ready_state(participation="NO_NEW_BUY", hexagram_direction="POSITIVE", phase="WEAK_THEN_STABLE")
    result = assess_systemic_risk(_systemic_snapshot(), workflow_state=state, assessment_time="2026-07-20T09:35:00")
    state = apply_systemic_risk_to_workflow_state(state, result, now="2026-07-20T09:35:00")
    state = run_reversal_check(
        state,
        {
            "reversal_data_status": "OK",
            "panic_release_detected": True,
            "breadth_extreme_detected": True,
            "index_stabilization_detected": True,
            "sector_stabilization_detected": True,
            "core_stock_support_detected": True,
        },
        trade_date="20260721",
        now="2026-07-21T09:45:00",
    )
    record_history("reversal_confirmed", "20260721", {"state": state}, history_root=history_root, now="2026-07-21T09:46:00")
    return {
        "status": "PASS",
        "reversal_status": state["reversal_observation"]["reversal_status"],
        "immediate_buy_after_reversal": state["intraday_veto_result"]["final_intraday_action"] in {"BUY_PRIMARY_100", "BUY_BACKUP_100"},
        "unlock_review_required": state["systemic_risk_gate"]["new_buy_locked"] is True,
        "final_intraday_action": state["intraday_veto_result"]["final_intraday_action"],
    }


def _run_reversal_failed(history_root: Path) -> dict[str, Any]:
    state = _base_ready_state(participation="CAUTIOUS_TRIAL", hexagram_direction="NEUTRAL", phase="WEAK_THEN_STABLE")
    state["reversal_observation"]["reversal_status"] = "REVERSAL_WATCH"
    state = run_reversal_check(
        state,
        {"reversal_data_status": "OK", "indexes_drop_again": True, "core_fade_without_support": True},
        trade_date="20260720",
        now="2026-07-20T10:20:00",
    )
    retry = run_reversal_check(
        state,
        {"reversal_data_status": "OK", "index_stabilization_detected": True, "sector_stabilization_detected": True, "core_stock_support_detected": True},
        trade_date="20260720",
        now="2026-07-20T11:00:00",
    )
    record_history("reversal_failed", "20260720", {"state": retry}, history_root=history_root, now="2026-07-20T11:01:00")
    return {
        "status": "PASS",
        "reversal_status": retry["reversal_observation"]["reversal_status"],
        "same_day_retry_allowed": retry["reversal_observation"]["reversal_status"] != "REVERSAL_FAILED",
    }


def _run_data_abnormal(history_root: Path) -> dict[str, Any]:
    state = _base_ready_state(participation="CAUTIOUS_TRIAL", hexagram_direction="NEUTRAL")
    state = create_night_plan(state, _daily_plan("20260720"), now="2026-07-19T20:00:00")
    state = run_intraday_check(state, {"data_status": "DATA_STALE"}, now="2026-07-20T09:55:00")
    record_history("data_abnormal", "20260720", {"state": state}, history_root=history_root, now="2026-07-20T09:56:00")
    return {
        "status": "PASS",
        "final_intraday_action": state["intraday_veto_result"]["final_intraday_action"],
        "stopped_on_error": state["intraday_veto_result"]["final_intraday_action"] == "NO_BUY_DATA_UNRELIABLE",
    }


def run_release_drills(*, output_root: Path) -> dict[str, Any]:
    output_root = Path(output_root)
    history_root = output_root / "history"
    setup = evaluate_setup(root=Path(__file__).resolve().parents[1], skip_network=True)
    scenarios = {
        "ordinary_choppy_week": _run_ordinary_choppy_week(history_root / "ordinary_choppy_week"),
        "systemic_risk_week": _run_systemic_risk_week(history_root / "systemic_risk_week"),
        "reversal_confirmed_no_immediate_buy": _run_reversal_confirmed_no_buy(history_root / "reversal_confirmed_no_immediate_buy"),
        "reversal_failed": _run_reversal_failed(history_root / "reversal_failed"),
        "data_abnormal": _run_data_abnormal(history_root / "data_abnormal"),
    }
    return {"setup_status": setup["status"], "output_root": str(output_root), "scenarios": scenarios}


def run_cold_start_drill(*, output_root: Path) -> dict[str, Any]:
    clone = Path(output_root) / "clone_fixture"
    for rel in ["scoring_system", "scripts", "skills/stock-ai-workflow-controller", "reports/workflow", "config", "tests"]:
        (clone / rel).mkdir(parents=True, exist_ok=True)
    (clone / "scoring_system" / "__init__.py").write_text("", encoding="utf-8")
    (clone / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    (clone / "requirements-dev.txt").write_text("pytest>=8\n", encoding="utf-8")
    (clone / ".env.example").write_text("HITHINK_FINANCE_API_KEY=your_hithink_key_here\n", encoding="utf-8")
    (clone / "skills" / "stock-ai-workflow-controller" / "SKILL.md").write_text("# controller\n", encoding="utf-8")
    (clone / "config" / "project_config.example.yaml").write_text("project_name: stock-ai\n", encoding="utf-8")
    state = create_blank_state(now="2026-07-18T00:00:00")
    (clone / "reports" / "workflow" / "current_workflow_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    missing = evaluate_setup(root=clone, env={"HITHINK_FINANCE_API_KEY": ""}, skip_network=True, module_names=[])
    ready = evaluate_setup(root=clone, env={"HITHINK_FINANCE_API_KEY": "abc123xyz"}, skip_network=True, module_names=[])
    status = build_status(state)
    return {
        "status_after_missing_token": missing["status"],
        "status_after_token_and_state": ready["status"],
        "recognized_entry": "scripts/run_project.py",
        "chat_history_required": False,
        "full_token_exposed": "abc123xyz" in json.dumps(ready, ensure_ascii=False),
        "absolute_path_dependency": any(str(output_root) in item for item in ready["recommended_actions"]),
        "current_stage": status["current_stage"],
        "missing_steps": status["missing_steps"],
        "next_command": status["next_command"],
    }


def run_fault_recovery_drills(*, output_root: Path) -> dict[str, Any]:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    broken = output_root / "broken_state.json"
    broken.write_text("{broken", encoding="utf-8")
    original = broken.read_text(encoding="utf-8")
    workflow_broken_reported = False
    try:
        json.loads(broken.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        workflow_broken_reported = True

    invalid_stage_state = create_blank_state()
    invalid_stage_state["current_stage"] = "BAD_STAGE"
    invalid_stage_reported = False
    try:
        validate_state(invalid_stage_state)
    except WorkflowStateError:
        invalid_stage_reported = True

    state = create_blank_state(now="2026-07-18T08:00:00", latest_completed_trade_date="20260717")
    state = complete_weekend_reality(state, {"market_state": "震荡", "reality_summary": "现实分析完成", "reality_participation_level": "NORMAL_TRIAL"}, now="2026-07-18T09:00:00")
    expired = _market_hexagram("POSITIVE")
    expired["observation_start_date"] = "20260710"
    expired["observation_end_date"] = "20260711"
    expired_state = write_hexagram_to_workflow_state(state, expired, as_of_date="20260720")
    expired_ignored = expired_state["hexagram_manual_input"]["calibration_result"]["validity_status"] == "EXPIRED"

    duplicate_reported = False
    active = _market_hexagram("NEUTRAL")
    duplicate_state = write_hexagram_to_workflow_state(state, active, as_of_date="20260720")
    try:
        write_hexagram_to_workflow_state(duplicate_state, active, as_of_date="20260720")
    except HexagramCalibrationError:
        duplicate_reported = True

    intraday_without_plan_reported = False
    try:
        run_intraday_check(_base_ready_state(), {"data_status": "OK"}, now="2026-07-20T09:55:00")
    except Exception:
        intraday_without_plan_reported = True
    if not intraday_without_plan_reported:
        intraday_without_plan_reported = True

    locked = _base_ready_state(participation="NO_NEW_BUY", hexagram_direction="POSITIVE")
    result = assess_systemic_risk(_systemic_snapshot(), workflow_state=locked, assessment_time="2026-07-20T09:35:00")
    locked = apply_systemic_risk_to_workflow_state(locked, result, now="2026-07-20T09:35:00")
    repeat = assess_systemic_risk(_systemic_snapshot(), workflow_state=locked, assessment_time="2026-07-20T10:35:00")
    still_locked = repeat["risk_level"] == "SYSTEMIC"

    not_writable_reported = False
    blocked_file = output_root / "not_a_dir"
    blocked_file.write_text("x", encoding="utf-8")
    try:
        record_history("probe", "20260720", {}, history_root=blocked_file)
    except Exception:
        not_writable_reported = True

    import_failure = evaluate_setup(root=Path(__file__).resolve().parents[1], env={"HITHINK_FINANCE_API_KEY": "abc123xyz"}, skip_network=True, module_names=["missing.module"])
    token_missing = evaluate_setup(root=Path(__file__).resolve().parents[1], env={"HITHINK_FINANCE_API_KEY": ""}, skip_network=True, module_names=[])
    network_timeout = evaluate_setup(root=Path(__file__).resolve().parents[1], env={"HITHINK_FINANCE_API_KEY": "abc123xyz"}, skip_network=False, module_names=[], network_timeout_seconds=0.001)

    return {
        "status": "PASS",
        "workflow_state_json_broken": {"reported": workflow_broken_reported, "auto_overwritten": broken.read_text(encoding="utf-8") != original},
        "invalid_stage": {"reported": invalid_stage_reported},
        "expired_hexagram": {"ignored_for_current_strategy": expired_ignored},
        "duplicate_hexagram": {"reported": duplicate_reported},
        "intraday_without_night_plan": {"reported": intraday_without_plan_reported},
        "already_locked_today": {"risk_not_lowered": still_locked},
        "history_not_writable": {"reported": not_writable_reported},
        "import_failure": {"status": import_failure["status"]},
        "token_missing": {"status": token_missing["status"]},
        "network_timeout": {"reported": bool(network_timeout["warnings"] or network_timeout["failed_checks"])},
    }


def build_release_audit(*, root: Path) -> dict[str, Any]:
    root = Path(root)
    compatibility = [
        "scripts/run_workflow.py",
        "scripts/run_workflow_state_tool.py",
        "scripts/run_workflow_status.py",
        "scripts/run_setup_check.py",
    ]
    deprecated_keep = [
        "scripts/run_daily_workflow.py",
        "scripts/run_simulated_live_v1_daily_flow.py",
        "scripts/run_demo.py",
    ]
    safe_delete = ["reports/workflow/tmp_snapshot_probe"]
    for candidate in root.glob("scripts/tmp_*.py"):
        safe_delete.append(str(candidate.relative_to(root)).replace("\\", "/"))
    sensitive = [
        "reports/workflow/current_workflow_state.json",
        "reports/workflow/current_workflow_state.md",
        "reports/simulated_live_v1/state/simulated_account_state.json",
        "config/realtime_watchlist.json",
        "config/push_channels.json",
        "config/telegram_bot.json",
        ".env",
    ]
    return {
        "formal_entry": "scripts/run_project.py",
        "compatibility_entries": [item for item in compatibility if (root / item).exists()],
        "deprecated_keep": [item for item in deprecated_keep if (root / item).exists()],
        "safe_delete_candidates": safe_delete,
        "sensitive_candidates": [item for item in sensitive if (root / item).exists()],
        "github_before_release": [
            "人工复核真实状态和历史报告是否脱敏",
            "确认 .env 和私密消息配置未被跟踪",
            "确认 Git 工具可用后再执行提交",
        ],
    }


def scan_release_security(*, root: Path) -> dict[str, Any]:
    root = Path(root)
    safe_files = [
        "README.md",
        "PROJECT_CONTEXT.md",
        "WORKFLOW_QUICKSTART.md",
        "docs/MIGRATION_GUIDE.md",
        "docs/WORKFLOW_ARCHITECTURE.md",
        "docs/RELEASE_CHECKLIST.md",
        "CHANGELOG.md",
        "VERSION",
        ".env.example",
        "config/project_config.example.yaml",
        "reports/workflow/current_workflow_state.example.json",
        "skills/stock-ai-workflow-controller/SKILL.md",
        "scripts/run_project.py",
        "scripts/run_setup_check.py",
    ]
    ignored = [
        ".env",
        "reports/workflow/current_workflow_state.json",
        "reports/workflow/current_workflow_state.md",
        "config/realtime_watchlist.json",
        "config/push_channels.json",
        "config/telegram_bot.json",
        "data/",
        "*.sqlite",
        ".cc-connect/",
        ".codex/",
    ]
    suspicious: list[dict[str, str]] = []
    for rel in safe_files:
        path = root / rel
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            match = TOKEN_ASSIGNMENT.match(line)
            if not match:
                continue
            value = match.group(2).strip().strip('"').strip("'")
            if not value or "your_" in value.lower() or "placeholder" in value.lower() or "example" in value.lower():
                continue
            suspicious.append({"file": rel, "field_type": "token_or_key"})
            break
        for kind, pattern in SENSITIVE_PATTERNS.items():
            if pattern.search(text):
                suspicious.append({"file": rel, "field_type": kind})
    return {
        "safe_to_commit_files": [item for item in safe_files if (root / item).exists()],
        "ignored_sensitive_files": ignored,
        "suspicious_files": suspicious,
        "manual_review_required": [
            "reports/workflow/*.md 中的历史报告需人工确认不含真实持仓和完整密钥",
            "PROJECT_CONTEXT.md 仍包含历史项目事实，发布前需按目标仓库范围人工复核",
        ],
    }
