from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountRiskLabel:
    code: str
    meaning: str
    action: str


ACCOUNT_RISK_LABELS: dict[str, AccountRiskLabel] = {
    "ACCOUNT_SAFE": AccountRiskLabel("ACCOUNT_SAFE", "账户风险较低", "可以继续等待高质量机会，不需要为了提高仓位而买。"),
    "ACCOUNT_BALANCED": AccountRiskLabel("ACCOUNT_BALANCED", "账户风险适中", "维持纪律，新增仓位必须同时满足天气、板块、角色和执行标签。"),
    "ACCOUNT_CONCENTRATED": AccountRiskLabel("ACCOUNT_CONCENTRATED", "持仓集中度偏高", "控制单票风险，避免单一股票影响账户波动。"),
    "ACCOUNT_OVEREXPOSED": AccountRiskLabel("ACCOUNT_OVEREXPOSED", "总仓位过高", "停止新增，优先降低总风险。"),
    "ACCOUNT_SECTOR_CROWDED": AccountRiskLabel("ACCOUNT_SECTOR_CROWDED", "板块过度集中", "不继续加同一板块，优先降低后排和弱结构。"),
    "ACCOUNT_NEED_REDUCE": AccountRiskLabel("ACCOUNT_NEED_REDUCE", "需要降低风险", "按执行标签、板块周期和持仓质量依次降风险。"),
    "ACCOUNT_CASH_HEAVY": AccountRiskLabel("ACCOUNT_CASH_HEAVY", "现金较多，可等待机会", "现金多不是问题，乱买才是问题。"),
    "ACCOUNT_NO_WATCH_RISK": AccountRiskLabel("ACCOUNT_NO_WATCH_RISK", "不能盯盘，风险需降低", "降低总仓位、单票上限和板块集中度。"),
}


def account_risk_info(code: str) -> AccountRiskLabel:
    return ACCOUNT_RISK_LABELS.get(code, ACCOUNT_RISK_LABELS["ACCOUNT_BALANCED"])
