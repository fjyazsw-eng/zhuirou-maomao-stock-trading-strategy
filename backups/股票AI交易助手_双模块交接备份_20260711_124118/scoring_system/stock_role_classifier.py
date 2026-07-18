from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from scoring_system.stock_role_labels import stock_role_info


CORE_ROLES = {"LEADER", "CAPACITY_CORE", "TREND_CORE", "SECONDARY_CORE"}


@dataclass(frozen=True)
class StockRoleResult:
    role: str
    role_name: str
    confidence: str
    evidence: list[str]
    risks: list[str]
    is_core: bool
    is_backrow: bool
    is_catch_up: bool
    is_weak_structure: bool
    suitable_for_no_watch: bool
    execution_effect: str


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _parse_json(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return {}


def _sub_value(sub_scores: dict[str, Any], bucket: str, key: str) -> float | None:
    item = sub_scores.get(bucket, {}).get(key, {})
    if isinstance(item, dict):
        return _num(item.get("value"))
    return None


def classify_stock_role(data: dict[str, Any]) -> StockRoleResult:
    name = _text(data.get("name"))
    stock_score = _num(data.get("stock_score")) or 0
    leader_score = _num(data.get("leader_score")) or 0
    trend_score = _num(data.get("trend_structure_score")) or 0
    volume_score = _num(data.get("volume_price_quality_score")) or 0
    heat_score = _num(data.get("position_heat_score")) or 0
    tradability_score = _num(data.get("tradability_score")) or 0
    pct_1d = _num(data.get("pct_1d", data.get("pct_chg")))
    pct_3d = _num(data.get("pct_3d"))
    pct_5d = _num(data.get("pct_5d"))
    pct_10d = _num(data.get("pct_10d"))
    pct_20d = _num(data.get("pct_20d"))
    amount_rank_pct = _num(data.get("amount_rank_pct"))
    relative_strength = _num(data.get("relative_strength"))
    turnover_rate = _num(data.get("turnover_rate"))
    sector_cycle = _text(data.get("sector_cycle") or "UNKNOWN")
    leader_labels = _text(data.get("leader_labels"))
    risk_text = _text(data.get("risk_text") or data.get("basic_risk"))
    status_text = _text(data.get("execution_status") or data.get("original_status"))
    sub_scores = _parse_json(data.get("sub_scores_json"))

    high_position_value = _sub_value(sub_scores, "position_heat", "price_percentile_20d")
    amount_percentile = _sub_value(sub_scores, "position_heat", "amount_percentile_20d")
    ma_distance = _sub_value(sub_scores, "position_heat", "ma_distance")
    high_position = bool(data.get("high_position")) or (high_position_value is not None and high_position_value >= 0.85) or "位置过热" in risk_text
    broken_ma = bool(data.get("broken_ma")) or "跌破MA20" in risk_text or "WEAK_STRUCTURE" in status_text
    sudden_catch_up = bool(data.get("sudden_catch_up"))
    if pct_1d is not None and pct_1d >= 7:
        sudden_catch_up = True
    if pct_3d is not None and pct_3d >= 12 and (pct_10d is None or pct_10d < pct_3d * 1.5):
        sudden_catch_up = True

    evidence: list[str] = []
    risks: list[str] = []
    role = "UNCERTAIN_ROLE"
    confidence = "LOW"

    if broken_ma or stock_score < 55:
        role = "WEAK_STRUCTURE"
        confidence = "HIGH" if broken_ma else "MEDIUM"
        risks.append("跌破关键均线、原始状态偏弱或个股分低。")
    elif (
        leader_score >= 88
        and stock_score >= 72
        and ("龙头" in leader_labels or relative_strength is None or relative_strength >= 70)
        and not sudden_catch_up
    ):
        role = "LEADER"
        confidence = "HIGH"
        evidence.append("龙头分和个股分同时靠前，且不是单日脉冲。")
    elif (tradability_score >= 13 or "容量核心" in leader_labels or (amount_rank_pct is not None and amount_rank_pct <= 0.25)) and leader_score >= 75:
        role = "CAPACITY_CORE"
        confidence = "HIGH" if leader_score >= 85 else "MEDIUM"
        evidence.append("成交承载能力和龙头分靠前，具备容量核心特征。")
    elif trend_score >= 26 and stock_score >= 70 and not broken_ma:
        role = "TREND_CORE"
        confidence = "MEDIUM"
        evidence.append("趋势结构得分较高，个股分靠前，未见明显破位。")
    elif sudden_catch_up and stock_score >= 65:
        role = "CATCH_UP"
        confidence = "MEDIUM"
        evidence.append("1日/3日短线突然增强，属于补涨候选而非直接龙头。")
        if sector_cycle in {"CLIMAX", "DIVERGENCE", "FADING", "ENDED"} or high_position:
            risks.append("补涨叠加高位或板块分歧，追高风险较大。")
    elif leader_score >= 70 or stock_score >= 65:
        role = "SECONDARY_CORE"
        confidence = "MEDIUM"
        evidence.append("有一定强度，但龙头、容量或趋势证据不足。")
    elif stock_score >= 55:
        role = "FOLLOWER"
        confidence = "MEDIUM" if amount_rank_pct is not None and amount_rank_pct > 0.6 else "LOW"
        evidence.append("有跟随表现，但辨识度或成交承载不足。")
    else:
        role = "UNCERTAIN_ROLE"
        confidence = "LOW"
        risks.append("证据不足，暂不硬贴核心标签。")

    if high_position and role in {"CATCH_UP", "FOLLOWER", "SECONDARY_CORE"}:
        risks.append("位置偏高，角色不支持放大仓位。")
    if amount_percentile is not None and amount_percentile >= 0.95 and volume_score < 18:
        risks.append("成交额处在高分位但量价质量不够强，可能是短线脉冲。")
    if turnover_rate is not None and turnover_rate >= 20 and role not in {"LEADER", "CAPACITY_CORE"}:
        risks.append("换手过高且非明确核心，不适合不能盯盘用户。")

    if not evidence:
        info = stock_role_info(role)
        evidence.append(info.meaning)

    is_core = role in CORE_ROLES
    is_backrow = role in {"FOLLOWER", "WEAK_STRUCTURE"}
    is_catch_up = role == "CATCH_UP"
    is_weak_structure = role == "WEAK_STRUCTURE"
    suitable_for_no_watch = role in {"LEADER", "CAPACITY_CORE", "TREND_CORE"} and confidence != "LOW" and not risks
    info = stock_role_info(role)
    return StockRoleResult(
        role=role,
        role_name=info.name,
        confidence=confidence,
        evidence=list(dict.fromkeys(evidence)),
        risks=list(dict.fromkeys(risks)),
        is_core=is_core,
        is_backrow=is_backrow,
        is_catch_up=is_catch_up,
        is_weak_structure=is_weak_structure,
        suitable_for_no_watch=suitable_for_no_watch,
        execution_effect=info.execution_effect,
    )


def classify_stock_role_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    result = classify_stock_role(data)
    return {
        "role": result.role,
        "role_name": result.role_name,
        "confidence": result.confidence,
        "evidence": result.evidence,
        "risks": result.risks,
        "is_core": result.is_core,
        "is_backrow": result.is_backrow,
        "is_catch_up": result.is_catch_up,
        "is_weak_structure": result.is_weak_structure,
        "suitable_for_no_watch": result.suitable_for_no_watch,
        "execution_effect": result.execution_effect,
    }
