from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HoldingLabel:
    code: str
    meaning: str
    default_action: str


HOLDING_LABELS: dict[str, HoldingLabel] = {
    "HOLD_NORMAL": HoldingLabel("HOLD_NORMAL", "正常持有", "继续持有，但不盲目加仓。"),
    "HOLD_WITH_PROTECTION": HoldingLabel("HOLD_WITH_PROTECTION", "持有但保护利润", "持有，同时设置利润保护线。"),
    "REDUCE_PROFIT_PROTECTION": HoldingLabel("REDUCE_PROFIT_PROTECTION", "浮盈保护性减仓", "已有利润优先落袋一部分，保留核心仓观察。"),
    "REDUCE_RISK": HoldingLabel("REDUCE_RISK", "风险减仓", "降低风险暴露，优先减少后排或弱结构仓位。"),
    "EXIT_STOP_LOSS": HoldingLabel("EXIT_STOP_LOSS", "止损退出", "亏损扩大且风险条件不支持继续持有，优先退出。"),
    "EXIT_LOGIC_BROKEN": HoldingLabel("EXIT_LOGIC_BROKEN", "逻辑失效退出", "买入逻辑或板块逻辑失效，退出或等待重新建模。"),
    "NO_ADD_WAIT_SUPPORT": HoldingLabel("NO_ADD_WAIT_SUPPORT", "不加仓，等待承接", "不加仓，等待板块或个股承接确认。"),
    "WATCH_ONLY_HOLDING": HoldingLabel("WATCH_ONLY_HOLDING", "只观察，不新增", "已有仓位只观察，不新增。"),
    "CORE_HOLD_BACKROW_REDUCE": HoldingLabel("CORE_HOLD_BACKROW_REDUCE", "核心保留，后排减仓", "核心可保留观察，后排和弱结构优先减仓。"),
    "NO_WATCH_REDUCE": HoldingLabel("NO_WATCH_REDUCE", "不能盯盘，主动降风险", "不能盯盘时主动降低风险，不加仓。"),
}


def holding_label_info(code: str) -> HoldingLabel:
    return HOLDING_LABELS.get(code, HOLDING_LABELS["WATCH_ONLY_HOLDING"])
