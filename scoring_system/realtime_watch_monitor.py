from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from scoring_system.cc_connect_notifier import send_via_cc_connect
from scoring_system.eastmoney_intraday import (
    IntradaySnapshot,
    MoneyFlowPoint,
    aggregate_five_minute,
    fetch_intraday_snapshot,
    fetch_money_flow,
)
from scoring_system.industry_members import fetch_stock_industry_profile
from scoring_system.tushare_client import get_tushare_pro


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "realtime_watchlist.json"
REPORT_DIR = ROOT / "reports" / "realtime_watch"
STATE_FILE = REPORT_DIR / "state.json"
LATEST_REPORT = REPORT_DIR / "latest_monitor_status.json"

DEFAULT_CANDIDATE_NOTIFICATION_STATES = {"CONFIRMED", "INVALIDATED"}
DEFAULT_HOLDING_NOTIFICATION_STATES = {"RECOVERY_REJECTED", "SUPPORT_BROKEN", "RISK_ESCALATED"}
DEFAULT_NOTIFICATION_MIN_INTERVAL_MINUTES = 60


STATE_LABELS = {
    "BELOW_ZONE": "尚未到达观察区",
    "ABOVE_ZONE": "突破观察，不追高，等二次买点",
    "ZONE_REACHED": "进入观察区，尚未站稳",
    "HOLDING": "出现承接，等待综合确认",
    "CONFIRMED": "价格、量能、资金和板块综合站稳",
    "TURNING_STRONG": "站稳后转强",
    "INVALIDATED": "跌破观察区，条件失效",
    "DATA_STALE": "行情不是今天，未触发盘中判断",
    "DATA_ERROR": "实时数据异常",
    "SUPPORT_TEST": "持仓进入防守观察区",
    "RECOVERED": "持仓重新站回修复位",
    "STRENGTH_CONFIRMED": "持仓站上转强确认位",
    "RECOVERY_REJECTED": "持仓反弹修复失败",
    "SUPPORT_BROKEN": "持仓跌破第一保护位",
    "RISK_ESCALATED": "持仓跌破风险线",
    "HOLDING_NORMAL": "持仓暂未触发关键条件",
}


def action_guidance(decision: WatchDecision) -> str:
    if decision.kind == "holding":
        actions = {
            "SUPPORT_TEST": "先别急着动，盯住保护位；如果继续走弱，再按风险线处理。",
            "RECOVERED": "先继续拿着观察，不因为一次修复就加仓。",
            "STRENGTH_CONFIRMED": "先继续拿着，让利润多跑一段；新加仓要重新人工确认。",
            "RECOVERY_REJECTED": "建议卖出一部分，先把回落风险降下来。",
            "SUPPORT_BROKEN": "建议卖出一部分做止损或止盈保护，不要硬扛。",
            "RISK_ESCALATED": "建议卖出一部分做止损风控，风险线破了先保本金。",
            "DATA_STALE": "行情不是今天，暂停盘中判断。",
            "DATA_ERROR": "数据异常，不做盘中动作判断。",
        }
        return actions.get(decision.state, "")
    actions = {
        "BELOW_ZONE": "先不买，还没到计划位置。",
        "ZONE_REACHED": "先不买，等它站稳后再说。",
        "HOLDING": "先不买，承接还没确认够。",
        "CONFIRMED": "可以考虑轻仓买入，但先回复确认AI审核；这只是进入人工确认候选，不会自动交易。",
        "TURNING_STRONG": "空仓不要追高；如果已有持仓，就按保护位继续拿。",
        "ABOVE_ZONE": "不要追高，原低吸计划未触发，等第一次回踩不破后再看。",
        "INVALIDATED": "原观察计划失效，本轮计划作废，先别买，等重新站回关键位再评估。",
        "DATA_STALE": "行情不是今天，暂停盘中判断。",
        "DATA_ERROR": "数据异常，不做盘中动作判断。",
    }
    return actions.get(decision.state, "")


def ai_review_guidance(decision: WatchDecision) -> str:
    review_required_states = {"CONFIRMED", "RECOVERY_REJECTED", "SUPPORT_BROKEN", "RISK_ESCALATED"}
    if decision.state in review_required_states:
        return "需要。你确认后，Codex会按股票AI交易助手逻辑重新检查市场、板块、个股和风险，再给出明确建议。"
    if decision.state == "INVALIDATED":
        return "不需要。本轮计划已经失效，明确建议是先别买。"
    return "不需要。当前只是记录状态，不需要马上处理。"


