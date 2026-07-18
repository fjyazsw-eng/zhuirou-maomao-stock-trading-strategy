from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WF_DIR = ROOT / "reports" / "walk_forward_2025"
REVIEW_DIR = ROOT / "reports" / "review_packages"
SUMMARY_JSON = WF_DIR / "walk_forward_10paths_summary.json"
CONFIRMED_REPLAY_JSON = WF_DIR / "confirmed_reduce_shadow_scenario_replay.json"
OUTPUT_STEM = "walk_forward_10paths_mvp_closure_package_20260706"
OUTPUT_JSON = REVIEW_DIR / f"{OUTPUT_STEM}.json"
OUTPUT_MD = REVIEW_DIR / f"{OUTPUT_STEM}.md"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_payload() -> dict[str, Any]:
    summary = read_json(SUMMARY_JSON)
    confirmed = read_json(CONFIRMED_REPLAY_JSON)

    original_action_counts = summary.get("original_action_counts", {})
    shadow_action_counts = summary.get("shadow_action_counts", {})
    top_shadow_change_reasons = summary.get("top_shadow_change_reasons", [])

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": "walk_forward_2025_10paths_mvp_closure_package",
        "boundaries": {
            "git_touched": False,
            "entered_full_pipeline_selection_walk_forward": False,
            "real_account_connected": False,
            "auto_trading_enabled": False,
            "news_module_enabled": False,
            "scoring_weights_changed": False,
            "real_trade_action_changed": False,
            "real_return_calculation_changed": False,
            "core_trading_logic_changed": False,
        },
        "mvp_closure_status": {
            "mvp_closure_completed": True,
            "stage_acceptance_passed": True,
            "recommend_enter_simulated_live_v1_preparation": True,
            "still_do_not_enter_full_pipeline_selection_walk_forward": True,
        },
        "completed_capabilities": [
            "candidate_structured_fields",
            "stock_selection_evidence",
            "sector_cycle_state",
            "leader_status",
            "ai_review_shadow_review",
            "final_user_action",
            "blocked_trade_review",
            "strong_risk_reduce_human_review",
            "dual_track_shadow_logging",
            "dual_track_shadow_pnl_estimate",
            "confirmed_reduce_shadow_scenario_replay",
        ],
        "validated_risk_controls": {
            "trade_density_limit": True,
            "position_limit": True,
            "buy_downgrade_to_observe": True,
            "needs_human_review_boundary": True,
            "strong_risk_reduce_not_auto_executed": True,
            "final_user_action_clarity": True,
        },
        "shadow_review_findings": {
            "pass": summary.get("shadow_pass_count"),
            "reject": summary.get("shadow_reject_count"),
            "needs_human": summary.get("shadow_human_review_count"),
            "shadow_changed_action_count": summary.get("shadow_changed_action_count"),
            "buy_to_observe_count": summary.get("buy_to_observe_count"),
            "hold_to_needs_human_review_count": summary.get("hold_to_needs_human_review_count"),
            "buy_to_observe_main_reasons": [item[0] for item in top_shadow_change_reasons if "buy_" in item[0]],
            "hold_to_needs_human_review_main_reasons": [
                item[0] for item in top_shadow_change_reasons if "needs_human_review" in item[0]
            ],
            "too_conservative_observe_found": False,
            "missed_hard_risk_found": False,
        },
        "dual_track_findings": {
            "original_action_counts": original_action_counts,
            "shadow_action_counts": shadow_action_counts,
            "change_point_count": summary.get("shadow_changed_action_count"),
            "shadow_track_tone": "more_conservative",
            "proved_shadow_more_profitable": False,
            "proved_shadow_more_stable": False,
            "paths_with_shadow_changes": summary.get("paths_with_shadow_changes", []),
        },
        "shadow_pnl_findings": {
            "avoided_loss": summary.get("estimated_avoided_loss_count"),
            "missed_gain": summary.get("estimated_missed_gain_count"),
            "reduced_drawdown": summary.get("estimated_reduced_drawdown_count"),
            "neutral": summary.get("estimated_neutral_count"),
            "unknown": summary.get("estimated_unknown_count"),
            "estimated_total_return_delta": summary.get("estimated_total_return_delta"),
            "estimated_total_drawdown_delta": summary.get("estimated_total_drawdown_delta"),
            "conclusion": (
                "shadow line currently looks stricter on BUY and more cautious on risk prompts, "
                "but current 10-path evidence does not prove better profit or better stability."
            ),
        },
        "confirmed_reduce_findings": {
            "all_four_review_only": confirmed.get("review_only_recommended_count") == 4,
            "confirmed_reduce_candidate_count": confirmed.get("confirmed_reduce_candidate_count"),
            "recommend_rule_change_now": confirmed.get("recommended_rule_change_now"),
            "second_confirmation_conditions_if_escalated": [
                "next_day_weakness_confirmation",
                "leader_broken_or_weakening_continues",
                "sector_cycle_fading_or_falling_confirms",
                "position_or_stop_risk_triggered",
            ],
        },
        "known_limitations": [
            "only_10_paths_sample_size_is_small",
            "currently_proves_process_structure_and_risk_boundaries_more_than_long_term_edge",
            "does_not_prove_long_term_profitability",
            "does_not_prove_full_auto_stock_selection",
            "shadow_pnl_estimate_is_not_formal_realized_pnl",
            "confirmed_reduce_is_not_auto_sell",
            "acc_01_deleveraging_plan_is_still_report_layer_only",
            "non_critical_candidate_fields_still_have_gaps",
            "news_module_is_still_out_of_scope",
        ],
        "not_proven_yet": [
            "long_term_profitability",
            "cross_market_regime_stability",
            "full_market_auto_stock_selection_capability",
            "ai_review_shadow_line_is_always_more_profitable",
            "ready_for_real_account_connection",
            "ready_for_auto_trading",
        ],
        "do_not_enter_full_pipeline_reasons": [
            "10_paths_are_fixed_path_validation_only",
            "auto_stock_selection_chain_not_fully_tested",
            "sample_size_still_small",
            "news_module_still_deferred",
            "ai_review_line_is_still_shadow_only",
            "simulated_live_v1_not_built_yet",
        ],
        "ready_for_simulated_live_v1_preparation": {
            "value": True,
            "reason": (
                "the MVP phase has passed staged acceptance on structure, report clarity, risk boundaries, "
                "and dual-track separation, so it is ready for a simulated-live-v1 preparation package"
            ),
            "blockers_if_false": [],
        },
        "simulated_live_v1_minimum_design": {
            "inputs": [
                "daily_questions_and_market_data",
                "simulated_account_current_positions",
                "candidate_pool",
                "no_real_account_connection",
                "no_news_module",
            ],
            "outputs": [
                "daily_simulated_decision_report",
                "original_model_action",
                "ai_review_shadow_action",
                "final_user_action",
                "risk_warnings",
                "position_suggestion",
                "feishu_notification",
            ],
            "boundaries": [
                "no_real_order_placement",
                "no_auto_trading",
                "no_scoring_weight_changes",
                "no_news_triggered_buy",
                "ai_review_stays_shadow",
                "needs_human_review_stays_manual_review_only",
            ],
            "acceptance_metrics": [
                "daily_report_generated",
                "original_and_shadow_tracks_logged",
                "real_and_shadow_pnl_separated",
                "no_risk_control_conflict",
                "no_overtrading",
                "no_ambiguous_final_action",
                "feishu_notification_sent",
            ],
        },
        "recommended_next_step": "build simulated_live_v1_minimum_design_package or simulated_live_v1_dry_run_setup; still do not enter FULL_PIPELINE or real account connection",
    }
    return payload


