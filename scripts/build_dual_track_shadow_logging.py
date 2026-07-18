from __future__ import annotations

import argparse
import json
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "walk_forward_2025"
SUMMARY_JSON = REPORT_DIR / "walk_forward_10paths_summary.json"
SUMMARY_MD = REPORT_DIR / "walk_forward_10paths_summary.md"
PREP_JSON = REPORT_DIR / "dual_track_shadow_preparation.json"
DUAL_TRACK_JSON = REPORT_DIR / "dual_track_shadow_logging.json"
DUAL_TRACK_MD = REPORT_DIR / "dual_track_shadow_logging.md"

REAL_TRADE_ACTIONS = {"BUY", "SELL", "REDUCE"}
REPORT_ACTIONS = {"BUY", "HOLD", "REDUCE", "SELL", "OBSERVE", "NEEDS_HUMAN_REVIEW"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def path_stem(path_id: str) -> str:
    return path_id.replace("-", "_")


def load_path_payload(path_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    stem = path_stem(path_id)
    result = read_json(REPORT_DIR / f"{stem}_result.json")
    decisions = read_json(REPORT_DIR / f"{stem}_decisions.json").get("decisions", [])
    execution_log = read_json(REPORT_DIR / f"{stem}_execution_log.json").get("execution_log", [])
    return result, decisions, execution_log


def original_action_from_decision(decision: dict[str, Any]) -> str:
    action = decision.get("action")
    if action == "WAIT":
        return "OBSERVE"
    if action in REPORT_ACTIONS:
        return action
    return "OBSERVE"


def shadow_action_from_decision(decision: dict[str, Any]) -> str:
    final_user_action = decision.get("final_user_action")
    if final_user_action in REPORT_ACTIONS:
        return final_user_action
    review = decision.get("ai_review") or {}
    reviewed_action = review.get("final_action_after_review")
    if reviewed_action in REPORT_ACTIONS:
        return reviewed_action
    return original_action_from_decision(decision)


def bool_trade_executed(decision: dict[str, Any], original_action: str) -> bool:
    if decision.get("whether_executed") is not None:
        return bool(decision.get("whether_executed"))
    return original_action in REAL_TRADE_ACTIONS


def position_effect_estimate(original_action: str, shadow_action: str) -> str:
    if original_action == shadow_action:
        return "no_shadow_change_keep_real_position_path"
    if original_action == "BUY" and shadow_action == "OBSERVE":
        return "would_skip_buy_no_new_shadow_position"
    if original_action == "HOLD" and shadow_action == "NEEDS_HUMAN_REVIEW":
        return "would_pause_hold_and_require_risk_review_before_shadow_estimate"
    if original_action in {"BUY", "HOLD"} and shadow_action == "REDUCE":
        return "would_shift_to_risk_reduction_in_shadow_only"
    return f"shadow_only_compare_{original_action.lower()}_to_{shadow_action.lower()}"


def load_reasonable_change_map(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    mapping: dict[tuple[str, str], dict[str, Any]] = {}
    for item in (summary.get("ai_review_reject_audit") or {}).get("details", []):
        mapping[(item.get("path"), item.get("date"))] = {
            "is_reasonable_change": bool(item.get("is_reasonable")),
            "audit_verdict": item.get("audit_verdict"),
        }
    for item in (summary.get("ai_review_needs_human_audit") or {}).get("details", []):
        mapping[(item.get("path"), item.get("date"))] = {
            "is_reasonable_change": not bool(item.get("is_abnormal")),
            "audit_verdict": "reasonable_needs_human_review" if not item.get("is_abnormal") else "abnormal_needs_human_review",
        }
    return mapping


def build_record(
    path_id: str,
    decision: dict[str, Any],
    reasonable_change_map: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    original_action = original_action_from_decision(decision)
    shadow_action = shadow_action_from_decision(decision)
    review = decision.get("ai_review") or {}
    evidence = decision.get("stock_selection_evidence") or {}
    original_trade_executed = bool_trade_executed(decision, original_action)
    change_reason = review.get("veto_reason") or review.get("exception_candidate_reason") or "no_change"
    change_key = (path_id, decision.get("date"))
    reasonability = reasonable_change_map.get(change_key, {})

    original_model_track = {
        "original_action": original_action,
        "original_ts_code": decision.get("candidate_ts_code"),
        "original_name": decision.get("candidate_name"),
        "original_reason": decision.get("reason"),
        "original_trade_executed": original_trade_executed,
        "original_position_after_action": deepcopy(decision.get("position_after_action")),
    }
    ai_review_shadow_track = {
        "shadow_action": shadow_action,
        "shadow_ts_code": decision.get("candidate_ts_code"),
        "shadow_name": decision.get("candidate_name"),
        "shadow_reason": decision.get("action_reason") or review.get("veto_reason") or review.get("review_status"),
        "shadow_changed_from_original": shadow_action != original_action,
        "shadow_change_reason": change_reason,
        "shadow_risk_warnings": list(review.get("risk_warnings") or []),
        "shadow_requires_human_review": bool(review.get("requires_human_review")),
        "shadow_position_effect_estimate": position_effect_estimate(original_action, shadow_action),
        "shadow_trade_executed": False,
    }
    return {
        "path": path_id,
        "date": decision.get("date"),
        "code": decision.get("candidate_ts_code"),
        "name": decision.get("candidate_name"),
        "ai_review_status": review.get("review_status"),
        "veto_reason": review.get("veto_reason"),
        "rule_conflicts": review.get("rule_conflicts", []),
        "stock_selection_evidence": {
            "evidence_quality": evidence.get("evidence_quality"),
        },
        "sector_cycle_state": decision.get("sector_cycle_state"),
        "leader_status": decision.get("leader_status"),
        "needs_shadow_pnl_estimate_later": shadow_action != original_action,
        "is_reasonable_change": reasonability.get("is_reasonable_change"),
        "change_audit_verdict": reasonability.get("audit_verdict", ""),
        "original_model_track": original_model_track,
        "ai_review_shadow_track": ai_review_shadow_track,
    }


def build_dual_track_logging(summary: dict[str, Any], prep: dict[str, Any]) -> dict[str, Any]:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reasonable_change_map = load_reasonable_change_map(summary)
    records: list[dict[str, Any]] = []
    per_path_summary: list[dict[str, Any]] = []
    invariant_issues: list[dict[str, Any]] = []

    for path_id in summary.get("reran_paths", []):
        result, decisions, _execution_log = load_path_payload(path_id)
        path_records = [build_record(path_id, decision, reasonable_change_map) for decision in decisions]
        records.extend(path_records)

        original_counts = Counter(record["original_model_track"]["original_action"] for record in path_records)
        shadow_counts = Counter(record["ai_review_shadow_track"]["shadow_action"] for record in path_records)
        path_changed = sum(
            1 for record in path_records if record["ai_review_shadow_track"]["shadow_changed_from_original"]
        )
        per_path_summary.append(
            {
                "path": path_id,
                "decision_count": len(path_records),
                "original_action_counts": dict(original_counts),
                "shadow_action_counts": dict(shadow_counts),
                "shadow_changed_action_count": path_changed,
                "shadow_human_review_count": shadow_counts.get("NEEDS_HUMAN_REVIEW", 0),
                "shadow_reject_count": sum(
                    1 for record in path_records if record.get("ai_review_status") == "REJECT"
                ),
                "shadow_pass_count": sum(
                    1 for record in path_records if record.get("ai_review_status") == "PASS"
                ),
            }
        )

        if dict(shadow_counts) != (next((item["shadow_action_counts"] for item in prep.get("per_path", []) if item.get("path_id") == path_id), {})):
            invariant_issues.append({"path": path_id, "type": "shadow_action_count_mismatch_vs_preparation"})
    original_action_counts = Counter(record["original_model_track"]["original_action"] for record in records)
    shadow_action_counts = Counter(record["ai_review_shadow_track"]["shadow_action"] for record in records)
    top_shadow_change_reasons = Counter(
        record["ai_review_shadow_track"]["shadow_change_reason"]
        for record in records
        if record["ai_review_shadow_track"]["shadow_changed_from_original"]
    )
    changed_points = [
        {
            "path": record["path"],
            "date": record["date"],
            "code": record["code"],
            "name": record["name"],
            "original_action": record["original_model_track"]["original_action"],
            "shadow_action": record["ai_review_shadow_track"]["shadow_action"],
            "ai_review_status": record["ai_review_status"],
            "veto_reason": record["veto_reason"],
            "rule_conflicts": record["rule_conflicts"],
            "stock_selection_evidence": record["stock_selection_evidence"],
            "sector_cycle_state": record["sector_cycle_state"],
            "leader_status": record["leader_status"],
            "is_reasonable_change": record["is_reasonable_change"],
            "change_audit_verdict": record["change_audit_verdict"],
            "needs_shadow_pnl_estimate_later": record["needs_shadow_pnl_estimate_later"],
        }
        for record in records
        if record["ai_review_shadow_track"]["shadow_changed_from_original"]
    ]
    dual_track_invariant_ok = (
        prep.get("readiness", {}).get("invariant_ok", False)
        and not invariant_issues
        and all(record["ai_review_shadow_track"]["shadow_trade_executed"] is False for record in records)
    )

    return {
        "generated_at": generated_at,
        "dual_track_logging_enabled": True,
        "dual_track_invariant_ok": dual_track_invariant_ok,
        "scope": "dual_track_shadow_logging_only",
        "boundaries": {
            "full_pipeline_selection_walk_forward": False,
            "real_account_connected": False,
            "auto_trading": False,
            "news_module_connected": False,
            "score_weight_changed": False,
            "real_trading_action_changed": False,
            "return_calculation_changed": False,
            "validation_private_used_for_daily_decision": False,
            "core_trading_rule_changed": False,
        },
        "original_action_counts": dict(original_action_counts),
        "shadow_action_counts": dict(shadow_action_counts),
        "shadow_changed_action_count": sum(
            1 for record in records if record["ai_review_shadow_track"]["shadow_changed_from_original"]
        ),
        "buy_to_observe_count": sum(
            1
            for record in records
            if record["original_model_track"]["original_action"] == "BUY"
            and record["ai_review_shadow_track"]["shadow_action"] == "OBSERVE"
        ),
        "hold_to_needs_human_review_count": sum(
            1
            for record in records
            if record["original_model_track"]["original_action"] == "HOLD"
            and record["ai_review_shadow_track"]["shadow_action"] == "NEEDS_HUMAN_REVIEW"
        ),
        "shadow_human_review_count": shadow_action_counts.get("NEEDS_HUMAN_REVIEW", 0),
        "shadow_reject_count": sum(1 for record in records if record["ai_review_status"] == "REJECT"),
        "shadow_pass_count": sum(1 for record in records if record["ai_review_status"] == "PASS"),
        "shadow_track_blocked_buy_count": sum(
            1
            for record in records
            if record["original_model_track"]["original_action"] == "BUY"
            and record["ai_review_shadow_track"]["shadow_action"] == "OBSERVE"
        ),
        "shadow_track_risk_reduce_review_count": sum(
            1 for record in records if record["ai_review_shadow_track"]["shadow_requires_human_review"]
        ),
        "paths_with_shadow_changes": sorted(
            {
                record["path"]
                for record in records
                if record["ai_review_shadow_track"]["shadow_changed_from_original"]
            }
        ),
        "top_shadow_change_reasons": top_shadow_change_reasons.most_common(10),
        "shadow_vs_original_by_path": per_path_summary,
        "shadow_change_points": changed_points,
        "all_records": records,
        "invariant_issues": invariant_issues,
    }


def build_dual_track_markdown(logging: dict[str, Any]) -> str:
    lines = [
        "# dual_track_shadow_logging",
        "",
        f"- generated_at: {logging['generated_at']}",
        f"- dual_track_logging_enabled: {logging['dual_track_logging_enabled']}",
        f"- dual_track_invariant_ok: {logging['dual_track_invariant_ok']}",
        f"- original_action_counts: {logging['original_action_counts']}",
        f"- shadow_action_counts: {logging['shadow_action_counts']}",
        f"- shadow_changed_action_count: {logging['shadow_changed_action_count']}",
        f"- buy_to_observe_count: {logging['buy_to_observe_count']}",
        f"- hold_to_needs_human_review_count: {logging['hold_to_needs_human_review_count']}",
        f"- shadow_human_review_count: {logging['shadow_human_review_count']}",
        f"- shadow_reject_count: {logging['shadow_reject_count']}",
        f"- shadow_pass_count: {logging['shadow_pass_count']}",
        f"- shadow_track_blocked_buy_count: {logging['shadow_track_blocked_buy_count']}",
        f"- shadow_track_risk_reduce_review_count: {logging['shadow_track_risk_reduce_review_count']}",
        f"- paths_with_shadow_changes: {logging['paths_with_shadow_changes']}",
        f"- top_shadow_change_reasons: {logging['top_shadow_change_reasons']}",
        "",
        "## Per Path",
        "",
        "| path | decisions | original_actions | shadow_actions | changed | human_review | reject | pass |",
        "| -- | --: | -- | -- | --: | --: | --: | --: |",
    ]
    for item in logging["shadow_vs_original_by_path"]:
        lines.append(
            f"| {item['path']} | {item['decision_count']} | {item['original_action_counts']} | "
            f"{item['shadow_action_counts']} | {item['shadow_changed_action_count']} | "
            f"{item['shadow_human_review_count']} | {item['shadow_reject_count']} | {item['shadow_pass_count']} |"
        )
    lines.extend(
        [
            "",
            "## 10 Change Points",
            "",
            "| path | date | code | name | original_action | shadow_action | ai_review_status | veto_reason | rule_conflicts | evidence_quality | sector_cycle_state | leader_status | reasonable_change | needs_shadow_pnl_estimate_later |",
            "| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |",
        ]
    )
    for item in logging["shadow_change_points"]:
        lines.append(
            f"| {item['path']} | {item['date']} | {item.get('code')} | {item.get('name')} | "
            f"{item['original_action']} | {item['shadow_action']} | {item['ai_review_status']} | "
            f"{item['veto_reason']} | {item['rule_conflicts']} | "
            f"{(item.get('stock_selection_evidence') or {}).get('evidence_quality')} | "
            f"{item['sector_cycle_state']} | {item['leader_status']} | "
            f"{item['is_reasonable_change']} | {item['needs_shadow_pnl_estimate_later']} |"
        )
    if logging["invariant_issues"]:
        lines.extend(["", "## Invariant Issues", ""])
        for issue in logging["invariant_issues"]:
            lines.append(f"- {issue}")
    lines.extend(
        [
            "",
            "## Boundary Note",
            "",
            "Shadow track only records AI-reviewed actions for comparison. It does not change real execution_log, real trade actions, or original return calculation.",
        ]
    )
    return "\n".join(lines)


def update_summary(summary: dict[str, Any], logging: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(summary)
    updated["dual_track_logging_enabled"] = logging["dual_track_logging_enabled"]
    updated["dual_track_invariant_ok"] = logging["dual_track_invariant_ok"]
    updated["original_action_counts"] = logging["original_action_counts"]
    updated["shadow_action_counts"] = logging["shadow_action_counts"]
    updated["shadow_changed_action_count"] = logging["shadow_changed_action_count"]
    updated["buy_to_observe_count"] = logging["buy_to_observe_count"]
    updated["hold_to_needs_human_review_count"] = logging["hold_to_needs_human_review_count"]
    updated["shadow_human_review_count"] = logging["shadow_human_review_count"]
    updated["shadow_reject_count"] = logging["shadow_reject_count"]
    updated["shadow_pass_count"] = logging["shadow_pass_count"]
    updated["shadow_track_blocked_buy_count"] = logging["shadow_track_blocked_buy_count"]
    updated["shadow_track_risk_reduce_review_count"] = logging["shadow_track_risk_reduce_review_count"]
    updated["paths_with_shadow_changes"] = logging["paths_with_shadow_changes"]
    updated["top_shadow_change_reasons"] = logging["top_shadow_change_reasons"]
    updated["shadow_vs_original_by_path"] = logging["shadow_vs_original_by_path"]
    updated["dual_track_shadow_logging_report"] = {
        "json": str(DUAL_TRACK_JSON),
        "markdown": str(DUAL_TRACK_MD),
        "shadow_change_point_count": len(logging["shadow_change_points"]),
    }
    return updated


def update_summary_markdown(logging: dict[str, Any]) -> None:
    existing = SUMMARY_MD.read_text(encoding="utf-8") if SUMMARY_MD.exists() else ""
    marker = "## Dual-track shadow logging"
    if marker in existing:
        existing = existing.split(marker)[0].rstrip()
    section = [
        marker,
        "",
        f"- dual_track_logging_enabled: {logging['dual_track_logging_enabled']}",
        f"- dual_track_invariant_ok: {logging['dual_track_invariant_ok']}",
        f"- original_action_counts: {logging['original_action_counts']}",
        f"- shadow_action_counts: {logging['shadow_action_counts']}",
        f"- shadow_changed_action_count: {logging['shadow_changed_action_count']}",
        f"- buy_to_observe_count: {logging['buy_to_observe_count']}",
        f"- hold_to_needs_human_review_count: {logging['hold_to_needs_human_review_count']}",
        f"- shadow_human_review_count: {logging['shadow_human_review_count']}",
        f"- shadow_reject_count: {logging['shadow_reject_count']}",
        f"- shadow_pass_count: {logging['shadow_pass_count']}",
        f"- shadow_track_blocked_buy_count: {logging['shadow_track_blocked_buy_count']}",
        f"- shadow_track_risk_reduce_review_count: {logging['shadow_track_risk_reduce_review_count']}",
        f"- paths_with_shadow_changes: {logging['paths_with_shadow_changes']}",
        f"- top_shadow_change_reasons: {logging['top_shadow_change_reasons']}",
        "",
        "### 10 change points",
        "",
        "| path | date | code | name | original_action | shadow_action | ai_review_status | veto_reason | rule_conflicts | evidence_quality | sector_cycle_state | leader_status | reasonable_change | needs_shadow_pnl_estimate_later |",
        "| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |",
    ]
    for item in logging["shadow_change_points"]:
        section.append(
            f"| {item['path']} | {item['date']} | {item.get('code')} | {item.get('name')} | "
            f"{item['original_action']} | {item['shadow_action']} | {item['ai_review_status']} | "
            f"{item['veto_reason']} | {item['rule_conflicts']} | "
            f"{(item.get('stock_selection_evidence') or {}).get('evidence_quality')} | "
            f"{item['sector_cycle_state']} | {item['leader_status']} | "
            f"{item['is_reasonable_change']} | {item['needs_shadow_pnl_estimate_later']} |"
        )
    content = existing.rstrip()
    if content:
        content += "\n\n"
    content += "\n".join(section) + "\n"
    SUMMARY_MD.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dual-track shadow logging and update summary")
    parser.add_argument("--summary-json", default=str(SUMMARY_JSON))
    parser.add_argument("--prep-json", default=str(PREP_JSON))
    args = parser.parse_args()

    summary_path = Path(args.summary_json)
    if not summary_path.is_absolute():
        summary_path = ROOT / summary_path
    prep_path = Path(args.prep_json)
    if not prep_path.is_absolute():
        prep_path = ROOT / prep_path

    summary = read_json(summary_path)
    prep = read_json(prep_path)
    logging = build_dual_track_logging(summary, prep)
    updated_summary = update_summary(summary, logging)

    write_json(DUAL_TRACK_JSON, logging)
    DUAL_TRACK_MD.write_text(build_dual_track_markdown(logging), encoding="utf-8")
    write_json(summary_path, updated_summary)
    update_summary_markdown(logging)

    print(
        json.dumps(
            {
                "dual_track_json": str(DUAL_TRACK_JSON),
                "dual_track_md": str(DUAL_TRACK_MD),
                "summary_json": str(summary_path),
                "summary_md": str(SUMMARY_MD),
                "dual_track_invariant_ok": logging["dual_track_invariant_ok"],
                "shadow_changed_action_count": logging["shadow_changed_action_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
