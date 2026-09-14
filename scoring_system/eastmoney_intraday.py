from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


TRENDS_URLS = []
MONEY_FLOW_URLS = []
HEADERS = {}


@dataclass(frozen=True)
class MinuteBar:
    timestamp: datetime
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
    average_price: float | None


@dataclass(frozen=True)
class MoneyFlowPoint:
    timestamp: datetime
    main_net: float
    small_net: float
    medium_net: float
    large_net: float
    super_large_net: float


@dataclass(frozen=True)
class IntradaySnapshot:
    secid: str
    code: str
    name: str
    trade_time: datetime
    price: float
    prev_close: float
    pct_chg: float
    open: float
    high: float
    low: float
    volume: float
    amount: float
    same_time_amount_ratio_5d: float | None
    bars: tuple[MinuteBar, ...]


def secid_for_code(code: str) -> str:
    raw = str(code or "").strip()
    if "." in raw and raw.split(".", 1)[0] in {"0", "1", "90"}:
        market, symbol = raw.split(".", 1)
        return f"{market}.{symbol}"
    digits = "".join(ch for ch in raw if ch.isdigit())[:6]
    if not digits:
        raise ValueError("missing stock code")
    return f"1.{digits}" if digits.startswith(("6", "9")) else f"0.{digits}"


def _session(*args, **kwargs):
    from scoring_system.market_data import DataSourceError
    raise DataSourceError('External provider disabled')



def _get_json(*args, **kwargs):
    from scoring_system.market_data import DataSourceError
    raise DataSourceError('External provider disabled; use hithink-finance / AKShare 新浪分钟线')



def parse_trend_rows(rows: list[str]) -> list[MinuteBar]:
    result: list[MinuteBar] = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 8:
            continue
        try:
            result.append(
                MinuteBar(
                    timestamp=datetime.strptime(parts[0], "%Y-%m-%d %H:%M"),
                    open=float(parts[1]),
                    close=float(parts[2]),
                    high=float(parts[3]),
                    low=float(parts[4]),
                    volume=float(parts[5]),
                    amount=float(parts[6]),
                    average_price=float(parts[7]) if parts[7] not in {"", "-"} else None,
                )
            )
        except (TypeError, ValueError):
            continue
    return result


def parse_money_flow_rows(rows: list[str]) -> list[MoneyFlowPoint]:
    result: list[MoneyFlowPoint] = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 6:
            continue
        try:
            result.append(
                MoneyFlowPoint(
                    timestamp=datetime.strptime(parts[0], "%Y-%m-%d %H:%M"),
                    main_net=float(parts[1]),
                    small_net=float(parts[2]),
                    medium_net=float(parts[3]),
                    large_net=float(parts[4]),
                    super_large_net=float(parts[5]),
                )
            )
        except (TypeError, ValueError):
            continue
    return result


def _same_time_amount_ratio(bars: list[MinuteBar]) -> float | None:
    if not bars:
        return None
    latest_date = bars[-1].timestamp.date()
    latest_minute = bars[-1].timestamp.time()
    by_date: dict[Any, float] = {}
    for bar in bars:
        if bar.timestamp.time() <= latest_minute:
            by_date[bar.timestamp.date()] = by_date.get(bar.timestamp.date(), 0.0) + bar.amount
    current = by_date.pop(latest_date, 0.0)
    historical = [value for value in by_date.values() if value > 0]
    if not current or not historical:
        return None
    return current / (sum(historical[-5:]) / len(historical[-5:]))


def fetch_intraday_snapshot(code, ndays=5):
    from scoring_system.market_data import minutes, snapshot, DataSourceError
    if '.' not in code or code.startswith(('0.','1.','90.')):
        raise DataSourceError('Use verified thscode for minute data; legacy sector secid is not supported')
    quote=snapshot(code)['data']['item'][0]
    data=minutes(code,'1m',min(800,240*ndays))['data']
    bars=[MinuteBar(timestamp=datetime.fromisoformat(r['datetime']),open=r['open'],close=r['close'],high=r['high'],low=r['low'],volume=r['vol'],amount=r['amount'],average_price=None) for r in data]
    latest=bars[-1]; today=[b for b in bars if b.timestamp.date()==latest.timestamp.date()]
    return IntradaySnapshot(secid=code,code=code,name=code,trade_time=latest.timestamp,
        price=latest.close,prev_close=quote['prev_price'],pct_chg=(latest.close/quote['prev_price']-1)*100,
        open=today[0].open,high=max(b.high for b in today),low=min(b.low for b in today),
        volume=sum(b.volume for b in today),amount=sum(b.amount for b in today),
        same_time_amount_ratio_5d=None,bars=tuple(today))



def fetch_money_flow(code, limit=30):
    from scoring_system.market_data import DataSourceError
    raise DataSourceError('Minute money-flow breakdown is not supported by configured sources; no fallback')



def aggregate_five_minute(bars: tuple[MinuteBar, ...] | list[MinuteBar]) -> list[MinuteBar]:
    groups: dict[tuple[Any, int, int], list[MinuteBar]] = {}
    for bar in bars:
        minute_bucket = (bar.timestamp.minute // 5) * 5
        key = (bar.timestamp.date(), bar.timestamp.hour, minute_bucket)
        groups.setdefault(key, []).append(bar)
    result: list[MinuteBar] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda item: item.timestamp)
        if len(ordered) < 5:
            continue
        result.append(
            MinuteBar(
                timestamp=ordered[-1].timestamp,
                open=ordered[0].open,
                close=ordered[-1].close,
                high=max(item.high for item in ordered),
                low=min(item.low for item in ordered),
                volume=sum(item.volume for item in ordered),
                amount=sum(item.amount for item in ordered),
                average_price=ordered[-1].average_price,
            )
        )
    return sorted(result, key=lambda item: item.timestamp)


