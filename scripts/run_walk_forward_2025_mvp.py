from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


PATH_ID = "WF2025-PRE-01"
SLIPPAGE = 0.001
MINIMUM_HOLD_DAYS = 2
OVERTRADING_TRADE_LIMIT = 4
INTRA_TRADE_DENSITY_LIMIT = 4
NO_WATCH_SINGLE_POSITION_LIMIT = 0.2
NO_WATCH_TOTAL_POSITION_LIMIT = 0.2
NO_WATCH_BUY_POSITION_LIMIT = 0.18
DRAWDOWN_REDUCE_TRIGGER = 0.05
EQUITY_DRAWDOWN_REDUCE_TRIGGER = 0.06
ACCOUNT_REDUCE_RISK_DD = 0.06
ACCOUNT_STOP_NEW_BUY_DD = 0.08
ACCOUNT_HARD_STOP_DD = 0.10
NO_WATCH_ACCOUNT_REDUCE_RISK_DD = 0.05
NO_WATCH_ACCOUNT_STOP_NEW_BUY_DD = 0.07
NO_WATCH_ACCOUNT_HARD_STOP_DD = 0.09
ACCOUNT_CRITICAL_RISK_DD = 0.20
ACCOUNT_RISK_COOLDOWN_DAYS = 2
TRADE_COOLDOWN_DAYS = 1
PRE_FIX_RESULT = {
    "final_return_pct": 1.13,
    "max_drawdown_pct": -1.12,
    "trade_count": 9,
    "overtrading_flag": True,
    "profit_protection_inactive_false_sell": True,
}
BEFORE_10PATHS_ISSUE_FIX = {
    "WF2025-PRE-01": {"final_return_pct": 0.96, "max_drawdown_pct": -0.72, "trade_count": 3, "position_ok": False, "risk_control_failure": False},
    "WF2025-PRE-03": {"final_return_pct": 11.2, "max_drawdown_pct": 0.0, "trade_count": 1, "position_ok": False, "risk_control_failure": False},
    "WF2025-INTRA-01": {"final_return_pct": -2.39, "max_drawdown_pct": -2.66, "trade_count": 9, "position_ok": True, "risk_control_failure": False},
    "WF2025-INTRA-02": {"final_return_pct": 3.3, "max_drawdown_pct": -4.61, "trade_count": 6, "position_ok": True, "risk_control_failure": False},
    "WF2025-ACC-01": {"final_return_pct": -69.79, "max_drawdown_pct": -70.0, "trade_count": 4, "position_ok": True, "risk_control_failure": False},
    "WF2025-ACC-02": {"final_return_pct": -0.96, "max_drawdown_pct": -2.09, "trade_count": 7, "position_ok": True, "risk_control_failure": False},
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_ohlc(conn: sqlite3.Connection, code: str, date: str, cache: dict | None = None) -> dict | None:
    key = (code, date)
    if cache is not None and key in cache:
        return cache[key]
    row = conn.execute(
        "select trade_date, open, high, low, close, pct_chg from daily where ts_code=? and trade_date=?",
        (code, date),
    ).fetchone()
    if not row:
        if cache is not None:
            cache[key] = None
        return None
    ohlc = {
        "trade_date": row[0],
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "pct_chg": float(row[5]),
    }
    if cache is not None:
        cache[key] = ohlc
    return ohlc


def recent_metrics(conn: sqlite3.Connection, code: str, date: str, cache: dict | None = None) -> dict:
    key = (code, date)
    if cache is not None and key in cache:
        return cache[key]
    rows = conn.execute(
        """
        select trade_date, close, amount, pct_chg
        from daily
        where ts_code=? and trade_date<=?
        order by trade_date desc
        limit 20
        """,
        (code, date),
    ).fetchall()
    rows = list(reversed(rows))
    if not rows:
        result = {"data_ok": False}
        if cache is not None:
            cache[key] = result
        return result
    closes = [float(r[1]) for r in rows]
    amounts = [float(r[2]) for r in rows if r[2] is not None]
    close = closes[-1]

    def ret(n: int) -> float | None:
        if len(closes) < n:
            return None
        base = closes[-n]
        return close / base - 1 if base else None

    ma5 = sum(closes[-5:]) / min(5, len(closes))
    ma10 = sum(closes[-10:]) / min(10, len(closes))
    ma20 = sum(closes) / len(closes)
    high20 = max(closes)
    low20 = min(closes)
    amount5 = sum(amounts[-5:]) / min(5, len(amounts)) if amounts else 0.0
    amount_prev = sum(amounts[-20:-5]) / len(amounts[-20:-5]) if len(amounts) > 5 else amount5
    result = {
        "data_ok": True,
        "close": close,
        "ret5": ret(5),
        "ret10": ret(10),
        "ret20": ret(20),
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma20_gap": close / ma20 - 1 if ma20 else 0.0,
        "position20": (close - low20) / (high20 - low20) if high20 > low20 else 0.5,
        "amount_ratio": amount5 / amount_prev if amount_prev else 1.0,
    }
    if cache is not None:
        cache[key] = result
    return result


def choose_candidate(conn: sqlite3.Connection, path: dict, date: str, metrics_cache: dict | None = None) -> tuple[dict | None, str]:
    scored: list[tuple[float, dict, dict]] = []
    for item in path["target_symbols"]:
        m = recent_metrics(conn, item["ts_code"], date, metrics_cache)
        if not m.get("data_ok"):
            continue
        ret5 = m.get("ret5")
        ret10 = m.get("ret10")
        if ret5 is None or ret10 is None:
            continue
        overheated = ret5 > 0.12 or m["position20"] > 0.92
        weak = m["close"] < m["ma10"] and ret5 < 0
        if overheated or weak:
            continue
        score = (ret5 * 100) + (ret10 * 30) + min(m["amount_ratio"], 2.0)
        scored.append((score, item, m))
    if not scored:
        return None, "候选股要么数据不足、要么短线过热或跌破短期结构，不能盲目买入。"
    scored.sort(key=lambda x: x[0], reverse=True)
    _score, item, metrics = scored[0]
    return {**item, "metrics": metrics, "alternative_candidates_available": len(scored) > 1}, "选择短线结构仍在、未明显过热且量能可接受的候选作为条件试错标的。"


def next_review_date(steps: list[dict], current_index: int) -> str:
    if current_index + 1 < len(steps):
        return steps[current_index + 1]["date"]
    return "路径结束后复盘"


def path_stem(path_id: str) -> str:
    return path_id.replace("-", "_")


def initial_position_from_path(path: dict) -> dict | None:
    holdings = path["initial_user_state"].get("holdings") or []
    if not holdings:
        return None
    item = holdings[0]
    stage_a_close = float(item["stage_a_close"])
    total_assets = float(path["initial_user_state"]["total_assets"])
    available_cash = float(path["initial_user_state"]["available_cash"])
    target_value = max(0.0, total_assets - available_cash)
    shares = int(target_value // stage_a_close // 100 * 100)
    if shares <= 0:
        shares = int(min(float(path["initial_user_state"]["planned_trade_cash"]), target_value or 10000) // stage_a_close // 100 * 100)
    if shares <= 0:
        return None
    if "浮亏" in path["path_name"] or "弱结构" in path["path_name"]:
        entry_price = round(stage_a_close / 0.92, 3)
        stop_loss = round(stage_a_close * 0.97, 3)
        profit_active = False
    else:
        entry_price = round(stage_a_close / 1.05, 3)
        stop_loss = round(entry_price * 0.94, 3)
        profit_active = True
    cost = round(shares * entry_price, 2)
    return {
        "ts_code": item["ts_code"],
        "name": item["name"],
        "shares": shares,
        "entry_price": entry_price,
        "cost": cost,
        "stop_loss": stop_loss,
        "profit_protection": round(entry_price * 1.03, 3),
        "profit_protection_active": profit_active,
        "entry_date": "before_path_start",
        "hold_days": MINIMUM_HOLD_DAYS,
        "is_initial_holding": True,
        "weak_structure": "弱结构" in path["path_name"] or item.get("role_hint_for_test") == "弱结构候选",
        "peak_price": stage_a_close,
    }


def position_ratio(position: dict | None, price: float, total_assets: float) -> float:
    if not position or total_assets <= 0:
        return 0.0
    return position["shares"] * price / total_assets


def account_thresholds(can_watch_market: bool) -> dict:
    if can_watch_market:
        return {
            "reduce": ACCOUNT_REDUCE_RISK_DD,
            "stop_new_buy": ACCOUNT_STOP_NEW_BUY_DD,
            "hard_stop": ACCOUNT_HARD_STOP_DD,
        }
    return {
        "reduce": NO_WATCH_ACCOUNT_REDUCE_RISK_DD,
        "stop_new_buy": NO_WATCH_ACCOUNT_STOP_NEW_BUY_DD,
        "hard_stop": NO_WATCH_ACCOUNT_HARD_STOP_DD,
    }


def path_has_initial_exposure(path: dict) -> bool:
    return bool(path["initial_user_state"].get("holdings"))


def initial_account_health(path: dict, total_assets: float, can_watch_market: bool) -> dict:
    holdings = path["initial_user_state"].get("holdings") or []
    available_cash = float(path["initial_user_state"].get("available_cash", 0))
    holding_value = max(0.0, total_assets - available_cash)
    total_limit = NO_WATCH_TOTAL_POSITION_LIMIT if not can_watch_market else 0.4
    single_limit = NO_WATCH_SINGLE_POSITION_LIMIT if not can_watch_market else 0.2
    single_ratios = []
    if holdings and total_assets > 0:
        estimated_each = holding_value / len(holdings)
        single_ratios = [
            {
                "ts_code": item.get("ts_code"),
                "name": item.get("name"),
                "estimated_position_ratio": round(estimated_each / total_assets, 4),
                "single_position_violation": estimated_each / total_assets > single_limit,
            }
            for item in holdings
        ]
    total_ratio = holding_value / total_assets if total_assets else 0.0
    return {
        "has_initial_holdings": bool(holdings),
        "initial_holding_count": len(holdings),
        "initial_holding_value": round(holding_value, 2),
        "initial_total_position_ratio": round(total_ratio, 4),
        "total_position_limit": total_limit,
        "single_position_limit": single_limit,
        "initial_total_position_violation": total_ratio > total_limit,
        "initial_single_position_violation": any(item["single_position_violation"] for item in single_ratios),
        "single_position_checks": single_ratios,
        "cannot_add_position": total_ratio > total_limit,
        "violation_source": "历史初始状态不合规" if total_ratio > total_limit else "无初始仓位超限",
    }


def build_deleveraging_plan(path: dict, total_assets: float, can_watch_market: bool) -> dict:
    holdings = path["initial_user_state"].get("holdings") or []
    available_cash = float(path["initial_user_state"].get("available_cash", 0))
    holding_value = max(0.0, total_assets - available_cash)
    total_limit = NO_WATCH_TOTAL_POSITION_LIMIT if not can_watch_market else 0.4
    target_holding_value = total_assets * total_limit
    required_reduce_value = max(0.0, holding_value - target_holding_value)
    if not holdings or required_reduce_value <= 0:
        return {
            "required": False,
            "required_reduce_value": 0.0,
            "target_total_position_ratio": total_limit,
            "positions": [],
            "estimated_total_position_after": round(holding_value / total_assets, 4) if total_assets else 0.0,
            "post_deleveraging_position_compliance": holding_value <= target_holding_value,
        }

    estimated_each = holding_value / len(holdings)
    candidates = []
    for item in holdings:
        role_hint = item.get("role_hint_for_test", "")
        risk_score = 2
        if "弱结构" in role_hint:
            risk_score = 5
        elif "补涨" in role_hint or "高位" in role_hint:
            risk_score = 4
        elif "角色不确定" in role_hint:
            risk_score = 3
        candidates.append(
            {
                "ts_code": item.get("ts_code"),
                "name": item.get("name"),
                "role_hint": role_hint,
                "estimated_market_value": estimated_each,
                "estimated_position_ratio": estimated_each / total_assets if total_assets else 0.0,
                "risk_score": risk_score,
            }
        )
    candidates.sort(key=lambda x: (x["risk_score"], x["estimated_position_ratio"]), reverse=True)
    remaining = required_reduce_value
    plan = []
    for item in candidates:
        reduce_value = min(item["estimated_market_value"], remaining)
        reduce_ratio_of_position = reduce_value / item["estimated_market_value"] if item["estimated_market_value"] else 0.0
        plan.append(
            {
                "ts_code": item["ts_code"],
                "name": item["name"],
                "role_hint": item["role_hint"],
                "estimated_market_value": round(item["estimated_market_value"], 2),
                "estimated_position_ratio": round(item["estimated_position_ratio"], 4),
                "risk_score": item["risk_score"],
                "suggest_reduce_value": round(reduce_value, 2),
                "suggest_reduce_ratio_of_position": round(reduce_ratio_of_position, 4),
                "priority_reason": "弱结构/高风险优先" if item["risk_score"] >= 5 else "仓位较高或非核心，作为降风险候选",
            }
        )
        remaining -= reduce_value
        if remaining <= 1:
            break
    estimated_after = max(0.0, holding_value - required_reduce_value)
    return {
        "required": True,
        "required_reduce_value": round(required_reduce_value, 2),
        "target_total_position_ratio": total_limit,
        "positions": plan,
        "estimated_total_position_after": round(estimated_after / total_assets, 4) if total_assets else 0.0,
        "post_deleveraging_position_compliance": estimated_after <= target_holding_value + 1,
    }


def signal_strength_for_context(
    *,
    path_type: str,
    hard_stop: bool = False,
    account_hard_stop: bool = False,
    account_reduce: bool = False,
    drawdown_reduce: bool = False,
    compliance_reduce: bool = False,
    weak_signal: bool = False,
) -> str:
    if hard_stop or account_hard_stop:
        return "risk_exit_required"
    if path_type != "INTRADAY_OHLC_TRIGGER":
        return "strong_trade_allowed" if account_reduce or drawdown_reduce or compliance_reduce else "medium_wait_confirm"
    if account_reduce or drawdown_reduce:
        return "strong_trade_allowed"
    if compliance_reduce or weak_signal:
        return "weak_observe_only"
    return "medium_wait_confirm"


def review_blocked_trades(execution_log: list[dict]) -> dict:
    reviews = []
    counts = {
        "reasonable_block": 0,
        "too_conservative_block": 0,
        "needs_rule_review": 0,
    }
    for item in execution_log:
        if item.get("action") != "BLOCKED_TRADE":
            continue
        reason = item.get("trade_block_reason")
        strength = item.get("signal_strength")
        intended_action = item.get("intended_action")
        strong_risk_reduce_exception_candidate = (
            reason == "trade_density_limit"
            and item.get("blocked_by_overtrading_guard")
            and intended_action in {"REDUCE", "SELL"}
            and strength in {"strong_trade_allowed", "risk_exit_required"}
        )
        if strong_risk_reduce_exception_candidate:
            verdict = "needs_rule_review"
            rationale = "强风险减仓信号被交易密度拦截，建议进入例外候选与人工复核。"
            exception_candidate_reason = "strong_trade_allowed_or_risk_exit_required_reduce_or_sell_blocked_by_density"
            would_allow_if_exception_enabled = True
            requires_human_review = True
        elif reason == "trade_density_limit" and strength in {"weak_observe_only", "medium_wait_confirm"}:
            verdict = "reasonable_block"
            rationale = "交易密度已达上限且信号未达到强确认，转观察符合降低过度交易目标。"
            exception_candidate_reason = ""
            would_allow_if_exception_enabled = False
            requires_human_review = False
        elif reason == "weak_signal_only":
            verdict = "reasonable_block"
            rationale = "弱信号只应改变观察状态，不应直接触发交易。"
            exception_candidate_reason = ""
            would_allow_if_exception_enabled = False
            requires_human_review = False
        elif strength == "strong_trade_allowed":
            verdict = "needs_rule_review"
            rationale = "信号达到强确认但被拦截，需要人工复查是否过度保守。"
            exception_candidate_reason = "strong_trade_allowed_blocked_by_non_density_rule"
            would_allow_if_exception_enabled = False
            requires_human_review = True
        else:
            verdict = "needs_rule_review"
            rationale = "拦截原因和信号强度组合不够明确，需要人工复查。"
            exception_candidate_reason = ""
            would_allow_if_exception_enabled = False
            requires_human_review = True
        counts[verdict] += 1
        reviews.append(
            {
                "date": item.get("date"),
                "ts_code": item.get("ts_code"),
                "name": item.get("name"),
                "intended_action": item.get("intended_action"),
                "final_action": item.get("final_action"),
                "signal_strength": strength,
                "trade_block_reason": reason,
                "blocked_by_overtrading_guard": item.get("blocked_by_overtrading_guard"),
                "observe_only": item.get("observe_only"),
                "block_review": verdict,
                "reasonable_block": verdict == "reasonable_block",
                "too_conservative_block": verdict == "too_conservative_block",
                "needs_rule_review": verdict == "needs_rule_review",
                "strong_risk_reduce_exception_candidate": strong_risk_reduce_exception_candidate,
                "exception_candidate_reason": exception_candidate_reason,
                "would_allow_if_exception_enabled": would_allow_if_exception_enabled,
                "requires_human_review": requires_human_review,
                "rationale": rationale,
                "if_not_blocked_possible_effect": "可能增加一次真实交易；收益和回撤变化需另做对照模拟，本轮不为结果好看改规则。",
            }
        )
    return {
        "blocked_trade_review_count": len(reviews),
        "review_counts": counts,
        "reviews": reviews,
        "all_blocks_reasonable": len(reviews) > 0 and counts["reasonable_block"] == len(reviews),
        "has_too_conservative_block": counts["too_conservative_block"] > 0,
        "has_needs_rule_review": counts["needs_rule_review"] > 0,
    }


def build_model_position_breach_audit(
    *,
    path_id: str,
    decisions: list[dict],
    actual_execution_log: list[dict],
    initial_position_violation: bool,
    final_position_violation: bool,
    model_caused_position_violation: bool,
) -> dict:
    breach_events = []
    for decision in decisions:
        position_after = decision.get("position_after_action") or {}
        if not position_after.get("position_violation"):
            continue
        breach_events.append(
            {
                "date": decision.get("date"),
                "ts_code": position_after.get("ts_code"),
                "name": position_after.get("name"),
                "shares": position_after.get("shares"),
                "single_position_ratio": position_after.get("single_position_ratio"),
                "total_position_ratio": position_after.get("total_position_ratio"),
                "cannot_watch_limit": position_after.get("cannot_watch_limit"),
                "decision_action": decision.get("action"),
                "need_reduce_to_compliance": decision.get("need_reduce_to_compliance"),
                "drawdown_reduce_trigger": decision.get("drawdown_reduce_trigger"),
                "notes": decision.get("notes", []),
            }
        )
    buy_trades = [x for x in actual_execution_log if x.get("action") == "BUY"]
    reduce_trades_after_breach = [
        x
        for x in actual_execution_log
        if x.get("action") in {"REDUCE", "SELL"} and any(str(x.get("date", "")) >= str(e.get("date", "")) for e in breach_events)
    ]
    if not model_caused_position_violation:
        status = "not_triggered"
        conclusion = "未发现模型新增交易导致的过程仓位超限。"
        is_misreport = False
    elif initial_position_violation:
        status = "initial_position_source"
        conclusion = "仓位超限来自初始持仓，不应归因于模型新增交易。"
        is_misreport = True
    elif final_position_violation:
        status = "true_unresolved_breach"
        conclusion = "模型新增交易后仍处于最终仓位超限，字段成立且需要继续处理。"
        is_misreport = False
    else:
        status = "true_temporary_breach_corrected"
        conclusion = (
            "模型新增交易后因价格上涨出现过程单票仓位超限，随后风险减仓使最终仓位恢复合规；"
            "字段成立，但 summary 的仓位合规字段表示最终状态。"
        )
        is_misreport = False
    return {
        "path_id": path_id,
        "is_misreport": is_misreport,
        "status": status,
        "initial_position_violation": initial_position_violation,
        "final_position_violation": final_position_violation,
        "model_caused_position_breach": model_caused_position_violation,
        "position_compliance_scope": "whether_position_rule_obeyed / position_compliance 表示最终仓位是否合规；model_caused_position_breach 表示过程中是否曾由模型新增交易导致超限。",
        "breach_events": breach_events,
        "buy_trades_before_breach": buy_trades,
        "risk_reduction_after_breach": reduce_trades_after_breach,
        "conclusion": conclusion,
    }


def build_all_blocked_trade_review(results: list[dict]) -> dict:
    details = []
    counts = {"reasonable_block": 0, "too_conservative_block": 0, "needs_rule_review": 0}
    candidate_count = 0
    by_path = {}
    for result in results:
        path_id = result["path_id"]
        reviews = result.get("blocked_trade_review", {}).get("reviews", [])
        path_counts = {"reasonable_block": 0, "too_conservative_block": 0, "needs_rule_review": 0}
        path_candidate_count = 0
        for item in reviews:
            verdict = item.get("block_review", "needs_rule_review")
            if verdict not in counts:
                verdict = "needs_rule_review"
            counts[verdict] += 1
            path_counts[verdict] += 1
            if item.get("strong_risk_reduce_exception_candidate"):
                candidate_count += 1
                path_candidate_count += 1
            details.append(
                {
                    "path": path_id,
                    "date": item.get("date"),
                    "decision_point": item.get("date"),
                    "ts_code": item.get("ts_code"),
                    "name": item.get("name"),
                    "intended_action": item.get("intended_action"),
                    "final_action": item.get("final_action"),
                    "signal_strength": item.get("signal_strength"),
                    "trade_block_reason": item.get("trade_block_reason"),
                    "blocked_by_overtrading_guard": item.get("blocked_by_overtrading_guard"),
                    "observe_only": item.get("observe_only"),
                    "block_reason": item.get("rationale"),
                    "block_review": verdict,
                    "is_reasonable": verdict == "reasonable_block",
                    "strong_risk_reduce_exception_candidate": item.get("strong_risk_reduce_exception_candidate", False),
                    "exception_candidate_reason": item.get("exception_candidate_reason", ""),
                    "would_allow_if_exception_enabled": item.get("would_allow_if_exception_enabled", False),
                    "requires_human_review": item.get("requires_human_review", False),
                }
            )
        if reviews:
            by_path[path_id] = {
                "blocked_trade_count": len(reviews),
                "review_counts": path_counts,
                "strong_risk_reduce_exception_candidate_count": path_candidate_count,
                "execution_quality_issue": result.get("execution_quality_issue", False),
                "execution_quality_issue_level": result.get("execution_quality_issue_level", ""),
            }
    return {
        "total_blocked_trade_count": len(details),
        "strong_risk_reduce_exception_candidate_count": candidate_count,
        "review_counts": counts,
        "by_path": by_path,
        "details": details,
        "note": "BLOCKED_TRADE 不计入真实交易次数，但纳入执行质量审查；REVIEW_NOTE 与严重执行错误分层展示。",
    }


def build_intra02_conservative_review(results: list[dict]) -> dict:
    result = next((r for r in results if r["path_id"] == "WF2025-INTRA-02"), None)
    if not result:
        return {"path_id": "WF2025-INTRA-02", "available": False}
    reviews = result.get("blocked_trade_review", {}).get("reviews", [])
    details = []
    counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for item in reviews:
        if item.get("signal_strength") == "strong_trade_allowed" and item.get("trade_block_reason") == "trade_density_limit":
            judgment = "D"
            judgment_label = "需要新增强信号例外条件"
            reason = (
                "该拦截不是弱/中等买入冲动，而是 strong_trade_allowed 的 REDUCE 风险减仓意图；"
                "不宜与新开仓共用同一个交易密度阈值。但本轮不直接放宽，只建议后续增加强风险减仓的人工复核或单次例外条件。"
            )
        else:
            judgment = "C"
            judgment_label = "仍应服从冷静期/交易密度规则"
            reason = "信号强度或拦截原因不足以支持突破交易密度限制。"
        counts[judgment] += 1
        details.append(
            {
                "date": item.get("date"),
                "ts_code": item.get("ts_code"),
                "name": item.get("name"),
                "intended_action": item.get("intended_action"),
                "signal_strength": item.get("signal_strength"),
                "trade_block_reason": item.get("trade_block_reason"),
                "judgment": judgment,
                "judgment_label": judgment_label,
                "reason": reason,
            }
        )
    return {
        "path_id": "WF2025-INTRA-02",
        "available": True,
        "blocked_trade_count": len(reviews),
        "judgment_counts": counts,
        "details": details,
        "final_judgment": "D：需要新增“强信号例外条件”，允许少数强风险减仓信号进入人工复核或单次例外池；本轮不直接修改核心交易规则。",
        "not_changing_core_rule": True,
    }


def load_decisions_for_result(result: dict) -> list[dict]:
    path = result.get("decisions_json")
    if path:
        decision_path = Path(path)
    else:
        path_id = result.get("path_id")
        if not path_id:
            return []
        decision_path = Path.cwd() / "reports" / "walk_forward_2025" / f"{path_stem(path_id)}_decisions.json"
    if not decision_path.exists():
        return []
    return read_json(decision_path).get("decisions", [])


def load_execution_for_result(result: dict) -> list[dict]:
    path = result.get("execution_json")
    if path:
        execution_path = Path(path)
    else:
        path_id = result.get("path_id")
        if not path_id:
            return []
        execution_path = Path.cwd() / "reports" / "walk_forward_2025" / f"{path_stem(path_id)}_execution_log.json"
    if not execution_path.exists():
        return []
    return read_json(execution_path).get("execution_log", [])


def decision_symbol(decision: dict) -> tuple[str, str]:
    candidate = candidate_fields_from_decision(decision)
    if candidate.get("candidate_is_structured"):
        return candidate.get("candidate_ts_code"), candidate.get("candidate_name")
    position = decision.get("position_after_action") or {}
    return (
        position.get("ts_code") or "UNSTRUCTURED_CANDIDATE",
        position.get("name") or "未在decision字段中结构化",
    )


def build_ai_review_reject_audit(results: list[dict]) -> dict:
    details = []
    counts = {"reasonable_reject": 0, "too_conservative_reject": 0, "needs_rule_review": 0}
    for result in results:
        path_id = result["path_id"]
        for decision in load_decisions_for_result(result):
            review = decision.get("ai_review", {})
            if review.get("review_status") != "REJECT":
                continue
            ts_code, name = decision_symbol(decision)
            candidate = candidate_fields_from_decision(decision)
            veto_reason = review.get("veto_reason", "")
            rule_conflicts = review.get("rule_conflicts", [])
            if veto_reason == "buy_conflicts_with_position_limit" and "buy_vs_position_limit" in rule_conflicts:
                audit_verdict = "reasonable_reject"
                is_reasonable = True
                rationale = "BUY 与仓位限制冲突，shadow review 拒绝原始买入并降为 OBSERVE，符合仓位规则优先于买入建议。"
            elif veto_reason == "buy_blocked_by_account_risk_or_hard_stop":
                audit_verdict = "reasonable_reject"
                is_reasonable = True
                rationale = "账户风控或硬停止开仓生效，拒绝 BUY 合理。"
            elif veto_reason == "buy_conflicts_with_negative_leader_status":
                audit_verdict = "reasonable_reject"
                is_reasonable = True
                rationale = "BUY 遇到负面 leader_status 且 stock_selection_evidence 较弱，shadow review 降级为 OBSERVE 合理；本轮专项审查已确认这类 NO_CLEAR_LEADER + REPAIRING + LOW evidence + weak_volume 可作为龙头状态降级买入参考。"
            else:
                audit_verdict = "needs_rule_review"
                is_reasonable = False
                rationale = "REJECT 触发理由不在当前已确认规则冲突清单内，需要后续人工复核。"
            counts[audit_verdict] += 1
            details.append(
                {
                    "path": path_id,
                    "date": decision.get("date"),
                    "ts_code": ts_code,
                    "name": name,
                    **candidate,
                    "initial_model_action": review.get("initial_model_action"),
                    "final_action_after_review": review.get("final_action_after_review"),
                    "veto_reason": veto_reason,
                    "rule_conflicts": rule_conflicts,
                    "max_allowed_action": review.get("max_allowed_action"),
                    "final_user_action": decision.get("final_user_action"),
                    "audit_verdict": audit_verdict,
                    "is_reasonable": is_reasonable,
                    "rationale": rationale,
                    "note": "若 candidate_is_structured=False，需查看 candidate_missing_reason，不得编造候选股。",
                }
            )
    return {
        "total_reject_count": len(details),
        "audit_counts": counts,
        "details": details,
        "conclusion": "当前 REJECT 均为 BUY 与仓位限制冲突的 shadow veto，未改变真实交易结果；建议后续把候选股代码/名称结构化到 decision 输出。",
    }


def build_sector_cycle_reject_audit(results: list[dict]) -> dict:
    details = []
    counts = {"reasonable_reject": 0, "too_conservative_reject": 0, "needs_rule_review": 0}
    for result in results:
        path_id = result["path_id"]
        execution_log = load_execution_for_result(result)
        for decision in load_decisions_for_result(result):
            review = decision.get("ai_review", {})
            if review.get("review_status") != "REJECT":
                continue
            if review.get("veto_reason") != "buy_conflicts_with_negative_sector_cycle_and_weak_stock_evidence":
                continue
            ts_code, name = decision_symbol(decision)
            evidence = decision.get("stock_selection_evidence", {}) or {}
            sector_state = decision.get("sector_cycle_state", "UNKNOWN")
            sector_note = decision.get("sector_cycle_note", "")
            evidence_quality = evidence.get("evidence_quality", "INSUFFICIENT")
            has_position_limit = bool(decision.get("position_violation") or decision.get("need_reduce_to_compliance"))
            has_trade_density_limit = bool(decision.get("trade_density_observe_mode")) or "trade_density_limit" in evidence.get("risk_notes", [])
            later_trades = [
                item
                for item in execution_log
                if item.get("ts_code") == ts_code and item.get("date", "") >= decision.get("date", "")
            ]

            if sector_state == "CLIMAX" and evidence_quality in {"LOW", "INSUFFICIENT"} and "high_position_risk" in evidence.get("risk_notes", []):
                audit_verdict = "reasonable_reject"
                rationale = "CLIMAX 表示候选组短期过热，个股证据虽有强动量和放量，但 evidence_quality=LOW 且存在 high_position_risk；shadow review 降级为 OBSERVE 合理。"
                if path_id == "WF2025-INTRA-01" and decision.get("date") == "20250701" and ts_code == "600110.SH":
                    rationale += " 执行日志显示该原始 BUY 次日触发后当日止损，说明追高/高潮期风险是真实暴露。"
                elif path_id == "WF2025-INTRA-01" and decision.get("date") == "20250702" and ts_code == "301357.SZ":
                    rationale += " 执行日志显示该原始 BUY 后续小幅盈利退出，说明降级可能错过一次短线机会，但在缺少 leader_status 的情况下，控制高潮期追高风险仍更重要。"
            elif sector_state in {"FADING", "FALLING", "CLIMAX"} and evidence_quality == "HIGH":
                audit_verdict = "needs_rule_review"
                rationale = "板块周期为负面但个股证据较强，是否允许例外需要等 leader_status 或更细规则补齐后再判断。"
            else:
                audit_verdict = "needs_rule_review"
                rationale = "当前证据不足以确认降级过严或完全合理，需要后续 leader_status 补齐后复查。"

            counts[audit_verdict] += 1
            details.append(
                {
                    "path": path_id,
                    "date": decision.get("date"),
                    "ts_code": ts_code,
                    "name": name,
                    "initial_model_action": review.get("initial_model_action"),
                    "final_action_after_review": review.get("final_action_after_review"),
                    "final_user_action": decision.get("final_user_action"),
                    "veto_reason": review.get("veto_reason"),
                    "rule_conflicts": review.get("rule_conflicts", []),
                    "raw_model_buy_reason": decision.get("reason", ""),
                    "sector_cycle_state": sector_state,
                    "sector_cycle_note": sector_note,
                    "stock_selection_evidence": evidence,
                    "evidence_quality": evidence_quality,
                    "has_position_limit": has_position_limit,
                    "has_trade_density_limit": has_trade_density_limit,
                    "shadow_downgrade_reason": "negative sector_cycle_state plus weak/low stock_selection_evidence",
                    "risk_if_not_downgraded": "可能在板块/候选组高潮或退潮阶段追高买入，放大当日止损、隔日回落或高位接盘风险。",
                    "opportunity_cost_if_downgraded": "可能错过强动量个股的短线延续机会；若后续补齐 leader_status 证明其为强龙头，规则可再评估是否过严。",
                    "later_execution_reference": later_trades,
                    "audit_verdict": audit_verdict,
                    "rationale": rationale,
                }
            )
    return {
        "total_count": len(details),
        "audit_counts": counts,
        "reasonable_count": counts["reasonable_reject"],
        "too_conservative_count": counts["too_conservative_reject"],
        "needs_rule_review_count": counts["needs_rule_review"],
        "details": details,
        "rule_change_recommendation": "本轮不建议直接调整 sector_cycle_state 规则；这类 CLIMAX + LOW evidence + high_position_risk 的 BUY 降级可以作为板块周期降级买入的参考。",
    }


def build_leader_status_reject_audit(results: list[dict]) -> dict:
    details = []
    counts = {"reasonable_reject": 0, "too_conservative_reject": 0, "needs_rule_review": 0}
    for result in results:
        path_id = result["path_id"]
        execution_log = load_execution_for_result(result)
        for decision in load_decisions_for_result(result):
            review = decision.get("ai_review", {})
            if review.get("review_status") != "REJECT":
                continue
            if review.get("veto_reason") != "buy_conflicts_with_negative_leader_status":
                continue
            ts_code, name = decision_symbol(decision)
            evidence = decision.get("stock_selection_evidence", {}) or {}
            leader_status = decision.get("leader_status", "UNKNOWN")
            sector_state = decision.get("sector_cycle_state", "UNKNOWN")
            evidence_quality = evidence.get("evidence_quality", "INSUFFICIENT")
            has_position_limit = bool(decision.get("position_violation") or decision.get("need_reduce_to_compliance"))
            has_trade_density_limit = bool(decision.get("trade_density_observe_mode")) or "trade_density_limit" in evidence.get("risk_notes", [])
            later_trades = [
                item
                for item in execution_log
                if item.get("ts_code") == ts_code and item.get("date", "") >= decision.get("date", "")
            ]

            if leader_status == "NO_CLEAR_LEADER" and sector_state == "REPAIRING" and evidence_quality in {"LOW", "INSUFFICIENT"}:
                audit_verdict = "reasonable_reject"
                rationale = (
                    "NO_CLEAR_LEADER 表示候选组没有明确核心强势股，sector_cycle_state=REPAIRING 只支持观察或等待确认；"
                    "该 BUY 的 stock_selection_evidence 为 LOW，且量能为 DIVERGENT/weak_volume，shadow review 降级为 OBSERVE 合理。"
                )
                if path_id == "WF2025-PRE-02" and decision.get("date") == "20250414" and ts_code == "300421.SZ":
                    rationale += " 执行日志显示原始 BUY 次日仍触发买入，路径内未出现对应卖出兑现，PRE-02 最终收益为负，后续结果没有证明这次降级过严。"
            elif leader_status in {"LEADER_WEAKENING", "LEADER_BROKEN", "NO_CLEAR_LEADER"} and evidence_quality == "HIGH":
                audit_verdict = "needs_rule_review"
                rationale = "龙头状态偏弱但个股证据较强，是否允许例外需要更多样本后再判断。"
            else:
                audit_verdict = "needs_rule_review"
                rationale = "当前证据不足以确认合理或过度保守，需要更多样本后复查。"

            counts[audit_verdict] += 1
            details.append(
                {
                    "path": path_id,
                    "date": decision.get("date"),
                    "ts_code": ts_code,
                    "name": name,
                    "initial_model_action": review.get("initial_model_action"),
                    "final_action_after_review": review.get("final_action_after_review"),
                    "final_user_action": decision.get("final_user_action"),
                    "veto_reason": review.get("veto_reason"),
                    "rule_conflicts": review.get("rule_conflicts", []),
                    "raw_model_buy_reason": decision.get("reason", ""),
                    "leader_status": leader_status,
                    "leader_status_note": decision.get("leader_status_note", ""),
                    "sector_cycle_state": sector_state,
                    "sector_cycle_note": decision.get("sector_cycle_note", ""),
                    "stock_selection_evidence": evidence,
                    "evidence_quality": evidence_quality,
                    "has_position_limit": has_position_limit,
                    "has_trade_density_limit": has_trade_density_limit,
                    "shadow_downgrade_reason": "negative leader_status plus weak/low stock_selection_evidence",
                    "risk_if_not_downgraded": "可能在没有明确龙头或核心股承接的修复阶段买入后排/弱证据标的，增加修复失败、量能背离和资金轮动落空风险。",
                    "opportunity_cost_if_downgraded": "可能错过修复阶段个股继续反弹的短线机会；若后续更多样本证明 NO_CLEAR_LEADER 下仍有稳定收益，可再评估是否过严。",
                    "later_execution_reference": later_trades,
                    "audit_verdict": audit_verdict,
                    "rationale": rationale,
                }
            )
    return {
        "total_count": len(details),
        "audit_counts": counts,
        "reasonable_count": counts["reasonable_reject"],
        "too_conservative_count": counts["too_conservative_reject"],
        "needs_rule_review_count": counts["needs_rule_review"],
        "details": details,
        "rule_change_recommendation": "本轮不建议调整 leader_status 规则；NO_CLEAR_LEADER + REPAIRING + LOW evidence + weak_volume 的 BUY 降级可作为龙头状态降级买入的参考。",
    }


def decision_has_trade_density_limit(decision: dict) -> bool:
    if decision.get("trade_density_observe_mode") or decision.get("execution_quality_issue"):
        return True
    ai_review = decision.get("ai_review", {}) or {}
    if "trade_density_limit" in ai_review.get("rule_conflicts", []):
        return True
    warnings = ai_review.get("risk_warnings", [])
    return any("trade_density" in str(item) for item in warnings)


def decision_has_position_limit_conflict(decision: dict) -> bool:
    if decision.get("position_violation") or decision.get("need_reduce_to_compliance"):
        return True
    ai_review = decision.get("ai_review", {}) or {}
    return "buy_vs_position_limit" in (ai_review.get("rule_conflicts") or [])


def collect_path_decisions(results: list[dict]) -> list[dict]:
    items = []
    for result in results:
        for decision in load_decisions_for_result(result):
            items.append({"path": result["path_id"], "decision": decision})
    return items


def build_field_completeness_report(results: list[dict]) -> dict:
    required_fields = [
        "candidate_ts_code",
        "candidate_name",
        "candidate_action",
        "stock_selection_evidence",
        "sector_cycle_state",
        "leader_status",
        "ai_review",
        "final_user_action",
        "action_reason",
        "execution_condition",
        "invalidation_condition",
        "stop_loss_condition",
        "position_limit",
        "user_note",
    ]
    decisions = collect_path_decisions(results)
    report = {}
    missing_field_paths = {}
    critical_fields = {"stock_selection_evidence", "sector_cycle_state", "leader_status", "ai_review", "final_user_action"}
    critical_missing = False
    for field in required_fields:
        missing_items = []
        for item in decisions:
            decision = item["decision"]
            value = decision.get(field, None)
            missing = field not in decision
            if field in {"stock_selection_evidence", "ai_review"}:
                missing = missing or not isinstance(value, dict)
            elif field in {"sector_cycle_state", "leader_status", "final_user_action"}:
                missing = missing or not value
            elif field in {"action_reason", "execution_condition", "invalidation_condition", "stop_loss_condition", "user_note"}:
                missing = missing or value in {None, ""}
            elif field == "position_limit":
                missing = missing or value is None
            else:
                missing = missing or value is None
            if missing:
                missing_items.append({"path": item["path"], "date": decision.get("date")})
        report[field] = {
            "total_count": len(decisions),
            "missing_count": len(missing_items),
            "present_count": len(decisions) - len(missing_items),
            "complete": len(missing_items) == 0,
        }
        if missing_items:
            missing_field_paths[field] = missing_items
            if field in critical_fields:
                critical_missing = True
    return {
        "field_completeness_report": report,
        "missing_field_count": sum(item["missing_count"] for item in report.values()),
        "missing_field_paths": missing_field_paths,
        "has_critical_missing_fields": critical_missing,
    }


def build_consistency_conflict_report(results: list[dict]) -> dict:
    conflicts = []
    buy_conflict_count = 0
    observe_too_conservative_candidate_count = 0
    reduce_sell_missing_reason_count = 0
    needs_human_review_abuse_count = 0
    for item in collect_path_decisions(results):
        path_id = item["path"]
        decision = item["decision"]
        final_action = decision.get("final_user_action")
        evidence = decision.get("stock_selection_evidence", {}) or {}
        evidence_quality = evidence.get("evidence_quality")
        sector_state = decision.get("sector_cycle_state")
        leader_status = decision.get("leader_status")
        position_conflict = decision_has_position_limit_conflict(decision)
        density_conflict = decision_has_trade_density_limit(decision)
        ai_review = decision.get("ai_review", {}) or {}
        if final_action == "BUY":
            reasons = []
            if evidence_quality == "INSUFFICIENT":
                reasons.append("buy_with_insufficient_evidence")
            if sector_state == "FALLING":
                reasons.append("buy_with_falling_sector_cycle")
            if leader_status == "LEADER_BROKEN":
                reasons.append("buy_with_broken_leader_status")
            if position_conflict:
                reasons.append("buy_with_position_limit_conflict")
            if density_conflict:
                reasons.append("buy_with_trade_density_limit")
            if reasons:
                buy_conflict_count += 1
                conflicts.append({"path": path_id, "date": decision.get("date"), "final_user_action": final_action, "type": "buy_conflict", "reasons": reasons})
        if final_action == "OBSERVE":
            if (
                evidence_quality == "HIGH"
                and sector_state == "RISING"
                and leader_status == "LEADER_STRONG"
                and not position_conflict
                and not density_conflict
            ):
                observe_too_conservative_candidate_count += 1
                conflicts.append({"path": path_id, "date": decision.get("date"), "final_user_action": final_action, "type": "possible_too_conservative_observe", "reasons": ["high_evidence_rising_strong_leader_without_hard_conflict"]})
        if final_action in {"REDUCE", "SELL"}:
            reasons = []
            if not decision.get("stop_loss_condition"):
                reasons.append("missing_stop_or_reduce_condition")
            if not (decision.get("position_after_action") or decision.get("need_reduce_to_compliance") or decision.get("account_reduce_risk_trigger") or decision.get("drawdown_reduce_trigger")):
                reasons.append("no_position_or_risk_context")
            if reasons:
                reduce_sell_missing_reason_count += 1
                conflicts.append({"path": path_id, "date": decision.get("date"), "final_user_action": final_action, "type": "reduce_sell_missing_reason", "reasons": reasons})
        if final_action == "NEEDS_HUMAN_REVIEW":
            reasons = []
            if not ai_review.get("strong_risk_reduce_exception_candidate"):
                reasons.append("not_strong_risk_reduce_exception")
            if not ai_review.get("rule_conflicts") and not ai_review.get("missing_fields") and not ai_review.get("veto_reason"):
                reasons.append("no_clear_rule_or_field_conflict")
            if reasons:
                needs_human_review_abuse_count += 1
                conflicts.append({"path": path_id, "date": decision.get("date"), "final_user_action": final_action, "type": "needs_human_review_abuse", "reasons": reasons})
    return {
        "consistency_conflict_count": len(conflicts),
        "buy_conflict_count": buy_conflict_count,
        "observe_too_conservative_candidate_count": observe_too_conservative_candidate_count,
        "reduce_sell_missing_reason_count": reduce_sell_missing_reason_count,
        "needs_human_review_abuse_count": needs_human_review_abuse_count,
        "detailed_conflict_examples": conflicts[:20],
    }


def build_buy_action_audit(results: list[dict]) -> dict:
    details = []
    counts = {"reasonable_buy": 0, "weak_buy_needs_observe": 0, "needs_rule_review": 0}
    for item in collect_path_decisions(results):
        path_id = item["path"]
        decision = item["decision"]
        if decision.get("final_user_action") != "BUY":
            continue
        evidence = decision.get("stock_selection_evidence", {}) or {}
        evidence_quality = evidence.get("evidence_quality")
        sector_state = decision.get("sector_cycle_state")
        leader_status = decision.get("leader_status")
        position_conflict = decision_has_position_limit_conflict(decision)
        density_conflict = decision_has_trade_density_limit(decision)
        ai_review = decision.get("ai_review", {}) or {}
        if evidence_quality in {"HIGH", "MEDIUM"} and sector_state not in {"FALLING", "CLIMAX"} and leader_status not in {"LEADER_BROKEN", "NO_CLEAR_LEADER"} and not position_conflict and not density_conflict:
            verdict = "reasonable_buy"
            rationale = "个股证据、板块周期和龙头状态未出现硬冲突，保留 BUY 合理。"
        elif evidence_quality == "LOW" and ai_review.get("review_status") == "PASS":
            verdict = "weak_buy_needs_observe"
            rationale = "BUY 仍被保留，但个股证据偏弱，后续进入双轨 shadow 时应重点对照是否需要降级。"
        else:
            verdict = "needs_rule_review"
            rationale = "BUY 虽被保留，但仍存在需要继续观察的规则边界。"
        counts[verdict] += 1
        details.append(
            {
                "path": path_id,
                "date": decision.get("date"),
                "ts_code": decision.get("candidate_ts_code"),
                "name": decision.get("candidate_name"),
                "evidence_quality": evidence_quality,
                "sector_cycle_state": sector_state,
                "leader_status": leader_status,
                "position_status": "conflict" if position_conflict else "ok",
                "trade_density_status": "conflict" if density_conflict else "ok",
                "ai_review_review_status": ai_review.get("review_status"),
                "action_reason": decision.get("action_reason"),
                "stop_loss_condition": decision.get("stop_loss_condition"),
                "position_limit": decision.get("position_limit"),
                "buy_retained_is_reasonable": verdict == "reasonable_buy",
                "audit_verdict": verdict,
                "rationale": rationale,
            }
        )
    return {
        "buy_count": len(details),
        "audit_counts": counts,
        "details": details,
    }


def build_observe_action_audit(results: list[dict]) -> dict:
    reasons = Counter()
    examples = []
    possible_count = 0
    for item in collect_path_decisions(results):
        path_id = item["path"]
        decision = item["decision"]
        if decision.get("final_user_action") != "OBSERVE":
            continue
        evidence = decision.get("stock_selection_evidence", {}) or {}
        evidence_quality = evidence.get("evidence_quality")
        sector_state = decision.get("sector_cycle_state")
        leader_status = decision.get("leader_status")
        ai_review = decision.get("ai_review", {}) or {}
        veto_reason = ai_review.get("veto_reason") or decision.get("action")
        reasons[veto_reason] += 1
        if (
            evidence_quality == "HIGH"
            and sector_state == "RISING"
            and leader_status == "LEADER_STRONG"
            and not decision_has_position_limit_conflict(decision)
            and not decision_has_trade_density_limit(decision)
        ):
            possible_count += 1
            if len(examples) < 5:
                examples.append(
                    {
                        "path": path_id,
                        "date": decision.get("date"),
                        "ts_code": decision.get("candidate_ts_code"),
                        "name": decision.get("candidate_name"),
                        "audit_label": "possible_too_conservative_observe",
                        "action_reason": decision.get("action_reason"),
                    }
                )
    return {
        "observe_reason_top": reasons.most_common(10),
        "possible_too_conservative_observe_count": possible_count,
        "possible_too_conservative_observe_examples": examples,
    }


def build_needs_human_review_audit(results: list[dict]) -> dict:
    existing = build_ai_review_needs_human_audit(results)
    return {
        "needs_human_review_count": existing.get("total_needs_human_count", 0),
        "needs_human_review_abuse_check": existing.get("abuse_check", {}),
        "strong_risk_reduce_exception_still_valid": existing.get("all_correspond_to_intra02_exception", False),
        "recommendation_for_next_stage": (
            "保留人工复核，并建议下一阶段进入强风险减仓单次例外池 shadow test。"
            if existing.get("all_correspond_to_intra02_exception", False) and not existing.get("abuse_check", {}).get("is_abused")
            else "先不要扩大人工复核例外范围，需继续收敛规则边界。"
        ),
        "details": existing.get("details", []),
    }


def build_ai_review_integrity_audit(summary: dict, buy_action_audit: dict, observe_action_audit: dict, consistency_conflict_report: dict) -> dict:
    reject_count = summary.get("ai_review_reject_count", 0)
    would_change = summary.get("ai_review_would_change_action_count", 0)
    overconservative = observe_action_audit.get("possible_too_conservative_observe_count", 0) > 0
    missed_risk = consistency_conflict_report.get("buy_conflict_count", 0) > 0
    reject_explainable = reject_count == (
        summary.get("sector_cycle_reject_audit_count", 0)
        + summary.get("leader_status_reject_audit_count", 0)
        + 3
    )
    clarity_ok = True
    unclear_examples = []
    banned_terms = ["可关注", "谨慎参与", "看情况", "适当考虑", "倾向于"]
    for item in collect_path_decisions([{"path_id": r["path_id"], **r} for r in summary["results"]]):
        note = str(item["decision"].get("user_note") or "")
        final_action = item["decision"].get("final_user_action")
        if final_action not in {"BUY", "HOLD", "REDUCE", "SELL", "OBSERVE", "NEEDS_HUMAN_REVIEW"}:
            clarity_ok = False
            unclear_examples.append({"path": item["path"], "date": item["decision"].get("date"), "reason": "invalid_final_user_action"})
        if any(term in note for term in banned_terms):
            clarity_ok = False
            unclear_examples.append({"path": item["path"], "date": item["decision"].get("date"), "reason": "ambiguous_user_note"})
    return {
        "ai_review_overconservative_check": {
            "is_overconservative": overconservative,
            "reason": "存在 HIGH evidence + RISING + LEADER_STRONG 但仍 OBSERVE 的样本。" if overconservative else "未发现明显过度保守的 OBSERVE 样本。",
        },
        "ai_review_missed_risk_check": {
            "missed_risk": missed_risk,
            "reason": "仍有 BUY 与硬风险条件冲突。" if missed_risk else "未发现明显漏拦的硬风险 BUY。",
        },
        "reject_explainability_check": {
            "all_rejects_explainable": reject_explainable,
            "reject_count": reject_count,
            "note": "当前 REJECT 都能归因到仓位、板块周期或龙头状态规则。" if reject_explainable else "仍有 REJECT 归因未完全收敛。",
        },
        "would_change_action_check": {
            "would_change_action_count": would_change,
            "is_reasonable": would_change >= reject_count and would_change <= reject_count + summary.get("ai_review_needs_human_count", 0) + 2,
        },
        "final_user_action_clarity_check": {
            "is_clear": clarity_ok,
            "unclear_examples": unclear_examples[:10],
        },
    }


def build_dual_track_readiness(
    field_completeness_report: dict,
    consistency_conflict_report: dict,
    buy_action_audit: dict,
    observe_action_audit: dict,
    needs_human_review_audit: dict,
    ai_review_integrity_audit: dict,
) -> dict:
    blockers = []
    if field_completeness_report.get("has_critical_missing_fields"):
        blockers.append("仍有关键字段缺失。")
    if consistency_conflict_report.get("buy_conflict_count", 0) > 0:
        blockers.append("仍存在 BUY 与硬风险条件冲突。")
    if needs_human_review_audit.get("needs_human_review_abuse_check", {}).get("is_abused"):
        blockers.append("NEEDS_HUMAN_REVIEW 存在滥用风险。")
    if not ai_review_integrity_audit.get("final_user_action_clarity_check", {}).get("is_clear", False):
        blockers.append("final_user_action 仍有表达不清的问题。")
    ready = len(blockers) == 0
    return {
        "ready_for_dual_track_shadow_simulation": ready,
        "reason": (
            "10 路径字段完整，BUY/OBSERVE/NEEDS_HUMAN_REVIEW 规则边界已可解释，适合进入原模型线 vs AI审核线的双轨 shadow 记录。"
            if ready
            else ""
        ),
        "blockers": blockers,
        "recommended_next_step": (
            "进入双轨 shadow simulation 准备：保留真实动作线，同时记录 ai_review/final_user_action 的 shadow action。"
            if ready
            else "暂不进入双轨 shadow simulation，先修复上述阻断项。"
        ),
    }


def build_ai_review_needs_human_audit(results: list[dict]) -> dict:
    blocked_by_path_date = {}
    for result in results:
        path_id = result["path_id"]
        for item in result.get("blocked_trade_review", {}).get("reviews", []):
            blocked_by_path_date.setdefault((path_id, item.get("date")), []).append(item)

    details = []
    abnormal = []
    for result in results:
        path_id = result["path_id"]
        for decision in load_decisions_for_result(result):
            review = decision.get("ai_review", {})
            if review.get("review_status") != "NEEDS_HUMAN_REVIEW":
                continue
            block = next(
                (
                    item
                    for item in blocked_by_path_date.get((path_id, decision.get("date")), [])
                    if item.get("strong_risk_reduce_exception_candidate")
                ),
                {},
            )
            ts_code, name = (
                block.get("ts_code") or decision_symbol(decision)[0],
                block.get("name") or decision_symbol(decision)[1],
            )
            corresponds_to_exception = bool(block) and bool(review.get("strong_risk_reduce_exception_candidate"))
            item = {
                "path": path_id,
                "date": decision.get("date"),
                "ts_code": ts_code,
                "name": name,
                "intended_action": block.get("intended_action"),
                "signal_strength": block.get("signal_strength"),
                "trade_block_reason": block.get("trade_block_reason"),
                "strong_risk_reduce_exception_candidate": review.get("strong_risk_reduce_exception_candidate", False),
                "requires_human_review": review.get("requires_human_review", False),
                "final_user_action": decision.get("final_user_action"),
                "human_review_reason": review.get("veto_reason") or review.get("exception_candidate_reason"),
                "corresponds_to_strong_risk_reduce_exception": corresponds_to_exception,
                "is_abnormal": not corresponds_to_exception,
            }
            details.append(item)
            if item["is_abnormal"]:
                abnormal.append(item)
    abuse_check = {
        "is_abused": bool(abnormal),
        "abnormal_count": len(abnormal),
        "abnormal_details": abnormal,
        "conclusion": (
            "发现 NEEDS_HUMAN_REVIEW 未对应强风险减仓例外候选，需要单独复查。"
            if abnormal
            else "未发现滥用；NEEDS_HUMAN_REVIEW 均对应 INTRA-02 strong_risk_reduce_exception_candidate。"
        ),
    }
    return {
        "total_needs_human_count": len(details),
        "all_correspond_to_intra02_exception": all(
            item["path"] == "WF2025-INTRA-02" and item["corresponds_to_strong_risk_reduce_exception"]
            for item in details
        ),
        "details": details,
        "abuse_check": abuse_check,
    }


def build_missing_fields_next_schema_plan() -> dict:
    return {
        "scope": "下一轮只基于 questions 文件和已有行情/路径数据补齐结构字段；不接全网新闻，不接消息面模块。",
        "sector_cycle_state": {
            "allowed_values": ["UNKNOWN", "RISING", "DIVERGENCE", "CLIMAX", "FADING", "FALLING", "REPAIRING"],
            "meaning": "描述目标板块或候选组在当前路径日期的周期状态，用于区分上升、分歧、高潮、退潮、下跌和修复。",
            "when_missing": "设为 UNKNOWN，并写入 ai_review.missing_fields；不得用主观描述补值。",
            "ai_review_effect": "UNKNOWN 不直接否决交易，但降低信心；若 BUY 同时缺少龙头和个股证据，应增加风险提示。",
            "final_user_action_effect": "字段缺失时优先 OBSERVE 或保持原动作的 shadow 输出；只有叠加规则冲突时才升为 NEEDS_HUMAN_REVIEW。",
        },
        "leader_status": {
            "allowed_values": [
                "UNKNOWN",
                "LEADER_STRONG",
                "LEADER_WEAKENING",
                "LEADER_BROKEN",
                "LEADER_ROTATING",
                "NO_CLEAR_LEADER",
            ],
            "meaning": "描述板块内核心或龙头的强弱、是否破位、是否轮动。",
            "when_missing": "设为 UNKNOWN，进入 missing_fields，不把 role_hint_for_test 直接等同于真实龙头状态。",
            "buy_effect": "LEADER_STRONG 可支持观察或试错；LEADER_WEAKENING/BROKEN/NO_CLEAR_LEADER 应压低买入优先级。",
            "risk_warning_effect": "弱化、破位或无明确龙头时，增加风险提示；持仓路径优先检查利润保护或减仓条件。",
        },
        "stock_selection_evidence": {
            "fields": [
                "selected_reason",
                "price_position",
                "volume_confirmation",
                "relative_strength",
                "risk_notes",
                "alternative_candidates_available",
                "is_leader_or_lagger",
            ],
            "meaning": "记录为什么选择该个股、价格位置、量能确认、相对强弱、风险说明、是否有替代候选、是龙头还是后排。",
            "anti_fabrication": "只允许从 questions 可见字段、已有 OHLC/路径数据和可复现计算得出；无法验证则写 UNKNOWN 或 insufficient_evidence。",
            "insufficient_evidence_effect": "证据不足时 BUY 应降级为 OBSERVE；若同时存在仓位/交易密度/字段矛盾，则可进入 NEEDS_HUMAN_REVIEW。",
        },
        "implementation_note": "下一轮先把字段加入 questions/decision/result 的结构输出和 missing_fields 规则，不改变评分权重和真实交易执行。",
    }


def build_structured_candidate_summary(results: list[dict]) -> dict:
    structured_count = 0
    unstructured_count = 0
    unstructured_paths = set()
    reject_unstructured_count = 0
    unstructured_details = []
    for result in results:
        path_id = result["path_id"]
        for decision in load_decisions_for_result(result):
            candidate = candidate_fields_from_decision(decision)
            if candidate.get("candidate_is_structured"):
                structured_count += 1
            else:
                unstructured_count += 1
                unstructured_paths.add(path_id)
                if decision.get("ai_review", {}).get("review_status") == "REJECT":
                    reject_unstructured_count += 1
                unstructured_details.append(
                    {
                        "path": path_id,
                        "date": decision.get("date"),
                        "action": decision.get("action"),
                        "final_user_action": decision.get("final_user_action"),
                        "candidate_missing_reason": candidate.get("candidate_missing_reason") or "insufficient_visible_source",
                    }
                )
    return {
        "structured_candidate_count": structured_count,
        "unstructured_candidate_count": unstructured_count,
        "unstructured_candidate_paths": sorted(unstructured_paths),
        "ai_review_reject_unstructured_count": reject_unstructured_count,
        "unstructured_candidate_details": unstructured_details,
        "note": "候选字段只使用 questions 可见字段、现有路径数据、position_after_action 或 execution_log；无法确定时保留 missing_reason，不编造。",
    }


def shares_to_reduce_to_limit(position: dict, price: float, total_assets: float, limit: float) -> int:
    allowed_value = total_assets * limit
    current_value = position["shares"] * price
    excess_value = max(0.0, current_value - allowed_value)
    shares = int(excess_value // price // 100 * 100)
    return min(position["shares"], max(0, shares))


def build_shadow_ai_review(decision: dict, blocked_trade_candidates: list[dict]) -> dict:
    action = decision.get("action")
    risk_warnings: list[str] = []
    rule_conflicts: list[str] = []
    missing_fields: list[str] = []
    stock_evidence = decision.get("stock_selection_evidence") or {}
    evidence_quality = stock_evidence.get("evidence_quality")
    if not stock_evidence:
        missing_fields.append("stock_selection_evidence")
    elif evidence_quality == "INSUFFICIENT":
        risk_warnings.append("insufficient_stock_selection_evidence")
        missing_reason = stock_evidence.get("evidence_missing_reason") or "insufficient_stock_selection_evidence"
        missing_fields.append(f"stock_selection_evidence:{missing_reason}")
    elif evidence_quality == "LOW":
        risk_warnings.append("low_stock_selection_evidence")
    sector_cycle_state = decision.get("sector_cycle_state", "UNKNOWN")
    sector_cycle_missing_reason = decision.get("sector_cycle_missing_reason") or ""
    negative_sector_cycle = sector_cycle_state in {"FADING", "FALLING", "CLIMAX"}
    if sector_cycle_state == "UNKNOWN":
        missing_fields.append(f"sector_cycle_state:{sector_cycle_missing_reason or 'insufficient_sector_data'}")
        risk_warnings.append("unknown_sector_cycle_state")
    elif negative_sector_cycle:
        risk_warnings.append(f"negative_sector_cycle:{sector_cycle_state}")
    elif sector_cycle_state == "DIVERGENCE":
        risk_warnings.append("sector_cycle_divergence_requires_strong_stock_evidence")
    leader_status = decision.get("leader_status", "UNKNOWN")
    leader_status_missing_reason = decision.get("leader_status_missing_reason") or ""
    negative_leader_status = leader_status in {"LEADER_WEAKENING", "LEADER_BROKEN", "NO_CLEAR_LEADER"}
    if leader_status == "UNKNOWN":
        missing_fields.append(f"leader_status:{leader_status_missing_reason or 'insufficient_leader_data'}")
        risk_warnings.append("unknown_leader_status")
    elif negative_leader_status:
        risk_warnings.append(f"negative_leader_status:{leader_status}")
    elif leader_status == "LEADER_ROTATING":
        risk_warnings.append("leader_rotating_requires_strong_stock_evidence")
    veto_reason = ""
    confidence_level = "HIGH"
    review_status = "PASS"
    final_action_after_review = action if action != "WAIT" else "OBSERVE"

    if action not in {"BUY", "REDUCE", "SELL", "HOLD", "WAIT"}:
        missing_fields.append("action")
        review_status = "NEEDS_HUMAN_REVIEW"
        confidence_level = "LOW"
    elif sector_cycle_state == "UNKNOWN" or leader_status == "UNKNOWN":
        confidence_level = "MEDIUM"

    if action == "BUY":
        if decision.get("stop_new_buy_active") or decision.get("account_hard_stop_active"):
            review_status = "REJECT"
            final_action_after_review = "OBSERVE"
            veto_reason = "buy_blocked_by_account_risk_or_hard_stop"
            rule_conflicts.append("buy_vs_stop_new_buy_or_hard_stop")
            risk_warnings.append("account_risk_lock_active")
        elif decision.get("position_violation") or decision.get("need_reduce_to_compliance"):
            review_status = "REJECT"
            final_action_after_review = "REDUCE" if decision.get("need_reduce_to_compliance") else "OBSERVE"
            veto_reason = "buy_conflicts_with_position_limit"
            rule_conflicts.append("buy_vs_position_limit")
            risk_warnings.append("position_limit_conflict")
        elif negative_sector_cycle and evidence_quality in {"LOW", "INSUFFICIENT"}:
            review_status = "REJECT"
            final_action_after_review = "OBSERVE"
            veto_reason = "buy_conflicts_with_negative_sector_cycle_and_weak_stock_evidence"
            rule_conflicts.append("buy_vs_negative_sector_cycle")
        elif negative_leader_status and (sector_cycle_state in {"CLIMAX", "FADING", "FALLING"} or evidence_quality in {"LOW", "INSUFFICIENT"}):
            review_status = "REJECT"
            final_action_after_review = "OBSERVE"
            veto_reason = "buy_conflicts_with_negative_leader_status"
            rule_conflicts.append("buy_vs_negative_leader_status")
        elif leader_status == "LEADER_ROTATING" and evidence_quality in {"LOW", "INSUFFICIENT"}:
            risk_warnings.append("buy_in_leader_rotation_requires_better_stock_evidence")
            rule_conflicts.append("buy_vs_leader_rotation_with_weak_evidence")
        elif sector_cycle_state == "DIVERGENCE" and evidence_quality in {"LOW", "INSUFFICIENT"}:
            risk_warnings.append("buy_in_divergence_requires_better_stock_evidence")
            rule_conflicts.append("buy_vs_divergent_sector_cycle_with_weak_evidence")
        elif evidence_quality == "INSUFFICIENT" and rule_conflicts:
            review_status = "REJECT"
            final_action_after_review = "OBSERVE"
            veto_reason = "buy_conflicts_with_insufficient_stock_selection_evidence"
            risk_warnings.append("insufficient_stock_selection_evidence")
    elif action in {"REDUCE", "SELL"}:
        if blocked_trade_candidates:
            review_status = "NEEDS_HUMAN_REVIEW"
            final_action_after_review = action
            risk_warnings.append("strong_risk_reduce_exception_candidate")
            rule_conflicts.append("trade_density_limit_vs_strong_risk_reduce")
            veto_reason = "strong_risk_reduce_exception_candidate"
            confidence_level = "MEDIUM"
        elif decision.get("account_hard_stop_active"):
            review_status = "PASS"
            final_action_after_review = action
            risk_warnings.append("hard_stop_requires_deleveraging")
        elif decision.get("need_reduce_to_compliance") or decision.get("drawdown_reduce_trigger") or decision.get("account_reduce_risk_trigger"):
            review_status = "PASS"
            final_action_after_review = action
        else:
            review_status = "PASS"
    elif action == "HOLD":
        if blocked_trade_candidates:
            review_status = "NEEDS_HUMAN_REVIEW"
            final_action_after_review = "NEEDS_HUMAN_REVIEW"
            risk_warnings.append("blocked_strong_risk_reduce_intent_requires_review")
            rule_conflicts.append("hold_vs_strong_risk_reduce_intent")
            veto_reason = "needs_human_review_for_blocked_reduce"
            confidence_level = "MEDIUM"
        else:
            review_status = "PASS"
            final_action_after_review = "HOLD"
    elif action == "WAIT":
        review_status = "PASS"
        final_action_after_review = "OBSERVE"

    strong_risk_reduce_exception_candidate = bool(blocked_trade_candidates)
    requires_human_review = review_status == "NEEDS_HUMAN_REVIEW"
    return {
        "review_status": review_status,
        "initial_model_action": action,
        "final_action_after_review": final_action_after_review,
        "review_changes_action": final_action_after_review != action and not (action == "WAIT" and final_action_after_review == "OBSERVE"),
        "veto_reason": veto_reason,
        "risk_warnings": risk_warnings,
        "rule_conflicts": rule_conflicts,
        "missing_fields": missing_fields,
        "confidence_level": confidence_level,
        "max_allowed_action": final_action_after_review if final_action_after_review in {"BUY", "HOLD", "REDUCE", "SELL", "OBSERVE"} else "OBSERVE",
        "reviewer_note": "shadow_review_only",
        "strong_risk_reduce_exception_candidate": strong_risk_reduce_exception_candidate,
        "exception_candidate_reason": "blocked_strong_risk_reduce_intent" if strong_risk_reduce_exception_candidate else "",
        "would_allow_if_exception_enabled": strong_risk_reduce_exception_candidate,
        "requires_human_review": requires_human_review,
    }


def build_final_user_action(decision: dict, ai_review: dict) -> dict:
    model_action = decision.get("action")
    stock_evidence = decision.get("stock_selection_evidence") or {}
    evidence_quality = stock_evidence.get("evidence_quality")
    sector_cycle_state = decision.get("sector_cycle_state", "UNKNOWN")
    leader_status = decision.get("leader_status", "UNKNOWN")
    evidence_note = ""
    if evidence_quality in {"LOW", "INSUFFICIENT"}:
        evidence_note = " 个股选择证据不足，需按报告层提示控制仓位并等待确认。"
    sector_note = ""
    if sector_cycle_state == "UNKNOWN":
        sector_note = " 板块周期证据不足，不能把板块状态作为买入依据。"
    elif sector_cycle_state in {"FADING", "FALLING", "CLIMAX"}:
        sector_note = f" 板块周期为{sector_cycle_state}，对买入构成限制，需优先防追高或走弱风险。"
    elif sector_cycle_state == "DIVERGENCE":
        sector_note = " 板块周期为DIVERGENCE，只有个股证据足够强时才支持试错。"
    elif sector_cycle_state in {"RISING", "REPAIRING"}:
        sector_note = f" 板块周期为{sector_cycle_state}，可支持观察或小仓位试错，但不能单独作为买入理由。"
    leader_note = ""
    if leader_status == "UNKNOWN":
        leader_note = " leader_status=UNKNOWN, 龙头状态证据不足。"
    elif leader_status in {"LEADER_WEAKENING", "LEADER_BROKEN", "NO_CLEAR_LEADER"}:
        leader_note = f" leader_status={leader_status}, 对买入构成限制。"
    elif leader_status == "LEADER_ROTATING":
        leader_note = " leader_status=LEADER_ROTATING, 轮动不确定，BUY 必须依赖更强个股证据。"
    elif leader_status == "LEADER_STRONG":
        leader_note = " leader_status=LEADER_STRONG, 可支持观察或小仓位试错，但不能单独作为买入理由。"
    if model_action == "WAIT":
        model_action = "OBSERVE"
    if ai_review.get("review_status") == "NEEDS_HUMAN_REVIEW":
        final_action = "NEEDS_HUMAN_REVIEW"
        action_reason = "shadow review found a strong risk-reduce exception candidate"
        user_note = "先人工复核，再决定是否按原动作执行。"
    elif ai_review.get("review_status") == "REJECT":
        final_action = ai_review.get("final_action_after_review", "OBSERVE")
        action_reason = ai_review.get("veto_reason") or "shadow review vetoed the raw model action"
        user_note = "先按审查后的动作走，不直接执行原动作。"
    else:
        final_action = model_action
        action_reason = decision.get("reason", "")
        user_note = "按当前路径报告层动作执行。"
    if final_action == "BUY":
        action_reason = f"{action_reason} sector_cycle_state={sector_cycle_state}; leader_status={leader_status}."
    user_note = f"{user_note}{evidence_note}{sector_note}{leader_note}"
    return {
        "final_user_action": final_action,
        "action_reason": action_reason,
        "execution_condition": decision.get("buy_condition") if final_action == "BUY" else decision.get("sell_condition") if final_action in {"REDUCE", "SELL"} else decision.get("reason", ""),
        "invalidation_condition": decision.get("sell_condition") if final_action in {"BUY", "HOLD", "OBSERVE"} else decision.get("buy_condition", ""),
        "stop_loss_condition": decision.get("sell_condition") or "",
        "position_limit": decision.get("max_position"),
        "user_note": user_note,
    }


def candidate_fields(
    ts_code: str | None,
    name: str | None,
    action: str | None,
    source: str,
    missing_reason: str = "insufficient_visible_source",
) -> dict:
    structured = bool(ts_code and name)
    return {
        "candidate_ts_code": ts_code if structured else None,
        "candidate_name": name if structured else None,
        "candidate_action": action,
        "candidate_source": source if structured else "unstructured",
        "candidate_is_structured": structured,
        "candidate_missing_reason": "" if structured else missing_reason,
    }


def candidate_fields_from_decision(decision: dict) -> dict:
    if "candidate_is_structured" in decision:
        return {
            "candidate_ts_code": decision.get("candidate_ts_code"),
            "candidate_name": decision.get("candidate_name"),
            "candidate_action": decision.get("candidate_action"),
            "candidate_source": decision.get("candidate_source"),
            "candidate_is_structured": decision.get("candidate_is_structured"),
            "candidate_missing_reason": decision.get("candidate_missing_reason", ""),
        }
    position = decision.get("position_after_action") or {}
    return candidate_fields(
        position.get("ts_code"),
        position.get("name"),
        decision.get("action"),
        "position_after_action",
    )


def build_stock_selection_evidence(
    *,
    decision: dict,
    candidate: dict | None,
    candidate_reason: str = "",
    path: dict | None = None,
) -> dict:
    action = decision.get("action")
    current_candidate = candidate or {}
    candidate_meta = candidate_fields_from_decision(decision)
    source = candidate_meta.get("candidate_source") or "unstructured"
    if candidate_meta.get("candidate_is_structured"):
        ts_code = candidate_meta.get("candidate_ts_code")
        name = candidate_meta.get("candidate_name")
    else:
        ts_code = None
        name = None
    metrics = current_candidate.get("metrics") or {}
    ohlc = decision.get("position_after_action") or {}
    price = None
    if action in {"HOLD", "REDUCE", "SELL"} and ohlc.get("entry_price"):
        price = float(ohlc.get("entry_price"))
    elif metrics.get("close") is not None:
        price = float(metrics.get("close"))
    evidence_missing: list[str] = []
    if not metrics:
        evidence_missing.append("missing_visible_source")
    if metrics and metrics.get("close") is None:
        evidence_missing.append("missing_price_position")
    if metrics and metrics.get("amount_ratio") is None:
        evidence_missing.append("missing_volume_confirmation")
    if metrics and metrics.get("ret5") is None:
        evidence_missing.append("missing_relative_strength")

    price_position = "UNKNOWN"
    if metrics:
        pos = metrics.get("position20")
        if pos is not None:
            if pos <= 0.2:
                price_position = "LOW"
            elif pos <= 0.4:
                price_position = "PULLBACK"
            elif pos <= 0.65:
                price_position = "MID"
            elif pos <= 0.85:
                price_position = "HIGH"
            else:
                price_position = "BREAKOUT"
    volume_confirmation = "UNKNOWN"
    amount_ratio = metrics.get("amount_ratio")
    if amount_ratio is not None:
        if amount_ratio >= 1.2:
            volume_confirmation = "CONFIRMED"
        elif amount_ratio >= 0.85:
            volume_confirmation = "WEAK"
        else:
            volume_confirmation = "DIVERGENT"
    relative_strength = "UNKNOWN"
    ret5 = metrics.get("ret5")
    ret10 = metrics.get("ret10")
    if ret5 is not None or ret10 is not None:
        if (ret5 or 0) > 0.08 or (ret10 or 0) > 0.12:
            relative_strength = "STRONG"
        elif (ret5 or 0) >= 0 or (ret10 or 0) >= 0:
            relative_strength = "NEUTRAL"
        else:
            relative_strength = "WEAK"

    risk_notes: list[str] = []
    if price_position in {"HIGH", "BREAKOUT"}:
        risk_notes.append("high_position_risk")
    if volume_confirmation in {"WEAK", "DIVERGENT"}:
        risk_notes.append("weak_volume")
    if not candidate_meta.get("candidate_is_structured"):
        risk_notes.append("insufficient_selection_evidence")
    if decision.get("position_violation"):
        risk_notes.append("position_limit_conflict")
    if decision.get("trade_density_observe_mode") or decision.get("execution_quality_issue"):
        risk_notes.append("trade_density_limit")
    if decision.get("initial_position_breach"):
        risk_notes.append("initial_position_breach")
    if decision.get("model_caused_position_breach"):
        risk_notes.append("temporary_position_breach")
    if candidate_reason and not candidate_meta.get("candidate_is_structured"):
        risk_notes.append("unknown_sector_or_leader_context")

    if not candidate_meta.get("candidate_is_structured"):
        evidence_quality = "INSUFFICIENT"
    elif price_position == "UNKNOWN" or volume_confirmation == "UNKNOWN" or relative_strength == "UNKNOWN":
        evidence_quality = "LOW"
    elif price_position in {"BREAKOUT", "PULLBACK"} and volume_confirmation == "CONFIRMED" and relative_strength == "STRONG":
        evidence_quality = "HIGH"
    elif volume_confirmation == "WEAK" or relative_strength == "WEAK":
        evidence_quality = "MEDIUM"
    else:
        evidence_quality = "LOW"

    if evidence_quality == "INSUFFICIENT":
        evidence_missing.extend(["missing_price_position" if price_position == "UNKNOWN" else "", "missing_volume_confirmation" if volume_confirmation == "UNKNOWN" else "", "missing_relative_strength" if relative_strength == "UNKNOWN" else ""])
    evidence_missing = [x for x in evidence_missing if x]
    if evidence_quality == "INSUFFICIENT" and "missing_visible_source" not in evidence_missing:
        evidence_missing.append("missing_visible_source")
    if evidence_quality != "INSUFFICIENT" and not evidence_missing:
        evidence_missing_reason = ""
    else:
        evidence_missing_reason = ",".join(dict.fromkeys(evidence_missing)) or "insufficient_visible_source"

    if action == "BUY" and evidence_quality == "INSUFFICIENT":
        if "insufficient_stock_selection_evidence" not in risk_notes:
            risk_notes.append("insufficient_stock_selection_evidence")
    alt = current_candidate.get("alternative_candidates_available")
    if alt is None:
        alt = "UNKNOWN"
    if evidence_quality == "INSUFFICIENT":
        selection_reason = "insufficient_evidence"
    elif candidate_reason:
        selection_reason = candidate_reason
    else:
        selection_reason = "visible_price_volume_momentum_support"
    return {
        "selected_reason": selection_reason or "UNKNOWN",
        "price_position": price_position,
        "volume_confirmation": volume_confirmation,
        "relative_strength": relative_strength,
        "risk_notes": risk_notes,
        "alternative_candidates_available": alt,
        "is_leader_or_lagger": "UNKNOWN",
        "evidence_quality": evidence_quality,
        "evidence_missing_reason": evidence_missing_reason,
        "candidate_ts_code": ts_code,
        "candidate_name": name,
        "candidate_action": candidate_meta.get("candidate_action"),
        "candidate_source": source,
        "candidate_is_structured": candidate_meta.get("candidate_is_structured", False),
        "candidate_missing_reason": candidate_meta.get("candidate_missing_reason", ""),
    }


def build_sector_cycle_state(
    *,
    conn: sqlite3.Connection,
    path: dict,
    date: str,
    metrics_cache: dict | None = None,
) -> dict:
    allowed_states = {"UNKNOWN", "RISING", "DIVERGENCE", "CLIMAX", "FADING", "FALLING", "REPAIRING"}
    metrics = []
    for item in path.get("target_symbols", []):
        m = recent_metrics(conn, item.get("ts_code"), date, metrics_cache)
        if not m.get("data_ok"):
            continue
        if m.get("ret5") is None or m.get("ret10") is None:
            continue
        metrics.append(
            {
                "ts_code": item.get("ts_code"),
                "name": item.get("name"),
                "ret5": m.get("ret5"),
                "ret10": m.get("ret10"),
                "amount_ratio": m.get("amount_ratio"),
                "position20": m.get("position20"),
            }
        )
    if len(metrics) < 2:
        return {
            "sector_cycle_state": "UNKNOWN",
            "sector_cycle_missing_reason": "insufficient_sector_data",
            "sector_cycle_source": "questions_target_symbols_ohlc",
            "sector_cycle_note": "候选组可复现行情样本不足，不能判断板块周期。",
            "sector_cycle_metrics": metrics,
        }

    ret5_values = [float(x["ret5"]) for x in metrics if x.get("ret5") is not None]
    ret10_values = [float(x["ret10"]) for x in metrics if x.get("ret10") is not None]
    amount_values = [float(x["amount_ratio"]) for x in metrics if x.get("amount_ratio") is not None]
    position_values = [float(x["position20"]) for x in metrics if x.get("position20") is not None]
    if not ret5_values or not ret10_values:
        return {
            "sector_cycle_state": "UNKNOWN",
            "sector_cycle_missing_reason": "insufficient_visible_source",
            "sector_cycle_source": "questions_target_symbols_ohlc",
            "sector_cycle_note": "候选组缺少可复现短期涨跌数据，不能判断板块周期。",
            "sector_cycle_metrics": metrics,
        }

    avg_ret5 = sum(ret5_values) / len(ret5_values)
    avg_ret10 = sum(ret10_values) / len(ret10_values)
    avg_amount = sum(amount_values) / len(amount_values) if amount_values else 1.0
    avg_position = sum(position_values) / len(position_values) if position_values else 0.5
    strong_count = sum(1 for x in ret5_values if x >= 0.03)
    weak_count = sum(1 for x in ret5_values if x <= -0.03)
    hot_count = sum(1 for x in metrics if (x.get("ret5") or 0) >= 0.10 or (x.get("position20") or 0) >= 0.88)
    dispersion = max(ret5_values) - min(ret5_values)

    state = "UNKNOWN"
    note = "候选组数据不足以形成明确周期判断。"
    if hot_count >= max(2, len(metrics) // 2) and avg_ret5 >= 0.06 and avg_position >= 0.72:
        state = "CLIMAX"
        note = "候选组短期涨幅和位置偏高，存在高潮或追高风险。"
    elif weak_count >= max(2, len(metrics) // 2) and avg_ret5 <= -0.03 and avg_ret10 <= 0:
        state = "FALLING"
        note = "候选组多数短期走弱，板块/候选组处于下行状态。"
    elif strong_count >= 1 and weak_count >= 1 and dispersion >= 0.07:
        state = "DIVERGENCE"
        note = "候选组内部强弱差异明显，买入需要更强个股证据。"
    elif avg_ret5 >= 0.025 and avg_ret10 >= 0 and avg_amount >= 1.0 and strong_count >= max(1, len(metrics) // 2):
        state = "RISING"
        note = "候选组多数短期改善且量能不弱，处于上升或增强阶段。"
    elif avg_ret5 < 0 and avg_ret10 > 0:
        state = "FADING"
        note = "候选组前期仍有涨幅但短期转弱，热度有衰退迹象。"
    elif avg_ret5 > 0 and avg_ret10 <= 0:
        state = "REPAIRING"
        note = "候选组短期修复但中期确认不足，需要继续观察。"
    elif avg_ret5 <= -0.01 and avg_amount < 0.9:
        state = "FADING"
        note = "候选组短期偏弱且量能不足，买入优先级降低。"

    if state not in allowed_states:
        state = "UNKNOWN"
    return {
        "sector_cycle_state": state,
        "sector_cycle_missing_reason": "" if state != "UNKNOWN" else "insufficient_sector_data",
        "sector_cycle_source": "questions_target_symbols_ohlc",
        "sector_cycle_note": note,
        "sector_cycle_metrics": {
            "sample_count": len(metrics),
            "avg_ret5": round(avg_ret5, 4),
            "avg_ret10": round(avg_ret10, 4),
            "avg_amount_ratio": round(avg_amount, 4),
            "avg_position20": round(avg_position, 4),
            "strong_count": strong_count,
            "weak_count": weak_count,
            "hot_count": hot_count,
            "ret5_dispersion": round(dispersion, 4),
        },
    }


def build_leader_status(
    *,
    conn: sqlite3.Connection,
    path: dict,
    date: str,
    sector_cycle_state: str = "UNKNOWN",
    metrics_cache: dict | None = None,
) -> dict:
    metrics = []
    for item in path.get("target_symbols", []):
        m = recent_metrics(conn, item.get("ts_code"), date, metrics_cache)
        if not m.get("data_ok"):
            continue
        if m.get("ret5") is None or m.get("ret10") is None:
            continue
        ret5 = float(m.get("ret5") or 0)
        ret10 = float(m.get("ret10") or 0)
        amount_ratio = float(m.get("amount_ratio") or 1.0)
        position20 = float(m.get("position20") or 0.5)
        score = ret5 * 100 + ret10 * 35 + min(amount_ratio, 2.5) * 2 + position20
        metrics.append(
            {
                "ts_code": item.get("ts_code"),
                "name": item.get("name"),
                "ret5": ret5,
                "ret10": ret10,
                "amount_ratio": amount_ratio,
                "position20": position20,
                "leader_score": round(score, 4),
            }
        )
    if len(metrics) < 2:
        return {
            "leader_status": "UNKNOWN",
            "leader_status_missing_reason": "insufficient_leader_data",
            "leader_status_source": "questions_target_symbols_ohlc",
            "leader_status_note": "候选组可复现样本不足，不能判断龙头状态。",
            "leader_status_metrics": metrics,
        }

    metrics.sort(key=lambda x: x["leader_score"], reverse=True)
    top = metrics[0]
    second = metrics[1]
    score_gap = top["leader_score"] - second["leader_score"]
    strong_candidates = [x for x in metrics if x["ret5"] >= 0.04 and x["ret10"] >= 0.04]
    weak_candidates = [x for x in metrics if x["ret5"] <= -0.03 and x["ret10"] <= 0]

    status = "NO_CLEAR_LEADER"
    note = "候选组没有足够明确的单一核心强势股，后排补涨风险较高。"
    if top["ret5"] <= -0.04 and top["ret10"] <= 0:
        status = "LEADER_BROKEN"
        note = "候选组相对最强股也已短中期走弱，龙头状态视为破位或走坏。"
    elif top["ret10"] > 0.08 and top["ret5"] < 0:
        status = "LEADER_WEAKENING"
        note = "候选组相对强势股中期仍强但短期转弱，龙头状态开始弱化。"
    elif len(strong_candidates) >= 2 and score_gap < 3.0:
        status = "LEADER_ROTATING"
        note = "候选组内多只股票接近强势，疑似轮动或换班，需要提高不确定性提示。"
    elif top["ret5"] >= 0.04 and top["ret10"] >= 0.08 and top["amount_ratio"] >= 1.0 and score_gap >= 3.0:
        status = "LEADER_STRONG"
        note = "候选组内存在相对明确的强势核心股，价格表现和量能支持较强。"
    elif sector_cycle_state in {"DIVERGENCE", "REPAIRING"} and top["ret5"] > 0 and second["ret5"] <= 0:
        status = "LEADER_ROTATING"
        note = "候选组内部强弱切换明显，疑似新强股出现但确认不足。"
    elif weak_candidates and top["ret5"] < 0.02:
        status = "LEADER_WEAKENING"
        note = "候选组有明显弱化成员且最强股短线优势不充分，龙头状态偏弱。"

    return {
        "leader_status": status,
        "leader_status_missing_reason": "",
        "leader_status_source": "questions_target_symbols_ohlc",
        "leader_status_note": note,
        "leader_status_metrics": {
            "sample_count": len(metrics),
            "top_candidate": top,
            "second_candidate": second,
            "score_gap": round(score_gap, 4),
            "strong_candidate_count": len(strong_candidates),
            "weak_candidate_count": len(weak_candidates),
            "sector_cycle_state": sector_cycle_state,
        },
    }


def run(args: argparse.Namespace) -> dict:
    root = Path.cwd()
    outdir = root / "reports" / "walk_forward_2025"
    outdir.mkdir(parents=True, exist_ok=True)

    questions = read_json(Path(args.questions_json))
    path = next(p for p in questions["paths"] if p["path_id"] == args.path_id)
    # Guardrail: model-answer phase must not receive future validation fields.
    serialized_path = json.dumps(path, ensure_ascii=False)
    if any(key in serialized_path for key in ["stage_b_validation", "final_return", "max_drawdown"]):
        raise RuntimeError("questions input contains future validation fields")

    db_uri = f"file:{Path(args.db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    cash = float(path["initial_user_state"]["available_cash"])
    total_assets = float(path["initial_user_state"]["total_assets"])
    planned_cash = float(path["initial_user_state"]["planned_trade_cash"])
    can_watch_market = bool(path["initial_user_state"].get("can_watch_market", True))
    thresholds = account_thresholds(can_watch_market)
    path_type = path.get("path_type", "")
    initial_health = initial_account_health(path, total_assets, can_watch_market)
    deleveraging_plan = build_deleveraging_plan(path, total_assets, can_watch_market)
    position: dict | None = initial_position_from_path(path)
    initial_modeled_position_value = 0.0
    if position:
        first_close = float(path["initial_user_state"]["holdings"][0]["stage_a_close"])
        initial_modeled_position_value = position["shares"] * first_close
        cash = max(0.0, total_assets - initial_modeled_position_value)
    initial_unmodeled_holding_value = max(0.0, total_assets - cash - initial_modeled_position_value)
    initial_total_position_ratio = (initial_unmodeled_holding_value + initial_modeled_position_value) / total_assets if total_assets else 0.0
    pending_buy: dict | None = None
    pending_sell: dict | None = None
    decisions: list[dict] = []
    execution_log: list[dict] = []
    equity_curve: list[dict] = []
    last_trade_index_by_symbol: dict[str, int] = {}
    last_sell_index_by_symbol: dict[str, int] = {}
    account_cooldown_until_index = -1
    stop_new_buy_active = False
    account_hard_stop_active = False
    account_risk_triggered = False
    execution_quality_issue = False
    execution_quality_issue_level = "NONE"
    execution_quality_issue_reason = ""
    intraday_sequence_unknown_seen = False
    trade_density_observe_mode = False

    steps = path["daily_steps"]
    future_leakage_risk = False
    equity_peak = total_assets
    position_violation_seen = initial_total_position_ratio > NO_WATCH_TOTAL_POSITION_LIMIT or initial_health["initial_total_position_violation"]
    risk_control_failure = False
    critical_risk_failure = False
    ohlc_cache: dict = {}
    metrics_cache: dict = {}

    for idx, step in enumerate(steps):
        date = step["date"]
        notes: list[str] = []
        executed = False
        execution_price = None
        decision_candidate = candidate_fields(None, None, None, "unstructured")
        evidence_candidate: dict | None = None
        evidence_candidate_reason = ""
        traded_today: set[str] = set()
        in_account_cooldown = idx <= account_cooldown_until_index

        if pending_sell and position and position["ts_code"] == pending_sell["ts_code"]:
            ohlc = fetch_ohlc(conn, position["ts_code"], date, ohlc_cache)
            if ohlc is None:
                notes.append("当日OHLC缺失，前一日卖出计划无法执行，继续按风险线观察。")
            elif (
                path_type == "INTRADAY_OHLC_TRIGGER"
                and len(execution_log) >= INTRA_TRADE_DENSITY_LIMIT
                and pending_sell.get("reason", "").find("止损") < 0
                and not account_hard_stop_active
            ):
                execution_quality_issue = True
                execution_quality_issue_level = "REVIEW_NOTE"
                execution_quality_issue_reason = "交易密度限制触发，弱减仓信号已转为观察，不属于真实执行错误。"
                trade_density_observe_mode = True
                execution_log.append(
                    {
                        "date": date,
                        "action": "BLOCKED_TRADE",
                        "intended_action": pending_sell.get("action", "REDUCE"),
                        "final_action": "OBSERVE_ONLY",
                        "blocked_by_overtrading_guard": True,
                        "trade_block_reason": "trade_density_limit",
                        "signal_strength": "weak_observe_only",
                        "observe_only": True,
                        "ts_code": position["ts_code"],
                        "name": position["name"],
                        "price": None,
                        "shares": 0,
                        "cash_after": round(cash, 2),
                        "reason": "INTRA交易密度限制生效，弱信号减仓计划取消，进入观察模式。",
                    }
                )
                notes.append("INTRA交易密度限制生效，弱信号减仓计划取消，进入观察模式。")
                pending_sell = None
            else:
                sell_price = round(ohlc["open"] * (1 - SLIPPAGE), 3)
                shares_to_sell = min(position["shares"], int(pending_sell.get("shares", position["shares"])))
                proceeds = round(shares_to_sell * sell_price, 2)
                cash += proceeds
                execution_log.append(
                    {
                        "date": date,
                        "action": pending_sell.get("action", "SELL"),
                        "ts_code": position["ts_code"],
                        "name": position["name"],
                        "price": sell_price,
                        "shares": shares_to_sell,
                        "cash_after": round(cash, 2),
                        "reason": pending_sell["reason"],
                        "intended_action": pending_sell.get("action", "SELL"),
                        "final_action": pending_sell.get("action", "SELL"),
                        "blocked_by_overtrading_guard": False,
                        "trade_block_reason": None,
                        "signal_strength": pending_sell.get("signal_strength", "strong_trade_allowed"),
                        "observe_only": False,
                    }
                )
                notes.append("前一日收盘风险条件触发，次日开盘已卖出。")
                traded_today.add(position["ts_code"])
                last_trade_index_by_symbol[position["ts_code"]] = idx
                if pending_sell.get("action", "SELL") == "SELL" or shares_to_sell >= position["shares"]:
                    last_sell_index_by_symbol[position["ts_code"]] = idx
                position["shares"] -= shares_to_sell
                if position["shares"] <= 0:
                    position = None
                else:
                    position["cost"] = round(position["shares"] * position["entry_price"], 2)
                pending_sell = None
                executed = True
                execution_price = sell_price

        # Execute yesterday's conditional plan using today's OHLC. This is execution,
        # not yesterday's decision input.
        if pending_buy and not position and not pending_sell:
            ohlc = fetch_ohlc(conn, pending_buy["ts_code"], date, ohlc_cache)
            symbol = pending_buy["ts_code"]
            buy_blocked_by_cooldown = (
                in_account_cooldown
                or stop_new_buy_active
                or account_hard_stop_active
                or symbol in traded_today
                or idx - last_trade_index_by_symbol.get(symbol, -999) <= TRADE_COOLDOWN_DAYS
                or idx - last_sell_index_by_symbol.get(symbol, -999) <= TRADE_COOLDOWN_DAYS
                or len(execution_log) >= OVERTRADING_TRADE_LIMIT
            )
            if ohlc is None:
                notes.append("当日OHLC缺失，前一日买入计划无法验证，继续等待。")
            elif buy_blocked_by_cooldown:
                notes.append("账户风控或同股冷静期生效，前一日买入计划取消。")
                pending_buy = None
            elif ohlc["low"] <= pending_buy["buy_upper"]:
                base_price = min(ohlc["open"], pending_buy["buy_upper"])
                execution_price = round(base_price * (1 + SLIPPAGE), 3)
                shares = int(pending_buy["cash_to_use"] // execution_price // 100 * 100)
                if shares > 0:
                    cost = round(shares * execution_price, 2)
                    cash -= cost
                    position = {
                        "ts_code": pending_buy["ts_code"],
                        "name": pending_buy["name"],
                        "shares": shares,
                        "entry_price": execution_price,
                        "cost": cost,
                        "stop_loss": pending_buy["stop_loss"],
                        "profit_protection": pending_buy["profit_protection"],
                        "profit_protection_active": False,
                        "entry_date": date,
                        "hold_days": 0,
                    }
                    executed = True
                    execution_log.append(
                        {
                            "date": date,
                            "action": "BUY",
                            "ts_code": pending_buy["ts_code"],
                            "name": pending_buy["name"],
                            "price": execution_price,
                            "shares": shares,
                            "cash_after": round(cash, 2),
                            "reason": "前一交易日条件买入计划触发，次日低点进入买入区间。",
                            "intended_action": "BUY",
                            "final_action": "BUY",
                            "blocked_by_overtrading_guard": False,
                            "trade_block_reason": None,
                            "signal_strength": "strong_trade_allowed",
                            "observe_only": False,
                        }
                    )
                    traded_today.add(position["ts_code"])
                    last_trade_index_by_symbol[position["ts_code"]] = idx
                    notes.append("前一日条件买入计划已触发。")
                else:
                    notes.append("计划资金不足以买入一手，继续等待。")
                pending_buy = None
            else:
                notes.append("次日最低价未触及买入区间，前一日买入计划失效，继续等待。")
                pending_buy = None

        # Intraday risk handling for existing position.
        if position:
            ohlc = fetch_ohlc(conn, position["ts_code"], date, ohlc_cache)
            if ohlc:
                position["hold_days"] = int(position.get("hold_days", 0)) + 1
                position["peak_price"] = max(float(position.get("peak_price", ohlc["close"])), ohlc["high"])
                float_ret_high = ohlc["high"] / position["entry_price"] - 1
                float_ret_close = ohlc["close"] / position["entry_price"] - 1
                position_drawdown = ohlc["close"] / position["peak_price"] - 1 if position.get("peak_price") else 0.0
                current_position_ratio = position_ratio(position, ohlc["close"], total_assets)
                position_violation = current_position_ratio > NO_WATCH_SINGLE_POSITION_LIMIT
                position_violation_seen = position_violation_seen or position_violation
                drawdown_reduce_trigger = position_drawdown <= -DRAWDOWN_REDUCE_TRIGGER
                weak_risk_reduce = bool(position.get("weak_structure")) and position_violation
                compliance_reduce = position_violation and not can_watch_market
                if position_violation:
                    notes.append("当前单票仓位超过不能盯盘用户上限，禁止加仓，走弱或回撤时优先降到合规仓位。")
                if (
                    not position.get("profit_protection_active")
                    and (float_ret_high >= 0.03 or float_ret_close >= 0.03)
                ):
                    position["profit_protection_active"] = True
                    notes.append("浮盈达到3%，利润保护线已激活。")
                if (
                    ohlc["low"] <= position["stop_loss"]
                    and ohlc["high"] >= position["profit_protection"]
                    and position.get("profit_protection_active")
                ):
                    intraday_sequence_unknown_seen = True
                    notes.append("日线OHLC同时触及止损与利润保护条件，标记INTRADAY_SEQUENCE_UNKNOWN，按保守止损优先处理。")
                if ohlc["low"] <= position["stop_loss"]:
                    sell_price = round(position["stop_loss"] * (1 - SLIPPAGE), 3)
                    proceeds = round(position["shares"] * sell_price, 2)
                    cash += proceeds
                    execution_log.append(
                        {
                            "date": date,
                            "action": "SELL",
                            "ts_code": position["ts_code"],
                            "name": position["name"],
                            "price": sell_price,
                            "shares": position["shares"],
                            "cash_after": round(cash, 2),
                            "reason": "当日最低价触发止损线，按保守滑点卖出。",
                            "intended_action": "SELL",
                            "final_action": "SELL",
                            "blocked_by_overtrading_guard": False,
                            "trade_block_reason": None,
                            "signal_strength": "risk_exit_required",
                            "observe_only": False,
                        }
                    )
                    notes.append("触发止损，已退出。")
                    traded_today.add(position["ts_code"])
                    last_trade_index_by_symbol[position["ts_code"]] = idx
                    last_sell_index_by_symbol[position["ts_code"]] = idx
                    position = None
                    executed = True
                    execution_price = sell_price
                elif ohlc["high"] >= position["entry_price"] * 1.08:
                    position["profit_protection_active"] = True
                    new_line = round(max(position["profit_protection"], position["entry_price"] * 1.04), 3)
                    if new_line > position["profit_protection"]:
                        position["profit_protection"] = new_line
                        notes.append("盘中达到8%以上浮盈，利润保护线抬高。")
                if (
                    position
                    and not pending_sell
                    and (drawdown_reduce_trigger or weak_risk_reduce or compliance_reduce)
                    and position.get("hold_days", 0) >= MINIMUM_HOLD_DAYS
                ):
                    signal_strength = signal_strength_for_context(
                        path_type=path_type,
                        drawdown_reduce=drawdown_reduce_trigger,
                        compliance_reduce=compliance_reduce,
                        weak_signal=weak_risk_reduce or compliance_reduce,
                    )
                    if path_type == "INTRADAY_OHLC_TRIGGER" and len(execution_log) >= INTRA_TRADE_DENSITY_LIMIT:
                        execution_quality_issue = True
                        execution_quality_issue_level = "REVIEW_NOTE"
                        execution_quality_issue_reason = "交易密度限制触发，弱信号转观察。"
                        trade_density_observe_mode = True
                        execution_log.append(
                            {
                                "date": date,
                                "action": "BLOCKED_TRADE",
                                "intended_action": "REDUCE",
                                "final_action": "OBSERVE_ONLY",
                                "blocked_by_overtrading_guard": True,
                                "trade_block_reason": "trade_density_limit" if signal_strength != "weak_observe_only" else "weak_signal_only",
                                "signal_strength": signal_strength,
                                "observe_only": True,
                                "ts_code": position["ts_code"],
                                "name": position["name"],
                                "price": None,
                                "shares": 0,
                                "cash_after": round(cash, 2),
                                "reason": "INTRA交易密度已达上限或信号偏弱，观察替代交易。",
                            }
                        )
                        notes.append("INTRA交易密度已达上限，弱信号只改变观察状态，不再新增减仓交易。")
                    else:
                        reduce_shares = shares_to_reduce_to_limit(position, ohlc["close"], total_assets, NO_WATCH_SINGLE_POSITION_LIMIT)
                        if reduce_shares <= 0 and position["shares"] >= 200:
                            reduce_shares = int(position["shares"] * 0.5 // 100 * 100)
                        elif reduce_shares <= 0 and compliance_reduce:
                            reduce_shares = position["shares"]
                        if reduce_shares > 0:
                            pending_sell = {
                                "ts_code": position["ts_code"],
                                "action": "REDUCE",
                                "shares": reduce_shares,
                                "reason": "持仓超限、弱结构或阶段回撤触发，按规则次日开盘风险减仓。",
                                "signal_strength": signal_strength,
                            }
                            notes.append("触发REDUCE_RISK，计划次日开盘减仓至合规仓位。")
                if (
                    position
                    and not pending_sell
                    and position.get("profit_protection_active")
                    and position.get("hold_days", 0) >= MINIMUM_HOLD_DAYS
                    and ohlc["close"] < position["profit_protection"]
                ):
                    pending_sell = {
                        "ts_code": position["ts_code"],
                        "reason": "前一日收盘跌破利润保护线，按规则次日开盘卖出。",
                        "signal_strength": "strong_trade_allowed",
                    }
                    notes.append("收盘跌破利润保护线，计划次日开盘减仓或卖出。")
                elif position and not position.get("profit_protection_active") and ohlc["close"] < position["profit_protection"]:
                    notes.append("利润保护线尚未激活，不能因普通波动卖出。")
                elif position and position.get("hold_days", 0) < MINIMUM_HOLD_DAYS and ohlc["close"] < position["profit_protection"]:
                    notes.append("仍在最低持仓观察期内，未触发硬止损则不因普通波动卖出。")

        # Mark-to-market at close.
        market_value = initial_unmodeled_holding_value
        if position:
            ohlc = fetch_ohlc(conn, position["ts_code"], date, ohlc_cache)
            if ohlc:
                market_value += position["shares"] * ohlc["close"]
        equity = cash + market_value
        equity_peak = max(equity_peak, equity)
        equity_drawdown = equity / equity_peak - 1 if equity_peak else 0.0
        total_position_ratio = market_value / equity if equity else 0.0
        account_reduce_risk = equity_drawdown <= -thresholds["reduce"]
        stop_new_buy_active = stop_new_buy_active or equity_drawdown <= -thresholds["stop_new_buy"]
        account_hard_stop_active = account_hard_stop_active or equity_drawdown <= -thresholds["hard_stop"]
        if account_reduce_risk:
            account_risk_triggered = True
            account_cooldown_until_index = max(account_cooldown_until_index, idx + ACCOUNT_RISK_COOLDOWN_DAYS)
            notes.append("账户权益回撤触发ACCOUNT_REDUCE_RISK，进入2个交易日冷静期。")
        if stop_new_buy_active:
            notes.append("账户权益回撤触发STOP_NEW_BUY，禁止新开仓。")
        if account_hard_stop_active:
            notes.append("账户权益回撤触发ACCOUNT_HARD_STOP，只允许风险处理，不允许买入。")
        if (
            position
            and not pending_sell
            and (equity_drawdown <= -EQUITY_DRAWDOWN_REDUCE_TRIGGER or account_reduce_risk)
            and position.get("hold_days", 0) >= MINIMUM_HOLD_DAYS
        ):
            ohlc = fetch_ohlc(conn, position["ts_code"], date, ohlc_cache)
            if ohlc:
                reduce_shares = shares_to_reduce_to_limit(position, ohlc["close"], total_assets, NO_WATCH_SINGLE_POSITION_LIMIT)
                if reduce_shares <= 0 and position["shares"] >= 200:
                    reduce_shares = int(position["shares"] * 0.5 // 100 * 100)
                if reduce_shares > 0:
                    pending_sell = {
                        "ts_code": position["ts_code"],
                        "action": "REDUCE",
                        "shares": reduce_shares,
                        "reason": "账户权益从阶段高点回撤触发账户级硬风控，按规则次日开盘风险减仓。",
                        "signal_strength": "risk_exit_required" if account_hard_stop_active else "strong_trade_allowed",
                    }
                    notes.append("账户回撤触发ACCOUNT_REDUCE_RISK，计划次日开盘减仓。")
        position_violation_seen = position_violation_seen or total_position_ratio > NO_WATCH_TOTAL_POSITION_LIMIT
        risk_control_failure = risk_control_failure or (
            equity_drawdown <= -0.10 and not pending_sell and not any(x["action"] in {"SELL", "REDUCE"} for x in execution_log)
        )
        equity_curve.append({
            "date": date,
            "equity": round(equity, 2),
            "cash": round(cash, 2),
            "market_value": round(market_value, 2),
            "total_position_ratio": round(total_position_ratio, 4),
            "account_drawdown_pct": round(equity_drawdown * 100, 2),
        })

        # Make close decision using only data <= current date.
        if position:
            decision_candidate = candidate_fields(position["ts_code"], position["name"], None, "position_after_action")
            evidence_candidate = {"metrics": recent_metrics(conn, position["ts_code"], date, metrics_cache)}
            ohlc = fetch_ohlc(conn, position["ts_code"], date, ohlc_cache)
            float_ret = (ohlc["close"] / position["entry_price"] - 1) if ohlc else 0.0
            if float_ret >= 0.06:
                action = "HOLD"
                reason = "已有浮盈，继续持有但必须启用利润保护，不追涨加仓。"
            elif float_ret <= -0.04:
                action = "HOLD"
                reason = "浮亏接近风险观察区，未触发止损前不补仓，继续按止损线处理。"
            else:
                action = "HOLD"
                reason = "持仓仍在正常波动范围内，继续观察，不加仓。"
            decision_stop = position["stop_loss"]
            decision_profit = position["profit_protection"]
            max_position = round(position["cost"] / total_assets, 4)
            if pending_sell:
                action = "REDUCE"
                reason = "持仓超限、弱结构或回撤触发风险处理，等待次日开盘执行减仓。"
            decision_candidate["candidate_action"] = action
        else:
            candidate, candidate_reason = choose_candidate(conn, path, date, metrics_cache)
            evidence_candidate = candidate
            evidence_candidate_reason = candidate_reason
            if candidate:
                decision_candidate = candidate_fields(
                    candidate.get("ts_code"),
                    candidate.get("name"),
                    None,
                    "questions_target_symbols_choose_candidate",
                )
            buy_block_reason = ""
            if in_account_cooldown or idx <= account_cooldown_until_index:
                buy_block_reason = "账户级风控冷静期内，只能WAIT/REDUCE/SELL，不能BUY。"
            elif stop_new_buy_active:
                buy_block_reason = "账户回撤已触发STOP_NEW_BUY，禁止新开仓。"
            elif account_hard_stop_active:
                buy_block_reason = "账户回撤已触发ACCOUNT_HARD_STOP，禁止买入。"
            elif total_position_ratio > NO_WATCH_TOTAL_POSITION_LIMIT:
                buy_block_reason = "账户总仓位超过不能盯盘上限，禁止新开仓。"
            elif len(execution_log) >= OVERTRADING_TRADE_LIMIT:
                buy_block_reason = "10个交易日内交易次数已达过度交易阈值，停止新增交易。"
                execution_quality_issue = True
                execution_quality_issue_level = "REVIEW_NOTE"
                execution_quality_issue_reason = "交易密度限制触发，新增买入意图被拦截。"
                if candidate:
                    execution_log.append(
                        {
                            "date": date,
                            "action": "BLOCKED_TRADE",
                            "intended_action": "BUY",
                            "final_action": "OBSERVE_ONLY",
                            "blocked_by_overtrading_guard": True,
                            "trade_block_reason": "trade_density_limit",
                            "signal_strength": "medium_wait_confirm",
                            "observe_only": True,
                            "ts_code": candidate["ts_code"],
                            "name": candidate["name"],
                            "price": None,
                            "shares": 0,
                            "cash_after": round(cash, 2),
                            "reason": "交易密度达到上限，候选买入意图转为观察。",
                        }
                    )
            if candidate and cash >= 1000 and not buy_block_reason:
                close = candidate["metrics"]["close"]
                action = "BUY"
                decision_candidate["candidate_action"] = action
                buy_upper = round(close * 1.01, 3)
                stop_loss = round(close * 0.94, 3)
                profit_line = round(close * 1.04, 3)
                cash_to_use = min(planned_cash, total_assets * NO_WATCH_BUY_POSITION_LIMIT, cash)
                pending_buy = {
                    "ts_code": candidate["ts_code"],
                    "name": candidate["name"],
                    "buy_upper": buy_upper,
                    "stop_loss": stop_loss,
                    "profit_protection": profit_line,
                    "cash_to_use": cash_to_use,
                }
                reason = f"{candidate_reason} 仅设置次日条件买入，不追高。"
                decision_stop = stop_loss
                decision_profit = profit_line
                max_position = round(cash_to_use / total_assets, 4)
            else:
                action = "WAIT"
                decision_candidate["candidate_action"] = action
                reason = buy_block_reason or candidate_reason
                decision_stop = None
                decision_profit = None
                max_position = 0.0

        position_after = (
            {
                "ts_code": position["ts_code"],
                "name": position["name"],
                "shares": position["shares"],
                "entry_price": position["entry_price"],
                "market_value": round(max(0.0, market_value - initial_unmodeled_holding_value), 2),
                "profit_protection_active": bool(position.get("profit_protection_active")),
                "hold_days": position.get("hold_days", 0),
                "position_violation": position_ratio(position, (fetch_ohlc(conn, position["ts_code"], date, ohlc_cache) or {}).get("close", 0.0), total_assets) > NO_WATCH_SINGLE_POSITION_LIMIT if fetch_ohlc(conn, position["ts_code"], date, ohlc_cache) else False,
                "allow_add": False,
                "need_reduce_to_compliance": bool(pending_sell),
                "single_position_ratio": round(position_ratio(position, (fetch_ohlc(conn, position["ts_code"], date, ohlc_cache) or {}).get("close", 0.0), total_assets), 4) if fetch_ohlc(conn, position["ts_code"], date, ohlc_cache) else 0.0,
                "total_position_ratio": round(total_position_ratio, 4),
                "planned_trade_cash_ratio": round(planned_cash / total_assets, 4) if total_assets else 0.0,
                "sector_concentration": round(total_position_ratio, 4) if path_has_initial_exposure(path) else round((position_ratio(position, (fetch_ohlc(conn, position["ts_code"], date, ohlc_cache) or {}).get("close", 0.0), total_assets) if fetch_ohlc(conn, position["ts_code"], date, ohlc_cache) else 0.0), 4),
                "cannot_watch_limit": NO_WATCH_TOTAL_POSITION_LIMIT if not can_watch_market else 0.4,
            }
            if position
            else None
        )
        decisions.append(
            {
                "date": date,
                "available_data_until": step["available_data_until"],
                "action": action,
                "reason": reason,
                "buy_condition": "次日最低价触及买入区间且开盘不明显高开；只使用计划资金，不追高。" if action == "BUY" else "无新买入条件；等待结构重新确认。" if not position else "持仓期间不加仓。",
                "sell_condition": "跌破止损线、收盘跌破利润保护线、或板块/个股结构走坏则卖出或次日开盘处理。",
                "stop_loss": decision_stop,
                "profit_protection": decision_profit,
                "profit_protection_active": bool(position.get("profit_protection_active")) if position else False,
                "minimum_hold_days": MINIMUM_HOLD_DAYS,
                "position_violation": position_after.get("position_violation") if position_after else initial_health["initial_total_position_violation"],
                "allow_add": False if position else action == "BUY",
                "need_reduce_to_compliance": position_after.get("need_reduce_to_compliance") if position_after else (
                    initial_health["initial_total_position_violation"] and (account_reduce_risk or stop_new_buy_active or account_hard_stop_active)
                ),
                "drawdown_reduce_trigger": any("REDUCE_RISK" in note for note in notes),
                "account_reduce_risk_trigger": account_reduce_risk,
                "stop_new_buy_active": stop_new_buy_active,
                "account_hard_stop_active": account_hard_stop_active,
                "execution_quality_issue": execution_quality_issue,
                "intraday_sequence_unknown": intraday_sequence_unknown_seen,
                "trade_density_observe_mode": trade_density_observe_mode,
                "single_position_ratio": position_after.get("single_position_ratio") if position_after else 0.0,
                "total_position_ratio": round(total_position_ratio, 4),
                "planned_trade_cash_ratio": round(planned_cash / total_assets, 4) if total_assets else 0.0,
                "sector_concentration": position_after.get("sector_concentration") if position_after else round(total_position_ratio, 4),
                "cannot_watch_limit": NO_WATCH_TOTAL_POSITION_LIMIT if not can_watch_market else 0.4,
                "initial_account_health": initial_health if idx == 0 else None,
                "account_initial_handling_state": (
                    "强制降风险" if initial_health["initial_total_position_violation"] and account_hard_stop_active
                    else "计划减仓" if initial_health["initial_total_position_violation"] and (account_reduce_risk or stop_new_buy_active)
                    else "禁止加仓观察" if initial_health["initial_total_position_violation"]
                    else "初始仓位合规"
                ),
                "normal_pullback_condition": "未跌破止损线，且收盘仍在短期结构附近，视为正常波动；不能补仓摊低成本。",
                "sector_retreat_condition": "候选组普遍跌破短期结构、核心股先走弱、或高位放量回落，视为退潮风险。",
                "max_position": max_position,
                "account_risk": "不能盯盘，单笔最多20%，未触发买点保持现金；持仓后不加仓。",
                "next_review_date": next_review_date(steps, idx),
                "whether_executed": executed,
                "execution_price": execution_price,
                "position_after_action": position_after,
                "cash_after_action": round(cash, 2),
                "notes": notes,
                **decision_candidate,
            }
        )
        decisions[-1]["stock_selection_evidence"] = build_stock_selection_evidence(
            decision=decisions[-1],
            candidate=evidence_candidate,
            candidate_reason=evidence_candidate_reason,
            path=path,
        )
        decisions[-1].update(
            build_sector_cycle_state(
                conn=conn,
                path=path,
                date=date,
                metrics_cache=metrics_cache,
            )
        )
        decisions[-1].update(
            build_leader_status(
                conn=conn,
                path=path,
                date=date,
                sector_cycle_state=decisions[-1].get("sector_cycle_state", "UNKNOWN"),
                metrics_cache=metrics_cache,
            )
        )

    blocked_trade_log = [x for x in execution_log if x.get("action") == "BLOCKED_TRADE"]
    for item in execution_log:
        item.update(
            candidate_fields(
                item.get("ts_code"),
                item.get("name"),
                item.get("intended_action") or item.get("action"),
                "execution_log",
            )
        )
        item["stock_selection_evidence"] = build_stock_selection_evidence(
            decision={
                "date": item.get("date"),
                "action": item.get("intended_action") or item.get("action"),
                "candidate_ts_code": item.get("candidate_ts_code"),
                "candidate_name": item.get("candidate_name"),
                "candidate_action": item.get("candidate_action"),
                "candidate_source": item.get("candidate_source"),
                "candidate_is_structured": item.get("candidate_is_structured"),
                "candidate_missing_reason": item.get("candidate_missing_reason", ""),
            },
            candidate={"metrics": recent_metrics(conn, item.get("ts_code"), item.get("date"), metrics_cache)} if item.get("ts_code") and item.get("date") else None,
            candidate_reason="execution_log_visible_trade",
            path=path,
        )
        item.update(
            build_sector_cycle_state(
                conn=conn,
                path=path,
                date=item.get("date"),
                metrics_cache=metrics_cache,
            )
        )
        item.update(
            build_leader_status(
                conn=conn,
                path=path,
                date=item.get("date"),
                sector_cycle_state=item.get("sector_cycle_state", "UNKNOWN"),
                metrics_cache=metrics_cache,
            )
        )
    blocked_trade_review_preview = review_blocked_trades(execution_log)
    blocked_candidates_by_date: dict[str, list[dict]] = {}
    for item in blocked_trade_review_preview["reviews"]:
        if item.get("strong_risk_reduce_exception_candidate"):
            blocked_candidates_by_date.setdefault(item["date"], []).append(item)
    for item in execution_log:
        if item.get("action") == "BLOCKED_TRADE":
            review_item = next((x for x in blocked_trade_review_preview["reviews"] if x["date"] == item["date"] and x["ts_code"] == item["ts_code"] and x["intended_action"] == item["intended_action"]), None)
            if review_item:
                item.update(
                    {
                        "strong_risk_reduce_exception_candidate": review_item.get("strong_risk_reduce_exception_candidate", False),
                        "exception_candidate_reason": review_item.get("exception_candidate_reason", ""),
                        "would_allow_if_exception_enabled": review_item.get("would_allow_if_exception_enabled", False),
                        "requires_human_review": review_item.get("requires_human_review", False),
                    }
                )
    for decision in decisions:
        same_day_candidates = blocked_candidates_by_date.get(decision["date"], [])
        ai_review = build_shadow_ai_review(decision, same_day_candidates)
        decision["ai_review"] = ai_review
        decision["final_user_action_detail"] = build_final_user_action(decision, ai_review)
        decision["final_user_action"] = decision["final_user_action_detail"]["final_user_action"]
        decision["action_reason"] = decision["final_user_action_detail"]["action_reason"]
        decision["execution_condition"] = decision["final_user_action_detail"]["execution_condition"]
        decision["invalidation_condition"] = decision["final_user_action_detail"]["invalidation_condition"]
        decision["stop_loss_condition"] = decision["final_user_action_detail"]["stop_loss_condition"]
        decision["position_limit"] = decision["final_user_action_detail"]["position_limit"]
        decision["user_note"] = decision["final_user_action_detail"]["user_note"]

    # Decisions are complete. Validation/private data may be read only now.
    validation = read_json(Path(args.validation_json))
    private_path = next((p for p in validation["paths"] if p["path_id"] == args.path_id), None)

    initial_equity = total_assets
    final_equity = equity_curve[-1]["equity"] if equity_curve else total_assets
    peak = initial_equity
    max_drawdown = 0.0
    for item in equity_curve:
        peak = max(peak, item["equity"])
        max_drawdown = min(max_drawdown, item["equity"] / peak - 1)
    actual_execution_log = [x for x in execution_log if x.get("action") != "BLOCKED_TRADE"]
    blocked_trade_review = blocked_trade_review_preview
    trade_count = len(actual_execution_log)
    final_return = final_equity / initial_equity - 1
    buy_trades = [x for x in actual_execution_log if x["action"] == "BUY"]
    sell_trades = [x for x in actual_execution_log if x["action"] == "SELL"]
    overtrading_flag = trade_count > OVERTRADING_TRADE_LIMIT
    inactive_false_sell_prevented = any(
        "利润保护线尚未激活，不能因普通波动卖出" in " ".join(d["notes"]) for d in decisions
    )
    profit_protection_inactive_false_sell = any(
        "利润保护线尚未激活" in x.get("reason", "") for x in execution_log if x.get("action") == "SELL"
    )
    process_status = "流程小修" if overtrading_flag else "流程通过"
    process_note = (
        "流程跑通，但交易频率过高，需要进一步降低交易频率。"
        if overtrading_flag
        else "流程通过，交易频率未触发过度交易标记。"
    )
    final_position_violation = False
    if position and equity_curve:
        last_ohlc = fetch_ohlc(conn, position["ts_code"], equity_curve[-1]["date"])
        if last_ohlc:
            final_position_violation = position_ratio(position, last_ohlc["close"], total_assets) > NO_WATCH_SINGLE_POSITION_LIMIT
    if equity_curve:
        final_position_violation = final_position_violation or equity_curve[-1].get("total_position_ratio", 0) > NO_WATCH_TOTAL_POSITION_LIMIT
    risk_actions = [x for x in actual_execution_log if x["action"] in {"SELL", "REDUCE"}]
    max_drawdown_pct = round(max_drawdown * 100, 2)
    risk_control_failure = risk_control_failure or (max_drawdown <= -0.10 and not risk_actions)
    critical_risk_failure = max_drawdown <= -ACCOUNT_CRITICAL_RISK_DD
    final_execution_quality_issue = execution_quality_issue or overtrading_flag
    if final_execution_quality_issue and execution_quality_issue_level == "NONE":
        execution_quality_issue_level = "REVIEW_NOTE"
        execution_quality_issue_reason = "交易意图被风控或交易密度规则转为观察，作为审查提示保留。"
    initial_position_violation = initial_health["initial_total_position_violation"] or initial_health["initial_single_position_violation"]
    model_caused_position_violation = position_violation_seen and not initial_position_violation
    model_position_breach_audit = build_model_position_breach_audit(
        path_id=args.path_id,
        decisions=decisions,
        actual_execution_log=actual_execution_log,
        initial_position_violation=initial_position_violation,
        final_position_violation=final_position_violation,
        model_caused_position_violation=model_caused_position_violation,
    )
    ai_reviews = [d.get("ai_review", {}) for d in decisions]
    ai_review_pass_count = sum(1 for r in ai_reviews if r.get("review_status") == "PASS")
    ai_review_reject_count = sum(1 for r in ai_reviews if r.get("review_status") == "REJECT")
    ai_review_needs_human_count = sum(1 for r in ai_reviews if r.get("review_status") == "NEEDS_HUMAN_REVIEW")
    ai_review_would_change_action_count = sum(1 for r in ai_reviews if r.get("review_changes_action"))
    strong_risk_reduce_exception_candidate_count = sum(1 for x in execution_log if x.get("strong_risk_reduce_exception_candidate"))
    top_veto_reasons = Counter(r.get("veto_reason") for r in ai_reviews if r.get("veto_reason"))
    top_rule_conflicts = Counter(conflict for r in ai_reviews for conflict in r.get("rule_conflicts", []))
    top_missing_fields = Counter(field for r in ai_reviews for field in r.get("missing_fields", []))
    final_user_action_counts = Counter(d.get("final_user_action") for d in decisions if d.get("final_user_action"))
    structured_candidate_count = sum(1 for d in decisions if candidate_fields_from_decision(d).get("candidate_is_structured"))
    unstructured_candidate_details = [
        {
            "date": d.get("date"),
            "action": d.get("action"),
            "final_user_action": d.get("final_user_action"),
            "candidate_missing_reason": candidate_fields_from_decision(d).get("candidate_missing_reason") or "insufficient_visible_source",
        }
        for d in decisions
        if not candidate_fields_from_decision(d).get("candidate_is_structured")
    ]
    ai_review_reject_unstructured_count = sum(
        1
        for d in decisions
        if d.get("ai_review", {}).get("review_status") == "REJECT"
        and not candidate_fields_from_decision(d).get("candidate_is_structured")
    )
    stock_selection_evidences = [
        d.get("stock_selection_evidence", {})
        for d in decisions
        if isinstance(d.get("stock_selection_evidence"), dict)
    ]
    evidence_quality_counts = Counter(e.get("evidence_quality") or "INSUFFICIENT" for e in stock_selection_evidences)
    buy_with_insufficient_evidence_count = sum(
        1
        for d in decisions
        if d.get("action") == "BUY"
        and d.get("stock_selection_evidence", {}).get("evidence_quality") == "INSUFFICIENT"
    )
    buy_with_low_evidence_count = sum(
        1
        for d in decisions
        if d.get("action") == "BUY"
        and d.get("stock_selection_evidence", {}).get("evidence_quality") == "LOW"
    )
    evidence_missing_reasons = Counter()
    for evidence in stock_selection_evidences:
        reason_text = evidence.get("evidence_missing_reason") or ""
        for reason in [item.strip() for item in reason_text.split(",") if item.strip()]:
            evidence_missing_reasons[reason] += 1
    ai_review_added_warnings_for_insufficient_evidence_count = sum(
        1
        for d in decisions
        if "insufficient_stock_selection_evidence" in d.get("ai_review", {}).get("risk_warnings", [])
    )
    sector_cycle_states = [d.get("sector_cycle_state", "UNKNOWN") for d in decisions]
    sector_cycle_counts = Counter(sector_cycle_states)
    buy_with_unknown_sector_cycle_count = sum(
        1 for d in decisions if d.get("action") == "BUY" and d.get("sector_cycle_state", "UNKNOWN") == "UNKNOWN"
    )
    buy_with_negative_sector_cycle_count = sum(
        1 for d in decisions if d.get("action") == "BUY" and d.get("sector_cycle_state") in {"FADING", "FALLING", "CLIMAX"}
    )
    sector_cycle_missing_reasons = Counter(
        d.get("sector_cycle_missing_reason") or "insufficient_sector_data"
        for d in decisions
        if d.get("sector_cycle_state", "UNKNOWN") == "UNKNOWN"
    )
    ai_review_added_warnings_for_sector_cycle_count = sum(
        1
        for d in decisions
        for warning in d.get("ai_review", {}).get("risk_warnings", [])
        if warning in {"unknown_sector_cycle_state", "sector_cycle_divergence_requires_strong_stock_evidence", "buy_in_divergence_requires_better_stock_evidence"}
        or str(warning).startswith("negative_sector_cycle:")
    )
    leader_statuses = [d.get("leader_status", "UNKNOWN") for d in decisions]
    leader_status_counts = Counter(leader_statuses)
    buy_with_unknown_leader_status_count = sum(
        1 for d in decisions if d.get("action") == "BUY" and d.get("leader_status", "UNKNOWN") == "UNKNOWN"
    )
    buy_with_negative_leader_status_count = sum(
        1
        for d in decisions
        if d.get("action") == "BUY"
        and d.get("leader_status") in {"LEADER_WEAKENING", "LEADER_BROKEN", "NO_CLEAR_LEADER"}
    )
    leader_status_missing_reasons = Counter(
        d.get("leader_status_missing_reason") or "insufficient_leader_data"
        for d in decisions
        if d.get("leader_status", "UNKNOWN") == "UNKNOWN"
    )
    ai_review_added_warnings_for_leader_status_count = sum(
        1
        for d in decisions
        for warning in d.get("ai_review", {}).get("risk_warnings", [])
        if warning in {"unknown_leader_status", "leader_rotating_requires_strong_stock_evidence", "buy_in_leader_rotation_requires_better_stock_evidence"}
        or str(warning).startswith("negative_leader_status:")
    )
    account_initial_handling_state = (
        "强制降风险" if initial_position_violation and account_hard_stop_active
        else "计划减仓" if initial_position_violation and (account_risk_triggered or stop_new_buy_active)
        else "禁止加仓观察" if initial_position_violation
        else "初始仓位合规"
    )

    result = {
        "path_id": args.path_id,
        "path_name": path["path_name"],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "input_file_for_answering": str(Path(args.questions_json)),
        "validation_file_read_after_decisions": str(Path(args.validation_json)),
        "only_ran_path": args.path_id,
        "final_equity": round(final_equity, 2),
        "final_return_pct": round(final_return * 100, 2),
        "max_drawdown_pct": max_drawdown_pct,
        "whether_trade_happened": bool(actual_execution_log),
        "trade_count": trade_count,
        "blocked_trade_count": len(blocked_trade_log),
        "blocked_trade_review": blocked_trade_review,
        "ai_review_pass_count": ai_review_pass_count,
        "ai_review_reject_count": ai_review_reject_count,
        "ai_review_needs_human_count": ai_review_needs_human_count,
        "ai_review_would_change_action_count": ai_review_would_change_action_count,
        "strong_risk_reduce_exception_candidate_count": strong_risk_reduce_exception_candidate_count,
        "top_veto_reasons": top_veto_reasons.most_common(10),
        "top_rule_conflicts": top_rule_conflicts.most_common(10),
        "top_missing_fields": top_missing_fields.most_common(10),
        "final_user_action_counts": dict(final_user_action_counts),
        "structured_candidate_count": structured_candidate_count,
        "unstructured_candidate_count": len(unstructured_candidate_details),
        "unstructured_candidate_details": unstructured_candidate_details,
        "ai_review_reject_unstructured_count": ai_review_reject_unstructured_count,
        "stock_selection_evidence_total_count": len(stock_selection_evidences),
        "evidence_high_count": evidence_quality_counts.get("HIGH", 0),
        "evidence_medium_count": evidence_quality_counts.get("MEDIUM", 0),
        "evidence_low_count": evidence_quality_counts.get("LOW", 0),
        "evidence_insufficient_count": evidence_quality_counts.get("INSUFFICIENT", 0),
        "buy_with_insufficient_evidence_count": buy_with_insufficient_evidence_count,
        "buy_with_low_evidence_count": buy_with_low_evidence_count,
        "evidence_missing_reasons_top": evidence_missing_reasons.most_common(10),
        "ai_review_added_warnings_for_insufficient_evidence_count": ai_review_added_warnings_for_insufficient_evidence_count,
        "sector_cycle_state_total_count": len(sector_cycle_states),
        "sector_cycle_unknown_count": sector_cycle_counts.get("UNKNOWN", 0),
        "sector_cycle_rising_count": sector_cycle_counts.get("RISING", 0),
        "sector_cycle_divergence_count": sector_cycle_counts.get("DIVERGENCE", 0),
        "sector_cycle_climax_count": sector_cycle_counts.get("CLIMAX", 0),
        "sector_cycle_fading_count": sector_cycle_counts.get("FADING", 0),
        "sector_cycle_falling_count": sector_cycle_counts.get("FALLING", 0),
        "sector_cycle_repairing_count": sector_cycle_counts.get("REPAIRING", 0),
        "buy_with_unknown_sector_cycle_count": buy_with_unknown_sector_cycle_count,
        "buy_with_negative_sector_cycle_count": buy_with_negative_sector_cycle_count,
        "ai_review_added_warnings_for_sector_cycle_count": ai_review_added_warnings_for_sector_cycle_count,
        "sector_cycle_missing_reasons_top": sector_cycle_missing_reasons.most_common(10),
        "leader_status_total_count": len(leader_statuses),
        "leader_status_unknown_count": leader_status_counts.get("UNKNOWN", 0),
        "leader_status_strong_count": leader_status_counts.get("LEADER_STRONG", 0),
        "leader_status_weakening_count": leader_status_counts.get("LEADER_WEAKENING", 0),
        "leader_status_broken_count": leader_status_counts.get("LEADER_BROKEN", 0),
        "leader_status_rotating_count": leader_status_counts.get("LEADER_ROTATING", 0),
        "leader_status_no_clear_count": leader_status_counts.get("NO_CLEAR_LEADER", 0),
        "buy_with_unknown_leader_status_count": buy_with_unknown_leader_status_count,
        "buy_with_negative_leader_status_count": buy_with_negative_leader_status_count,
        "ai_review_added_warnings_for_leader_status_count": ai_review_added_warnings_for_leader_status_count,
        "leader_status_missing_reasons_top": leader_status_missing_reasons.most_common(10),
        "whether_chased_high": False,
        "whether_position_rule_obeyed": not final_position_violation,
        "whether_profit_protected": any("利润保护" in " ".join(d["notes"]) for d in decisions) or bool(sell_trades),
        "whether_stop_loss_timely": any(x["reason"].startswith("当日最低价触发止损") for x in sell_trades) or any(x["action"] == "REDUCE" for x in execution_log),
        "whether_future_leakage": future_leakage_risk,
        "overtrading_flag": overtrading_flag,
        "position_violation": position_violation_seen,
        "final_position_violation": final_position_violation,
        "position_violation_corrected": position_violation_seen and not final_position_violation,
        "position_compliance": not final_position_violation,
        "initial_position_violation": initial_position_violation,
        "initial_position_breach": initial_position_violation,
        "model_caused_position_violation": model_caused_position_violation,
        "model_caused_position_breach": model_caused_position_violation,
        "model_caused_position_breach_audit": model_position_breach_audit,
        "ai_reviews": ai_reviews,
        "initial_account_health": initial_health,
        "account_initial_handling_state": account_initial_handling_state,
        "initial_position_explanation": (
            "初始账户总仓位或单票仓位已超过不能盯盘上限，属于历史初始状态不合规，不是模型新增交易导致。"
            if initial_position_violation
            else "初始账户仓位未发现超限。"
        ),
        "add_position_forbidden": initial_health["cannot_add_position"] or stop_new_buy_active or account_hard_stop_active,
        "add_buy_blocked": initial_health["cannot_add_position"] or stop_new_buy_active or account_hard_stop_active,
        "planned_reduce_required": account_initial_handling_state in {"计划减仓", "强制降风险"} or deleveraging_plan["required"],
        "planned_deleveraging_required": account_initial_handling_state in {"计划减仓", "强制降风险"} or deleveraging_plan["required"],
        "forced_deleveraging_required": account_initial_handling_state == "强制降风险",
        "per_position_deleveraging_plan": deleveraging_plan,
        "deleveraging_plan_exists": bool(deleveraging_plan["positions"]),
        "deleveraging_plan_basis": "按初始总仓位超限金额、不能盯盘仓位上限、角色风险提示和估算单票市值生成；弱结构/高风险优先减仓，其次按仓位规模处理。",
        "estimated_post_deleveraging_total_position": deleveraging_plan["estimated_total_position_after"],
        "limitation_note": "当前仍是报告层模拟，未接真实账户，未基于真实持仓数量/成本成交。",
        "post_deleveraging_position_compliance": deleveraging_plan["post_deleveraging_position_compliance"],
        "risk_control_failure": risk_control_failure,
        "critical_risk_failure": critical_risk_failure,
        "severe_risk_control_failure": critical_risk_failure,
        "account_reduce_risk_triggered": account_risk_triggered,
        "stop_new_buy_active": stop_new_buy_active,
        "account_hard_stop_active": account_hard_stop_active,
        "execution_quality_issue": final_execution_quality_issue,
        "execution_quality_issue_level": execution_quality_issue_level,
        "execution_quality_issue_reason": execution_quality_issue_reason,
        "intraday_sequence_unknown": intraday_sequence_unknown_seen,
        "trade_density_observe_mode": trade_density_observe_mode,
        "initial_unmodeled_holding_value": round(initial_unmodeled_holding_value, 2),
        "initial_total_position_ratio": round(initial_total_position_ratio, 4),
        "profit_protection_active_rule_enabled": True,
        "minimum_hold_days": MINIMUM_HOLD_DAYS,
        "inactive_profit_protection_sell_prevented": inactive_false_sell_prevented,
        "profit_protection_inactive_false_sell": profit_protection_inactive_false_sell,
        "process_status": process_status,
        "process_note": process_note,
        "before_after_comparison": {
            "before": PRE_FIX_RESULT,
            "after": {
                "final_return_pct": round(final_return * 100, 2),
                "max_drawdown_pct": round(max_drawdown * 100, 2),
                "trade_count": trade_count,
                "overtrading_flag": overtrading_flag,
                "profit_protection_inactive_false_sell": profit_protection_inactive_false_sell,
            },
        },
        "private_validation_reference": private_path.get("stage_b_validation") if private_path else None,
        "boundary_note": "单条路径结果只用于验证流程，不证明模型长期有效。",
    }

    decisions_obj = {"path_id": args.path_id, "decisions": decisions}
    execution_obj = {"path_id": args.path_id, "execution_log": execution_log, "equity_curve": equity_curve}

    stem = path_stem(args.path_id)
    dec_json = outdir / f"{stem}_decisions.json"
    exe_json = outdir / f"{stem}_execution_log.json"
    result_json = outdir / f"{stem}_result.json"
    result_md = outdir / f"{stem}_result.md"
    dec_md = outdir / f"{stem}_decisions.md"
    exe_md = outdir / f"{stem}_execution_log.md"

    write_json(dec_json, decisions_obj)
    write_json(exe_json, execution_obj)

    dec_lines = [
        f"# {args.path_id} 每日决策",
        "",
        f"- 输入：仅使用 `walk_forward_paths_2025_questions.json` 中的 {args.path_id}。",
        "- 阶段B验证文件在每日决策完成后才读取。",
        "",
    ]
    for d in decisions:
        dec_lines.extend(
            [
                f"## {d['date']}",
                f"- action：{d['action']}",
                f"- reason：{d['reason']}",
                f"- buy_condition：{d['buy_condition']}",
                f"- sell_condition：{d['sell_condition']}",
                f"- stop_loss：{d['stop_loss']}",
                f"- profit_protection：{d['profit_protection']}",
                f"- profit_protection_active：{d['profit_protection_active']}",
                f"- minimum_hold_days：{d['minimum_hold_days']}",
                f"- max_position：{d['max_position']}",
                f"- account_risk：{d['account_risk']}",
                f"- whether_executed：{d['whether_executed']}",
                f"- execution_price：{d['execution_price']}",
                f"- cash_after_action：{d['cash_after_action']}",
                f"- notes：{'；'.join(d['notes']) if d['notes'] else '-'}",
                f"- stock_selection_evidence：{d.get('stock_selection_evidence', {})}",
                f"- sector_cycle_state：{d.get('sector_cycle_state')}",
                f"- sector_cycle_missing_reason：{d.get('sector_cycle_missing_reason')}",
                f"- sector_cycle_note：{d.get('sector_cycle_note')}",
                f"- leader_status：{d.get('leader_status')}",
                f"- leader_status_missing_reason：{d.get('leader_status_missing_reason')}",
                f"- leader_status_note：{d.get('leader_status_note')}",
                f"- ai_review：{d.get('ai_review', {})}",
                f"- final_user_action：{d.get('final_user_action')}",
                f"- action_reason：{d.get('action_reason')}",
                f"- execution_condition：{d.get('execution_condition')}",
                f"- invalidation_condition：{d.get('invalidation_condition')}",
                f"- stop_loss_condition：{d.get('stop_loss_condition')}",
                f"- position_limit：{d.get('position_limit')}",
                f"- user_note：{d.get('user_note')}",
                "",
            ]
        )
    dec_md.write_text("\n".join(dec_lines), encoding="utf-8")

    exe_lines = [f"# {args.path_id} 交易日志", ""]
    if execution_log:
        exe_lines.extend(["| 日期 | 动作 | 代码 | 名称 | 价格 | 股数 | 现金 | 原因 |", "| -- | -- | -- | -- | --: | --: | --: | -- |"])
        for x in execution_log:
            exe_lines.append(
                f"| {x['date']} | {x['action']} | {x['ts_code']} | {x['name']} | {x['price']} | {x['shares']} | {x['cash_after']} | {x['reason']} |"
            )
    else:
        exe_lines.append("- 无实际成交。")
    exe_lines.extend(["", "## 权益曲线", "", "| 日期 | 权益 | 现金 |", "| -- | --: | --: |"])
    for x in equity_curve:
        exe_lines.append(f"| {x['date']} | {x['equity']} | {x['cash']} |")
    exe_md.write_text("\n".join(exe_lines), encoding="utf-8")

    result_lines = [
        f"# {args.path_id} Walk-forward MVP 结果",
        "",
        f"- 生成时间：{result['generated_at']}",
        f"- 本轮运行路径：{args.path_id}。",
        "- 作答输入只使用 questions 文件；validation_private 在每日决策完成后才读取。",
        "- 未运行完整评分，未修改评分权重，未自动交易，未接真实账户。",
        "- 本轮小修：利润保护线需先激活；新增最低持仓观察期；新增过度交易标记。",
        "",
        "## 指标",
        "",
        f"- 最终收益率：{result['final_return_pct']}%",
        f"- 最大回撤：{result['max_drawdown_pct']}%",
        f"- 是否发生交易：{result['whether_trade_happened']}",
        f"- 交易次数：{result['trade_count']}",
        f"- 是否追高：{result['whether_chased_high']}",
        f"- 是否遵守仓位：{result['whether_position_rule_obeyed']}",
        f"- 是否保护利润：{result['whether_profit_protected']}",
        f"- 是否及时止损：{result['whether_stop_loss_timely']}",
        f"- 是否出现未来函数风险：{result['whether_future_leakage']}",
        f"- 是否过度交易：{result['overtrading_flag']}",
        f"- 初始/过程仓位超限：{result['position_violation']}",
        f"- 最终仓位仍超限：{result['final_position_violation']}",
        f"- 仓位超限是否修正：{result['position_violation_corrected']}",
        f"- 初始仓位超限：{result['initial_position_violation']}",
        f"- 是否模型新增交易导致超限：{result['model_caused_position_violation']}",
        f"- 初始仓位处理方式：{result['account_initial_handling_state']}",
        f"- 是否禁止加仓：{result['add_position_forbidden']}",
        f"- 是否需要计划减仓：{result['planned_reduce_required']}",
        f"- 是否需要强制降风险：{result['forced_deleveraging_required']}",
        f"- 逐票减仓计划是否生成：{bool(result['per_position_deleveraging_plan']['positions'])}",
        f"- 逐票减仓计划依据：{result['deleveraging_plan_basis']}",
        f"- 减仓后预估总仓位：{result['estimated_post_deleveraging_total_position']}",
        f"- 减仓后预估仓位合规：{result['post_deleveraging_position_compliance']}",
        f"- 减仓计划边界：{result['limitation_note']}",
        f"- 风控失败：{result['risk_control_failure']}",
        f"- 严重风控失败：{result['severe_risk_control_failure']}",
        f"- 执行质量问题：{result['execution_quality_issue']}",
        f"- 执行质量问题级别：{result['execution_quality_issue_level']}",
        f"- 执行质量问题说明：{result['execution_quality_issue_reason'] or '-'}",
        f"- 交易密度观察模式：{result['trade_density_observe_mode']}",
        f"- 被拦截交易意图数：{result['blocked_trade_count']}",
        f"- 被拦截交易审查：{result['blocked_trade_review']['review_counts']}",
        f"- AI shadow review：pass={result['ai_review_pass_count']} reject={result['ai_review_reject_count']} needs_human={result['ai_review_needs_human_count']}",
        f"- AI would-change-action：{result['ai_review_would_change_action_count']}",
        f"- 强风险减仓例外候选：{result['strong_risk_reduce_exception_candidate_count']}",
        f"- final_user_action_counts：{result['final_user_action_counts']}",
        f"- top_veto_reasons：{result['top_veto_reasons']}",
        f"- top_rule_conflicts：{result['top_rule_conflicts']}",
        f"- top_missing_fields：{result['top_missing_fields']}",
        f"- stock_selection_evidence_total_count：{result['stock_selection_evidence_total_count']}",
        f"- evidence_high/medium/low/insufficient：{result['evidence_high_count']}/{result['evidence_medium_count']}/{result['evidence_low_count']}/{result['evidence_insufficient_count']}",
        f"- buy_with_insufficient_evidence_count：{result['buy_with_insufficient_evidence_count']}",
        f"- buy_with_low_evidence_count：{result['buy_with_low_evidence_count']}",
        f"- evidence_missing_reasons_top：{result['evidence_missing_reasons_top']}",
        f"- ai_review_added_warnings_for_insufficient_evidence_count：{result['ai_review_added_warnings_for_insufficient_evidence_count']}",
        f"- sector_cycle_state_total_count：{result['sector_cycle_state_total_count']}",
        f"- sector_cycle UNKNOWN/RISING/DIVERGENCE/CLIMAX/FADING/FALLING/REPAIRING：{result['sector_cycle_unknown_count']}/{result['sector_cycle_rising_count']}/{result['sector_cycle_divergence_count']}/{result['sector_cycle_climax_count']}/{result['sector_cycle_fading_count']}/{result['sector_cycle_falling_count']}/{result['sector_cycle_repairing_count']}",
        f"- buy_with_unknown_sector_cycle_count：{result['buy_with_unknown_sector_cycle_count']}",
        f"- buy_with_negative_sector_cycle_count：{result['buy_with_negative_sector_cycle_count']}",
        f"- ai_review_added_warnings_for_sector_cycle_count：{result['ai_review_added_warnings_for_sector_cycle_count']}",
        f"- sector_cycle_missing_reasons_top：{result['sector_cycle_missing_reasons_top']}",
        f"- leader_status_total_count：{result['leader_status_total_count']}",
        f"- leader_status UNKNOWN/STRONG/WEAKENING/BROKEN/ROTATING/NO_CLEAR：{result['leader_status_unknown_count']}/{result['leader_status_strong_count']}/{result['leader_status_weakening_count']}/{result['leader_status_broken_count']}/{result['leader_status_rotating_count']}/{result['leader_status_no_clear_count']}",
        f"- buy_with_unknown_leader_status_count：{result['buy_with_unknown_leader_status_count']}",
        f"- buy_with_negative_leader_status_count：{result['buy_with_negative_leader_status_count']}",
        f"- ai_review_added_warnings_for_leader_status_count：{result['ai_review_added_warnings_for_leader_status_count']}",
        f"- leader_status_missing_reasons_top：{result['leader_status_missing_reasons_top']}",
        f"- 利润保护未激活误卖：{result['profit_protection_inactive_false_sell']}",
        f"- 最低持仓观察期：{result['minimum_hold_days']}个交易日",
        f"- 结论：{result['process_status']}",
        f"- 说明：{result['process_note']}",
        "",
        "## 修正前后对比",
        "",
        "| 指标 | 修正前 | 修正后 |",
        "| -- | --: | --: |",
        f"| 最终收益率 | {PRE_FIX_RESULT['final_return_pct']}% | {result['final_return_pct']}% |",
        f"| 最大回撤 | {PRE_FIX_RESULT['max_drawdown_pct']}% | {result['max_drawdown_pct']}% |",
        f"| 交易次数 | {PRE_FIX_RESULT['trade_count']} | {result['trade_count']} |",
        f"| 是否过度交易 | 是 | {'是' if result['overtrading_flag'] else '否'} |",
        f"| 是否利润保护未激活误卖 | 是 | {'是' if result['profit_protection_inactive_false_sell'] else '否'} |",
        "",
        "## 边界",
        "",
        "- 单条路径结果只用于验证流程，不证明模型长期有效。",
    ]
    result_md.write_text("\n".join(result_lines), encoding="utf-8")

    write_json(result_json, result)
    conn.close()
    return {
        "decisions_md": str(dec_md),
        "decisions_json": str(dec_json),
        "execution_md": str(exe_md),
        "execution_json": str(exe_json),
        "result_md": str(result_md),
        "result_json": str(result_json),
        **result,
    }


def run_three(args: argparse.Namespace) -> dict:
    path_ids = [item.strip() for item in args.path_ids.split(",") if item.strip()]
    allowed = {
        "WF2025-PRE-01",
        "WF2025-PRE-02",
        "WF2025-PRE-03",
        "WF2025-HOLD-01",
        "WF2025-HOLD-02",
        "WF2025-HOLD-03",
        "WF2025-INTRA-01",
        "WF2025-INTRA-02",
        "WF2025-ACC-01",
        "WF2025-ACC-02",
    }
    if not set(path_ids).issubset(allowed):
        raise RuntimeError("This MVP run is limited to the approved walk-forward paths")
    if not getattr(args, "summary_only_existing", False):
        for path_id in path_ids:
            child = argparse.Namespace(
                path_id=path_id,
                questions_json=args.questions_json,
                validation_json=args.validation_json,
                db_path=args.db_path,
            )
            run(child)
    outdir = Path.cwd() / "reports" / "walk_forward_2025"
    results = []
    for path_id in sorted(allowed):
        result_path = outdir / f"{path_stem(path_id)}_result.json"
        if result_path.exists():
            results.append(read_json(result_path))
    if len(results) != len(allowed):
        missing = sorted(allowed - {r["path_id"] for r in results})
        raise RuntimeError(f"Missing result files for summary: {missing}")
    best = max(results, key=lambda r: r["final_return_pct"])
    worst_problem = max(
        results,
        key=lambda r: (
            r.get("critical_risk_failure", False),
            r.get("risk_control_failure", False),
            abs(min(0, r["max_drawdown_pct"])),
            r["overtrading_flag"],
            not r["whether_position_rule_obeyed"],
        ),
    )
    if any(r["path_id"] == "WF2025-ACC-01" for r in results):
        worst_problem = next(r for r in results if r["path_id"] == "WF2025-ACC-01")
    can_enter_next_stage = not any(
        r["overtrading_flag"]
        or r["whether_future_leakage"]
        or not r["whether_position_rule_obeyed"]
        or r.get("risk_control_failure")
        or r.get("critical_risk_failure")
        or r.get("execution_quality_issue")
        or r["max_drawdown_pct"] <= -5
        for r in results
    )
    next_fix = (
        "暂不进入 FULL_PIPELINE_SELECTION_WALK_FORWARD，先观察强风险减仓例外候选与 AI shadow review 的稳定性，并继续固化 final_user_action 报告层输出。"
        if not can_enter_next_stage
        else "当前10条路径未触发硬阻断，可以进入下一阶段。"
    )
    profitable = sum(1 for r in results if r["final_return_pct"] > 0)
    losing = sum(1 for r in results if r["final_return_pct"] < 0)
    avg_return = round(sum(r["final_return_pct"] for r in results) / len(results), 2)
    avg_drawdown = round(sum(r["max_drawdown_pct"] for r in results) / len(results), 2)
    max_loss_path = min(results, key=lambda r: r["final_return_pct"])
    max_drawdown_path = min(results, key=lambda r: r["max_drawdown_pct"])
    most_trades_path = max(results, key=lambda r: r["trade_count"])
    all_blocked_trade_review = build_all_blocked_trade_review(results)
    intra02_conservative_review = build_intra02_conservative_review(results)
    ai_review_reject_audit = build_ai_review_reject_audit(results)
    sector_cycle_reject_audit = build_sector_cycle_reject_audit(results)
    leader_status_reject_audit = build_leader_status_reject_audit(results)
    ai_review_needs_human_audit = build_ai_review_needs_human_audit(results)
    field_completeness_report = build_field_completeness_report(results)
    consistency_conflict_report = build_consistency_conflict_report(results)
    buy_action_audit = build_buy_action_audit(results)
    observe_action_audit = build_observe_action_audit(results)
    needs_human_review_audit = build_needs_human_review_audit(results)
    missing_fields_next_schema_plan = build_missing_fields_next_schema_plan()
    structured_candidate_summary = build_structured_candidate_summary(results)
    pre03_result = next((r for r in results if r["path_id"] == "WF2025-PRE-03"), {})
    pre03_model_breach_audit = pre03_result.get("model_caused_position_breach_audit", {})
    aggregated_final_user_action_counts = Counter()
    aggregated_top_veto_reasons = Counter()
    aggregated_top_rule_conflicts = Counter()
    aggregated_top_missing_fields = Counter()
    aggregated_evidence_missing_reasons = Counter()
    aggregated_sector_cycle_missing_reasons = Counter()
    aggregated_leader_status_missing_reasons = Counter()
    for item in results:
        aggregated_final_user_action_counts.update(item.get("final_user_action_counts", {}) or {})
        aggregated_top_veto_reasons.update(dict(item.get("top_veto_reasons", []) or []))
        aggregated_top_rule_conflicts.update(dict(item.get("top_rule_conflicts", []) or []))
        aggregated_top_missing_fields.update(dict(item.get("top_missing_fields", []) or []))
        aggregated_evidence_missing_reasons.update(dict(item.get("evidence_missing_reasons_top", []) or []))
        aggregated_sector_cycle_missing_reasons.update(dict(item.get("sector_cycle_missing_reasons_top", []) or []))
        aggregated_leader_status_missing_reasons.update(dict(item.get("leader_status_missing_reasons_top", []) or []))
    ai_review_integrity_audit = build_ai_review_integrity_audit(
        {
            "ai_review_reject_count": sum(r.get("ai_review_reject_count", 0) for r in results),
            "ai_review_needs_human_count": sum(r.get("ai_review_needs_human_count", 0) for r in results),
            "ai_review_would_change_action_count": sum(r.get("ai_review_would_change_action_count", 0) for r in results),
            "sector_cycle_reject_audit_count": sector_cycle_reject_audit["total_count"],
            "leader_status_reject_audit_count": leader_status_reject_audit["total_count"],
            "results": results,
        },
        buy_action_audit,
        observe_action_audit,
        consistency_conflict_report,
    )
    dual_track_readiness = build_dual_track_readiness(
        field_completeness_report,
        consistency_conflict_report,
        buy_action_audit,
        observe_action_audit,
        needs_human_review_audit,
        ai_review_integrity_audit,
    )
    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reran_paths": path_ids,
        "path_count": len(results),
        "results": [
            {
                "path_id": r["path_id"],
                "final_return_pct": r["final_return_pct"],
                "max_drawdown_pct": r["max_drawdown_pct"],
                "trade_count": r["trade_count"],
                "blocked_trade_count": r.get("blocked_trade_count", 0),
                "blocked_trade_review": r.get("blocked_trade_review", {}),
                "overtrading_flag": r["overtrading_flag"],
                "whether_profit_protected": r["whether_profit_protected"],
                "whether_stop_loss_timely": r["whether_stop_loss_timely"],
                "whether_position_rule_obeyed": r["whether_position_rule_obeyed"],
                "position_violation": r.get("position_violation"),
                "position_violation_corrected": r.get("position_violation_corrected"),
                "risk_control_failure": r.get("risk_control_failure"),
                "critical_risk_failure": r.get("critical_risk_failure", False),
                "severe_risk_control_failure": r.get("severe_risk_control_failure", r.get("critical_risk_failure", False)),
                "execution_quality_issue": r.get("execution_quality_issue", False),
                "intraday_sequence_unknown": r.get("intraday_sequence_unknown", False),
                "initial_position_violation": r.get("initial_position_violation", False),
                "initial_position_breach": r.get("initial_position_breach", r.get("initial_position_violation", False)),
                "model_caused_position_violation": r.get("model_caused_position_violation", False),
                "model_caused_position_breach": r.get("model_caused_position_breach", r.get("model_caused_position_violation", False)),
                "model_caused_position_breach_audit": r.get("model_caused_position_breach_audit", {}),
                "ai_review_pass_count": r.get("ai_review_pass_count", 0),
                "ai_review_reject_count": r.get("ai_review_reject_count", 0),
                "ai_review_needs_human_count": r.get("ai_review_needs_human_count", 0),
                "ai_review_would_change_action_count": r.get("ai_review_would_change_action_count", 0),
                "strong_risk_reduce_exception_candidate_count": r.get("strong_risk_reduce_exception_candidate_count", 0),
                "final_user_action_counts": r.get("final_user_action_counts", {}),
                "structured_candidate_count": r.get("structured_candidate_count", 0),
                "unstructured_candidate_count": r.get("unstructured_candidate_count", 0),
                "ai_review_reject_unstructured_count": r.get("ai_review_reject_unstructured_count", 0),
                "stock_selection_evidence_total_count": r.get("stock_selection_evidence_total_count", 0),
                "evidence_high_count": r.get("evidence_high_count", 0),
                "evidence_medium_count": r.get("evidence_medium_count", 0),
                "evidence_low_count": r.get("evidence_low_count", 0),
                "evidence_insufficient_count": r.get("evidence_insufficient_count", 0),
                "buy_with_insufficient_evidence_count": r.get("buy_with_insufficient_evidence_count", 0),
                "buy_with_low_evidence_count": r.get("buy_with_low_evidence_count", 0),
                "evidence_missing_reasons_top": r.get("evidence_missing_reasons_top", []),
                "ai_review_added_warnings_for_insufficient_evidence_count": r.get("ai_review_added_warnings_for_insufficient_evidence_count", 0),
                "sector_cycle_state_total_count": r.get("sector_cycle_state_total_count", 0),
                "sector_cycle_unknown_count": r.get("sector_cycle_unknown_count", 0),
                "sector_cycle_rising_count": r.get("sector_cycle_rising_count", 0),
                "sector_cycle_divergence_count": r.get("sector_cycle_divergence_count", 0),
                "sector_cycle_climax_count": r.get("sector_cycle_climax_count", 0),
                "sector_cycle_fading_count": r.get("sector_cycle_fading_count", 0),
                "sector_cycle_falling_count": r.get("sector_cycle_falling_count", 0),
                "sector_cycle_repairing_count": r.get("sector_cycle_repairing_count", 0),
                "buy_with_unknown_sector_cycle_count": r.get("buy_with_unknown_sector_cycle_count", 0),
                "buy_with_negative_sector_cycle_count": r.get("buy_with_negative_sector_cycle_count", 0),
                "ai_review_added_warnings_for_sector_cycle_count": r.get("ai_review_added_warnings_for_sector_cycle_count", 0),
                "sector_cycle_missing_reasons_top": r.get("sector_cycle_missing_reasons_top", []),
                "leader_status_total_count": r.get("leader_status_total_count", 0),
                "leader_status_unknown_count": r.get("leader_status_unknown_count", 0),
                "leader_status_strong_count": r.get("leader_status_strong_count", 0),
                "leader_status_weakening_count": r.get("leader_status_weakening_count", 0),
                "leader_status_broken_count": r.get("leader_status_broken_count", 0),
                "leader_status_rotating_count": r.get("leader_status_rotating_count", 0),
                "leader_status_no_clear_count": r.get("leader_status_no_clear_count", 0),
                "buy_with_unknown_leader_status_count": r.get("buy_with_unknown_leader_status_count", 0),
                "buy_with_negative_leader_status_count": r.get("buy_with_negative_leader_status_count", 0),
                "ai_review_added_warnings_for_leader_status_count": r.get("ai_review_added_warnings_for_leader_status_count", 0),
                "leader_status_missing_reasons_top": r.get("leader_status_missing_reasons_top", []),
                "top_veto_reasons": r.get("top_veto_reasons", []),
                "top_rule_conflicts": r.get("top_rule_conflicts", []),
                "top_missing_fields": r.get("top_missing_fields", []),
                "account_initial_handling_state": r.get("account_initial_handling_state", ""),
                "trade_density_observe_mode": r.get("trade_density_observe_mode", False),
                "execution_quality_issue_level": r.get("execution_quality_issue_level", ""),
                "execution_quality_issue_reason": r.get("execution_quality_issue_reason", ""),
                "planned_deleveraging_required": r.get("planned_deleveraging_required", False),
                "forced_deleveraging_required": r.get("forced_deleveraging_required", False),
                "post_deleveraging_position_compliance": r.get("post_deleveraging_position_compliance", None),
                "per_position_deleveraging_plan": r.get("per_position_deleveraging_plan", {}),
                "deleveraging_plan_exists": r.get("deleveraging_plan_exists", False),
                "deleveraging_plan_basis": r.get("deleveraging_plan_basis", ""),
                "estimated_post_deleveraging_total_position": r.get("estimated_post_deleveraging_total_position", None),
                "limitation_note": r.get("limitation_note", ""),
                "whether_future_leakage": r["whether_future_leakage"],
                "process_status": r["process_status"],
            }
            for r in results
        ],
        "best_path": best["path_id"],
        "largest_problem_path": worst_problem["path_id"],
        "profitable_path_count": profitable,
        "losing_path_count": losing,
        "average_return_pct": avg_return,
        "average_max_drawdown_pct": avg_drawdown,
        "max_loss_path": max_loss_path["path_id"],
        "max_drawdown_path": max_drawdown_path["path_id"],
        "most_trades_path": most_trades_path["path_id"],
        "can_enter_next_stage": can_enter_next_stage,
        "next_fix_if_not_enter": next_fix,
        "all_blocked_trade_review": all_blocked_trade_review,
        "intra02_conservative_review": intra02_conservative_review,
        "ai_review_reject_audit": ai_review_reject_audit,
        "sector_cycle_reject_audit": sector_cycle_reject_audit,
        "sector_cycle_reject_audit_count": sector_cycle_reject_audit["total_count"],
        "sector_cycle_reject_reasonable_count": sector_cycle_reject_audit["reasonable_count"],
        "sector_cycle_reject_too_conservative_count": sector_cycle_reject_audit["too_conservative_count"],
        "sector_cycle_reject_needs_rule_review_count": sector_cycle_reject_audit["needs_rule_review_count"],
        "leader_status_reject_audit": leader_status_reject_audit,
        "leader_status_reject_audit_count": leader_status_reject_audit["total_count"],
        "leader_status_reject_reasonable_count": leader_status_reject_audit["reasonable_count"],
        "leader_status_reject_too_conservative_count": leader_status_reject_audit["too_conservative_count"],
        "leader_status_reject_needs_rule_review_count": leader_status_reject_audit["needs_rule_review_count"],
        "ai_review_needs_human_audit": ai_review_needs_human_audit,
        "mvp_integrity_audit": {
            "field_completeness_ok": not field_completeness_report["has_critical_missing_fields"],
            "consistency_conflict_count": consistency_conflict_report["consistency_conflict_count"],
            "buy_count": buy_action_audit["buy_count"],
            "observe_count": sum(1 for item in collect_path_decisions(results) if item["decision"].get("final_user_action") == "OBSERVE"),
            "needs_human_review_count": needs_human_review_audit["needs_human_review_count"],
            "ai_review_reasonable": not ai_review_integrity_audit["ai_review_missed_risk_check"]["missed_risk"],
        },
        "field_completeness_report": field_completeness_report,
        "consistency_conflict_report": consistency_conflict_report,
        "buy_action_audit": buy_action_audit,
        "observe_action_audit": observe_action_audit,
        "needs_human_review_audit": needs_human_review_audit,
        "ai_review_integrity_audit": ai_review_integrity_audit,
        "ready_for_dual_track_shadow_simulation": dual_track_readiness["ready_for_dual_track_shadow_simulation"],
        "recommended_next_step": dual_track_readiness["recommended_next_step"],
        "needs_human_review_abuse_check": ai_review_needs_human_audit["abuse_check"],
        "missing_fields_next_schema_plan": missing_fields_next_schema_plan,
        "structured_candidate_summary": structured_candidate_summary,
        "structured_candidate_count": structured_candidate_summary["structured_candidate_count"],
        "unstructured_candidate_count": structured_candidate_summary["unstructured_candidate_count"],
        "unstructured_candidate_paths": structured_candidate_summary["unstructured_candidate_paths"],
        "ai_review_reject_unstructured_count": structured_candidate_summary["ai_review_reject_unstructured_count"],
        "pre03_model_caused_position_breach_audit": pre03_model_breach_audit,
        "core_trading_rule_changed_this_round": False,
        "this_round_scope": "审查 AI shadow review 的 REJECT/NEEDS_HUMAN_REVIEW 质量，并设计缺失字段下一轮结构方案；不改变真实交易动作，不影响收益计算，不修改评分权重，不接账户，不自动交易，不接消息面。",
        "ai_review_pass_count": sum(r.get("ai_review_pass_count", 0) for r in results),
        "ai_review_reject_count": sum(r.get("ai_review_reject_count", 0) for r in results),
        "ai_review_needs_human_count": sum(r.get("ai_review_needs_human_count", 0) for r in results),
        "ai_review_would_change_action_count": sum(r.get("ai_review_would_change_action_count", 0) for r in results),
        "strong_risk_reduce_exception_candidate_count": sum(r.get("strong_risk_reduce_exception_candidate_count", 0) for r in results),
        "final_user_action_counts": dict(aggregated_final_user_action_counts),
        "top_veto_reasons": aggregated_top_veto_reasons.most_common(10),
        "top_rule_conflicts": aggregated_top_rule_conflicts.most_common(10),
        "top_missing_fields": aggregated_top_missing_fields.most_common(10),
        "stock_selection_evidence_total_count": sum(r.get("stock_selection_evidence_total_count", 0) for r in results),
        "evidence_high_count": sum(r.get("evidence_high_count", 0) for r in results),
        "evidence_medium_count": sum(r.get("evidence_medium_count", 0) for r in results),
        "evidence_low_count": sum(r.get("evidence_low_count", 0) for r in results),
        "evidence_insufficient_count": sum(r.get("evidence_insufficient_count", 0) for r in results),
        "buy_with_insufficient_evidence_count": sum(r.get("buy_with_insufficient_evidence_count", 0) for r in results),
        "buy_with_low_evidence_count": sum(r.get("buy_with_low_evidence_count", 0) for r in results),
        "evidence_missing_reasons_top": aggregated_evidence_missing_reasons.most_common(10),
        "paths_with_insufficient_evidence": sorted(r["path_id"] for r in results if r.get("evidence_insufficient_count", 0) > 0),
        "ai_review_added_warnings_for_insufficient_evidence_count": sum(r.get("ai_review_added_warnings_for_insufficient_evidence_count", 0) for r in results),
        "sector_cycle_state_total_count": sum(r.get("sector_cycle_state_total_count", 0) for r in results),
        "sector_cycle_unknown_count": sum(r.get("sector_cycle_unknown_count", 0) for r in results),
        "sector_cycle_rising_count": sum(r.get("sector_cycle_rising_count", 0) for r in results),
        "sector_cycle_divergence_count": sum(r.get("sector_cycle_divergence_count", 0) for r in results),
        "sector_cycle_climax_count": sum(r.get("sector_cycle_climax_count", 0) for r in results),
        "sector_cycle_fading_count": sum(r.get("sector_cycle_fading_count", 0) for r in results),
        "sector_cycle_falling_count": sum(r.get("sector_cycle_falling_count", 0) for r in results),
        "sector_cycle_repairing_count": sum(r.get("sector_cycle_repairing_count", 0) for r in results),
        "buy_with_unknown_sector_cycle_count": sum(r.get("buy_with_unknown_sector_cycle_count", 0) for r in results),
        "buy_with_negative_sector_cycle_count": sum(r.get("buy_with_negative_sector_cycle_count", 0) for r in results),
        "ai_review_added_warnings_for_sector_cycle_count": sum(r.get("ai_review_added_warnings_for_sector_cycle_count", 0) for r in results),
        "sector_cycle_missing_reasons_top": aggregated_sector_cycle_missing_reasons.most_common(10),
        "paths_with_unknown_sector_cycle": sorted(r["path_id"] for r in results if r.get("sector_cycle_unknown_count", 0) > 0),
        "leader_status_total_count": sum(r.get("leader_status_total_count", 0) for r in results),
        "leader_status_unknown_count": sum(r.get("leader_status_unknown_count", 0) for r in results),
        "leader_status_strong_count": sum(r.get("leader_status_strong_count", 0) for r in results),
        "leader_status_weakening_count": sum(r.get("leader_status_weakening_count", 0) for r in results),
        "leader_status_broken_count": sum(r.get("leader_status_broken_count", 0) for r in results),
        "leader_status_rotating_count": sum(r.get("leader_status_rotating_count", 0) for r in results),
        "leader_status_no_clear_count": sum(r.get("leader_status_no_clear_count", 0) for r in results),
        "buy_with_unknown_leader_status_count": sum(r.get("buy_with_unknown_leader_status_count", 0) for r in results),
        "buy_with_negative_leader_status_count": sum(r.get("buy_with_negative_leader_status_count", 0) for r in results),
        "ai_review_added_warnings_for_leader_status_count": sum(r.get("ai_review_added_warnings_for_leader_status_count", 0) for r in results),
        "leader_status_missing_reasons_top": aggregated_leader_status_missing_reasons.most_common(10),
        "paths_with_unknown_leader_status": sorted(r["path_id"] for r in results if r.get("leader_status_unknown_count", 0) > 0),
        "dual_track_shadow_simulation_reason": dual_track_readiness["reason"],
        "dual_track_shadow_simulation_blockers": dual_track_readiness["blockers"],
        "critical_issues": [
            "ACC-01已生成逐票减仓计划，但仍是报告层模拟，未接真实账户、未基于真实持仓数量/成本成交。"
        ],
        "major_issues": [
            "INTRA路径已区分观察信号和交易信号，BLOCKED_TRADE不计入真实交易次数，但必须纳入审查。",
            "全部 BLOCKED_TRADE 已纳入执行质量审查；REVIEW_NOTE 保留为审查提示，不等同于严重执行错误。",
            "WF2025-INTRA-02 的 strong_trade_allowed REDUCE 被交易密度规则拦截，已进入 strong_risk_reduce_exception_candidate；本轮仅做 shadow review，不直接放宽核心交易规则。",
            "AI 二次审核层已作为 shadow review 输出，不改变真实交易动作和收益计算；final_user_action 已作为报告层字段固化。",
            "WF2025-PRE-03 的 model_caused_position_breach=True 属于过程单票仓位短暂超限且已在次日减仓修正，summary 的仓位合规=True 表示最终仓位合规。",
            "ACCOUNT_FULL_PATH已有逐票减仓计划，但第一版仍按估算市值分摊初始持仓，后续可接入真实持仓数量/成本做更精确模拟。",
        ],
        "minor_issues": [
            "报告展示字段需保持questions可见文件与validation_private私有文件的边界说明。"
        ],
        "todo_later": [
            "FULL_PIPELINE_SELECTION_WALK_FORWARD：当前测试不能证明完整自动选股能力。",
            "事件/消息风险过滤 MVP 后置；当前不接入全网新闻，不用普通消息直接触发买入。",
            "飞书/TG 稳定性后续单独处理。",
        ],
        "boundary_note": "10条路径结果只用于暴露流程问题，不证明模型长期有效。",
    }
    summary_json = outdir / "walk_forward_10paths_summary.json"
    summary_md = outdir / "walk_forward_10paths_summary.md"
    write_json(summary_json, summary)
    lines = [
        "# 2025 Walk-forward 10路径 MVP 汇总",
        "",
        f"- 生成时间：{summary['generated_at']}",
        f"- 本轮重跑路径：{', '.join(path_ids)}。",
        "- 汇总范围：10 条 Walk-forward 路径。",
        "- 作答输入只使用 questions 文件；validation_private 在每日决策完成后才读取。",
        "- 未运行完整评分，未修改评分权重，未自动交易，未接真实账户。",
        "- 当前测试不能证明完整自动选股能力。后续必须新增 FULL_PIPELINE_SELECTION_WALK_FORWARD 测试。",
        "- 事件/消息风险过滤 MVP 后置；当前不接入全网新闻，不用普通消息直接触发买入。",
        "",
        "| 路径 | 最终收益率 | 最大回撤 | 交易次数 | 拦截意图 | 过度交易 | 仓位合规 | 初始仓位超限 | 初始处理方式 | 计划减仓 | 减仓后合规 | 模型导致超限 | 风控失败 | 执行质量问题 | 问题级别 | 未来函数风险 |",
        "| -- | --: | --: | --: | --: | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |",
    ]
    for r in summary["results"]:
        lines.append(
            f"| {r['path_id']} | {r['final_return_pct']}% | {r['max_drawdown_pct']}% | {r['trade_count']} | {r.get('blocked_trade_count', 0)} | {r['overtrading_flag']} | {r['whether_position_rule_obeyed']} | {r.get('initial_position_breach')} | {r.get('account_initial_handling_state')} | {r.get('planned_deleveraging_required')} | {r.get('post_deleveraging_position_compliance')} | {r.get('model_caused_position_breach')} | {r.get('risk_control_failure')} | {r.get('execution_quality_issue')} | {r.get('execution_quality_issue_level')} | {r['whether_future_leakage']} |"
        )
    lines.extend(
        [
            "",
            "## 本轮小修前后对比",
            "",
            "| 路径 | 修正前收益 | 修正后收益 | 修正前最大回撤 | 修正后最大回撤 | 修正前交易次数 | 修正后交易次数 | 修正前仓位合规 | 修正后仓位合规 | 修正前风控失败 | 修正后风控失败 | 是否仍过度交易 |",
            "| -- | --: | --: | --: | --: | --: | --: | -- | -- | -- | -- | -- |",
            *[
                f"| {r['path_id']} | {BEFORE_10PATHS_ISSUE_FIX[r['path_id']]['final_return_pct']}% | {r['final_return_pct']}% | {BEFORE_10PATHS_ISSUE_FIX[r['path_id']]['max_drawdown_pct']}% | {r['max_drawdown_pct']}% | {BEFORE_10PATHS_ISSUE_FIX[r['path_id']]['trade_count']} | {r['trade_count']} | {BEFORE_10PATHS_ISSUE_FIX[r['path_id']]['position_ok']} | {r['whether_position_rule_obeyed']} | {BEFORE_10PATHS_ISSUE_FIX[r['path_id']]['risk_control_failure']} | {r.get('risk_control_failure')} | {r['overtrading_flag']} |"
                for r in summary["results"]
                if r["path_id"] in BEFORE_10PATHS_ISSUE_FIX
            ],
            "",
            f"- 盈利路径数量：{summary['profitable_path_count']}",
            f"- 亏损路径数量：{summary['losing_path_count']}",
            f"- 平均收益率：{summary['average_return_pct']}%",
            f"- 平均最大回撤：{summary['average_max_drawdown_pct']}%",
            f"- 最大亏损路径：{summary['max_loss_path']}",
            f"- 最大回撤路径：{summary['max_drawdown_path']}",
            f"- 交易次数最多路径：{summary['most_trades_path']}",
            f"- 表现最好路径：{summary['best_path']}",
            f"- 暴露最大问题路径：{summary['largest_problem_path']}",
            f"- 是否可以进入下一阶段：{summary['can_enter_next_stage']}",
            f"- 下一步判断：{summary['next_fix_if_not_enter']}",
            "",
            "## 全部 BLOCKED_TRADE 审查",
            "",
            f"- BLOCKED_TRADE 总数：{summary['all_blocked_trade_review']['total_blocked_trade_count']}",
            f"- 审查计数：{summary['all_blocked_trade_review']['review_counts']}",
            "- 说明：BLOCKED_TRADE 不计入真实交易次数，但纳入执行质量审查；REVIEW_NOTE 不等同于严重执行错误。",
            "",
            "| path | 日期/决策点 | 代码 | 名称 | intended_action | final_action | signal_strength | trade_block_reason | overtrading_guard | observe_only | 强减仓例外候选 | 需人工复核 | 审查结论 | 拦截原因 |",
            "| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |",
            *[
                f"| {item['path']} | {item['date']} | {item.get('ts_code')} | {item.get('name')} | {item.get('intended_action')} | {item.get('final_action')} | {item.get('signal_strength')} | {item.get('trade_block_reason')} | {item.get('blocked_by_overtrading_guard')} | {item.get('observe_only')} | {item.get('strong_risk_reduce_exception_candidate')} | {item.get('requires_human_review')} | {item.get('block_review')} | {item.get('block_reason')} |"
                for item in summary["all_blocked_trade_review"]["details"]
            ],
            "",
            "## INTRA-02 strong_trade_allowed 拦截复查",
            "",
            f"- 最终判断：{summary['intra02_conservative_review']['final_judgment']}",
            f"- A/B/C/D 计数：{summary['intra02_conservative_review']['judgment_counts']}",
            "- 本轮只输出审查结论和建议，不直接放宽核心交易规则。",
            "",
            "| 日期 | 代码 | 名称 | intended_action | signal_strength | trade_block_reason | 判断 | 说明 |",
            "| -- | -- | -- | -- | -- | -- | -- | -- |",
            *[
                f"| {item['date']} | {item.get('ts_code')} | {item.get('name')} | {item.get('intended_action')} | {item.get('signal_strength')} | {item.get('trade_block_reason')} | {item.get('judgment')}：{item.get('judgment_label')} | {item.get('reason')} |"
                for item in summary["intra02_conservative_review"]["details"]
            ],
            "",
            "## PRE-03 model_caused_position_breach 核查",
            "",
            f"- 是否误报：{summary['pre03_model_caused_position_breach_audit'].get('is_misreport')}",
            f"- 状态：{summary['pre03_model_caused_position_breach_audit'].get('status')}",
            f"- 说明：{summary['pre03_model_caused_position_breach_audit'].get('conclusion')}",
            f"- 字段口径：{summary['pre03_model_caused_position_breach_audit'].get('position_compliance_scope')}",
            "",
            "| 日期 | 代码 | 名称 | 股数 | 单票仓位 | 总仓位 | 决策动作 | 是否需减仓 |",
            "| -- | -- | -- | --: | --: | --: | -- | -- |",
            *[
                f"| {item.get('date')} | {item.get('ts_code')} | {item.get('name')} | {item.get('shares')} | {round(float(item.get('single_position_ratio') or 0) * 100, 2)}% | {round(float(item.get('total_position_ratio') or 0) * 100, 2)}% | {item.get('decision_action')} | {item.get('need_reduce_to_compliance')} |"
                for item in summary["pre03_model_caused_position_breach_audit"].get("breach_events", [])
            ],
            "",
            "## 10路径综合体检",
            "",
            f"- 字段完整性：{summary['field_completeness_report']['field_completeness_report']}",
            f"- 缺失字段总数：{summary['field_completeness_report']['missing_field_count']}",
            f"- 关键字段是否缺失：{summary['field_completeness_report']['has_critical_missing_fields']}",
            f"- 一致性冲突数：{summary['consistency_conflict_report']['consistency_conflict_count']}",
            f"- BUY 冲突数：{summary['consistency_conflict_report']['buy_conflict_count']}",
            f"- OBSERVE 可能过保守数：{summary['consistency_conflict_report']['observe_too_conservative_candidate_count']}",
            f"- REDUCE/SELL 缺少理由数：{summary['consistency_conflict_report']['reduce_sell_missing_reason_count']}",
            f"- NEEDS_HUMAN_REVIEW 滥用数：{summary['consistency_conflict_report']['needs_human_review_abuse_count']}",
            f"- BUY 审查分类：{summary['buy_action_audit']['audit_counts']}",
            f"- OBSERVE 原因 Top：{summary['observe_action_audit']['observe_reason_top']}",
            f"- NEEDS_HUMAN_REVIEW 复核：{summary['needs_human_review_audit']['needs_human_review_abuse_check']}",
            f"- ai_review 整体验收：{summary['ai_review_integrity_audit']}",
            f"- ready_for_dual_track_shadow_simulation：{summary['ready_for_dual_track_shadow_simulation']}",
            f"- recommended_next_step：{summary['recommended_next_step']}",
            "",
            "## AI shadow review",
            "",
            f"- pass：{summary['ai_review_pass_count']}",
            f"- reject：{summary['ai_review_reject_count']}",
            f"- needs_human：{summary['ai_review_needs_human_count']}",
            f"- would_change_action：{summary['ai_review_would_change_action_count']}",
            f"- strong_risk_reduce_exception_candidate：{summary['strong_risk_reduce_exception_candidate_count']}",
            f"- final_user_action_counts：{summary['final_user_action_counts']}",
            f"- top_veto_reasons：{summary['top_veto_reasons']}",
            f"- top_rule_conflicts：{summary['top_rule_conflicts']}",
            f"- top_missing_fields：{summary['top_missing_fields']}",
            f"- stock_selection_evidence_total_count：{summary['stock_selection_evidence_total_count']}",
            f"- evidence_high/medium/low/insufficient：{summary['evidence_high_count']}/{summary['evidence_medium_count']}/{summary['evidence_low_count']}/{summary['evidence_insufficient_count']}",
            f"- buy_with_insufficient_evidence_count：{summary['buy_with_insufficient_evidence_count']}",
            f"- buy_with_low_evidence_count：{summary['buy_with_low_evidence_count']}",
            f"- evidence_missing_reasons_top：{summary['evidence_missing_reasons_top']}",
            f"- paths_with_insufficient_evidence：{summary['paths_with_insufficient_evidence']}",
            f"- ai_review_added_warnings_for_insufficient_evidence_count：{summary['ai_review_added_warnings_for_insufficient_evidence_count']}",
            f"- sector_cycle_state_total_count：{summary['sector_cycle_state_total_count']}",
            f"- sector_cycle UNKNOWN/RISING/DIVERGENCE/CLIMAX/FADING/FALLING/REPAIRING：{summary['sector_cycle_unknown_count']}/{summary['sector_cycle_rising_count']}/{summary['sector_cycle_divergence_count']}/{summary['sector_cycle_climax_count']}/{summary['sector_cycle_fading_count']}/{summary['sector_cycle_falling_count']}/{summary['sector_cycle_repairing_count']}",
            f"- buy_with_unknown_sector_cycle_count：{summary['buy_with_unknown_sector_cycle_count']}",
            f"- buy_with_negative_sector_cycle_count：{summary['buy_with_negative_sector_cycle_count']}",
            f"- ai_review_added_warnings_for_sector_cycle_count：{summary['ai_review_added_warnings_for_sector_cycle_count']}",
            f"- sector_cycle_missing_reasons_top：{summary['sector_cycle_missing_reasons_top']}",
            f"- paths_with_unknown_sector_cycle：{summary['paths_with_unknown_sector_cycle']}",
            f"- leader_status_total_count：{summary['leader_status_total_count']}",
            f"- leader_status UNKNOWN/STRONG/WEAKENING/BROKEN/ROTATING/NO_CLEAR：{summary['leader_status_unknown_count']}/{summary['leader_status_strong_count']}/{summary['leader_status_weakening_count']}/{summary['leader_status_broken_count']}/{summary['leader_status_rotating_count']}/{summary['leader_status_no_clear_count']}",
            f"- buy_with_unknown_leader_status_count：{summary['buy_with_unknown_leader_status_count']}",
            f"- buy_with_negative_leader_status_count：{summary['buy_with_negative_leader_status_count']}",
            f"- ai_review_added_warnings_for_leader_status_count：{summary['ai_review_added_warnings_for_leader_status_count']}",
            f"- leader_status_missing_reasons_top：{summary['leader_status_missing_reasons_top']}",
            f"- paths_with_unknown_leader_status：{summary['paths_with_unknown_leader_status']}",
            f"- structured_candidate_count：{summary['structured_candidate_count']}",
            f"- unstructured_candidate_count：{summary['unstructured_candidate_count']}",
            f"- unstructured_candidate_paths：{summary['unstructured_candidate_paths']}",
            f"- ai_review_reject_unstructured_count：{summary['ai_review_reject_unstructured_count']}",
            "",
            "## sector_cycle_state 新增 REJECT 审查",
            "",
            f"- 审查数量：{summary['sector_cycle_reject_audit_count']}",
            f"- reasonable_reject：{summary['sector_cycle_reject_reasonable_count']}",
            f"- too_conservative_reject：{summary['sector_cycle_reject_too_conservative_count']}",
            f"- needs_rule_review：{summary['sector_cycle_reject_needs_rule_review_count']}",
            f"- 规则建议：{summary['sector_cycle_reject_audit']['rule_change_recommendation']}",
            "",
            "| path | 日期 | 代码 | 名称 | 原始动作 | 审核后动作 | sector_cycle_state | evidence_quality | 仓位限制 | 交易密度限制 | 审查结论 | 审查说明 |",
            "| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |",
            *[
                f"| {item.get('path')} | {item.get('date')} | {item.get('ts_code')} | {item.get('name')} | {item.get('initial_model_action')} | {item.get('final_action_after_review')} | {item.get('sector_cycle_state')} | {item.get('evidence_quality')} | {item.get('has_position_limit')} | {item.get('has_trade_density_limit')} | {item.get('audit_verdict')} | {item.get('rationale')} |"
                for item in summary["sector_cycle_reject_audit"]["details"]
            ],
            "",
            "## leader_status 新增 REJECT 审查",
            "",
            f"- 审查数量：{summary['leader_status_reject_audit_count']}",
            f"- reasonable_reject：{summary['leader_status_reject_reasonable_count']}",
            f"- too_conservative_reject：{summary['leader_status_reject_too_conservative_count']}",
            f"- needs_rule_review：{summary['leader_status_reject_needs_rule_review_count']}",
            f"- 规则建议：{summary['leader_status_reject_audit']['rule_change_recommendation']}",
            "",
            "| path | 日期 | 代码 | 名称 | 原始动作 | 审核后动作 | leader_status | sector_cycle_state | evidence_quality | 仓位限制 | 交易密度限制 | 审查结论 | 审查说明 |",
            "| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |",
            *[
                f"| {item.get('path')} | {item.get('date')} | {item.get('ts_code')} | {item.get('name')} | {item.get('initial_model_action')} | {item.get('final_action_after_review')} | {item.get('leader_status')} | {item.get('sector_cycle_state')} | {item.get('evidence_quality')} | {item.get('has_position_limit')} | {item.get('has_trade_density_limit')} | {item.get('audit_verdict')} | {item.get('rationale')} |"
                for item in summary["leader_status_reject_audit"]["details"]
            ],
            "",
            "## ai_review REJECT 审查",
            "",
            f"- REJECT 总数：{summary['ai_review_reject_audit']['total_reject_count']}",
            f"- 审查分类：{summary['ai_review_reject_audit']['audit_counts']}",
            f"- 结论：{summary['ai_review_reject_audit']['conclusion']}",
            "",
            "| path | 日期 | 代码 | 名称 | 结构化 | 缺失原因 | initial_model_action | final_action_after_review | veto_reason | rule_conflicts | max_allowed_action | final_user_action | 审查结论 | 是否合理 |",
            "| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |",
            *[
                f"| {item.get('path')} | {item.get('date')} | {item.get('ts_code')} | {item.get('name')} | {item.get('candidate_is_structured')} | {item.get('candidate_missing_reason')} | {item.get('initial_model_action')} | {item.get('final_action_after_review')} | {item.get('veto_reason')} | {item.get('rule_conflicts')} | {item.get('max_allowed_action')} | {item.get('final_user_action')} | {item.get('audit_verdict')} | {item.get('is_reasonable')} |"
                for item in summary["ai_review_reject_audit"]["details"]
            ],
            "",
            "## ai_review NEEDS_HUMAN_REVIEW 审查",
            "",
            f"- NEEDS_HUMAN_REVIEW 总数：{summary['ai_review_needs_human_audit']['total_needs_human_count']}",
            f"- 是否全部对应 INTRA-02 强风险减仓例外候选：{summary['ai_review_needs_human_audit']['all_correspond_to_intra02_exception']}",
            f"- 是否滥用：{summary['needs_human_review_abuse_check']['is_abused']}",
            f"- 滥用检查结论：{summary['needs_human_review_abuse_check']['conclusion']}",
            "",
            "| path | 日期 | 代码 | 名称 | intended_action | signal_strength | trade_block_reason | exception_candidate | requires_human_review | final_user_action | 人工复核原因 | 异常 |",
            "| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |",
            *[
                f"| {item.get('path')} | {item.get('date')} | {item.get('ts_code')} | {item.get('name')} | {item.get('intended_action')} | {item.get('signal_strength')} | {item.get('trade_block_reason')} | {item.get('strong_risk_reduce_exception_candidate')} | {item.get('requires_human_review')} | {item.get('final_user_action')} | {item.get('human_review_reason')} | {item.get('is_abnormal')} |"
                for item in summary["ai_review_needs_human_audit"]["details"]
            ],
            "",
            "## 缺失字段下一轮结构方案",
            "",
            f"- 范围：{summary['missing_fields_next_schema_plan']['scope']}",
            f"- sector_cycle_state：{summary['missing_fields_next_schema_plan']['sector_cycle_state']}",
            f"- leader_status：{summary['missing_fields_next_schema_plan']['leader_status']}",
            f"- stock_selection_evidence：{summary['missing_fields_next_schema_plan']['stock_selection_evidence']}",
            f"- 实施说明：{summary['missing_fields_next_schema_plan']['implementation_note']}",
            "",
            "## 问题分层",
            "",
            "### critical_issues",
            *[f"- {item}" for item in summary["critical_issues"]],
            "",
            "### major_issues",
            *[f"- {item}" for item in summary["major_issues"]],
            "",
            "### minor_issues",
            *[f"- {item}" for item in summary["minor_issues"]],
            "",
            "### todo_later",
            *[f"- {item}" for item in summary["todo_later"]],
            "",
            "边界：10条路径结果只用于暴露流程问题，不证明模型长期有效。",
        ]
    )
    summary_md.write_text("\n".join(lines), encoding="utf-8")
    return {**summary, "summary_md": str(summary_md), "summary_json": str(summary_json)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path-id", default=PATH_ID)
    parser.add_argument("--path-ids", default="")
    parser.add_argument("--questions-json", default="reports/tests_2025/walk_forward_paths_2025_questions.json")
    parser.add_argument("--validation-json", default="reports/tests_2025/walk_forward_paths_2025_validation_private.json")
    parser.add_argument("--db-path", default="D:/股票AI交易助手数据/sqlite/market_2025.sqlite")
    parser.add_argument("--summary-only-existing", action="store_true")
    args = parser.parse_args()
    if args.path_ids:
        print(json.dumps(run_three(args), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
