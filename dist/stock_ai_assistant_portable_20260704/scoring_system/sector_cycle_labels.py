from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CycleLabel:
    code: str
    name: str
    meaning: str
    trigger: str
    empty_advice: str
    holding_advice: str
    no_watch_advice: str
    max_position: str


CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")


MAIN_CYCLE_LABELS: dict[str, CycleLabel] = {
    "STARTING": CycleLabel("STARTING", "启动", "板块刚从低位或弱势转强。", "5日或10日开始转强，核心股先于板块走强。", "观察仓或试错仓。", "观察是否继续转强。", "只观察或极小仓。", "低仓"),
    "FERMENTING": CycleLabel("FERMENTING", "发酵", "板块已经开始扩散。", "5/10/20日表现连续走强，上涨家数扩散。", "优先核心，可小仓到中低仓。", "可持有，强确认后小幅加仓。", "小仓，必须有提醒。", "中低仓"),
    "CLIMAX": CycleLabel("CLIMAX", "高潮", "板块处在加速高位。", "5/10/20日涨幅较大，成交额高位，核心和补涨都活跃。", "不追高。", "保护利润。", "不新开仓。", "新仓0，持仓降风险"),
    "DIVERGENCE": CycleLabel("DIVERGENCE", "分歧", "板块高位或上涨后出现内部不一致。", "涨跌家数分化，核心和后排表现不一致。", "等承接。", "减后排，看核心。", "不参与。", "低仓或降仓"),
    "REPAIR": CycleLabel("REPAIR", "修复", "回调后出现修复尝试。", "核心股先止跌或反包，板块短线改善。", "核心小仓试错。", "保留核心，淘汰后排。", "只观察或极小仓。", "低仓"),
    "FADING": CycleLabel("FADING", "退潮", "板块从分歧走向整体降温。", "5/10日转弱，后排先跌，核心开始破位。", "不开仓。", "减仓或退出。", "不参与。", "空仓或极低仓"),
    "ENDED": CycleLabel("ENDED", "结束", "板块主升周期结束。", "核心失效、持续弱化、资金撤离。", "不参与。", "退出或放弃。", "不参与。", "0"),
    "UNKNOWN": CycleLabel("UNKNOWN", "状态不确定", "证据不足或信号冲突。", "数据不足、窗口太短，或强弱证据相互冲突。", "等待确认。", "按个股止损和保护线处理。", "不参与。", "0或观察仓"),
}


AUXILIARY_LABELS: dict[str, CycleLabel] = {
    "CLIMAX_FADING_RISK": CycleLabel("CLIMAX_FADING_RISK", "高潮后退潮风险", "高位加速后出现回落风险。", "高位区股票多，补涨活跃，短线开始不稳。", "禁止追高。", "强制利润保护。", "不参与。", "新仓0"),
    "HIGH_LEVEL_UNSTABLE": CycleLabel("HIGH_LEVEL_UNSTABLE", "高位不稳定", "位置偏高但承接不稳。", "高位股比例较高，短线波动和回撤变大。", "不参与或等待。", "降低后排暴露。", "不参与。", "低仓"),
    "WAIT_FOR_CONFIRMATION": CycleLabel("WAIT_FOR_CONFIRMATION", "等待确认", "方向还没有确认。", "承接不清晰、信号冲突。", "等待承接。", "不加仓。", "不参与。", "0或观察仓"),
    "STRUCTURAL_START": CycleLabel("STRUCTURAL_START", "结构性启动", "局部核心先转强。", "少数核心明显强于板块，板块整体未全面扩散。", "观察仓或试错仓。", "可继续观察。", "极小仓或观察。", "低仓"),
    "SHORT_REPAIR": CycleLabel("SHORT_REPAIR", "短线修复", "回调后短线修复。", "前期走弱后5日改善，核心先修复。", "等确认或核心小仓。", "看核心修复。", "不盯盘不参与。", "低仓"),
    "NON_MAINLINE_OPPORTUNITY": CycleLabel("NON_MAINLINE_OPPORTUNITY", "非主线结构机会", "不是全面主线，但有局部机会。", "板块整体一般，核心局部走强。", "只做核心。", "按个股止损。", "降仓。", "小仓"),
    "BACKROW_RISK_SPREAD": CycleLabel("BACKROW_RISK_SPREAD", "后排风险扩散", "风险从后排开始扩散。", "后排先跌，弱结构增加。", "不参与。", "先减后排。", "不参与。", "降仓"),
    "CORE_STILL_VALID": CycleLabel("CORE_STILL_VALID", "核心仍有效", "核心股仍能支撑板块。", "核心股仍强于板块，未破关键趋势。", "只看核心。", "可保留核心。", "小仓跟踪。", "中低仓"),
    "CORE_BREAKING_DOWN": CycleLabel("CORE_BREAKING_DOWN", "核心转弱", "核心股开始破位。", "核心连续下跌或弱于板块。", "不参与。", "降仓。", "不参与。", "降仓"),
    "SUPPORT_CONFIRMED": CycleLabel("SUPPORT_CONFIRMED", "承接确认", "下跌后出现承接。", "下跌后止跌、缩量或反包。", "核心可小仓试错。", "可看修复。", "小仓观察。", "低仓"),
    "SUPPORT_NOT_CONFIRMED": CycleLabel("SUPPORT_NOT_CONFIRMED", "承接未确认", "还没看到有效承接。", "下跌后仍无止跌证据。", "不参与。", "继续等。", "不参与。", "0"),
}


def advice_for(main_label: str, auxiliary_labels: list[str] | tuple[str, ...]) -> dict[str, str]:
    base = MAIN_CYCLE_LABELS.get(main_label, MAIN_CYCLE_LABELS["UNKNOWN"])
    aux = set(auxiliary_labels)
    advice = {
        "empty_advice": base.empty_advice,
        "holding_advice": base.holding_advice,
        "no_watch_advice": base.no_watch_advice,
        "max_position": base.max_position,
    }
    if "CLIMAX_FADING_RISK" in aux:
        advice.update({"empty_advice": "不追高，等待分歧后承接确认。", "holding_advice": "保护利润，后排先降仓。", "no_watch_advice": "不新开仓。", "max_position": "新仓0"})
    elif "HIGH_LEVEL_UNSTABLE" in aux:
        advice.update({"empty_advice": "等待承接，不机械抄底。", "holding_advice": "不加仓，按保护线处理。", "no_watch_advice": "不参与。", "max_position": "0或极低仓"})
    elif "STRUCTURAL_START" in aux:
        advice.update({"empty_advice": "允许观察仓或极小试错仓，只看核心。", "holding_advice": "看核心能否继续确认。", "no_watch_advice": "极小仓或只观察。", "max_position": "低仓"})
    elif "SUPPORT_CONFIRMED" in aux:
        advice.update({"empty_advice": "核心可小仓试错。", "holding_advice": "保留核心，淘汰后排。", "no_watch_advice": "小仓观察。", "max_position": "低仓"})
    elif "SUPPORT_NOT_CONFIRMED" in aux or "WAIT_FOR_CONFIRMATION" in aux:
        advice.update({"empty_advice": "等待承接确认。", "holding_advice": "不加仓，按个股保护线处理。", "no_watch_advice": "不参与。", "max_position": "0或观察仓"})
    return advice
