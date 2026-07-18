from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "walk_forward_2025"
SUMMARY_JSON = REPORT_DIR / "walk_forward_10paths_summary.json"

REAL_TRADE_ACTIONS = {"BUY", "SELL", "REDUCE"}
ALLOWED_SHADOW_ACTIONS = {"BUY", "HOLD", "REDUCE", "SELL", "OBSERVE", "NEEDS_HUMAN_REVIEW"}


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


def real_trade_count(execution_log: list[dict[str, Any]]) -> int:
    return sum(1 for item in execution_log if item.get("action") in REAL_TRADE_ACTIONS)


def blocked_trade_count(execution_log: list[dict[str, Any]]) -> int:
    return sum(1 for item in execution_log if item.get("action") == "BLOCKED_TRADE")


def shadow_action_from_decision(decision: dict[str, Any]) -> str:
    final_user_action = decision.get("final_user_action")
    if final_user_action in ALLOWED_SHADOW_ACTIONS:
        return final_user_action
    review = decision.get("ai_review") or {}
    reviewed_action = review.get("final_action_after_review")
    if reviewed_action in ALLOWED_SHADOW_ACTIONS:
        return reviewed_action
    action = decision.get("action")
    return "OBSERVE" if action == "WAIT" else action if action in ALLOWED_SHADOW_ACTIONS else "NEEDS_HUMAN_REVIEW"


