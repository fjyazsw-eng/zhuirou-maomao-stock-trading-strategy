from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionLabel:
    code: str
    meaning: str
    allow_new_buy: bool
    allow_add: bool
    suitable_holding: bool
    empty_max_position_pct: int
    holding_advice: str
    no_watch_action: str
    trigger: str
    upgrade_condition: str
    downgrade_condition: str


EXECUTION_LABELS: dict[str, ExecutionLabel] = {
    "READY_CONFIRM": ExecutionLabel(
        "READY_CONFIRM",
        "条件较完整，可以正常参与，但仍有仓位上限。",
        True,
        False,
        True,
        20,
        "可持有，新增仓位必须受板块和个股保护线约束。",
        "降级为READY_TRIAL。",
        "板块与个股共振，风险标签不突出，承接确认。",
        "板块继续发酵，个股放量突破后不冲高回落。",
        "板块转分歧、个股过热、不能盯盘或承接失败。",
    ),
    "READY_TRIAL": ExecutionLabel(
        "READY_TRIAL",
        "允许小仓试错。",
        True,
        False,
        True,
        10,
        "可保留小仓观察，失败要及时收缩。",
        "降级为OBSERVE_ONLY。",
        "结构性启动或低仓试错条件出现。",
        "板块确认发酵，个股承接增强。",
        "板块置信度低、后排风险扩散或个股高波动。",
    ),
    "OBSERVE_ONLY": ExecutionLabel(
        "OBSERVE_ONLY",
        "只观察，不买。",
        False,
        False,
        False,
        0,
        "已有持仓也要降低期待，按保护线处理。",
        "不参与。",
        "证据不足或风险大于机会。",
        "出现承接确认或板块升级。",
        "板块退潮、个股破位或风险继续扩散。",
    ),
    "WAIT_CONFIRM": ExecutionLabel(
        "WAIT_CONFIRM",
        "等待确认。",
        False,
        False,
        True,
        0,
        "不加仓，等确认信号。",
        "不参与。",
        "方向不清晰，信号冲突。",
        "板块和个股同步转强。",
        "转弱、破位或后排风险扩散。",
    ),
    "WAIT_FOR_SUPPORT": ExecutionLabel(
        "WAIT_FOR_SUPPORT",
        "等待承接。",
        False,
        False,
        True,
        0,
        "不加仓，等核心承接。",
        "不参与。",
        "板块分歧或个股回调，承接未确认。",
        "缩量止跌、核心反包或支撑确认。",
        "继续放量下跌或跌破关键均线。",
    ),
    "WAIT_STRONG_PULLBACK": ExecutionLabel(
        "WAIT_STRONG_PULLBACK",
        "强趋势等待回踩。",
        False,
        False,
        True,
        0,
        "持仓可保护利润，新增等待回踩。",
        "不参与。",
        "强趋势但短期过热。",
        "回踩后承接确认。",
        "高潮后风险释放或冲高回落。",
    ),
    "OVERHEATED_NO_CHASE": ExecutionLabel(
        "OVERHEATED_NO_CHASE",
        "高位过热，不追高。",
        False,
        False,
        True,
        0,
        "不新增，已有持仓保护利润。",
        "不参与。",
        "高位、过热、冲高回落或板块高潮。",
        "充分回踩并重新确认承接。",
        "板块转退潮或核心破位。",
    ),
    "HOLD_WITH_PROTECTION": ExecutionLabel(
        "HOLD_WITH_PROTECTION",
        "持仓可继续，但要保护利润。",
        False,
        False,
        True,
        0,
        "持有但设置保护线，后排优先降仓。",
        "降仓或不新增。",
        "持仓有浮盈但板块或个股风险上升。",
        "核心继续有效且风险释放后修复。",
        "跌破保护线或板块退潮。",
    ),
    "REDUCE_RISK": ExecutionLabel(
        "REDUCE_RISK",
        "降低风险，减仓。",
        False,
        False,
        False,
        0,
        "减仓，尤其先减后排和弱结构。",
        "不参与。",
        "板块退潮风险、个股弱化或后排风险扩散。",
        "重新站回关键结构并获得板块确认。",
        "核心破位或亏损扩大。",
    ),
    "EXIT_LOGIC_BROKEN": ExecutionLabel(
        "EXIT_LOGIC_BROKEN",
        "逻辑失效，退出。",
        False,
        False,
        False,
        0,
        "退出或等待重新建模。",
        "不参与。",
        "买入逻辑被破坏，核心破位或止损触发。",
        "重新形成完整买点。",
        "继续下跌或事件面恶化。",
    ),
    "BREAKDOWN_AVOID": ExecutionLabel(
        "BREAKDOWN_AVOID",
        "结构破坏，规避。",
        False,
        False,
        False,
        0,
        "减仓或退出。",
        "不参与。",
        "后排、弱结构、跌破关键均线或板块退潮。",
        "重新站回关键均线并获得板块支持。",
        "继续破位。",
    ),
    "PULLBACK_WEAKENING": ExecutionLabel(
        "PULLBACK_WEAKENING",
        "回调中转弱。",
        False,
        False,
        False,
        0,
        "降低仓位，等待止跌。",
        "不参与。",
        "回调没有承接，短线逐步转弱。",
        "出现明确承接。",
        "跌破关键结构。",
    ),
}


def label_info(code: str) -> ExecutionLabel:
    return EXECUTION_LABELS.get(code, EXECUTION_LABELS["OBSERVE_ONLY"])