def ai_review_reply_template(decision: WatchDecision) -> str:
    review_topics = {
        "CONFIRMED": "确认轻仓买入",
        "RECOVERY_REJECTED": "反弹修复失败",
        "SUPPORT_BROKEN": "跌破保护位",
        "RISK_ESCALATED": "跌破风险线",
    }
    topic = review_topics.get(decision.state)
    if not topic:
        return ""
    return f"审核 {decision.name} {decision.code} {decision.trade_time} {topic}"


def ai_review_required(decision: WatchDecision) -> bool:
    return decision.state in {"CONFIRMED", "RECOVERY_REJECTED", "SUPPORT_BROKEN", "RISK_ESCALATED"}


def notification_state_summary(decision: WatchDecision) -> str:
    summaries = {
        "CONFIRMED": "已站稳观察条件",
        "INVALIDATED": "已跌破观察区",
        "RECOVERY_REJECTED": "修复失败",
        "SUPPORT_BROKEN": "已跌破保护位",
        "RISK_ESCALATED": "已跌破风险线",
    }
    return summaries.get(decision.state, STATE_LABELS.get(decision.state, decision.state))


def is_trading_session(value: datetime) -> bool:
    if value.weekday() >= 5:
        return False
    current_time = value.strftime("%H:%M")
    return "09:25" <= current_time <= "11:35" or "12:55" <= current_time <= "15:05"


@dataclass(frozen=True)
class WatchDecision:
    code: str
    name: str
    state: str
    price: float | None
    trade_time: str
    zone_low: float
    zone_high: float
    price_held: bool
    volume_ratio: float | None
    volume_ratio_source: str
    volume_ok: bool
    main_net: float | None
    main_net_delta_5m: float | None
    funds_ok: bool
    sector_pct: float | None
    sector_momentum_5m: float | None
    reference_avg_pct: float | None
    sector_ok: bool
    market_avg_pct: float | None
    market_avg_momentum_5m: float | None
    market_ok: bool
    reasons: tuple[str, ...]
    error: str = ""
    kind: str = "candidate"
    quantity: int = 0
    cost: float | None = None
    levels: dict[str, float] | None = None
    industry_profile: dict[str, Any] | None = None


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def notification_states_for(config: dict[str, Any], decision: WatchDecision) -> set[str]:
    notification = config.get("notification") or {}
    key = "holding_states" if decision.kind == "holding" else "candidate_states"
    if key in notification:
        return {str(state) for state in notification.get(key) or []}
    legacy_states = notification.get("states")
    if legacy_states is not None:
        return {str(state) for state in legacy_states}
    if decision.kind == "holding":
        return set(DEFAULT_HOLDING_NOTIFICATION_STATES)
    return set(DEFAULT_CANDIDATE_NOTIFICATION_STATES)


def notification_min_interval_minutes(config: dict[str, Any]) -> int:
    notification = config.get("notification") or {}
    return max(0, int(notification.get("min_interval_minutes", DEFAULT_NOTIFICATION_MIN_INTERVAL_MINUTES)))


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _pct(snapshot: IntradaySnapshot | None) -> float | None:
    return snapshot.pct_chg if snapshot else None


def _momentum_5m(snapshot: IntradaySnapshot | None) -> float | None:
    if not snapshot or len(snapshot.bars) < 6:
        return None
    base = snapshot.bars[-6].close
    return ((snapshot.price / base - 1) * 100) if base else None


def _money_metrics(points: list[MoneyFlowPoint]) -> tuple[float | None, float | None]:
    if not points:
        return None, None
    latest = points[-1].main_net
    prior = points[-6].main_net if len(points) >= 6 else points[0].main_net
    return latest, latest - prior


def _snapshot_fresh(reference: IntradaySnapshot | None, target_time: datetime, max_lag_minutes: int = 5) -> bool:
    if reference is None or reference.trade_time.date() != target_time.date():
        return False
    return abs((target_time - reference.trade_time).total_seconds()) <= max_lag_minutes * 60


def _flows_fresh(points: list[MoneyFlowPoint], target_time: datetime, max_lag_minutes: int = 5) -> bool:
    if not points or points[-1].timestamp.date() != target_time.date():
        return False
    return abs((target_time - points[-1].timestamp).total_seconds()) <= max_lag_minutes * 60