def build_shadow_records(path_id: str, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for decision in decisions:
        review = decision.get("ai_review") or {}
        model_action = decision.get("action")
        if model_action == "WAIT":
            model_report_action = "OBSERVE"
        else:
            model_report_action = model_action
        shadow_action = shadow_action_from_decision(decision)
        records.append(
            {
                "path_id": path_id,
                "date": decision.get("date"),
                "candidate_ts_code": decision.get("candidate_ts_code"),
                "candidate_name": decision.get("candidate_name"),
                "model_action": model_action,
                "model_report_action": model_report_action,
                "actual_execution_action": model_action,
                "ai_review_status": review.get("review_status"),
                "ai_review_shadow_action": review.get("final_action_after_review"),
                "final_user_action": decision.get("final_user_action"),
                "shadow_action": shadow_action,
                "would_change_report_action": shadow_action != model_report_action,
                "review_changes_action": bool(review.get("review_changes_action")),
                "veto_reason": review.get("veto_reason", ""),
                "rule_conflicts": review.get("rule_conflicts", []),
                "missing_fields": review.get("missing_fields", []),
                "risk_warnings": review.get("risk_warnings", []),
                "requires_human_review": bool(review.get("requires_human_review")),
                "strong_risk_reduce_exception_candidate": bool(
                    review.get("strong_risk_reduce_exception_candidate")
                ),
                "candidate_is_structured": decision.get("candidate_is_structured"),
                "candidate_missing_reason": decision.get("candidate_missing_reason", ""),
                "evidence_quality": (decision.get("stock_selection_evidence") or {}).get("evidence_quality"),
                "sector_cycle_state": decision.get("sector_cycle_state"),
                "leader_status": decision.get("leader_status"),
            }
        )
    return records


def build_preparation_package(summary: dict[str, Any]) -> dict[str, Any]:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_records: list[dict[str, Any]] = []
    per_path: list[dict[str, Any]] = []
    invariant_issues: list[dict[str, Any]] = []

    for path_id in summary.get("reran_paths", []):
        result, decisions, execution_log = load_path_payload(path_id)
        records = build_shadow_records(path_id, decisions)
        all_records.extend(records)

        real_count = real_trade_count(execution_log)
        blocked_count = blocked_trade_count(execution_log)
        result_trade_count = result.get("trade_count")
        result_blocked_count = result.get("blocked_trade_count")
        if real_count != result_trade_count:
            invariant_issues.append(
                {
                    "path_id": path_id,
                    "type": "trade_count_mismatch",
                    "result_trade_count": result_trade_count,
                    "execution_log_real_trade_count": real_count,
                }
            )
        if blocked_count != result_blocked_count:
            invariant_issues.append(
                {
                    "path_id": path_id,
                    "type": "blocked_trade_count_mismatch",
                    "result_blocked_trade_count": result_blocked_count,
                    "execution_log_blocked_trade_count": blocked_count,
                }
            )

        per_path.append(
            {
                "path_id": path_id,
                "decision_count": len(decisions),
                "real_trade_count": real_count,
                "reported_trade_count": result_trade_count,
                "blocked_trade_count": blocked_count,
                "reported_blocked_trade_count": result_blocked_count,
                "actual_action_counts": dict(Counter(r["model_report_action"] for r in records)),
                "shadow_action_counts": dict(Counter(r["shadow_action"] for r in records)),
                "would_change_report_action_count": sum(1 for r in records if r["would_change_report_action"]),
                "ai_review_status_counts": dict(Counter(r["ai_review_status"] for r in records)),
                "needs_human_review_count": sum(1 for r in records if r["shadow_action"] == "NEEDS_HUMAN_REVIEW"),
                "strong_risk_reduce_exception_candidate_count": sum(
                    1 for r in records if r["strong_risk_reduce_exception_candidate"]
                ),
            }
        )

    shadow_action_counts = Counter(r["shadow_action"] for r in all_records)
    model_report_action_counts = Counter(r["model_report_action"] for r in all_records)
    review_status_counts = Counter(r["ai_review_status"] for r in all_records)
    top_veto_reasons = Counter(r["veto_reason"] for r in all_records if r["veto_reason"])
    top_rule_conflicts = Counter(conflict for r in all_records for conflict in r["rule_conflicts"])
    top_missing_fields = Counter(field for r in all_records for field in r["missing_fields"])

    readiness_from_summary = bool(summary.get("ready_for_dual_track_shadow_simulation"))
    blockers_from_summary = summary.get("dual_track_shadow_simulation_blockers") or []
    invariant_ok = not invariant_issues
    ready = readiness_from_summary and not blockers_from_summary and invariant_ok

    return {
        "generated_at": generated_at,
        "source_summary_json": str(SUMMARY_JSON),
        "scope": "dual_track_shadow_simulation_preparation_only",
        "boundaries": {
            "full_pipeline_selection_walk_forward": False,
            "real_account_connected": False,
            "auto_trading": False,
            "news_module_connected": False,
            "score_weight_changed": False,
            "real_trading_action_changed": False,
            "return_calculation_changed": False,
            "validation_private_read_by_this_script": False,
            "core_trading_rule_changed": False,
        },
        "readiness": {
            "ready_for_dual_track_shadow_simulation": ready,
            "readiness_from_summary": readiness_from_summary,
            "blockers_from_summary": blockers_from_summary,
            "invariant_ok": invariant_ok,
            "invariant_issues": invariant_issues,
            "recommended_next_step": (
                "enter_dual_track_shadow_logging_preparation"
                if ready
                else "do_not_enter_dual_track_shadow_logging_until_blockers_fixed"
            ),
        },
        "aggregate": {
            "path_count": len(per_path),
            "decision_count": len(all_records),
            "model_report_action_counts": dict(model_report_action_counts),
            "shadow_action_counts": dict(shadow_action_counts),
            "ai_review_status_counts": dict(review_status_counts),
            "would_change_report_action_count": sum(1 for r in all_records if r["would_change_report_action"]),
            "review_changes_action_count": sum(1 for r in all_records if r["review_changes_action"]),
            "needs_human_review_count": shadow_action_counts.get("NEEDS_HUMAN_REVIEW", 0),
            "strong_risk_reduce_exception_candidate_count": sum(
                1 for r in all_records if r["strong_risk_reduce_exception_candidate"]
            ),
            "structured_candidate_count": sum(1 for r in all_records if r["candidate_is_structured"]),
            "unstructured_candidate_count": sum(1 for r in all_records if not r["candidate_is_structured"]),
            "top_veto_reasons": top_veto_reasons.most_common(10),
            "top_rule_conflicts": top_rule_conflicts.most_common(10),
            "top_missing_fields": top_missing_fields.most_common(10),
        },
        "per_path": per_path,
        "shadow_change_records": [
            r for r in all_records if r["would_change_report_action"] or r["requires_human_review"]
        ],
    }


def build_markdown(package: dict[str, Any]) -> str:
    aggregate = package["aggregate"]
    readiness = package["readiness"]
    lines = [
        "# Dual-track shadow simulation 准备包",
        "",
        f"- 生成时间：{package['generated_at']}",
        f"- 范围：{package['scope']}",
        f"- 是否可进入双轨 shadow 记录准备：{readiness['ready_for_dual_track_shadow_simulation']}",
        f"- invariant_ok：{readiness['invariant_ok']}",
        f"- recommended_next_step：{readiness['recommended_next_step']}",
        "",
        "## 边界确认",
        "",
    ]
    for key, value in package["boundaries"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## 汇总",
            "",
            f"- path_count：{aggregate['path_count']}",
            f"- decision_count：{aggregate['decision_count']}",
            f"- model_report_action_counts：{aggregate['model_report_action_counts']}",
            f"- shadow_action_counts：{aggregate['shadow_action_counts']}",
            f"- ai_review_status_counts：{aggregate['ai_review_status_counts']}",
            f"- would_change_report_action_count：{aggregate['would_change_report_action_count']}",
            f"- review_changes_action_count：{aggregate['review_changes_action_count']}",
            f"- needs_human_review_count：{aggregate['needs_human_review_count']}",
            f"- strong_risk_reduce_exception_candidate_count：{aggregate['strong_risk_reduce_exception_candidate_count']}",
            f"- structured/unstructured candidate：{aggregate['structured_candidate_count']}/{aggregate['unstructured_candidate_count']}",
            f"- top_veto_reasons：{aggregate['top_veto_reasons']}",
            f"- top_rule_conflicts：{aggregate['top_rule_conflicts']}",
            f"- top_missing_fields：{aggregate['top_missing_fields']}",
            "",
            "## 每路径对照",
            "",
            "| path | decisions | real_trades | blocked | actual_actions | shadow_actions | would_change | needs_human | exception_candidates |",
            "| -- | --: | --: | --: | -- | -- | --: | --: | --: |",
        ]
    )
    for item in package["per_path"]:
        lines.append(
            f"| {item['path_id']} | {item['decision_count']} | {item['real_trade_count']} | "
            f"{item['blocked_trade_count']} | {item['actual_action_counts']} | {item['shadow_action_counts']} | "
            f"{item['would_change_report_action_count']} | {item['needs_human_review_count']} | "
            f"{item['strong_risk_reduce_exception_candidate_count']} |"
        )
    lines.extend(
        [
            "",
            "## Shadow 变化/人工复核样本",
            "",
            "| path | date | code | name | model_report_action | shadow_action | review_status | veto_reason | rule_conflicts |",
            "| -- | -- | -- | -- | -- | -- | -- | -- | -- |",
        ]
    )
    for record in package["shadow_change_records"]:
        lines.append(
            f"| {record['path_id']} | {record['date']} | {record.get('candidate_ts_code')} | "
            f"{record.get('candidate_name')} | {record['model_report_action']} | {record['shadow_action']} | "
            f"{record['ai_review_status']} | {record['veto_reason']} | {record['rule_conflicts']} |"
        )
    if readiness["invariant_issues"]:
        lines.extend(["", "## Invariant Issues", ""])
        for issue in readiness["invariant_issues"]:
            lines.append(f"- {issue}")
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "本准备包只证明当前 10 路径结果已经具备双轨 shadow 记录的字段基础；不证明完整自动选股能力，不进入 FULL_PIPELINE_SELECTION_WALK_FORWARD。",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dual-track shadow simulation preparation package")
    parser.add_argument("--summary-json", default=str(SUMMARY_JSON))
    parser.add_argument("--output-prefix", default="dual_track_shadow_preparation")
    args = parser.parse_args()

    summary_path = Path(args.summary_json)
    if not summary_path.is_absolute():
        summary_path = ROOT / summary_path
    summary = read_json(summary_path)
    package = build_preparation_package(summary)

    json_path = REPORT_DIR / f"{args.output_prefix}.json"
    md_path = REPORT_DIR / f"{args.output_prefix}.md"
    write_json(json_path, package)
    md_path.write_text(build_markdown(package), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "ready": package["readiness"]["ready_for_dual_track_shadow_simulation"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
