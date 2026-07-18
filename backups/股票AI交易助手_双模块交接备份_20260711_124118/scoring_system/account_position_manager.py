from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scoring_system.account_risk_labels import account_risk_info


CORE_ROLES = {"LEADER", "CAPACITY_CORE", "TREND_CORE", "SECONDARY_CORE"}
BLOCKED_EXECUTION = {
    "OBSERVE_ONLY",
    "WAIT_CONFIRM",
    "WAIT_FOR_SUPPORT",
    "WAIT_STRONG_PULLBACK",
    "OVERHEATED_NO_CHASE",
    "BREAKDOWN_AVOID",
    "EXIT_LOGIC_BROKEN",
    "PULLBACK_WEAKENING",
    "REDUCE_RISK",
}


@dataclass(frozen=True)
class AccountHolding:
    ts_code: str
    name: str
    shares: float
    cost: float
    current_price: float
    sector_code: str
    sector_name: str
    stock_role: str
    final_execution_label: str
    holding_label: str
    pnl_pct: float | None
    sector_cycle: str = "UNKNOWN"
    sector_aux_labels: tuple[str, ...] = ()
    sector_confidence: str = "LOW"

    @property
    def market_value(self) -> float:
        return max(0.0, self.shares * self.current_price)


@dataclass(frozen=True)
class AccountCandidate:
    ts_code: str
    name: str
    sector_code: str
    sector_name: str
    stock_role: str
    final_execution_label: str
    sector_cycle: str
    sector_aux_labels: tuple[str, ...] = ()
    sector_confidence: str = "LOW"
    latest_price: float | None = None


@dataclass(frozen=True)
class AccountDecision:
    total_asset: float
    cash: float
    invested_value: float
    total_position_pct: float
    cash_pct: float
    market_weather: str
    total_position_limit_pct: float
    allowed_new_total_pct: float
    allowed_new_total_value: float
    risk_labels: list[str]
    risk_label_names: list[str]
    stock_positions: list[dict[str, Any]]
    sector_positions: list[dict[str, Any]]
    candidate_limits: list[dict[str, Any]]
    need_reduce: bool
    allow_new_buy: bool
    no_watch_action: str
    account_advice: str


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def total_position_limit(market_weather: str, can_watch: bool) -> float:
    text = market_weather or ""
    if "极端" in text:
        limit = 10.0
    elif "风险" in text:
        limit = 20.0
    elif "强势" in text:
        limit = 60.0
    elif "普通" in text or "震荡" in text or "结构" in text:
        limit = 40.0
    else:
        limit = 40.0
    if not can_watch:
        limit = min(limit, 20.0) * 0.75
    return round(limit, 2)


def role_limit(role: str, can_watch: bool) -> float:
    role = (role or "UNCERTAIN_ROLE").upper()
    if role in {"LEADER", "CAPACITY_CORE"}:
        limit = 20.0
    elif role == "TREND_CORE":
        limit = 15.0
    elif role == "SECONDARY_CORE":
        limit = 10.0
    elif role == "CATCH_UP":
        limit = 5.0
    elif role in {"FOLLOWER", "WEAK_STRUCTURE"}:
        limit = 0.0
    else:
        limit = 5.0
    if not can_watch:
        limit *= 0.5
    return round(limit, 2)


def execution_limit(label: str) -> float:
    label = (label or "OBSERVE_ONLY").upper()
    if label == "READY_CONFIRM":
        return 100.0
    if label == "READY_TRIAL":
        return 10.0
    if label in BLOCKED_EXECUTION:
        return 0.0
    return 0.0


def sector_limit(cycle: str, aux_labels: tuple[str, ...] | list[str], confidence: str, can_watch: bool) -> float:
    cycle = (cycle or "UNKNOWN").upper()
    aux = set(aux_labels or [])
    confidence = (confidence or "LOW").upper()
    if cycle in {"FADING", "ENDED"}:
        limit = 0.0
    elif cycle == "CLIMAX" or "CLIMAX_FADING_RISK" in aux:
        limit = 0.0
    elif cycle == "DIVERGENCE":
        limit = 10.0
    elif cycle == "FERMENTING" and confidence == "HIGH":
        limit = 30.0
    elif cycle == "STARTING" or "STRUCTURAL_START" in aux:
        limit = 15.0
    elif cycle == "UNKNOWN":
        limit = 10.0
    else:
        limit = 15.0
    if not can_watch:
        limit *= 0.5
    return round(limit, 2)


