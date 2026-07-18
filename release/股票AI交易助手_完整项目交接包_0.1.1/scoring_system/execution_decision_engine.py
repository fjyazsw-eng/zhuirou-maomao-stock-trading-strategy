from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scoring_system.execution_labels import label_info
from scoring_system.position_sizing import position_plan


CORE_WORDS = ("情绪龙头", "容量核心", "趋势核心", "MULTI_CORE", "CORE", "疑似龙头", "次核心")
BACKROW_WORDS = ("后排", "弱结构", "WEAK", "FOLLOWER")
HIGH_RISK_WORDS = ("位置过热", "最近5日波动过大", "单日异动", "放量但收盘位置弱", "跌破MA20", "冲高回落")


@dataclass(frozen=True)
class ExecutionInput:
    ts_code: str
    name: str
    stock_score: float | None
    leader_score: float | None
    original_status: str
    sector_name: str
    sector_cycle: str
    sector_aux_labels: list[str]
    sector_confidence: str
    risk_text: str
    leader_labels: str
    core_identity: str
    stock_role: str = ""
    user_state: str = "empty"
    can_watch: bool = True
    has_alert: bool = True
    cost: float | None = None
    latest_price: float | None = None


@dataclass(frozen=True)
class ExecutionDecision:
    original_status: str
    final_label: str
    allow_buy: bool
    allow_add: bool
    max_position_pct: int
    sector_cycle_text: str
    sector_confidence: str
    downgrade_reasons: list[str]
    empty_advice: str
    holding_advice: str
    no_watch_advice: str
    stop_advice: str
    profit_protection_advice: str
    upgrade_conditions: list[str]
    invalid_conditions: list[str]


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _is_core(inp: ExecutionInput) -> bool:
    text = f"{inp.leader_labels} {inp.core_identity} {inp.stock_role}"
    return _has_any(text, CORE_WORDS)


def _is_backrow(inp: ExecutionInput) -> bool:
    text = f"{inp.leader_labels} {inp.core_identity} {inp.risk_text} {inp.stock_role}"
    return _has_any(text, BACKROW_WORDS)


def _role_code(inp: ExecutionInput) -> str:
    return (inp.stock_role or "").upper()


def _is_catch_up(inp: ExecutionInput) -> bool:
    return _role_code(inp) == "CATCH_UP" or "补涨" in (inp.stock_role or "")


def _is_weak_role(inp: ExecutionInput) -> bool:
    role = _role_code(inp)
    return role in {"FOLLOWER", "WEAK_STRUCTURE"} or _is_backrow(inp)


def _high_risk(inp: ExecutionInput) -> bool:
    return _has_any(inp.risk_text, HIGH_RISK_WORDS)


def _base_label(inp: ExecutionInput) -> tuple[str, list[str]]:
    reasons: list[str] = []
    status = inp.original_status or ""
    stock_score = inp.stock_score or 0
    is_core = _is_core(inp)
    high_risk = _high_risk(inp)

    if status in {"READY_CORE", "READY_SECONDARY", "READY_CONFIRM"} and stock_score >= 78 and is_core and not high_risk:
        return "READY_CONFIRM", reasons
    if status in {"READY_CORE", "READY_SECONDARY", "WAIT_CONFIRM"} and stock_score >= 72 and is_core:
        return "READY_TRIAL", reasons
    if "WAIT_PULLBACK" in status:
        reasons.append("原始状态提示短期过热或等待回踩。")
        return "WAIT_STRONG_PULLBACK", reasons
    if "WAIT_CONFIRM" in status:
        reasons.append("原始状态仍需等待确认。")
        return "WAIT_CONFIRM", reasons
    if status in {"WEAK_STRUCTURE", "AVOID"}:
        reasons.append("原始状态偏弱。")
        return "BREAKDOWN_AVOID", reasons
    if stock_score >= 78 and is_core:
        return "READY_TRIAL", reasons
    reasons.append("个股条件不足以直接参与。")
    return "OBSERVE_ONLY", reasons


