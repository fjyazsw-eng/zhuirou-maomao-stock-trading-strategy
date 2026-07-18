from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "reports" / "review_packages"
CLOSURE_JSON = REVIEW_DIR / "walk_forward_10paths_mvp_closure_package_20260706.json"
OUTPUT_STEM = "simulated_live_v1_minimum_design_package_20260706"
OUTPUT_JSON = REVIEW_DIR / f"{OUTPUT_STEM}.json"
OUTPUT_MD = REVIEW_DIR / f"{OUTPUT_STEM}.md"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_payload() -> dict[str, Any]:
    closure = read_json(CLOSURE_JSON)

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": "simulated_live_v1_minimum_design_package",
        "source_stage": {
            "mvp_closure_completed": closure["mvp_closure_status"]["mvp_closure_completed"],
            "stage_acceptance_passed": closure["mvp_closure_status"]["stage_acceptance_passed"],
            "recommend_enter_simulated_live_v1_preparation": closure["mvp_closure_status"][
                "recommend_enter_simulated_live_v1_preparation"
            ],
        },
        "simulated_live_v1_status": {
            "simulated_live_v1_preparation_started": True,
            "still_do_not_enter_full_pipeline_selection_walk_forward": True,
            "still_do_not_connect_real_account": True,
            "still_do_not_auto_trade": True,
            "still_do_not_enable_news_module": True,
        },
        "objective": [
            "generate_daily_simulated_decision_report",
            "log_original_model_action_and_ai_review_shadow_action_together",
            "keep_execution_line_and_shadow_line_separated",
            "check_overtrading_risk",
            "check_position_conflict_risk",
            "check_final_user_action_clarity",
            "send_result_by_feishu_notification",
            "simulate_only_without_real_trade_execution",
        ],
        "inputs": {
            "trade_date": "YYYY-MM-DD",
            "daily_questions_or_market_data": {
                "required": True,
                "fields": [
                    "market_snapshot",
                    "target_symbols_ohlc",
                    "index_context",
                    "candidate_supporting_data",
                ],
            },
            "simulated_account_state": {
                "required": True,
                "source": "local_simulated_state_only",
            },
            "simulated_positions": {
                "required": True,
                "fields": ["ts_code", "name", "shares", "cost_basis", "mark_price", "market_value", "pnl_ratio"],
            },
            "candidate_pool": {
                "required": True,
                "fields": ["ts_code", "name", "candidate_action", "candidate_source", "candidate_score_hint"],
            },
            "previous_day_report": {
                "required": False,
                "purpose": "carry_forward_observation_and_human_review_context",
            },
            "risk_config": {
                "required": True,
                "fields": [
                    "max_position_per_stock",
                    "max_total_position",
                    "trade_density_limit",
                    "stop_loss_rule",
                    "review_only_boundaries",
                ],
            },
            "no_real_account_connection": True,
            "no_news_module": True,
        },
        "simulated_account_state": {
            "description": "simulated account only; never connected to a real broker account",
            "fields": [
                "initial_cash",
                "cash",
                "total_equity",
                "positions",
                "max_position_per_stock",
                "max_total_position",
                "trade_count_today",
                "trade_density_limit",
                "unrealized_pnl",
                "realized_pnl",
                "account_risk_flags",
            ],
        },
        "daily_decision_output": {
            "fields": [
                "original_model_action",
                "ai_review_shadow_action",
                "final_user_action",
                "candidate_ts_code",
                "candidate_name",
                "action_reason",
                "execution_condition",
                "invalidation_condition",
                "stop_loss_condition",
                "position_limit",
                "user_note",
                "stock_selection_evidence",
                "sector_cycle_state",
                "leader_status",
                "ai_review",
                "risk_warnings",
                "needs_human_review_reason",
                "feishu_message_summary",
            ]
        },
        "dual_track_recording": {
            "original_model_track": "records the model's original report-layer action",
            "ai_review_shadow_track": "records the ai-review shadow action only",
            "shadow_does_not_change_execution_line": True,
            "shadow_pnl_estimated_separately": True,
            "tracks_must_stay_separated": True,
            "shadow_cannot_write_back_to_original": True,
        },
        "risk_boundaries": [
            "no_real_order_execution",
            "no_auto_trading",
            "no_real_account_connection",
            "no_news_triggered_buy_signal",
            "no_scoring_weight_change",
            "no_full_pipeline_entry",
            "needs_human_review_is_not_auto_reduce",
            "confirmed_reduce_requires_second_confirmation",
            "validation_private_cannot_be_used_for_same_day_decision",
            "feishu_is_notification_only_not_execution",
        ],
        "daily_report_format": [
            "today_market_state",
            "candidate_list",
            "original_model_recommendation",
            "ai_review_shadow_recommendation",
            "final_user_action",
            "simulated_position_change",
            "risk_warnings",
            "human_review_items",
            "today_uncertainties",
            "next_day_watch_conditions",
            "feishu_summary",
        ],
        "acceptance_metrics": [
            "daily_report_generated",
            "original_and_shadow_tracks_logged",
            "real_and_shadow_pnl_separated",
            "no_risk_control_conflict",
            "no_overtrading",
            "no_ambiguous_final_action",
            "feishu_notification_sent",
            "no_real_account_access",
            "no_auto_trade",
            "validation_private_boundary_respected",
        ],
        "directory_and_file_plan": {
            "directories": [
                "reports/simulated_live_v1/daily/",
                "reports/simulated_live_v1/state/",
                "reports/simulated_live_v1/summary/",
                "reports/simulated_live_v1/review/",
            ],
            "current_report_script": "scripts/build_simulated_live_v1_design_package.py",
            "future_script_naming_suggestions": [
                "scripts/setup_simulated_live_v1_dry_run.py",
                "scripts/build_simulated_live_v1_daily_report.py",
                "scripts/update_simulated_account_state.py",
                "scripts/build_simulated_live_v1_summary.py",
            ],
            "note": "this round does not implement live-running logic",
        },
        "not_in_scope": [
            "full_market_auto_stock_selection",
            "real_account_connection",
            "automatic_order_placement",
            "news_module_integration",
            "core_trading_rule_change",
            "full_pipeline_selection_walk_forward",
            "profitability_proof",
        ],
        "recommended_next_step": {
            "preferred_option": "simulated_live_v1_dry_run_setup",
            "alternative_option": "simulated_account_state_schema",
            "reason": (
                "dry_run_setup is higher priority because it turns the current design into a daily-operable simulation shell "
                "while still preserving all current safety boundaries"
            ),
        },
    }
    return payload