def decide_account_position(
    total_asset: float,
    cash: float,
    holdings: list[AccountHolding],
    candidates: list[AccountCandidate],
    market_weather: str,
    can_watch: bool = True,
) -> AccountDecision:
    total_asset = max(_num(total_asset), 0.01)
    cash = max(_num(cash), 0.0)
    invested = sum(item.market_value for item in holdings)
    total_position_pct = invested / total_asset * 100
    cash_pct = cash / total_asset * 100
    total_limit = total_position_limit(market_weather, can_watch)
    allowed_new_total_pct = max(0.0, total_limit - total_position_pct)
    allowed_new_total_value = min(cash, total_asset * allowed_new_total_pct / 100)

    stock_positions: list[dict[str, Any]] = []
    sector_value: dict[str, float] = {}
    sector_meta: dict[str, dict[str, Any]] = {}
    single_too_high = False
    for item in holdings:
        pct = item.market_value / total_asset * 100
        limit = role_limit(item.stock_role, can_watch)
        stock_positions.append({
            "ts_code": item.ts_code,
            "name": item.name,
            "sector_code": item.sector_code,
            "sector_name": item.sector_name,
            "market_value": item.market_value,
            "position_pct": pct,
            "stock_role": item.stock_role,
            "role_limit_pct": limit,
            "final_execution_label": item.final_execution_label,
            "holding_label": item.holding_label,
            "is_too_high": pct > max(limit, 0.01) and limit > 0,
            "pnl_pct": item.pnl_pct,
        })
        if pct > max(limit, 0.01) and limit > 0:
            single_too_high = True
        sector_key = item.sector_code or item.sector_name or "UNKNOWN"
        sector_value[sector_key] = sector_value.get(sector_key, 0.0) + item.market_value
        sector_meta[sector_key] = {
            "sector_code": item.sector_code,
            "sector_name": item.sector_name,
            "sector_cycle": item.sector_cycle,
            "sector_aux_labels": list(item.sector_aux_labels),
            "sector_confidence": item.sector_confidence,
        }

    sector_positions: list[dict[str, Any]] = []
    sector_crowded = False
    for key, value in sector_value.items():
        meta = sector_meta[key]
        pct = value / total_asset * 100
        limit = sector_limit(meta["sector_cycle"], meta["sector_aux_labels"], meta["sector_confidence"], can_watch)
        crowded = pct > max(limit, 0.01)
        sector_crowded = sector_crowded or crowded
        sector_positions.append({
            **meta,
            "market_value": value,
            "position_pct": pct,
            "sector_limit_pct": limit,
            "is_crowded": crowded,
        })
    sector_positions.sort(key=lambda x: x["position_pct"], reverse=True)

    candidate_limits: list[dict[str, Any]] = []
    allow_new_buy = False
    for item in candidates:
        role_cap = role_limit(item.stock_role, can_watch)
        exec_cap = execution_limit(item.final_execution_label)
        sec_cap = sector_limit(item.sector_cycle, item.sector_aux_labels, item.sector_confidence, can_watch)
        existing_sector_pct = next((x["position_pct"] for x in sector_positions if x["sector_code"] == item.sector_code), 0.0)
        sector_room = max(0.0, sec_cap - existing_sector_pct)
        single_cap = min(role_cap, exec_cap, allowed_new_total_pct, sector_room)
        value_cap = min(cash, total_asset * single_cap / 100, allowed_new_total_value)
        allowed = value_cap > 0 and item.final_execution_label in {"READY_CONFIRM", "READY_TRIAL"}
        allow_new_buy = allow_new_buy or allowed
        candidate_limits.append({
            "ts_code": item.ts_code,
            "name": item.name,
            "sector_code": item.sector_code,
            "sector_name": item.sector_name,
            "stock_role": item.stock_role,
            "final_execution_label": item.final_execution_label,
            "sector_cycle": item.sector_cycle,
            "role_limit_pct": role_cap,
            "execution_limit_pct": exec_cap,
            "sector_limit_pct": sec_cap,
            "account_room_pct": allowed_new_total_pct,
            "single_new_limit_pct": max(0.0, single_cap),
            "single_new_limit_value": max(0.0, value_cap),
            "allow_buy": allowed,
        })

    labels: list[str] = []
    if not can_watch:
        labels.append("ACCOUNT_NO_WATCH_RISK")
    if total_position_pct > total_limit:
        labels.extend(["ACCOUNT_OVEREXPOSED", "ACCOUNT_NEED_REDUCE"])
    if sector_crowded:
        labels.append("ACCOUNT_SECTOR_CROWDED")
    if single_too_high:
        labels.append("ACCOUNT_CONCENTRATED")
    if cash_pct >= 70 and not allow_new_buy:
        labels.append("ACCOUNT_CASH_HEAVY")
    if not labels:
        labels.append("ACCOUNT_SAFE" if total_position_pct <= total_limit * 0.5 else "ACCOUNT_BALANCED")
    labels = list(dict.fromkeys(labels))
    label_names = [account_risk_info(x).meaning for x in labels]

    need_reduce = "ACCOUNT_NEED_REDUCE" in labels or "ACCOUNT_OVEREXPOSED" in labels or "ACCOUNT_SECTOR_CROWDED" in labels
    if need_reduce:
        advice = "账户层面先降风险，不建议新增买入；优先处理后排、弱结构、低置信度板块和超限板块。"
    elif allow_new_buy:
        advice = "账户层面仍有少量新增空间，但必须只用于READY_CONFIRM或READY_TRIAL且板块不拥挤的核心标的。"
    else:
        advice = "账户层面保持现金，不为了提高仓位而买；等待更明确的板块和个股确认。"
    no_watch_action = "不能盯盘时，总仓位、单票上限和板块上限均降低；不追高波动、补涨和后排。"

    return AccountDecision(
        total_asset=total_asset,
        cash=cash,
        invested_value=invested,
        total_position_pct=total_position_pct,
        cash_pct=cash_pct,
        market_weather=market_weather,
        total_position_limit_pct=total_limit,
        allowed_new_total_pct=allowed_new_total_pct,
        allowed_new_total_value=allowed_new_total_value,
        risk_labels=labels,
        risk_label_names=label_names,
        stock_positions=stock_positions,
        sector_positions=sector_positions,
        candidate_limits=candidate_limits,
        need_reduce=need_reduce,
        allow_new_buy=allow_new_buy,
        no_watch_action=no_watch_action,
        account_advice=advice,
    )