def trading_elapsed_fraction(value: datetime) -> float:
    minutes = value.hour * 60 + value.minute
    morning_start = 9 * 60 + 30
    morning_end = 11 * 60 + 30
    afternoon_start = 13 * 60
    afternoon_end = 15 * 60
    if minutes <= morning_start:
        elapsed = 1
    elif minutes <= morning_end:
        elapsed = minutes - morning_start + 1
    elif minutes < afternoon_start:
        elapsed = 120
    elif minutes <= afternoon_end:
        elapsed = 120 + minutes - afternoon_start + 1
    else:
        elapsed = 240
    return max(1 / 240, min(elapsed / 240, 1.0))


def fetch_avg_daily_amount_yuan(code: str, trade_time: datetime) -> float | None:
    pro = get_tushare_pro(ROOT)
    end = (trade_time.date() - timedelta(days=1)).strftime("%Y%m%d")
    start = (trade_time.date() - timedelta(days=30)).strftime("%Y%m%d")
    frame = pro.daily(ts_code=code, start_date=start, end_date=end, fields="ts_code,trade_date,amount")
    if frame is None or frame.empty or "amount" not in frame.columns:
        return None
    values = frame.sort_values("trade_date", ascending=False)["amount"].head(5)
    clean = [float(value) * 1000 for value in values if value is not None and float(value) > 0]
    return sum(clean) / len(clean) if clean else None


