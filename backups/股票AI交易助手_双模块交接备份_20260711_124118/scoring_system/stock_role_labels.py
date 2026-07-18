from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StockRoleLabel:
    code: str
    name: str
    meaning: str
    execution_effect: str


STOCK_ROLE_LABELS: dict[str, StockRoleLabel] = {
    "LEADER": StockRoleLabel("LEADER", "情绪/强度龙头", "板块内强度和辨识度靠前，不等于单日涨幅第一。", "可作为观察池核心，但高潮不追高。"),
    "CAPACITY_CORE": StockRoleLabel("CAPACITY_CORE", "容量核心", "成交额和承载资金能力靠前，修复时更有参考意义。", "可优先观察，仓位仍受板块周期限制。"),
    "TREND_CORE": StockRoleLabel("TREND_CORE", "趋势核心", "10日、20日趋势相对持续，未明显破位。", "适合观察趋势延续和回踩承接。"),
    "SECONDARY_CORE": StockRoleLabel("SECONDARY_CORE", "次核心", "有一定辨识度，但不如龙头和容量核心。", "只能低仓或等待确认。"),
    "CATCH_UP": StockRoleLabel("CATCH_UP", "补涨候选", "短线突然变强，但中期辨识度不一定够。", "高潮和分歧阶段优先压制，不适合不能盯盘追。"),
    "FOLLOWER": StockRoleLabel("FOLLOWER", "后排跟随", "跟涨为主，成交或辨识度不足。", "不作为空仓主要买入对象，分歧优先减仓。"),
    "WEAK_STRUCTURE": StockRoleLabel("WEAK_STRUCTURE", "弱结构", "走势弱、破位或板块强它不强。", "规避，持仓也要谨慎。"),
    "UNCERTAIN_ROLE": StockRoleLabel("UNCERTAIN_ROLE", "角色不确定", "证据不足或信号冲突。", "等待确认。"),
}


def stock_role_info(code: str) -> StockRoleLabel:
    return STOCK_ROLE_LABELS.get(code, STOCK_ROLE_LABELS["UNCERTAIN_ROLE"])