def holding_from_dict(data: dict[str, Any]) -> AccountHolding:
    cost = _num(data.get("cost"))
    current_price = _num(data.get("current_price", data.get("latest_price")), cost)
    shares = _num(data.get("shares"))
    pnl = None
    if cost:
        pnl = (current_price - cost) / cost * 100
    return AccountHolding(
        ts_code=str(data.get("ts_code", "")),
        name=str(data.get("name", "")),
        shares=shares,
        cost=cost,
        current_price=current_price,
        sector_code=str(data.get("sector_code", "")),
        sector_name=str(data.get("sector_name", "")),
        stock_role=str(data.get("stock_role", "UNCERTAIN_ROLE")),
        final_execution_label=str(data.get("final_execution_label", "OBSERVE_ONLY")),
        holding_label=str(data.get("holding_label", "WATCH_ONLY_HOLDING")),
        pnl_pct=pnl,
        sector_cycle=str(data.get("sector_cycle", "UNKNOWN")),
        sector_aux_labels=tuple(data.get("sector_aux_labels", []) or []),
        sector_confidence=str(data.get("sector_confidence", "LOW")),
    )


def candidate_from_dict(data: dict[str, Any]) -> AccountCandidate:
    return AccountCandidate(
        ts_code=str(data.get("ts_code", "")),
        name=str(data.get("name", "")),
        sector_code=str(data.get("sector_code", "")),
        sector_name=str(data.get("sector_name", "")),
        stock_role=str(data.get("stock_role", "UNCERTAIN_ROLE")),
        final_execution_label=str(data.get("final_execution_label", "OBSERVE_ONLY")),
        sector_cycle=str(data.get("sector_cycle", "UNKNOWN")),
        sector_aux_labels=tuple(data.get("sector_aux_labels", []) or []),
        sector_confidence=str(data.get("sector_confidence", "LOW")),
        latest_price=_num(data.get("latest_price"), None),
    )


def decision_to_dict(decision: AccountDecision) -> dict[str, Any]:
    return {
        "total_asset": decision.total_asset,
        "cash": decision.cash,
        "invested_value": decision.invested_value,
        "total_position_pct": decision.total_position_pct,
        "cash_pct": decision.cash_pct,
        "market_weather": decision.market_weather,
        "total_position_limit_pct": decision.total_position_limit_pct,
        "allowed_new_total_pct": decision.allowed_new_total_pct,
        "allowed_new_total_value": decision.allowed_new_total_value,
        "risk_labels": decision.risk_labels,
        "risk_label_names": decision.risk_label_names,
        "stock_positions": decision.stock_positions,
        "sector_positions": decision.sector_positions,
        "candidate_limits": decision.candidate_limits,
        "need_reduce": decision.need_reduce,
        "allow_new_buy": decision.allow_new_buy,
        "no_watch_action": decision.no_watch_action,
        "account_advice": decision.account_advice,
    }