def decide_watch_state(
    item: dict[str, Any],
    stock: IntradaySnapshot,
    flows: list[MoneyFlowPoint],
    sector: IntradaySnapshot | None,
    references: list[IntradaySnapshot],
    market_refs: list[IntradaySnapshot],
    now: datetime,
    previous_state: str = "",
) -> WatchDecision:
    low = float(item["zone"]["low"])
    high = float(item["zone"]["high"])
    settings = item.get("rules") or {}
    tolerance = float(settings.get("break_tolerance_pct", 0.2)) / 100
    min_volume_ratio = float(settings.get("min_same_time_amount_ratio", 0.8))
    max_sector_drop = float(settings.get("max_sector_drop_pct", -1.0))
    max_sector_momentum_drop = float(settings.get("max_sector_momentum_5m_pct", -0.5))
    max_reference_drop = float(settings.get("max_reference_avg_drop_pct", -1.5))
    max_market_drop = float(settings.get("max_market_avg_drop_pct", -1.5))
    max_market_momentum_drop = float(settings.get("max_market_momentum_5m_pct", -0.5))
    max_data_lag = int(settings.get("max_data_lag_minutes", 5))

    stock_lag_seconds = abs((now - stock.trade_time).total_seconds())
    if stock.trade_time.date() != now.date() or stock_lag_seconds > max_data_lag * 60:
        return WatchDecision(
            item["code"], item["name"], "DATA_STALE", stock.price, stock.trade_time.isoformat(timespec="minutes"),
            low, high, False, stock.same_time_amount_ratio_5d, "eastmoney_5d_same_time", False, None, None, False,
            _pct(sector), _momentum_5m(sector), None, False, None, None, False,
            ("行情日期不是今天或分钟数据已停止更新",),
        )

    five_minute = aggregate_five_minute(stock.bars)
    last_two = five_minute[-2:]
    recent = five_minute[-6:]
    zone_touched = any(bar.low <= high for bar in recent)
    price_held = zone_touched and len(last_two) == 2 and all(
        bar.close >= low and bar.low >= low * (1 - tolerance) for bar in last_two
    )
    volume_ratio = stock.same_time_amount_ratio_5d
    volume_ratio_source = "eastmoney_5d_same_time"
    volume_ok = volume_ratio is not None and volume_ratio >= min_volume_ratio
    main_net, main_delta = _money_metrics(flows)
    funds_fresh = _flows_fresh(flows, stock.trade_time, max_data_lag)
    funds_ok = funds_fresh and main_net is not None and main_delta is not None and (main_net >= 0 or main_delta > 0)
    sector_pct = _pct(sector)
    sector_momentum = _momentum_5m(sector)
    reference_pcts = [snapshot.pct_chg for snapshot in references]
    reference_avg = sum(reference_pcts) / len(reference_pcts) if reference_pcts else None
    sector_data_fresh = _snapshot_fresh(sector, stock.trade_time, max_data_lag) and all(
        _snapshot_fresh(reference, stock.trade_time, max_data_lag) for reference in references
    )
    sector_ok = (
        sector_data_fresh
        and
        sector_pct is not None
        and sector_momentum is not None
        and reference_avg is not None
        and sector_pct >= max_sector_drop
        and sector_momentum >= max_sector_momentum_drop
        and reference_avg >= max_reference_drop
    )
    market_pcts = [snapshot.pct_chg for snapshot in market_refs]
    market_momentums = [value for value in (_momentum_5m(snapshot) for snapshot in market_refs) if value is not None]
    market_avg = sum(market_pcts) / len(market_pcts) if market_pcts else None
    market_momentum = sum(market_momentums) / len(market_momentums) if market_momentums else None
    market_data_fresh = bool(market_refs) and all(
        _snapshot_fresh(reference, stock.trade_time, max_data_lag) for reference in market_refs
    )
    market_ok = (
        market_data_fresh
        and
        market_avg is not None
        and market_momentum is not None
        and market_avg >= max_market_drop
        and market_momentum >= max_market_momentum_drop
    )

    reasons: list[str] = []
    active_states = {"ABOVE_ZONE", "ZONE_REACHED", "HOLDING", "CONFIRMED", "TURNING_STRONG"}
    touched_today = any(bar.high >= low and bar.low <= high for bar in stock.bars)
    below_confirmed = len(stock.bars) >= 2 and all(bar.close < low * (1 - tolerance) for bar in stock.bars[-2:])
    if stock.price < low * (1 - tolerance):
        if below_confirmed and (previous_state in active_states or touched_today):
            state = "INVALIDATED"
            reasons.append("到达观察区后连续两分钟低于下沿容差")
        else:
            state = "BELOW_ZONE"
            reasons.append("价格在观察区下方，尚未形成有效到价状态")
    elif not price_held:
        if low <= stock.price <= high:
            state = "ZONE_REACHED"
            reasons.append("价格到达观察区，但两个完整5分钟周期尚未确认")
        elif stock.price > high:
            state = "ABOVE_ZONE"
            reasons.append("价格高于观察区但未完成回踩站稳，空仓不追高")
        else:
            state = "BELOW_ZONE"
            reasons.append("价格尚未进入观察区")
    elif price_held and volume_ok and funds_ok and sector_ok and market_ok:
        last_bar_rising = len(last_two) == 2 and last_two[-1].close > last_two[-2].close
        if previous_state in {"CONFIRMED", "TURNING_STRONG"} and stock.price > high and last_bar_rising and (main_delta or 0) > 0:
            state = "TURNING_STRONG"
            reasons.append("站稳后价格转强，资金边际改善")
        elif previous_state == "ABOVE_ZONE":
            state = "CONFIRMED"
            reasons.append("突破后首次回踩未破，并完成量能、资金和环境确认")
        else:
            state = "CONFIRMED"
            reasons.append("价格、同期成交、资金和板块均通过确认")
    else:
        state = "HOLDING"
        if previous_state == "ABOVE_ZONE" and price_held:
            reasons.append("突破后已有回踩承接，但综合条件尚未全部确认")
        else:
            reasons.append("价格已有承接，但综合条件尚未全部确认")
    if not volume_ok:
        reasons.append("同期成交不足或暂无可比数据")
    if not funds_ok:
        reasons.append("主力资金未改善、缺失或时间不同步")
    if not sector_ok:
        reasons.append("板块或参照股未同步确认")
    if not market_ok:
        reasons.append("大盘环境未同步确认")

    return WatchDecision(
        code=item["code"], name=item["name"], state=state, price=stock.price,
        trade_time=stock.trade_time.isoformat(timespec="minutes"), zone_low=low, zone_high=high,
        price_held=price_held, volume_ratio=volume_ratio, volume_ratio_source=volume_ratio_source, volume_ok=volume_ok,
        main_net=main_net, main_net_delta_5m=main_delta, funds_ok=funds_ok,
        sector_pct=sector_pct, sector_momentum_5m=sector_momentum,
        reference_avg_pct=reference_avg, sector_ok=sector_ok,
        market_avg_pct=market_avg, market_avg_momentum_5m=market_momentum, market_ok=market_ok,
        reasons=tuple(reasons),
    )


