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
SHADOW_LOGGING_JSON = REPORT_DIR / "dual_track_shadow_logging.json"
OUTPUT_JSON = REPORT_DIR / "dual_track_shadow_pnl_estimate.json"
OUTPUT_MD = REPORT_DIR / "dual_track_shadow_pnl_estimate.md"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def path_stem(path_id: str) -> str:
    return path_id.replace("-", "_")


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def load_path_payload(path_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stem = path_stem(path_id)
    decisions = read_json(REPORT_DIR / f"{stem}_decisions.json").get("decisions", [])
    execution_log = read_json(REPORT_DIR / f"{stem}_execution_log.json").get("execution_log", [])
    equity_curve = read_json(REPORT_DIR / f"{stem}_execution_log.json").get("equity_curve", [])
    return decisions, execution_log, equity_curve


def build_path_cache(path_id: str) -> dict[str, Any]:
    decisions, execution_log, equity_curve = load_path_payload(path_id)
    decisions_by_date = {item.get("date"): item for item in decisions}
    equity_by_date = {item.get("date"): item for item in equity_curve}
    return {
        "decisions": decisions,
        "execution_log": execution_log,
        "equity_curve": equity_curve,
        "decisions_by_date": decisions_by_date,
        "equity_by_date": equity_by_date,
    }


def find_trade_after(
    execution_log: list[dict[str, Any]],
    *,
    ts_code: str,
    action: str,
    min_date: str,
    max_date: str | None = None,
) -> dict[str, Any] | None:
    for item in execution_log:
        if item.get("ts_code") != ts_code:
            continue
        if item.get("action") != action:
            continue
        if str(item.get("date")) <= str(min_date):
            continue
        if max_date is not None and str(item.get("date")) > str(max_date):
            continue
        return item
    return None


def find_next_exit_after(
    execution_log: list[dict[str, Any]],
    *,
    ts_code: str,
    min_date: str,
) -> dict[str, Any] | None:
    for item in execution_log:
        if item.get("ts_code") != ts_code:
            continue
        if item.get("action") not in {"SELL", "REDUCE"}:
            continue
        if str(item.get("date")) < str(min_date):
            continue
        return item
    return None


def extract_position_timeline(
    decisions: list[dict[str, Any]],
    *,
    ts_code: str,
    start_date: str,
) -> list[dict[str, Any]]:
    timeline = []
    for decision in decisions:
        if str(decision.get("date")) < str(start_date):
            continue
        position_after = decision.get("position_after_action") or {}
        if position_after.get("ts_code") != ts_code:
            continue
        shares = position_after.get("shares")
        market_value = position_after.get("market_value")
        if not shares or market_value is None:
            continue
        timeline.append(
            {
                "date": decision.get("date"),
                "shares": shares,
                "market_value": float(market_value),
                "price": float(market_value) / float(shares) if shares else None,
            }
        )
    return timeline


def classify_buy_effect(realized_pnl: float | None) -> str:
    if realized_pnl is None:
        return "unknown"
    if realized_pnl < 0:
        return "avoided_loss"
    if realized_pnl > 0:
        return "missed_gain"
    return "neutral"


def make_buy_estimate(
    change: dict[str, Any],
    cache: dict[str, Any],
    *,
    next_change_date: str | None,
) -> dict[str, Any]:
    ts_code = change.get("code")
    date = change.get("date")
    execution_log = cache["execution_log"]
    decisions = cache["decisions"]
    equity_at_change = (cache["equity_by_date"].get(date) or {}).get("equity")
    buy_trade = find_trade_after(
        execution_log,
        ts_code=ts_code,
        action="BUY",
        min_date=date,
        max_date=next_change_date,
    )

    base = {
        "path": change.get("path"),
        "date": date,
        "ts_code": ts_code,
        "name": change.get("name"),
        "original_action": change.get("original_action"),
        "shadow_action": change.get("shadow_action"),
        "change_reason": change.get("veto_reason"),
        "confidence_level": "LOW",
        "estimate_method": "buy_path_follow_through_from_real_execution_log",
        "estimate_limitations": "shadow estimate only; does not rewrite real execution or real pnl",
    }
    if not buy_trade:
        return {
            **base,
            "original_trade_after_change": "no_real_buy_found_after_change",
            "original_outcome_after_change": "insufficient_trade_data",
            "estimated_shadow_effect_type": "unknown",
            "estimated_return_delta": None,
            "estimated_drawdown_delta": None,
        }

    shares = float(buy_trade.get("shares") or 0)
    buy_price = float(buy_trade.get("price") or 0)
    entry_value = shares * buy_price if shares and buy_price else None
    timeline = extract_position_timeline(decisions, ts_code=ts_code, start_date=buy_trade.get("date"))
    exit_trade = find_next_exit_after(execution_log, ts_code=ts_code, min_date=buy_trade.get("date"))

    realized_pnl = None
    realized_return_pct = None
    original_outcome_after_change = "unknown"
    original_trade_after_change = f"BUY@{buy_trade.get('date')} price={buy_price} shares={int(shares)}"
    exit_price = None
    if exit_trade and entry_value:
        exit_price = float(exit_trade.get("price") or 0)
        realized_pnl = (exit_price - buy_price) * shares
        realized_return_pct = (exit_price / buy_price - 1) * 100 if buy_price else None
        original_trade_after_change += f" -> {exit_trade.get('action')}@{exit_trade.get('date')} price={exit_price}"
        original_outcome_after_change = (
            f"realized_trade_return_pct={round_or_none(realized_return_pct, 2)} "
            f"pnl_value={round_or_none(realized_pnl, 2)}"
        )
    elif timeline and entry_value:
        end_mark = timeline[-1]
        exit_price = float(end_mark["price"] or 0)
        realized_pnl = (exit_price - buy_price) * shares
        realized_return_pct = (exit_price / buy_price - 1) * 100 if buy_price else None
        original_trade_after_change += f" -> mark_to_path_end@{end_mark['date']} price={round_or_none(exit_price, 4)}"
        original_outcome_after_change = (
            f"mark_to_path_end_return_pct={round_or_none(realized_return_pct, 2)} "
            f"pnl_value={round_or_none(realized_pnl, 2)}"
        )

    min_value = min((item["market_value"] for item in timeline), default=entry_value)
    adverse_value = None
    if entry_value is not None and min_value is not None:
        adverse_value = max(0.0, entry_value - min_value)
    estimated_return_delta = None
    estimated_drawdown_delta = None
    if realized_pnl is not None and equity_at_change:
        estimated_return_delta = (-realized_pnl / float(equity_at_change)) * 100
    if adverse_value is not None and equity_at_change:
        estimated_drawdown_delta = (adverse_value / float(equity_at_change)) * 100

    effect_type = classify_buy_effect(realized_pnl)
    confidence_level = "HIGH" if exit_trade else "MEDIUM" if timeline else "LOW"
    limitations = "shadow estimate only; based on real buy follow-through and path-end mark when no explicit exit exists"
    return {
        **base,
        "original_trade_after_change": original_trade_after_change,
        "original_outcome_after_change": original_outcome_after_change,
        "estimated_shadow_effect_type": effect_type,
        "estimated_return_delta": round_or_none(estimated_return_delta, 4),
        "estimated_drawdown_delta": round_or_none(estimated_drawdown_delta, 4),
        "confidence_level": confidence_level,
        "estimate_method": "real_buy_then_real_exit_or_path_end_mark",
        "estimate_limitations": limitations,
    }


def classify_confirmed_reduce_effect(return_delta: float | None, drawdown_delta: float | None) -> str:
    if return_delta is None:
        return "unknown"
    if return_delta > 0:
        return "avoided_loss"
    if return_delta < 0:
        return "reduced_drawdown" if (drawdown_delta or 0) > 0 else "missed_gain"
    if (drawdown_delta or 0) > 0:
        return "reduced_drawdown"
    return "neutral"


def make_hold_review_estimate(change: dict[str, Any], cache: dict[str, Any]) -> dict[str, Any]:
    ts_code = change.get("code")
    date = change.get("date")
    decisions_by_date = cache["decisions_by_date"]
    decision = decisions_by_date.get(date) or {}
    equity_at_change = (cache["equity_by_date"].get(date) or {}).get("equity")
    position_after = decision.get("position_after_action") or {}
    shares = float(position_after.get("shares") or 0)
    market_value = float(position_after.get("market_value") or 0)
    current_price = market_value / shares if shares else None
    timeline = extract_position_timeline(cache["decisions"], ts_code=ts_code, start_date=date)

    base = {
        "path": change.get("path"),
        "date": date,
        "ts_code": ts_code,
        "name": change.get("name"),
        "original_action": change.get("original_action"),
        "shadow_action": change.get("shadow_action"),
        "change_reason": change.get("veto_reason"),
        "confidence_level": "MEDIUM",
        "estimate_method": "review_only_plus_half_reduce_if_confirmed_shadow_scenario",
        "estimate_limitations": (
            "review_only is the primary estimate; confirmed-reduce branch is a shadow risk scenario only "
            "and is not a real trade result"
        ),
    }
    if not timeline or not shares or not current_price:
        return {
            **base,
            "original_trade_after_change": "hold_path_found_but_insufficient_position_trace",
            "original_outcome_after_change": "insufficient_hold_trace_data",
            "estimated_shadow_effect_type": "unknown",
            "estimated_return_delta": None,
            "estimated_drawdown_delta": None,
            "review_only_estimate": {
                "estimated_shadow_effect_type": "unknown",
                "estimated_return_delta": None,
                "estimated_drawdown_delta": None,
            },
            "risk_reduce_if_confirmed_estimate": {
                "assumed_reduce_ratio": 0.5,
                "estimated_shadow_effect_type": "unknown",
                "estimated_return_delta": None,
                "estimated_drawdown_delta": None,
            },
        }

    end_price = timeline[-1]["price"]
    min_price = min(item["price"] for item in timeline if item.get("price") is not None)
    assumed_reduce_ratio = 0.5
    reduced_shares = shares * assumed_reduce_ratio
    foregone_pnl_value = (float(end_price) - float(current_price)) * reduced_shares
    adverse_avoided_value = max(0.0, (float(current_price) - float(min_price)) * reduced_shares)
    confirmed_return_delta = None
    confirmed_drawdown_delta = None
    if equity_at_change:
        confirmed_return_delta = (-foregone_pnl_value / float(equity_at_change)) * 100
        confirmed_drawdown_delta = (adverse_avoided_value / float(equity_at_change)) * 100

    return {
        **base,
        "original_trade_after_change": (
            f"hold_trace_from_{date}_to_{timeline[-1]['date']} shares={int(shares)} "
            f"current_price={round_or_none(current_price, 4)} end_price={round_or_none(end_price, 4)}"
        ),
        "original_outcome_after_change": (
            f"hold_review_only_keeps_real_path; path_end_price={round_or_none(end_price, 4)} "
            f"future_min_price={round_or_none(min_price, 4)}"
        ),
        "estimated_shadow_effect_type": "neutral",
        "estimated_return_delta": 0.0,
        "estimated_drawdown_delta": 0.0,
        "review_only_estimate": {
            "estimated_shadow_effect_type": "neutral",
            "estimated_return_delta": 0.0,
            "estimated_drawdown_delta": 0.0,
        },
        "risk_reduce_if_confirmed_estimate": {
            "assumed_reduce_ratio": assumed_reduce_ratio,
            "estimated_shadow_effect_type": classify_confirmed_reduce_effect(
                confirmed_return_delta, confirmed_drawdown_delta
            ),
            "estimated_return_delta": round_or_none(confirmed_return_delta, 4),
            "estimated_drawdown_delta": round_or_none(confirmed_drawdown_delta, 4),
            "scenario_note": "half position risk reduction at change-date mark, for shadow-only risk review",
        },
    }


def build_estimates(logging: dict[str, Any]) -> dict[str, Any]:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path_cache: dict[str, dict[str, Any]] = {}
    estimates = []
    change_points_by_path: dict[str, list[dict[str, Any]]] = {}
    for change in logging.get("shadow_change_points", []):
        change_points_by_path.setdefault(change.get("path"), []).append(change)
    for path_changes in change_points_by_path.values():
        path_changes.sort(key=lambda item: str(item.get("date")))

    for change in logging.get("shadow_change_points", []):
        path_id = change.get("path")
        if path_id not in path_cache:
            path_cache[path_id] = build_path_cache(path_id)
        cache = path_cache[path_id]
        path_changes = change_points_by_path.get(path_id, [])
        next_change_date = None
        for idx, item in enumerate(path_changes):
            if item.get("date") == change.get("date") and item.get("code") == change.get("code"):
                if idx + 1 < len(path_changes):
                    next_change_date = path_changes[idx + 1].get("date")
                break
        if change.get("original_action") == "BUY" and change.get("shadow_action") == "OBSERVE":
            estimates.append(make_buy_estimate(change, cache, next_change_date=next_change_date))
        elif change.get("original_action") == "HOLD" and change.get("shadow_action") == "NEEDS_HUMAN_REVIEW":
            estimates.append(make_hold_review_estimate(change, cache))
        else:
            estimates.append(
                {
                    "path": change.get("path"),
                    "date": change.get("date"),
                    "ts_code": change.get("code"),
                    "name": change.get("name"),
                    "original_action": change.get("original_action"),
                    "shadow_action": change.get("shadow_action"),
                    "change_reason": change.get("veto_reason"),
                    "original_trade_after_change": "unsupported_change_type_for_this_round",
                    "original_outcome_after_change": "unsupported_change_type_for_this_round",
                    "estimated_shadow_effect_type": "unknown",
                    "estimated_return_delta": None,
                    "estimated_drawdown_delta": None,
                    "confidence_level": "LOW",
                    "estimate_method": "unsupported_change_type_for_this_round",
                    "estimate_limitations": "this round only estimates BUY->OBSERVE and HOLD->NEEDS_HUMAN_REVIEW",
                }
            )

    counts = {
        "avoided_loss": sum(1 for item in estimates if item.get("estimated_shadow_effect_type") == "avoided_loss"),
        "missed_gain": sum(1 for item in estimates if item.get("estimated_shadow_effect_type") == "missed_gain"),
        "reduced_drawdown": sum(
            1 for item in estimates if item.get("estimated_shadow_effect_type") == "reduced_drawdown"
        ),
        "neutral": sum(1 for item in estimates if item.get("estimated_shadow_effect_type") == "neutral"),
        "unknown": sum(1 for item in estimates if item.get("estimated_shadow_effect_type") == "unknown"),
    }
    estimated_total_return_delta = sum(float(item["estimated_return_delta"] or 0.0) for item in estimates)
    estimated_total_drawdown_delta = sum(float(item["estimated_drawdown_delta"] or 0.0) for item in estimates)
    confidence_summary = {
        "HIGH": sum(1 for item in estimates if item.get("confidence_level") == "HIGH"),
        "MEDIUM": sum(1 for item in estimates if item.get("confidence_level") == "MEDIUM"),
        "LOW": sum(1 for item in estimates if item.get("confidence_level") == "LOW"),
    }

    buy_summary = {
        "count": sum(1 for item in estimates if item.get("original_action") == "BUY"),
        "avoided_loss_count": sum(
            1
            for item in estimates
            if item.get("original_action") == "BUY"
            and item.get("estimated_shadow_effect_type") == "avoided_loss"
        ),
        "missed_gain_count": sum(
            1
            for item in estimates
            if item.get("original_action") == "BUY"
            and item.get("estimated_shadow_effect_type") == "missed_gain"
        ),
        "unknown_count": sum(
            1
            for item in estimates
            if item.get("original_action") == "BUY"
            and item.get("estimated_shadow_effect_type") == "unknown"
        ),
    }
    hold_summary = {
        "count": sum(1 for item in estimates if item.get("original_action") == "HOLD"),
        "review_only_neutral_count": sum(
            1
            for item in estimates
            if item.get("original_action") == "HOLD"
            and item.get("estimated_shadow_effect_type") == "neutral"
        ),
        "risk_reduce_if_confirmed_effect_counts": {
            "avoided_loss": sum(
                1
                for item in estimates
                if (item.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_shadow_effect_type")
                == "avoided_loss"
            ),
            "missed_gain": sum(
                1
                for item in estimates
                if (item.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_shadow_effect_type")
                == "missed_gain"
            ),
            "reduced_drawdown": sum(
                1
                for item in estimates
                if (item.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_shadow_effect_type")
                == "reduced_drawdown"
            ),
            "neutral": sum(
                1
                for item in estimates
                if (item.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_shadow_effect_type")
                == "neutral"
            ),
            "unknown": sum(
                1
                for item in estimates
                if (item.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_shadow_effect_type")
                == "unknown"
            ),
        },
        "risk_reduce_if_confirmed_total_return_delta": round_or_none(
            sum(
                float((item.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_return_delta") or 0.0)
                for item in estimates
            ),
            4,
        ),
        "risk_reduce_if_confirmed_total_drawdown_delta": round_or_none(
            sum(
                float((item.get("risk_reduce_if_confirmed_estimate") or {}).get("estimated_drawdown_delta") or 0.0)
                for item in estimates
            ),
            4,
        ),
    }
    invariant_ok = (
        logging.get("dual_track_invariant_ok", False)
        and len(estimates) == 10
        and all(item.get("shadow_action") != "SELL" for item in estimates if item.get("original_action") == "HOLD")
    )
    return {
        "generated_at": generated_at,
        "shadow_pnl_estimate_enabled": True,
        "shadow_pnl_invariant_ok": invariant_ok,
        "scope": "shadow_pnl_estimate_for_10_shadow_change_points_only",
        "boundaries": {
            "real_execution_log_changed": False,
            "real_trade_action_changed": False,
            "real_return_calculation_changed": False,
            "validation_private_used_for_daily_decision": False,
            "full_pipeline_selection_walk_forward": False,
            "core_trading_rule_changed": False,
        },
        "change_point_count": len(estimates),
        "estimates": estimates,
        "estimated_avoided_loss_count": counts["avoided_loss"],
        "estimated_missed_gain_count": counts["missed_gain"],
        "estimated_reduced_drawdown_count": counts["reduced_drawdown"],
        "estimated_neutral_count": counts["neutral"],
        "estimated_unknown_count": counts["unknown"],
        "buy_to_observe_estimate_summary": buy_summary,
        "hold_to_review_estimate_summary": hold_summary,
        "estimated_total_return_delta": round_or_none(estimated_total_return_delta, 4),
        "estimated_total_drawdown_delta": round_or_none(estimated_total_drawdown_delta, 4),
        "estimate_confidence_summary": confidence_summary,
        "estimate_limitations": [
            "all outputs are shadow estimates only and do not rewrite real pnl",
            "BUY->OBSERVE uses real buy follow-through and path-end mark if no explicit exit exists",
            "HOLD->NEEDS_HUMAN_REVIEW keeps review_only as primary estimate and uses a half-reduce scenario only as a shadow branch",
            "account-level deltas are approximate and based on path equity at the change date",
        ],
        "recommended_next_step": (
            "if needed, build a separate shadow scenario replay for hold-to-review confirmed-reduce variants, still isolated from real pnl"
        ),
    }


def build_markdown(estimate: dict[str, Any]) -> str:
    lines = [
        "# dual_track_shadow_pnl_estimate",
        "",
        f"- generated_at: {estimate['generated_at']}",
        f"- shadow_pnl_estimate_enabled: {estimate['shadow_pnl_estimate_enabled']}",
        f"- shadow_pnl_invariant_ok: {estimate['shadow_pnl_invariant_ok']}",
        f"- change_point_count: {estimate['change_point_count']}",
        f"- estimated_avoided_loss_count: {estimate['estimated_avoided_loss_count']}",
        f"- estimated_missed_gain_count: {estimate['estimated_missed_gain_count']}",
        f"- estimated_reduced_drawdown_count: {estimate['estimated_reduced_drawdown_count']}",
        f"- estimated_neutral_count: {estimate['estimated_neutral_count']}",
        f"- estimated_unknown_count: {estimate['estimated_unknown_count']}",
        f"- estimated_total_return_delta: {estimate['estimated_total_return_delta']}",
        f"- estimated_total_drawdown_delta: {estimate['estimated_total_drawdown_delta']}",
        f"- estimate_confidence_summary: {estimate['estimate_confidence_summary']}",
        "",
        "## 10 Estimates",
        "",
        "| path | date | ts_code | name | original_action | shadow_action | effect_type | return_delta | drawdown_delta | confidence | method |",
        "| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |",
    ]
    for item in estimate["estimates"]:
        lines.append(
            f"| {item['path']} | {item['date']} | {item.get('ts_code')} | {item.get('name')} | "
            f"{item['original_action']} | {item['shadow_action']} | {item['estimated_shadow_effect_type']} | "
            f"{item['estimated_return_delta']} | {item['estimated_drawdown_delta']} | "
            f"{item['confidence_level']} | {item['estimate_method']} |"
        )
    lines.extend(
        [
            "",
            "## Hold Review Shadow Branch",
            "",
            "| path | date | review_only_effect | confirmed_reduce_effect | confirmed_reduce_return_delta | confirmed_reduce_drawdown_delta |",
            "| -- | -- | -- | -- | -- | -- |",
        ]
    )
    for item in estimate["estimates"]:
        if item["original_action"] != "HOLD":
            continue
        confirmed = item.get("risk_reduce_if_confirmed_estimate") or {}
        review_only = item.get("review_only_estimate") or {}
        lines.append(
            f"| {item['path']} | {item['date']} | {review_only.get('estimated_shadow_effect_type')} | "
            f"{confirmed.get('estimated_shadow_effect_type')} | {confirmed.get('estimated_return_delta')} | "
            f"{confirmed.get('estimated_drawdown_delta')} |"
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
        ]
    )
    for item in estimate["estimate_limitations"]:
        lines.append(f"- {item}")
    return "\n".join(lines)


def update_summary(summary: dict[str, Any], estimate: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(summary)
    updated["shadow_pnl_estimate_enabled"] = estimate["shadow_pnl_estimate_enabled"]
    updated["shadow_pnl_invariant_ok"] = estimate["shadow_pnl_invariant_ok"]
    updated["estimated_avoided_loss_count"] = estimate["estimated_avoided_loss_count"]
    updated["estimated_missed_gain_count"] = estimate["estimated_missed_gain_count"]
    updated["estimated_reduced_drawdown_count"] = estimate["estimated_reduced_drawdown_count"]
    updated["estimated_neutral_count"] = estimate["estimated_neutral_count"]
    updated["estimated_unknown_count"] = estimate["estimated_unknown_count"]
    updated["buy_to_observe_estimate_summary"] = estimate["buy_to_observe_estimate_summary"]
    updated["hold_to_review_estimate_summary"] = estimate["hold_to_review_estimate_summary"]
    updated["estimated_total_return_delta"] = estimate["estimated_total_return_delta"]
    updated["estimated_total_drawdown_delta"] = estimate["estimated_total_drawdown_delta"]
    updated["estimate_confidence_summary"] = estimate["estimate_confidence_summary"]
    updated["estimate_limitations"] = estimate["estimate_limitations"]
    updated["recommended_next_step"] = estimate["recommended_next_step"]
    updated["dual_track_shadow_pnl_estimate_report"] = {
        "json": str(OUTPUT_JSON),
        "markdown": str(OUTPUT_MD),
        "change_point_count": estimate["change_point_count"],
    }
    return updated


def update_summary_markdown(estimate: dict[str, Any]) -> None:
    existing = SUMMARY_MD.read_text(encoding="utf-8") if SUMMARY_MD.exists() else ""
    marker = "## Dual-track shadow pnl estimate"
    if marker in existing:
        existing = existing.split(marker)[0].rstrip()
    section = [
        marker,
        "",
        f"- shadow_pnl_estimate_enabled: {estimate['shadow_pnl_estimate_enabled']}",
        f"- shadow_pnl_invariant_ok: {estimate['shadow_pnl_invariant_ok']}",
        f"- estimated_avoided_loss_count: {estimate['estimated_avoided_loss_count']}",
        f"- estimated_missed_gain_count: {estimate['estimated_missed_gain_count']}",
        f"- estimated_reduced_drawdown_count: {estimate['estimated_reduced_drawdown_count']}",
        f"- estimated_neutral_count: {estimate['estimated_neutral_count']}",
        f"- estimated_unknown_count: {estimate['estimated_unknown_count']}",
        f"- buy_to_observe_estimate_summary: {estimate['buy_to_observe_estimate_summary']}",
        f"- hold_to_review_estimate_summary: {estimate['hold_to_review_estimate_summary']}",
        f"- estimated_total_return_delta: {estimate['estimated_total_return_delta']}",
        f"- estimated_total_drawdown_delta: {estimate['estimated_total_drawdown_delta']}",
        f"- estimate_confidence_summary: {estimate['estimate_confidence_summary']}",
        f"- estimate_limitations: {estimate['estimate_limitations']}",
        f"- recommended_next_step: {estimate['recommended_next_step']}",
        "",
        "### 10 estimate points",
        "",
        "| path | date | ts_code | original_action | shadow_action | effect_type | return_delta | drawdown_delta | confidence |",
        "| -- | -- | -- | -- | -- | -- | -- | -- | -- |",
    ]
    for item in estimate["estimates"]:
        section.append(
            f"| {item['path']} | {item['date']} | {item.get('ts_code')} | {item['original_action']} | "
            f"{item['shadow_action']} | {item['estimated_shadow_effect_type']} | "
            f"{item['estimated_return_delta']} | {item['estimated_drawdown_delta']} | {item['confidence_level']} |"
        )
    content = existing.rstrip()
    if content:
        content += "\n\n"
    content += "\n".join(section) + "\n"
    SUMMARY_MD.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build shadow pnl estimate for 10 dual-track change points")
    parser.add_argument("--summary-json", default=str(SUMMARY_JSON))
    parser.add_argument("--shadow-logging-json", default=str(SHADOW_LOGGING_JSON))
    args = parser.parse_args()

    summary_path = Path(args.summary_json)
    if not summary_path.is_absolute():
        summary_path = ROOT / summary_path
    logging_path = Path(args.shadow_logging_json)
    if not logging_path.is_absolute():
        logging_path = ROOT / logging_path

    summary = read_json(summary_path)
    logging = read_json(logging_path)
    estimate = build_estimates(logging)
    updated_summary = update_summary(summary, estimate)

    write_json(OUTPUT_JSON, estimate)
    OUTPUT_MD.write_text(build_markdown(estimate), encoding="utf-8")
    write_json(summary_path, updated_summary)
    update_summary_markdown(estimate)
    print(
        json.dumps(
            {
                "output_json": str(OUTPUT_JSON),
                "output_md": str(OUTPUT_MD),
                "shadow_pnl_invariant_ok": estimate["shadow_pnl_invariant_ok"],
                "change_point_count": estimate["change_point_count"],
                "estimated_total_return_delta": estimate["estimated_total_return_delta"],
                "estimated_total_drawdown_delta": estimate["estimated_total_drawdown_delta"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