def build_markdown(payload: dict[str, Any]) -> str:
    status = payload["simulated_live_v1_status"]
    inputs = payload["inputs"]
    dual_track = payload["dual_track_recording"]
    next_step = payload["recommended_next_step"]

    lines = [
        f"# {OUTPUT_STEM}",
        "",
        f"- generated_at: {payload['generated_at']}",
        "",
        "## simulated_live_v1_status",
        "",
        f"- simulated_live_v1_preparation_started: {status['simulated_live_v1_preparation_started']}",
        f"- still_do_not_enter_full_pipeline_selection_walk_forward: {status['still_do_not_enter_full_pipeline_selection_walk_forward']}",
        f"- still_do_not_connect_real_account: {status['still_do_not_connect_real_account']}",
        f"- still_do_not_auto_trade: {status['still_do_not_auto_trade']}",
        f"- still_do_not_enable_news_module: {status['still_do_not_enable_news_module']}",
        "",
        "## objective",
        "",
    ]
    lines.extend([f"- {item}" for item in payload["objective"]])
    lines.extend(
        [
            "",
            "## inputs",
            "",
            f"- trade_date: {inputs['trade_date']}",
            f"- daily_questions_or_market_data.fields: {', '.join(inputs['daily_questions_or_market_data']['fields'])}",
            f"- simulated_account_state.source: {inputs['simulated_account_state']['source']}",
            f"- simulated_positions.fields: {', '.join(inputs['simulated_positions']['fields'])}",
            f"- candidate_pool.fields: {', '.join(inputs['candidate_pool']['fields'])}",
            f"- previous_day_report.required: {inputs['previous_day_report']['required']}",
            f"- risk_config.fields: {', '.join(inputs['risk_config']['fields'])}",
            f"- no_real_account_connection: {inputs['no_real_account_connection']}",
            f"- no_news_module: {inputs['no_news_module']}",
            "",
            "## simulated_account_state",
            "",
            f"- description: {payload['simulated_account_state']['description']}",
            f"- fields: {', '.join(payload['simulated_account_state']['fields'])}",
            "",
            "## daily_decision_output",
            "",
            f"- fields: {', '.join(payload['daily_decision_output']['fields'])}",
            "",
            "## dual_track_recording",
            "",
            f"- original_model_track: {dual_track['original_model_track']}",
            f"- ai_review_shadow_track: {dual_track['ai_review_shadow_track']}",
            f"- shadow_does_not_change_execution_line: {dual_track['shadow_does_not_change_execution_line']}",
            f"- shadow_pnl_estimated_separately: {dual_track['shadow_pnl_estimated_separately']}",
            f"- tracks_must_stay_separated: {dual_track['tracks_must_stay_separated']}",
            f"- shadow_cannot_write_back_to_original: {dual_track['shadow_cannot_write_back_to_original']}",
            "",
            "## risk_boundaries",
            "",
        ]
    )
    lines.extend([f"- {item}" for item in payload["risk_boundaries"]])
    lines.extend(["", "## daily_report_format", ""])
    lines.extend([f"- {item}" for item in payload["daily_report_format"]])
    lines.extend(["", "## acceptance_metrics", ""])
    lines.extend([f"- {item}" for item in payload["acceptance_metrics"]])
    lines.extend(["", "## directory_and_file_plan", ""])
    lines.extend([f"- {item}" for item in payload["directory_and_file_plan"]["directories"]])
    lines.append(f"- current_report_script: {payload['directory_and_file_plan']['current_report_script']}")
    lines.extend([f"- future_script: {item}" for item in payload["directory_and_file_plan"]["future_script_naming_suggestions"]])
    lines.append(f"- note: {payload['directory_and_file_plan']['note']}")
    lines.extend(["", "## not_in_scope", ""])
    lines.extend([f"- {item}" for item in payload["not_in_scope"]])
    lines.extend(
        [
            "",
            "## recommended_next_step",
            "",
            f"- preferred_option: {next_step['preferred_option']}",
            f"- alternative_option: {next_step['alternative_option']}",
            f"- reason: {next_step['reason']}",
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
                "preferred_next_step": payload["recommended_next_step"]["preferred_option"],
                "still_do_not_enter_full_pipeline_selection_walk_forward": payload["simulated_live_v1_status"][
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