def decide_holding_state(
    item: dict[str, Any],
    stock: IntradaySnapshot,
    flows: list[MoneyFlowPoint],
    sector: IntradaySnapshot | None,
    references: list[IntradaySnapshot],
    market_refs: list[IntradaySnapshot],
    now: datetime,
    previous_state: str = "",
) -> WatchDecision:
    levels = item["levels"]
    support = float(levels["support"])
    recovery = float(levels["recovery"])
    risk = float(levels["risk"])
    strength = float(levels.get("strength") or 0)
    synthetic = dict(item)
    synthetic["zone"] = {"low": support, "high": recovery}
    base = decide_watch_state(synthetic, stock, flows, sector, references, market_refs, now, previous_state)
    holding_fields = {
        "kind": "holding",
        "quantity": int(item.get("quantity") or 0),
        "cost": float(item["cost"]) if item.get("cost") is not None else None,
        "levels": {key: float(value) for key, value in levels.items()},
    }
    if base.state in {"DATA_STALE", "DATA_ERROR"}:
        return replace(base, **holding_fields)

    tolerance = float((item.get("rules") or {}).get("break_tolerance_pct", 0.2)) / 100
    bars_5m = aggregate_five_minute(stock.bars)
    last_two_1m = stock.bars[-2:]
    last_two_5m = bars_5m[-2:]
    below_risk = len(last_two_1m) == 2 and all(bar.close < risk * (1 - tolerance) for bar in last_two_1m)
    below_support = len(last_two_1m) == 2 and all(bar.close < support * (1 - tolerance) for bar in last_two_1m)
    recovered = len(last_two_5m) == 2 and all(bar.close >= recovery for bar in last_two_5m)
    strengthened = strength > 0 and len(last_two_5m) == 2 and all(bar.close >= strength for bar in last_two_5m)
    recovery_rejected = (
        stock.high >= recovery
        and stock.price < recovery
        and len(last_two_5m) == 2
        and last_two_5m[-1].close < last_two_5m[-2].close
        and not base.funds_ok
    )

    if below_risk:
        state, reason = "RISK_ESCALATED", "连续两分钟跌破风险线，持仓风险升级"
    elif below_support:
        state, reason = "SUPPORT_BROKEN", "连续两分钟跌破第一保护位"
    elif strengthened and base.volume_ok and base.funds_ok and base.sector_ok and base.market_ok:
        state, reason = "STRENGTH_CONFIRMED", "连续两个5分钟周期站上转强位，环境同步确认"
    elif recovery_rejected:
        state, reason = "RECOVERY_REJECTED", "盘中触及修复位后回落，资金未同步改善"
    elif recovered:
        state, reason = "RECOVERED", "连续两个5分钟周期站回修复位"
    elif support <= stock.price < recovery:
        state, reason = "SUPPORT_TEST", "进入持仓防守区，继续观察承接"
    else:
        state, reason = "HOLDING_NORMAL", "暂未触发持仓关键条件"
    return replace(base, state=state, reasons=(reason,) + tuple(base.reasons[1:]), **holding_fields)


def build_message(decision: WatchDecision) -> str:
    price_text = f"{decision.price:.2f}" if decision.price is not None else "暂无"
    summary = notification_state_summary(decision)
    action = action_guidance(decision) or "先继续观察。"
    review_required = ai_review_required(decision)
    message = f"{decision.name}现价{price_text}，{summary}，建议{action}，AI审核：{'需要' if review_required else '不需要'}"
    review_template = ai_review_reply_template(decision)
    if review_template:
        message += f"，如需审核请回复：{review_template}"
    return message


def format_industry_profile(profile: dict[str, Any] | None) -> str:
    if not profile:
        return ""
    parts: list[str] = []
    sw = profile.get("sw") or {}
    ci = profile.get("ci") or {}
    if sw.get("l3_name"):
        parts.append(f"申万 {sw.get('l1_name', '-')}/{sw.get('l2_name', '-')}/{sw.get('l3_name', '-')}")
    if ci.get("l3_name"):
        parts.append(f"中信 {ci.get('l1_name', '-')}/{ci.get('l2_name', '-')}/{ci.get('l3_name', '-')}")
    return "；".join(parts)


