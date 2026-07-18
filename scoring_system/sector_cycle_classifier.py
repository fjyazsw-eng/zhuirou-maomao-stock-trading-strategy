from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scoring_system.sector_cycle_labels import AUXILIARY_LABELS, MAIN_CYCLE_LABELS, advice_for


@dataclass(frozen=True)
class CycleResult:
    main_label: str
    auxiliary_labels: list[str]
    confidence: str
    support_evidence: list[str]
    oppose_evidence: list[str]
    empty_advice: str
    holding_advice: str
    no_watch_advice: str
    max_position: str


def _confidence(score: int, evidence_count: int) -> str:
    if score >= 3 and evidence_count >= 3:
        return "HIGH"
    if score >= 1 and evidence_count >= 2:
        return "MEDIUM"
    return "LOW"


def classify_sector_cycle(metrics: dict[str, Any], breadth: dict[str, Any], pool: list[dict[str, Any]]) -> CycleResult:
    r1 = metrics.get("1日", {}).get("等权涨跌幅%")
    r3 = metrics.get("3日", {}).get("等权涨跌幅%")
    r5 = metrics.get("5日", {}).get("等权涨跌幅%")
    r10 = metrics.get("10日", {}).get("等权涨跌幅%")
    r20 = metrics.get("20日", {}).get("等权涨跌幅%")
    up = int(breadth.get("当日上涨家数", 0) or 0)
    down = int(breadth.get("当日下跌家数", 0) or 0)
    total = max(up + down, 1)
    up_ratio = up / total
    high_count = sum(1 for x in pool if isinstance(x.get("20日位置"), (int, float)) and x["20日位置"] >= 0.8)
    weak_count = sum(1 for x in pool if x["角色"] in {"后排或弱结构", "角色不确定"})
    core_count = sum(1 for x in pool if x["角色"] in {"疑似龙头", "容量核心", "趋势核心", "次核心"})
    support_evidence: list[str] = []
    oppose_evidence: list[str] = []
    main_label = "UNKNOWN"
    aux: list[str] = []
    score = 0

    if all(v is None for v in [r1, r3, r5, r10, r20]):
        support_evidence.append("窗口指标不足，无法形成稳定判断。")
        confidence = "LOW"
        advice = advice_for(main_label, aux)
        return CycleResult(main_label, aux, confidence, support_evidence, oppose_evidence, advice["empty_advice"], advice["holding_advice"], advice["no_watch_advice"], advice["max_position"])

    if r20 is not None and r10 is not None and r5 is not None and r20 >= 20 and r10 >= 10 and up_ratio < 0.58 and (weak_count >= 2 or high_count >= 3):
        main_label = "DIVERGENCE"
        score += 2
        support_evidence.append("中期涨幅很高，但当日扩散不足，已经从强势转为高位分歧。")
        aux.extend(["HIGH_LEVEL_UNSTABLE", "WAIT_FOR_CONFIRMATION"])
        if weak_count >= 2:
            aux.append("BACKROW_RISK_SPREAD")
            support_evidence.append("后排或弱结构数量偏多，风险开始扩散。")
        if high_count >= 3:
            support_evidence.append("高位区个股较多，追高风险上升。")
    elif r20 is not None and r10 is not None and r5 is not None and r20 >= 12 and r10 >= 5 and r5 >= 0 and up_ratio >= 0.55:
        main_label = "CLIMAX"
        score += 3
        support_evidence.append("20日、10日、5日都偏强，且上涨家数占优。")
        if high_count >= 3:
            aux.append("HIGH_LEVEL_UNSTABLE")
            support_evidence.append("高位区个股数量偏多。")
        if high_count >= 5 and r20 >= 30:
            aux.append("CLIMAX_FADING_RISK")
            support_evidence.append("高位加速程度较强，需要防高潮后风险释放。")
        if weak_count >= 2:
            aux.append("CLIMAX_FADING_RISK")
            support_evidence.append("后排已有先弱迹象。")
    elif r10 is not None and r5 is not None and r10 > 0 and r5 < 0 and up_ratio < 0.55:
        main_label = "DIVERGENCE"
        score += 2
        support_evidence.append("中期仍有强度，但短线开始分歧。")
        aux.append("WAIT_FOR_CONFIRMATION")
        if weak_count >= 2:
            aux.append("BACKROW_RISK_SPREAD")
            support_evidence.append("后排风险有扩散迹象。")
        if high_count >= 2:
            aux.append("HIGH_LEVEL_UNSTABLE")
    elif r10 is not None and r10 > 0 and r5 is not None and r5 >= -2 and core_count >= 1:
        main_label = "STARTING"
        score += 2
        support_evidence.append("中期开始走强，且有核心先行。")
        aux.append("STRUCTURAL_START")
        if r3 is not None and r3 > 0 and r1 is not None and r1 > 0:
            aux.append("WEAK_TO_STRONG_WATCH")
    elif r5 is not None and r5 > 0 and r10 is not None and r10 > 0 and r20 is not None and r20 > 0 and core_count >= 1:
        main_label = "FERMENTING"
        score += 2
        support_evidence.append("多周期转强并且核心有效。")
        aux.append("CORE_STILL_VALID")
    elif r10 is not None and r10 < 0 and r5 is not None and r5 < 0:
        main_label = "FADING"
        score += 2
        support_evidence.append("中短线都走弱，板块进入退潮。")
        aux.append("CORE_BREAKING_DOWN")
        if weak_count >= 1:
            aux.append("BACKROW_RISK_SPREAD")
    elif r20 is not None and r20 >= 5 and r5 is not None and r5 < 0 and high_count >= 2:
        main_label = "CLIMAX"
        score += 1
        support_evidence.append("中期仍强，但短线回落且高位股较多。")
        aux.extend(["CLIMAX_FADING_RISK", "HIGH_LEVEL_UNSTABLE"])
    elif r5 is not None and r5 < 0 and r10 is not None and r10 >= 0:
        main_label = "REPAIR"
        score += 1
        support_evidence.append("短线回调后，仍有修复尝试可能。")
        aux.append("SHORT_REPAIR")
        if core_count >= 1:
            aux.append("SUPPORT_CONFIRMED")
    else:
        main_label = "UNKNOWN"
        if core_count >= 1 and max([v for v in [r1, r3, r5, r10, r20] if v is not None], default=0) > 0:
            aux.append("STRUCTURAL_START")
            aux.append("NON_MAINLINE_OPPORTUNITY")
            support_evidence.append("存在局部结构性转强信号，但不足以定义为全面强势。")
            score += 1
        elif weak_count >= 2:
            aux.append("WAIT_FOR_CONFIRMATION")
            oppose_evidence.append("强弱证据冲突，等待确认更稳。")
        else:
            oppose_evidence.append("证据不足，无法分型。")

    if r1 is not None and r1 < 0:
        oppose_evidence.append("介入日当日偏弱，不适合直接追。")
    if r20 is not None and r20 is not None and r20 < 0 and "CLIMAX" in aux:
        oppose_evidence.append("20日并不强，不足以支撑高潮。")
    if high_count >= 4 and "HIGH_LEVEL_UNSTABLE" not in aux:
        aux.append("HIGH_LEVEL_UNSTABLE")
    if weak_count >= 3 and "BACKROW_RISK_SPREAD" not in aux:
        aux.append("BACKROW_RISK_SPREAD")
    if "WAIT_FOR_CONFIRMATION" not in aux and main_label == "UNKNOWN" and not support_evidence:
        aux.append("WAIT_FOR_CONFIRMATION")

    confidence = _confidence(score, len(support_evidence) + len(oppose_evidence))
    if main_label == "UNKNOWN" and "STRUCTURAL_START" in aux and confidence == "LOW":
        confidence = "MEDIUM"

    advice = advice_for(main_label, aux)
    return CycleResult(
        main_label=main_label,
        auxiliary_labels=aux,
        confidence=confidence,
        support_evidence=support_evidence,
        oppose_evidence=oppose_evidence,
        empty_advice=advice["empty_advice"],
        holding_advice=advice["holding_advice"],
        no_watch_advice=advice["no_watch_advice"],
        max_position=advice["max_position"],
    )


def labels_to_text(labels: list[str]) -> str:
    if not labels:
        return "-"
    return " / ".join(labels)


def label_desc(code: str) -> dict[str, Any]:
    if code in MAIN_CYCLE_LABELS:
        label = MAIN_CYCLE_LABELS[code]
    else:
        label = AUXILIARY_LABELS[code]
    return {
        "code": label.code,
        "name": label.name,
        "meaning": label.meaning,
        "trigger": label.trigger,
        "empty_advice": label.empty_advice,
        "holding_advice": label.holding_advice,
        "no_watch_advice": label.no_watch_advice,
        "max_position": label.max_position,
    }