def build_markdown(payload: dict[str, Any]) -> str:
    status = payload["mvp_closure_status"]
    shadow = payload["shadow_review_findings"]
    dual_track = payload["dual_track_findings"]
    shadow_pnl = payload["shadow_pnl_findings"]
    confirmed = payload["confirmed_reduce_findings"]
    ready = payload["ready_for_simulated_live_v1_preparation"]
    design = payload["simulated_live_v1_minimum_design"]

    lines = [
        f"# {OUTPUT_STEM}",
        "",
        f"- generated_at: {payload['generated_at']}",
        "",
        "## mvp_closure_status",
        "",
        f"- mvp_closure_completed: {status['mvp_closure_completed']}",
        f"- stage_acceptance_passed: {status['stage_acceptance_passed']}",
        f"- recommend_enter_simulated_live_v1_preparation: {status['recommend_enter_simulated_live_v1_preparation']}",
        f"- still_do_not_enter_full_pipeline_selection_walk_forward: {status['still_do_not_enter_full_pipeline_selection_walk_forward']}",
        "",
        "## completed_capabilities",
        "",
    ]
    lines.extend([f"- {item}" for item in payload["completed_capabilities"]])
    lines.extend(
        [
            "",
            "## validated_risk_controls",
            "",
        ]
    )
    lines.extend([f"- {k}: {v}" for k, v in payload["validated_risk_controls"].items()])
    lines.extend(
        [
            "",
            "## shadow_review_findings",
            "",
            f"- pass/reject/needs_human: {shadow['pass']} / {shadow['reject']} / {shadow['needs_human']}",
            f"- shadow_changed_action_count: {shadow['shadow_changed_action_count']}",
            f"- buy_to_observe_count: {shadow['buy_to_observe_count']}",
            f"- hold_to_needs_human_review_count: {shadow['hold_to_needs_human_review_count']}",
            f"- buy_to_observe_main_reasons: {', '.join(shadow['buy_to_observe_main_reasons'])}",
            f"- hold_to_needs_human_review_main_reasons: {', '.join(shadow['hold_to_needs_human_review_main_reasons'])}",
            f"- too_conservative_observe_found: {shadow['too_conservative_observe_found']}",
            f"- missed_hard_risk_found: {shadow['missed_hard_risk_found']}",
            "",
            "## dual_track_findings",
            "",
            f"- original_action_counts: {dual_track['original_action_counts']}",
            f"- shadow_action_counts: {dual_track['shadow_action_counts']}",
            f"- change_point_count: {dual_track['change_point_count']}",
            f"- shadow_track_tone: {dual_track['shadow_track_tone']}",
            f"- proved_shadow_more_profitable: {dual_track['proved_shadow_more_profitable']}",
            f"- proved_shadow_more_stable: {dual_track['proved_shadow_more_stable']}",
            f"- paths_with_shadow_changes: {', '.join(dual_track['paths_with_shadow_changes'])}",
            "",
            "## shadow_pnl_findings",
            "",
            f"- avoided_loss / missed_gain / reduced_drawdown / neutral / unknown: "
            f"{shadow_pnl['avoided_loss']} / {shadow_pnl['missed_gain']} / {shadow_pnl['reduced_drawdown']} / "
            f"{shadow_pnl['neutral']} / {shadow_pnl['unknown']}",
            f"- estimated_total_return_delta: {shadow_pnl['estimated_total_return_delta']}",
            f"- estimated_total_drawdown_delta: {shadow_pnl['estimated_total_drawdown_delta']}",
            f"- conclusion: {shadow_pnl['conclusion']}",
            "",
            "## confirmed_reduce_findings",
            "",
            f"- all_four_review_only: {confirmed['all_four_review_only']}",
            f"- confirmed_reduce_candidate_count: {confirmed['confirmed_reduce_candidate_count']}",
            f"- recommend_rule_change_now: {confirmed['recommend_rule_change_now']}",
            f"- second_confirmation_conditions_if_escalated: {', '.join(confirmed['second_confirmation_conditions_if_escalated'])}",
            "",
            "## known_limitations",
            "",
        ]
    )
    lines.extend([f"- {item}" for item in payload["known_limitations"]])
    lines.extend(["", "## not_proven_yet", ""])
    lines.extend([f"- {item}" for item in payload["not_proven_yet"]])
    lines.extend(["", "## do_not_enter_full_pipeline_reasons", ""])
    lines.extend([f"- {item}" for item in payload["do_not_enter_full_pipeline_reasons"]])
    lines.extend(
        [
            "",
            "## ready_for_simulated_live_v1_preparation",
            "",
            f"- value: {ready['value']}",
            f"- reason: {ready['reason']}",
            "",
            "## simulated_live_v1_minimum_design",
            "",
            "- inputs:",
        ]
    )
    lines.extend([f"  - {item}" for item in design["inputs"]])
    lines.append("- outputs:")
    lines.extend([f"  - {item}" for item in design["outputs"]])
    lines.append("- boundaries:")
    lines.extend([f"  - {item}" for item in design["boundaries"]])
    lines.append("- acceptance_metrics:")
    lines.extend([f"  - {item}" for item in design["acceptance_metrics"]])
    lines.extend(
        [
            "",
            "## recommended_next_step",
            "",
            f"- {payload['recommended_next_step']}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    write_json(OUTPUT_JSON, payload)
    OUTPUT_MD.write_text(build_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_json": str(OUTPUT_JSON),
                "output_md": str(OUTPUT_MD),
                "recommend_enter_simulated_live_v1_preparation": payload["mvp_closure_status"][
                    "recommend_enter_simulated_live_v1_preparation"
                ],
                "still_do_not_enter_full_pipeline_selection_walk_forward": payload["mvp_closure_status"][
                    "still_do_not_enter_full_pipeline_selection_walk_forward"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