class RealtimeWatchMonitor:
    def __init__(
        self,
        config: dict[str, Any],
        snapshot_fetcher: Callable[[str, int], IntradaySnapshot] = fetch_intraday_snapshot,
        flow_fetcher: Callable[[str, int], list[MoneyFlowPoint]] = fetch_money_flow,
        baseline_fetcher: Callable[[str, datetime], float | None] = fetch_avg_daily_amount_yuan,
        industry_fetcher: Callable[[str], dict[str, Any]] | None = None,
        config_path: Path | None = None,
    ) -> None:
        self.config = config
        self.snapshot_fetcher = snapshot_fetcher
        self.flow_fetcher = flow_fetcher
        self.baseline_fetcher = baseline_fetcher
        self.industry_fetcher = industry_fetcher or self._fetch_industry_profile
        self.config_path = config_path
        self._config_mtime = config_path.stat().st_mtime if config_path and config_path.exists() else None
        self._config_signature = config_path.read_text(encoding="utf-8") if config_path and config_path.exists() else None
        self._baseline_cache: dict[tuple[str, str], float | None] = {}
        self._industry_cache: dict[str, dict[str, Any]] = {}
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

    def _fetch_industry_profile(self, code: str) -> dict[str, Any]:
        pro = get_tushare_pro(ROOT)
        return fetch_stock_industry_profile(pro, code)

    def reload_config_if_changed(self) -> bool:
        if not self.config_path or not self.config_path.exists():
            return False
        mtime = self.config_path.stat().st_mtime
        content = self.config_path.read_text(encoding="utf-8")
        if self._config_mtime is not None and mtime == self._config_mtime and content == self._config_signature:
            return False
        self.config = json.loads(content)
        self._config_mtime = mtime
        self._config_signature = content
        self._baseline_cache.clear()
        self._industry_cache.clear()
        return True

    def _load_state(self) -> dict[str, Any]:
        if not STATE_FILE.exists():
            return {}
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def run_once(self, now: datetime | None = None, send: bool = False, force_notify: bool = False) -> dict[str, Any]:
        current = now or datetime.now()
        previous = self._load_state()
        decisions: list[WatchDecision] = []
        delivery: list[dict[str, Any]] = []
        next_platform_states: dict[str, dict[str, str]] = {}
        next_platform_times: dict[str, dict[str, str]] = {}
        cache: dict[str, IntradaySnapshot] = {}

        def snapshot(code: str, ndays: int = 1) -> IntradaySnapshot:
            key = f"{code}:{ndays}"
            if key not in cache:
                cache[key] = self.snapshot_fetcher(code, ndays)
            return cache[key]

        market_refs: list[IntradaySnapshot] = []
        try:
            market_refs = [snapshot(code, 1) for code in self.config.get("market", {}).get("references", [])]
        except Exception:
            market_refs = []

        all_items = [(item, False) for item in self.config.get("watchlist", [])]
        all_items.extend((item, True) for item in self.config.get("holding_watchlist", []))
        industry_enabled = bool((self.config.get("industry_profile") or {}).get("enabled", False))
        for item, is_holding in all_items:
            industry_profile = None
            try:
                if industry_enabled:
                    code = str(item["code"])
                    if code not in self._industry_cache:
                        self._industry_cache[code] = self.industry_fetcher(code)
                    industry_profile = self._industry_cache[code]
                stock = snapshot(item["code"], 5)
                projected_volume_ratio = False
                if stock.same_time_amount_ratio_5d is None:
                    baseline_key = (item["code"], stock.trade_time.strftime("%Y%m%d"))
                    if baseline_key not in self._baseline_cache:
                        self._baseline_cache[baseline_key] = self.baseline_fetcher(item["code"], stock.trade_time)
                    baseline = self._baseline_cache[baseline_key]
                    if baseline:
                        projected = stock.amount / (baseline * trading_elapsed_fraction(stock.trade_time))
                        stock = replace(stock, same_time_amount_ratio_5d=projected)
                        projected_volume_ratio = True
                flows = self.flow_fetcher(item["code"], 30)
                sector = snapshot(item["sector"]["secid"], 1)
                references = [snapshot(code, 1) for code in item["sector"].get("references", [])]
                decision_fn = decide_holding_state if is_holding else decide_watch_state
                decision = decision_fn(item, stock, flows, sector, references, market_refs, current)
                if projected_volume_ratio:
                    decision = replace(decision, volume_ratio_source="tushare_5d_elapsed_projection")
                decision = replace(decision, industry_profile=industry_profile)
            except Exception as exc:
                decision = WatchDecision(
                    item["code"], item["name"], "DATA_ERROR", None, current.isoformat(timespec="minutes"),
                    float(item["zone"]["low"]), float(item["zone"]["high"]), False, None, "unavailable", False,
                    None, None, False, None, None, None, False, None, None, False, ("实时数据获取失败",),
                    f"{type(exc).__name__}: {str(exc)[:300]}", industry_profile=industry_profile,
                )
            old_record = previous.get(decision.code) or {}
            decision_trade_date = decision.trade_time[:10]
            same_trade_date = str(old_record.get("trade_date") or "") == decision_trade_date
            old_state = str(old_record.get("state") or "") if same_trade_date else ""
            if decision.state != "DATA_ERROR":
                decision_fn = decide_holding_state if is_holding else decide_watch_state
                decision = decision_fn(item, stock, flows, sector, references, market_refs, current, old_state)
                if projected_volume_ratio:
                    decision = replace(decision, volume_ratio_source="tushare_5d_elapsed_projection")
                decision = replace(decision, industry_profile=industry_profile)
            decisions.append(decision)
            notify_states = notification_states_for(self.config, decision)
            min_interval_minutes = notification_min_interval_minutes(self.config)
            target_platforms = self.config.get("cc_connect", {}).get("platforms", ["weixin", "feishu"])
            previous_platform_states = dict(old_record.get("platform_states") or {}) if same_trade_date else {}
            previous_platform_times = dict(old_record.get("platform_notification_times") or {}) if same_trade_date else {}
            missing_platforms: list[str] = []
            for platform in target_platforms:
                if force_notify:
                    missing_platforms.append(platform)
                    continue
                last_sent_at = _parse_iso_datetime(previous_platform_times.get(platform))
                if last_sent_at is None:
                    missing_platforms.append(platform)
                    continue
                elapsed_seconds = (current - last_sent_at).total_seconds()
                if elapsed_seconds >= min_interval_minutes * 60:
                    missing_platforms.append(platform)
            should_notify = decision.state in notify_states and bool(missing_platforms)
            if send and should_notify:
                try:
                    results = send_via_cc_connect(
                        build_message(decision),
                        project=self.config.get("cc_connect", {}).get("project", "codex-weixin"),
                        platforms=missing_platforms,
                        session_overrides=self.config.get("cc_connect", {}).get("session_overrides", {}),
                    )
                    delivery.extend(asdict(result) for result in results)
                    for result in results:
                        if result.sent:
                            previous_platform_states[result.platform] = decision.state
                            previous_platform_times[result.platform] = current.isoformat(timespec="seconds")
                except Exception as exc:
                    delivery.append({"platform": "cc_connect", "session": "", "sent": False, "detail": f"{type(exc).__name__}: {str(exc)[:300]}"})

            next_platform_states[decision.code] = previous_platform_states
            next_platform_times[decision.code] = previous_platform_times

        state = {}
        for decision in decisions:
            old_record = previous.get(decision.code) or {}
            state[decision.code] = {
                "state": decision.state,
                "trade_date": decision.trade_time[:10],
                "platform_states": next_platform_states.get(decision.code, old_record.get("platform_states", {})),
                "platform_notification_times": next_platform_times.get(decision.code, old_record.get("platform_notification_times", {})),
                "updated_at": current.isoformat(timespec="seconds"),
            }
        report = {
            "generated_at": current.isoformat(timespec="seconds"),
            "source": "eastmoney_intraday",
            "send_enabled": send,
            "decisions": [asdict(decision) for decision in decisions],
            "delivery": delivery,
        }
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        LATEST_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def run_forever(self, send: bool = True, session_only: bool = False) -> None:
        interval = max(30, int(self.config.get("poll_interval_seconds", 60)))
        while True:
            self.reload_config_if_changed()
            now = datetime.now()
            in_session = is_trading_session(now)
            if session_only and not in_session:
                return
            if in_session:
                try:
                    self.run_once(now=now, send=send)
                except Exception as exc:
                    REPORT_DIR.mkdir(parents=True, exist_ok=True)
                    with (REPORT_DIR / "monitor_runtime_error.log").open("a", encoding="utf-8") as handle:
                        handle.write(f"{now.isoformat(timespec='seconds')} {type(exc).__name__}: {str(exc)[:500]}\n")
                if session_only:
                    time.sleep(interval)
                    continue
            time.sleep(interval if in_session else min(300, interval * 5))
