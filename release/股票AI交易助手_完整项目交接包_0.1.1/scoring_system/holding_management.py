from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scoring_system.holding_labels import holding_label_info


CORE_WORDS = ("龙头", "容量核心", "趋势核心", "次核心", "LEADER", "CAPACITY_CORE", "TREND_CORE", "SECONDARY_CORE", "MULTI_CORE", "CORE", "疑似龙头")
BACKROW_WORDS = ("后排", "弱结构", "补涨", "FOLLOWER", "WEAK_STRUCTURE", "CATCH_UP", "WEAK")
HIGH_RISK_EXECUTION = {
    "REDUCE_RISK",
    "EXIT_LOGIC_BROKEN",
    "BREAKDOWN_AVOID",
    "PULLBACK_WEAKENING",
}
PROTECTION_EXECUTION = {
    "HOLD_WITH_PROTECTION",
    "OVERHEATED_NO_CHASE",
    "WAIT_STRONG_PULLBACK",
}


@dataclass(frozen=True)
class HoldingInput:
    ts_code: str
    name: str
    cost: float | None
    current_price: float | None
    current_position_pct: float | None
    original_status: str
    final_execution_label: str
    sector_cycle: str
    sector_aux_labels: list[str]
    sector_confidence: str
    can_watch: bool
    stock_role: str
    recent_change_pct: float | None = None
    ma_signal: str = ""


@dataclass(frozen=True)
class HoldingDecision:
    holding_label: str
    holding_label_name: str
    pnl_pct: float | None
    continue_hold: bool
    reduce_position: bool
    exit_position: bool
    allow_add: bool
    suggested_retain_pct: int
    stop_loss_line: str
    profit_protection_line: str
    reduce_trigger: str
    exit_trigger: str
    no_watch_action: str
    main_reasons: list[str]


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _price(value: float | None) -> str:
    if value is None:
        return "暂无法计算"
    return f"{value:.2f}"


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _is_core(inp: HoldingInput) -> bool:
    text = f"{inp.stock_role} {inp.original_status}"
    return _has_any(text, CORE_WORDS)


def _is_backrow(inp: HoldingInput) -> bool:
    text = f"{inp.stock_role} {inp.original_status} {inp.ma_signal}"
    return _has_any(text, BACKROW_WORDS)


def _pnl_pct(inp: HoldingInput) -> float | None:
    if not inp.cost or not inp.current_price:
        return None
    return (inp.current_price - inp.cost) / inp.cost * 100


def _profit_line(inp: HoldingInput, pnl_pct: float | None) -> str:
    if pnl_pct is None or inp.current_price is None or inp.cost is None:
        return "数据不足，先按成本和关键均线人工观察"
    if pnl_pct >= 8:
        line = max(inp.cost * 1.03, inp.current_price * 0.95)
        return f"{_price(line)}，浮盈较大，回撤约3%到5%触发保护性减仓"
    if pnl_pct >= 3:
        line = max(inp.cost, inp.current_price * 0.97)
        return f"{_price(line)}，浮盈未很厚，回撤约3%或跌回成本附近要保护"
    if pnl_pct >= 0:
        return f"{_price(inp.cost)}，利润不厚，跌回成本附近不硬扛"
    return "暂无利润保护线，重点看止损线和逻辑是否破坏"


def _stop_line(inp: HoldingInput, pnl_pct: float | None) -> str:
    if inp.cost is None:
        return "成本缺失，暂无法计算"
    if pnl_pct is not None and pnl_pct <= -6:
        return f"{_price(inp.cost * 0.94)}，亏损超过6%附近必须复核逻辑"
    if pnl_pct is not None and pnl_pct <= -3:
        return f"{_price(inp.cost * 0.97)}，亏损扩大或板块走弱时减仓"
    return f"{_price(inp.cost)}，跌破成本且板块走弱时退出或降风险"