def _apply_sector_rules(label: str, inp: ExecutionInput, reasons: list[str]) -> str:
    cycle = inp.sector_cycle
    aux = set(inp.sector_aux_labels)
    is_core = _is_core(inp)
    is_backrow = _is_backrow(inp)

    if cycle == "CLIMAX" or "CLIMAX_FADING_RISK" in aux:
        reasons.append("板块处于高潮或高潮后退潮风险，空仓不追高。")
        if inp.user_state == "holding":
            return "HOLD_WITH_PROTECTION" if is_core else "REDUCE_RISK"
        if label == "READY_CONFIRM":
            return "WAIT_STRONG_PULLBACK"
        return "OVERHEATED_NO_CHASE"

    if cycle == "DIVERGENCE":
        reasons.append("板块分歧，空仓等待承接。")
        if is_backrow:
            reasons.append("板块分歧时后排或弱结构优先降级。")
            return "BREAKDOWN_AVOID"
        if "SUPPORT_CONFIRMED" not in aux:
            return "WAIT_FOR_SUPPORT"
        return label if label in {"READY_TRIAL", "READY_CONFIRM"} else "WAIT_FOR_SUPPORT"

    if cycle in {"FADING", "ENDED"}:
        reasons.append("板块退潮或结束，不开新仓。")
        if inp.user_state == "holding":
            return "EXIT_LOGIC_BROKEN" if is_backrow else "REDUCE_RISK"
        return "BREAKDOWN_AVOID"

    if cycle == "STARTING" or "STRUCTURAL_START" in aux:
        if is_backrow:
            reasons.append("结构性启动阶段只看核心，后排不参与。")
            return "OBSERVE_ONLY"
        if inp.sector_confidence == "LOW":
            reasons.append("板块置信度低，只允许观察或小试错。")
            return "READY_TRIAL" if label == "READY_CONFIRM" and is_core else "OBSERVE_ONLY"
        if is_core and label in {"READY_CONFIRM", "READY_TRIAL", "WAIT_CONFIRM"}:
            return "READY_TRIAL"

    if cycle == "UNKNOWN":
        if "HIGH_LEVEL_UNSTABLE" in aux:
            reasons.append("板块状态不明且高位不稳定。")
            return "OBSERVE_ONLY"
        if "STRUCTURAL_START" in aux and is_core and inp.sector_confidence != "LOW":
            reasons.append("状态不确定但有结构性启动，只允许小仓观察。")
            return "READY_TRIAL"
        reasons.append("板块状态不确定，默认等待确认。")
        return "WAIT_CONFIRM"

    return label


def _apply_stock_risks(label: str, inp: ExecutionInput, reasons: list[str]) -> str:
    risk = inp.risk_text
    is_core = _is_core(inp)
    is_backrow = _is_backrow(inp)
    aux = set(inp.sector_aux_labels)

    if is_backrow and inp.sector_cycle in {"DIVERGENCE", "FADING", "ENDED"}:
        reasons.append("后排个股遇到板块分歧或退潮，规避。")
        return "BREAKDOWN_AVOID"
    if "跌破MA20" in risk:
        reasons.append("跌破关键均线。")
        return "BREAKDOWN_AVOID"
    if "冲高回落" in risk and ("位置过热" in risk or inp.sector_cycle in {"CLIMAX", "DIVERGENCE"}):
        reasons.append("高位冲高回落，不追。")
        return "OVERHEATED_NO_CHASE"
    if "位置过热" in risk and label in {"READY_CONFIRM", "READY_TRIAL", "WAIT_STRONG_PULLBACK"}:
        reasons.append("个股位置过热，等待回踩或承接。")
        return "WAIT_STRONG_PULLBACK" if is_core else "OVERHEATED_NO_CHASE"
    if "放量但收盘位置弱" in risk:
        reasons.append("放量但收盘位置弱，先等确认。")
        return "WAIT_CONFIRM"
    if not is_core and inp.stock_score and inp.stock_score >= 78 and inp.sector_cycle not in {"FERMENTING", "STARTING"}:
        reasons.append("个股较强但板块不同步，降低为观察或等待。")
        return "READY_TRIAL" if "STRUCTURAL_START" in aux else "WAIT_CONFIRM"
    return label


def _apply_role_rules(label: str, inp: ExecutionInput, reasons: list[str]) -> str:
    role = _role_code(inp)
    cycle = inp.sector_cycle
    if role == "WEAK_STRUCTURE":
        reasons.append("个股角色为弱结构，不作为买入对象，持仓也要更谨慎。")
        return "BREAKDOWN_AVOID" if inp.user_state == "empty" else "REDUCE_RISK"
    if role == "FOLLOWER":
        if cycle in {"DIVERGENCE", "FADING", "ENDED"}:
            reasons.append("个股角色为后排，板块分歧或退潮时优先规避。")
            return "BREAKDOWN_AVOID" if inp.user_state == "empty" else "REDUCE_RISK"
        if label in {"READY_CONFIRM", "READY_TRIAL"}:
            reasons.append("个股角色为后排，不能作为主要仓位。")
            return "OBSERVE_ONLY"
    if role == "CATCH_UP":
        if cycle in {"CLIMAX", "DIVERGENCE", "FADING", "ENDED"}:
            reasons.append("个股角色为补涨，板块高潮、分歧或退潮阶段不追。")
            return "OVERHEATED_NO_CHASE" if cycle == "CLIMAX" else "WAIT_FOR_SUPPORT"
        if label == "READY_CONFIRM":
            reasons.append("补涨候选只能降为小仓试错或观察，不能按龙头处理。")
            return "READY_TRIAL"
    if role in {"LEADER", "CAPACITY_CORE", "TREND_CORE"}:
        if cycle in {"STARTING", "FERMENTING"} and label in {"WAIT_CONFIRM", "OBSERVE_ONLY"}:
            reasons.append("个股角色为核心，允许进入观察池等待确认。")
            return "READY_TRIAL" if inp.sector_confidence != "LOW" else label
        if cycle == "DIVERGENCE":
            reasons.append("核心股在板块分歧期只观察承接，不直接追买。")
            return "WAIT_FOR_SUPPORT"
    return label


