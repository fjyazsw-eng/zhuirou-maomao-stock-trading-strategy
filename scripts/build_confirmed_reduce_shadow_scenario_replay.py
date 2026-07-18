from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "walk_forward_2025"
SUMMARY_JSON = REPORT_DIR / "walk_forward_10paths_summary.json"
SUMMARY_MD = REPORT_DIR / "walk_forward_10paths_summary.md"
PNL_ESTIMATE_JSON = REPORT_DIR / "dual_track_shadow_pnl_estimate.json"
SHADOW_LOGGING_JSON = REPORT_DIR / "dual_track_shadow_logging.json"
OUTPUT_JSON = REPORT_DIR / "confirmed_reduce_shadow_scenario_replay.json"
OUTPUT_MD = REPORT_DIR / "confirmed_reduce_shadow_scenario_replay.md"

TARGET_PATH = "WF2025-INTRA-02"
TARGET_CODE = "300300.SZ"
TARGET_DATES = {"20251107", "20251110", "20251111", "20251112"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def decision_map() -> dict[str, dict[str, Any]]:
    decisions = read_json(REPORT_DIR / "WF2025_INTRA_02_decisions.json").get("decisions", [])
    return {item.get("date"): item for item in decisions}


def execution_log() -> list[dict[str, Any]]:
    return read_json(REPORT_DIR / "WF2025_INTRA_02_execution_log.json").get("execution_log", [])


def change_points() -> dict[str, dict[str, Any]]:
    payload = read_json(SHADOW_LOGGING_JSON)
    result = {}
    for item in payload.get("shadow_change_points", []):
        if item.get("path") == TARGET_PATH and item.get("code") == TARGET_CODE and item.get("date") in TARGET_DATES:
            result[item["date"]] = item
    return result


def pnl_estimates() -> dict[str, dict[str, Any]]:
    payload = read_json(PNL_ESTIMATE_JSON)
    result = {}
    for item in payload.get("estimates", []):
        if item.get("path") == TARGET_PATH and item.get("ts_code") == TARGET_CODE and item.get("date") in TARGET_DATES:
            result[item["date"]] = item
    return result


def blocked_trade_by_date(exec_log: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for item in exec_log:
        if (
            item.get("action") == "BLOCKED_TRADE"
            and item.get("ts_code") == TARGET_CODE
            and item.get("date") in TARGET_DATES
        ):
            result[item["date"]] = item
    return result


def compute_recommendation(
    *,
    date: str,
    sector_cycle_state: str | None,
    leader_status: str | None,
    evidence_quality: str | None,
    risk_notes: list[str],
    confirmed_effect: str | None,
    confirmed_return_delta: float | None,
    confirmed_drawdown_delta: float | None,
) -> dict[str, Any]:
    review_only = True
    reduce_if_next_day_weak = False
    reduce_if_break_position_rule = False
    reduce_if_leader_broken = False
    reduce_if_sector_falling = False
    do_not_reduce = False
    confirmed_reduce_candidate = False
    reasons: list[str] = []

    high_position_risk = "high_position_risk" in risk_notes
    weak_evidence = evidence_quality in {"LOW", "INSUFFICIENT"}
    negative_sector = sector_cycle_state in {"FADING", "FALLING"}
    negative_leader = leader_status in {"LEADER_WEAKENING", "LEADER_BROKEN"}
    next_day_confirmation_combo = high_position_risk and negative_sector and negative_leader and weak_evidence
    drawdown_small = confirmed_drawdown_delta is not None and confirmed_drawdown_delta <= 0.1
    missed_gain_bias = confirmed_effect == "missed_gain" and (confirmed_return_delta or 0) < 0

    if date == "20251107":
        review_only = True
        reduce_if_next_day_weak = True
        confirmed_reduce_candidate = next_day_confirmation_combo
        reasons.append(
            "Next day moved into FADING + LEADER_WEAKENING, and this point had LOW evidence quality, "
            "so it is reasonable as a human-review escalation candidate."
        )
        reasons.append(
            "But the confirmed-reduce branch only improves drawdown slightly and gives up later upside, "
            "so it should not be promoted into an automatic reduce rule."
        )
    elif date in {"20251110", "20251111"}:
        review_only = True
        do_not_reduce = True
        if date == "20251110" and next_day_confirmation_combo:
            reasons.append(
                "The same-day risk combo was meaningful, but it fits manual review better than confirmed_reduce."
            )
        reasons.append(
            "The later path stayed strong, and the confirmed-reduce branch mainly shows missed_gain, "
            "so a mechanical reduce is not supported."
        )
    elif date == "20251112":
        review_only = True
        do_not_reduce = True
        reasons.append(
            "This point was back to DIVERGENCE + LEADER_STRONG + HIGH evidence, which is closer to "
            "a manual check prompt than an actual reduce signal."
        )
        reasons.append(
            "The later path remained strong, and confirmed_reduce would clearly miss gains, so no escalation."
        )

    if sector_cycle_state == "FALLING":
        reduce_if_sector_falling = True
        confirmed_reduce_candidate = True
    if leader_status == "LEADER_BROKEN":
        reduce_if_leader_broken = True
        confirmed_reduce_candidate = True
    if "position_limit_conflict" in risk_notes:
        reduce_if_break_position_rule = True
        confirmed_reduce_candidate = True

    if not reasons:
        if missed_gain_bias and drawdown_small:
            do_not_reduce = True
            reasons.append("Reducing mainly creates missed_gain while drawdown improvement is limited, so keep review_only.")
        elif next_day_confirmation_combo:
            confirmed_reduce_candidate = True
            reasons.append(
                "The risk-condition combo is fairly complete, but a reduce still needs next-day weakness "
                "or explicit position/stop-risk confirmation."
            )
        else:
            reasons.append("This is better treated as a human-review prompt and is not enough for confirmed_reduce.")

    return {
        "review_only": review_only,
        "reduce_if_next_day_weak": reduce_if_next_day_weak,
        "reduce_if_break_position_rule": reduce_if_break_position_rule,
        "reduce_if_leader_broken": reduce_if_leader_broken,
        "reduce_if_sector_falling": reduce_if_sector_falling,
        "do_not_reduce": do_not_reduce,
        "confirmed_reduce_candidate": confirmed_reduce_candidate,
        "rationale": " ".join(reasons),
    }


def build_replay() -> dict[str, Any]:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    decisions = decision_map()
    changes = change_points()
    estimates = pnl_estimates()
    blocked = blocked_trade_by_date(execution_log())

    items = []
    for date in sorted(TARGET_DATES):
        decision = decisions.get(date, {})
        change = changes.get(date, {})
        estimate = estimates.get(date, {})
        block = blocked.get(date, {})
        evidence = decision.get("stock_selection_evidence") or {}
        risk_notes = list(evidence.get("risk_notes") or [])
        recommendation = compute_recommendation(
            date=date,
            sector_cycle_state=decision.get("sector_cycle_state"),
            leader_status=decision.get("leader_status"),
            evidence_quality=evidence.get("evidence_quality"),
            risk_notes=risk_notes,
            confirmed_effect=(estimate.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_shadow_effect_type"),
            confirmed_return_delta=(estimate.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_return_delta"),
            confirmed_drawdown_delta=(estimate.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_drawdown_delta"),
        )
        items.append(
            {
                "date": date,
                "original_action": change.get("original_action"),
                "shadow_action": change.get("shadow_action"),
                "signal_strength": block.get("signal_strength"),
                "trade_block_reason": block.get("trade_block_reason"),
                "sector_cycle_state": decision.get("sector_cycle_state"),
                "leader_status": decision.get("leader_status"),
                "evidence_quality": evidence.get("evidence_quality"),
                "original_subsequent_outcome": estimate.get("original_outcome_after_change"),
                "review_only_effect": (estimate.get("review_only_estimate") or {}).get("estimated_shadow_effect_type"),
                "confirmed_reduce_effect": (estimate.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_shadow_effect_type"),
                "confirmed_reduce_return_delta": (estimate.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_return_delta"),
                "confirmed_reduce_drawdown_delta": (estimate.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_drawdown_delta"),
                "worth_actual_reduce": {
                    "review_only": recommendation["review_only"],
                    "reduce_if_next_day_weak": recommendation["reduce_if_next_day_weak"],
                    "reduce_if_break_position_rule": recommendation["reduce_if_break_position_rule"],
                    "reduce_if_leader_broken": recommendation["reduce_if_leader_broken"],
                    "reduce_if_sector_falling": recommendation["reduce_if_sector_falling"],
                    "do_not_reduce": recommendation["do_not_reduce"],
                },
                "confirmed_reduce_candidate": recommendation["confirmed_reduce_candidate"],
                "reason": recommendation["rationale"],
            }
        )

    summary = {
        "confirmed_reduce_replay_enabled": True,
        "confirmed_reduce_replay_count": len(items),
        "review_only_recommended_count": sum(1 for item in items if item["worth_actual_reduce"]["review_only"]),
        "confirmed_reduce_candidate_count": sum(1 for item in items if item["confirmed_reduce_candidate"]),
        "do_not_reduce_count": sum(1 for item in items if item["worth_actual_reduce"]["do_not_reduce"]),
        "reduce_if_next_day_weak_count": sum(1 for item in items if item["worth_actual_reduce"]["reduce_if_next_day_weak"]),
        "reduce_if_break_position_rule_count": sum(
            1 for item in items if item["worth_actual_reduce"]["reduce_if_break_position_rule"]
        ),
        "reduce_if_leader_broken_count": sum(
            1 for item in items if item["worth_actual_reduce"]["reduce_if_leader_broken"]
        ),
        "reduce_if_sector_falling_count": sum(
            1 for item in items if item["worth_actual_reduce"]["reduce_if_sector_falling"]
        ),
        "recommended_rule_change_now": False,
        "recommended_next_step": (
            "keep NEEDS_HUMAN_REVIEW as shadow review only; if future rounds need escalation, require next-day weakness or explicit leader/sector deterioration before confirmed_reduce"
        ),
    }
    return {
        "generated_at": generated_at,
        "scope": "confirmed_reduce_shadow_scenario_replay_for_intra02_only",
        "boundaries": {
            "real_execution_log_changed": False,
            "real_trade_action_changed": False,
            "real_return_calculation_changed": False,
            "full_pipeline_selection_walk_forward": False,
            "core_trading_rule_changed": False,
            "needs_human_review_auto_equals_reduce": False,
        },
        "items": items,
        **summary,
    }


def build_markdown(replay: dict[str, Any]) -> str:
    lines = [
        "# confirmed_reduce_shadow_scenario_replay",
        "",
        f"- generated_at: {replay['generated_at']}",
        f"- confirmed_reduce_replay_enabled: {replay['confirmed_reduce_replay_enabled']}",
        f"- confirmed_reduce_replay_count: {replay['confirmed_reduce_replay_count']}",
        f"- review_only_recommended_count: {replay['review_only_recommended_count']}",
        f"- confirmed_reduce_candidate_count: {replay['confirmed_reduce_candidate_count']}",
        f"- do_not_reduce_count: {replay['do_not_reduce_count']}",
        f"- reduce_if_next_day_weak_count: {replay['reduce_if_next_day_weak_count']}",
        f"- reduce_if_break_position_rule_count: {replay['reduce_if_break_position_rule_count']}",
        f"- reduce_if_leader_broken_count: {replay['reduce_if_leader_broken_count']}",
        f"- reduce_if_sector_falling_count: {replay['reduce_if_sector_falling_count']}",
        f"- recommended_rule_change_now: {replay['recommended_rule_change_now']}",
        f"- recommended_next_step: {replay['recommended_next_step']}",
        "",
        "## Replay Items",
        "",
        "| date | original_action | shadow_action | signal_strength | trade_block_reason | sector_cycle_state | leader_status | evidence_quality | review_only_effect | confirmed_reduce_effect | return_delta | drawdown_delta | review_only | next_day_weak | break_position_rule | leader_broken | sector_falling | do_not_reduce |",
        "| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |",
    ]
    for item in replay["items"]:
        worth = item["worth_actual_reduce"]
        lines.append(
            f"| {item['date']} | {item['original_action']} | {item['shadow_action']} | "
            f"{item['signal_strength']} | {item['trade_block_reason']} | {item['sector_cycle_state']} | "
            f"{item['leader_status']} | {item['evidence_quality']} | {item['review_only_effect']} | "
            f"{item['confirmed_reduce_effect']} | {item['confirmed_reduce_return_delta']} | "
            f"{item['confirmed_reduce_drawdown_delta']} | {worth['review_only']} | "
            f"{worth['reduce_if_next_day_weak']} | {worth['reduce_if_break_position_rule']} | "
            f"{worth['reduce_if_leader_broken']} | {worth['reduce_if_sector_falling']} | "
            f"{worth['do_not_reduce']} |"
        )
    lines.extend(["", "## Reasoning", ""])
    for item in replay["items"]:
        lines.append(f"- {item['date']}: {item['reason']}")
    return "\n".join(lines)


def update_summary(summary: dict[str, Any], replay: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(summary)
    for key in [
        "confirmed_reduce_replay_enabled",
        "confirmed_reduce_replay_count",
        "review_only_recommended_count",
        "confirmed_reduce_candidate_count",
        "do_not_reduce_count",
        "reduce_if_next_day_weak_count",
        "reduce_if_break_position_rule_count",
        "reduce_if_leader_broken_count",
        "reduce_if_sector_falling_count",
        "recommended_rule_change_now",
        "recommended_next_step",
    ]:
        updated[key] = replay[key]
    updated["confirmed_reduce_shadow_scenario_replay_report"] = {
        "json": str(OUTPUT_JSON),
        "markdown": str(OUTPUT_MD),
        "count": replay["confirmed_reduce_replay_count"],
    }
    return updated


def update_summary_markdown(replay: dict[str, Any]) -> None:
    existing = SUMMARY_MD.read_text(encoding="utf-8") if SUMMARY_MD.exists() else ""
    marker = "## Confirmed-reduce shadow scenario replay"
    if marker in existing:
        existing = existing.split(marker)[0].rstrip()
    section = [
        marker,
        "",
        f"- confirmed_reduce_replay_enabled: {replay['confirmed_reduce_replay_enabled']}",
        f"- confirmed_reduce_replay_count: {replay['confirmed_reduce_replay_count']}",
        f"- review_only_recommended_count: {replay['review_only_recommended_count']}",
        f"- confirmed_reduce_candidate_count: {replay['confirmed_reduce_candidate_count']}",
        f"- do_not_reduce_count: {replay['do_not_reduce_count']}",
        f"- reduce_if_next_day_weak_count: {replay['reduce_if_next_day_weak_count']}",
        f"- reduce_if_break_position_rule_count: {replay['reduce_if_break_position_rule_count']}",
        f"- reduce_if_leader_broken_count: {replay['reduce_if_leader_broken_count']}",
        f"- reduce_if_sector_falling_count: {replay['reduce_if_sector_falling_count']}",
        f"- recommended_rule_change_now: {replay['recommended_rule_change_now']}",
        f"- recommended_next_step: {replay['recommended_next_step']}",
        "",
        "| date | review_only | next_day_weak | break_position_rule | leader_broken | sector_falling | do_not_reduce | confirmed_reduce_effect |",
        "| -- | -- | -- | -- | -- | -- | -- | -- |",
    ]
    for item in replay["items"]:
        worth = item["worth_actual_reduce"]
        section.append(
            f"| {item['date']} | {worth['review_only']} | {worth['reduce_if_next_day_weak']} | "
            f"{worth['reduce_if_break_position_rule']} | {worth['reduce_if_leader_broken']} | "
            f"{worth['reduce_if_sector_falling']} | {worth['do_not_reduce']} | {item['confirmed_reduce_effect']} |"
        )
    content = existing.rstrip()
    if content:
        content += "\n\n"
    content += "\n".join(section) + "\n"
    SUMMARY_MD.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build confirmed-reduce shadow scenario replay")
    parser.add_argument("--summary-json", default=str(SUMMARY_JSON))
    args = parser.parse_args()

    summary_path = Path(args.summary_json)
    if not summary_path.is_absolute():
        summary_path = ROOT / summary_path

    replay = build_replay()
    summary = read_json(summary_path)
    updated_summary = update_summary(summary, replay)

    write_json(OUTPUT_JSON, replay)
    OUTPUT_MD.write_text(build_markdown(replay), encoding="utf-8")
    write_json(summary_path, updated_summary)
    update_summary_markdown(replay)
    print(
        json.dumps(
            {
                "output_json": str(OUTPUT_JSON),
                "output_md": str(OUTPUT_MD),
                "confirmed_reduce_replay_count": replay["confirmed_reduce_replay_count"],
                "recommended_rule_change_now": replay["recommended_rule_change_now"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