def decide_holding(inp: HoldingInput) -> HoldingDecision:
    pnl_pct = _pnl_pct(inp)
    reasons: list[str] = []
    aux = set(inp.sector_aux_labels or [])
    cycle = inp.sector_cycle or "UNKNOWN"
    final_label = inp.final_execution_label or "OBSERVE_ONLY"
    is_core = _is_core(inp)
    is_backrow = _is_backrow(inp)

    label = "HOLD_NORMAL"
    retain_pct = 100
    allow_add = final_label in {"READY_CONFIRM", "READY_TRIAL"} and cycle in {"STARTING", "FERMENTING"} and inp.sector_confidence != "LOW"

    if pnl_pct is None:
        label = "WATCH_ONLY_HOLDING"
        retain_pct = 70
        allow_add = False
        reasons.append("成本或现价不足，先不做进攻判断。")
    elif pnl_pct >= 8:
        label = "HOLD_WITH_PROTECTION" if is_core else "REDUCE_PROFIT_PROTECTION"
        retain_pct = 80 if is_core else 50
        allow_add = False
        reasons.append("浮盈超过8%，必须进入利润保护。")
    elif pnl_pct >= 3:
        label = "HOLD_WITH_PROTECTION"
        retain_pct = 80
        allow_add = False
        reasons.append("浮盈在3%到8%，可以持有，但不追涨加仓。")
    elif pnl_pct >= 0:
        label = "HOLD_NORMAL" if final_label in {"READY_CONFIRM", "READY_TRIAL"} else "WATCH_ONLY_HOLDING"
        retain_pct = 100 if label == "HOLD_NORMAL" else 70
        allow_add = False
        reasons.append("浮盈不足3%，还不是安全利润。")
    elif pnl_pct >= -3:
        label = "WATCH_ONLY_HOLDING"
        retain_pct = 70
        allow_add = False
        reasons.append("浮亏0%到-3%，先视为正常波动，但不补仓。")
    elif pnl_pct >= -6:
        label = "NO_ADD_WAIT_SUPPORT" if final_label in {"WAIT_FOR_SUPPORT", "OBSERVE_ONLY"} else "REDUCE_RISK"
        retain_pct = 60
        allow_add = False
        reasons.append("浮亏-3%到-6%，进入风险观察，禁止补仓。")
    else:
        label = "EXIT_STOP_LOSS" if is_backrow or cycle in {"FADING", "ENDED"} else "REDUCE_RISK"
        retain_pct = 0 if label == "EXIT_STOP_LOSS" else 30
        allow_add = False
        reasons.append("浮亏超过-6%，必须判断逻辑是否破坏。")

    if final_label in {"EXIT_LOGIC_BROKEN"}:
        label = "EXIT_LOGIC_BROKEN"
        retain_pct = 0
        allow_add = False
        reasons.append("最终执行标签显示逻辑失效。")
    elif final_label == "BREAKDOWN_AVOID":
        label = "EXIT_LOGIC_BROKEN" if is_backrow else "REDUCE_RISK"
        retain_pct = 0 if is_backrow else min(retain_pct, 50)
        allow_add = False
        reasons.append("最终执行标签为规避，持仓也要减仓或退出。")
    elif final_label == "REDUCE_RISK":
        label = "REDUCE_RISK"
        retain_pct = min(retain_pct, 50)
        allow_add = False
        reasons.append("最终执行标签要求降低风险。")
    elif final_label in PROTECTION_EXECUTION and label == "HOLD_NORMAL":
        label = "HOLD_WITH_PROTECTION"
        retain_pct = min(retain_pct, 80)
        allow_add = False
        reasons.append("执行标签要求持仓保护利润。")
    elif final_label in {"WAIT_FOR_SUPPORT", "WAIT_CONFIRM", "OBSERVE_ONLY"} and label == "HOLD_NORMAL":
        label = "NO_ADD_WAIT_SUPPORT" if final_label == "WAIT_FOR_SUPPORT" else "WATCH_ONLY_HOLDING"
        retain_pct = min(retain_pct, 80)
        allow_add = False
        reasons.append("执行标签尚未允许加仓。")

    if cycle == "CLIMAX" or "CLIMAX_FADING_RISK" in aux:
        allow_add = False
        label = "REDUCE_PROFIT_PROTECTION" if (pnl_pct or 0) >= 3 and is_backrow else "HOLD_WITH_PROTECTION"
        retain_pct = min(retain_pct, 70 if is_core else 50)
        reasons.append("板块高潮或高潮后退潮风险，浮盈必须保护，后排优先减仓。")
    elif cycle == "DIVERGENCE":
        allow_add = False
        if is_backrow:
            label = "CORE_HOLD_BACKROW_REDUCE"
            retain_pct = min(retain_pct, 50)
        elif not is_core:
            label = "NO_ADD_WAIT_SUPPORT"
            retain_pct = min(retain_pct, 70)
        reasons.append("板块分歧，核心观察，后排减仓，未承接前不加仓。")
    elif cycle in {"FADING", "ENDED"}:
        allow_add = False
        if is_backrow or final_label in HIGH_RISK_EXECUTION:
            label = "EXIT_LOGIC_BROKEN"
            retain_pct = 0
        else:
            label = "REDUCE_RISK"
            retain_pct = min(retain_pct, 30)
        reasons.append("板块退潮或结束，不加仓，弱结构优先退出。")
    elif cycle == "STARTING" or "STRUCTURAL_START" in aux:
        allow_add = allow_add and is_core
        if is_backrow:
            label = "WATCH_ONLY_HOLDING"
            retain_pct = min(retain_pct, 70)
            reasons.append("结构性启动只看核心，后排不加仓。")

    if not inp.can_watch:
        allow_add = False
        if label not in {"EXIT_LOGIC_BROKEN", "EXIT_STOP_LOSS"}:
            label = "NO_WATCH_REDUCE"
            retain_pct = min(retain_pct, 50)
        reasons.append("不能盯盘，主动降低风险，不给加仓。")

    info = holding_label_info(label)
    exit_position = label in {"EXIT_STOP_LOSS", "EXIT_LOGIC_BROKEN"}
    reduce_position = label in {
        "REDUCE_PROFIT_PROTECTION",
        "REDUCE_RISK",
        "CORE_HOLD_BACKROW_REDUCE",
        "NO_WATCH_REDUCE",
    }
    continue_hold = not exit_position

    reduce_trigger = "跌破利润保护线、板块降级、放量下跌、核心承接失败时减仓。"
    exit_trigger = "跌破止损线、最终执行标签转为EXIT_LOGIC_BROKEN、板块进入FADING/ENDED且个股非核心时退出。"
    no_watch_action = "不能盯盘时不加仓，保留仓位上限进一步降到当前仓位的50%以内。"
    return HoldingDecision(
        holding_label=label,
        holding_label_name=info.meaning,
        pnl_pct=pnl_pct,
        continue_hold=continue_hold,
        reduce_position=reduce_position,
        exit_position=exit_position,
        allow_add=allow_add,
        suggested_retain_pct=max(0, min(100, int(retain_pct))),
        stop_loss_line=_stop_line(inp, pnl_pct),
        profit_protection_line=_profit_line(inp, pnl_pct),
        reduce_trigger=reduce_trigger,
        exit_trigger=exit_trigger,
        no_watch_action=no_watch_action,
        main_reasons=list(dict.fromkeys(reasons)) or [info.default_action],
    )


def decide_holding_from_dict(data: dict[str, Any]) -> HoldingDecision:
    return decide_holding(
        HoldingInput(
            ts_code=str(data.get("ts_code", "")),
            name=str(data.get("name", "")),
            cost=_num(data.get("cost")),
            current_price=_num(data.get("current_price", data.get("latest_price"))),
            current_position_pct=_num(data.get("current_position_pct")),
            original_status=str(data.get("original_status", "")),
            final_execution_label=str(data.get("final_execution_label", "OBSERVE_ONLY")),
            sector_cycle=str(data.get("sector_cycle", "UNKNOWN")),
            sector_aux_labels=list(data.get("sector_aux_labels", []) or []),
            sector_confidence=str(data.get("sector_confidence", "LOW")),
            can_watch=bool(data.get("can_watch", True)),
            stock_role=str(data.get("stock_role", "")),
            recent_change_pct=_num(data.get("recent_change_pct")),
            ma_signal=str(data.get("ma_signal", "")),
        )
    )
