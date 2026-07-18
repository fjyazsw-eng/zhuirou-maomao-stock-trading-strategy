from __future__ import annotations

from dataclasses import dataclass


EMPTY_MAX_POSITION_PCT: dict[str, int] = {
    "READY_CONFIRM": 20,
    "READY_TRIAL": 10,
    "OBSERVE_ONLY": 0,
    "WAIT_CONFIRM": 0,
    "WAIT_FOR_SUPPORT": 0,
    "WAIT_STRONG_PULLBACK": 0,
    "OVERHEATED_NO_CHASE": 0,
    "HOLD_WITH_PROTECTION": 0,
    "REDUCE_RISK": 0,
    "EXIT_LOGIC_BROKEN": 0,
    "BREAKDOWN_AVOID": 0,
    "PULLBACK_WEAKENING": 0,
}


HOLDING_ACTION: dict[str, str] = {
    "READY_CONFIRM": "允许参与，但仍受仓位上限约束。",
    "READY_TRIAL": "只允许小仓试错，失败及时收缩。",
    "OBSERVE_ONLY": "只观察，不新增；已有仓位按保护线处理。",
    "WAIT_CONFIRM": "不加仓，等待确认。",
    "WAIT_FOR_SUPPORT": "不加仓，等待承接。",
    "WAIT_STRONG_PULLBACK": "持仓保护利润，新增等待回踩。",
    "OVERHEATED_NO_CHASE": "不新增，已有持仓保护利润。",
    "HOLD_WITH_PROTECTION": "持有，但必须设置保护线。",
    "REDUCE_RISK": "减仓，优先降低后排或高风险仓位。",
    "EXIT_LOGIC_BROKEN": "逻辑失效，退出。",
    "BREAKDOWN_AVOID": "规避，持仓也应减仓或退出。",
    "PULLBACK_WEAKENING": "降低仓位，等待止跌。",
}


NO_WATCH_DOWNGRADE: dict[str, str] = {
    "READY_CONFIRM": "READY_TRIAL",
    "READY_TRIAL": "OBSERVE_ONLY",
    "WAIT_CONFIRM": "WAIT_CONFIRM",
    "WAIT_FOR_SUPPORT": "WAIT_FOR_SUPPORT",
    "WAIT_STRONG_PULLBACK": "WAIT_STRONG_PULLBACK",
    "OVERHEATED_NO_CHASE": "OVERHEATED_NO_CHASE",
    "OBSERVE_ONLY": "OBSERVE_ONLY",
    "HOLD_WITH_PROTECTION": "REDUCE_RISK",
    "REDUCE_RISK": "REDUCE_RISK",
    "EXIT_LOGIC_BROKEN": "EXIT_LOGIC_BROKEN",
    "BREAKDOWN_AVOID": "BREAKDOWN_AVOID",
    "PULLBACK_WEAKENING": "PULLBACK_WEAKENING",
}


NO_WATCH_ACTION: dict[str, str] = {
    "READY_CONFIRM": "降级为小仓试错，必须有提醒。",
    "READY_TRIAL": "不参与，只观察。",
    "OBSERVE_ONLY": "不参与。",
    "WAIT_CONFIRM": "不参与，等确认。",
    "WAIT_FOR_SUPPORT": "不参与，等承接。",
    "WAIT_STRONG_PULLBACK": "不参与，等回踩。",
    "OVERHEATED_NO_CHASE": "不参与，不追高。",
    "HOLD_WITH_PROTECTION": "不新增，持仓降风险。",
    "REDUCE_RISK": "不参与，持仓降风险。",
    "EXIT_LOGIC_BROKEN": "不参与，逻辑失效则退出。",
    "BREAKDOWN_AVOID": "不参与，规避。",
    "PULLBACK_WEAKENING": "不参与，等止跌。",
}


@dataclass(frozen=True)
class PositionPlan:
    label: str
    allow_buy: bool
    allow_add: bool
    empty_max_position_pct: int
    holding_action: str
    no_watch_label: str
    no_watch_action: str


def position_plan(label: str, can_watch: bool = True, has_alert: bool = True) -> PositionPlan:
    final_label = label
    if not can_watch:
        final_label = NO_WATCH_DOWNGRADE.get(final_label, final_label)
    if not has_alert and final_label in {"READY_CONFIRM", "READY_TRIAL"}:
        final_label = NO_WATCH_DOWNGRADE.get(final_label, final_label)

    allow_buy = final_label in {"READY_CONFIRM", "READY_TRIAL"}
    return PositionPlan(
        label=final_label,
        allow_buy=allow_buy,
        allow_add=False,
        empty_max_position_pct=EMPTY_MAX_POSITION_PCT.get(final_label, 0),
        holding_action=HOLDING_ACTION.get(final_label, "按保护线处理。"),
        no_watch_label=NO_WATCH_DOWNGRADE.get(label, label),
        no_watch_action=NO_WATCH_ACTION.get(NO_WATCH_DOWNGRADE.get(label, label), "不参与。"),
    )