def decide_execution(inp: ExecutionInput) -> ExecutionDecision:
    reasons: list[str] = []
    label, base_reasons = _base_label(inp)
    reasons.extend(base_reasons)
    label = _apply_sector_rules(label, inp, reasons)
    label = _apply_stock_risks(label, inp, reasons)
    label = _apply_role_rules(label, inp, reasons)

    if not inp.can_watch:
        if label in {"READY_CONFIRM", "READY_TRIAL"}:
            reasons.append("用户不能盯盘，执行标签自动降级。")
        if _high_risk(inp) and label in {"READY_CONFIRM", "READY_TRIAL"}:
            reasons.append("不能盯盘且个股高波动，不买。")
            label = "OBSERVE_ONLY"
        if inp.sector_cycle in {"CLIMAX", "DIVERGENCE", "FADING", "ENDED"}:
            reasons.append("不能盯盘且板块处于高潮、分歧或退潮，不新开仓。")
            label = "OBSERVE_ONLY" if inp.user_state == "empty" else "REDUCE_RISK"

    plan = position_plan(label, can_watch=inp.can_watch, has_alert=inp.has_alert)
    final_label = plan.label
    info = label_info(final_label)
    if final_label != label:
        reasons.append(f"仓位规则将 {label} 降级为 {final_label}。")

    allow_buy = plan.allow_buy and inp.user_state == "empty"
    sector_cycle_text = inp.sector_cycle
    if inp.sector_aux_labels:
        sector_cycle_text += " + " + " / ".join(inp.sector_aux_labels)

    stop_advice = "若跌破关键均线、承接失败或板块降级，停止新买并按保护线处理。"
    profit_advice = "有浮盈时优先保护利润；板块高潮、分歧或后排转弱时先降风险。"
    if final_label in {"BREAKDOWN_AVOID", "EXIT_LOGIC_BROKEN"}:
        stop_advice = "结构或逻辑已破坏，优先退出或规避。"
    elif final_label in {"WAIT_FOR_SUPPORT", "WAIT_STRONG_PULLBACK"}:
        stop_advice = "等待承接确认，未确认前不新增。"

    return ExecutionDecision(
        original_status=inp.original_status,
        final_label=final_label,
        allow_buy=allow_buy,
        allow_add=plan.allow_add,
        max_position_pct=plan.empty_max_position_pct if inp.user_state == "empty" else 0,
        sector_cycle_text=sector_cycle_text,
        sector_confidence=inp.sector_confidence,
        downgrade_reasons=list(dict.fromkeys(reasons)) or ["无明显降级。"],
        empty_advice="可以买小仓试错。" if allow_buy else "不买，先观察或等待确认。",
        holding_advice=plan.holding_action,
        no_watch_advice=plan.no_watch_action if not inp.can_watch else position_plan(final_label, can_watch=False).no_watch_action,
        stop_advice=stop_advice,
        profit_protection_advice=profit_advice,
        upgrade_conditions=[info.upgrade_condition],
        invalid_conditions=[info.downgrade_condition],
    )


def decide_execution_from_dict(data: dict[str, Any]) -> ExecutionDecision:
    return decide_execution(
        ExecutionInput(
            ts_code=str(data.get("ts_code", "")),
            name=str(data.get("name", "")),
            stock_score=_num(data.get("stock_score")),
            leader_score=_num(data.get("leader_score")),
            original_status=str(data.get("original_status", data.get("final_decision", data.get("execution_status", "")))),
            sector_name=str(data.get("sector_name", "")),
            sector_cycle=str(data.get("sector_cycle", "UNKNOWN")),
            sector_aux_labels=list(data.get("sector_aux_labels", []) or []),
            sector_confidence=str(data.get("sector_confidence", "LOW")),
            risk_text=str(data.get("risk_text", "")),
            leader_labels=str(data.get("leader_labels", "")),
            core_identity=str(data.get("core_identity", "")),
            stock_role=str(data.get("stock_role", "")),
            user_state=str(data.get("user_state", "empty")),
            can_watch=bool(data.get("can_watch", True)),
            has_alert=bool(data.get("has_alert", True)),
            cost=_num(data.get("cost")),
            latest_price=_num(data.get("latest_price")),
        )
    )
