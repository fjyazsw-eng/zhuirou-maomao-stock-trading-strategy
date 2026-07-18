from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


TRENDS_URLS = [
    "https://push2delay.eastmoney.com/api/qt/stock/trends2/get",
    "https://push2his.eastmoney.com/api/qt/stock/trends2/get",
]
MONEY_FLOW_URLS = [
    "https://push2delay.eastmoney.com/api/qt/stock/fflow/kline/get",
    "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
]
HEADERS = {
    "Accept": "application/json",
    "Referer": "https://quote.eastmoney.com/",
    "User-Agent": "Mozilla/5.0 stock-ai-assistant/1.0",
}


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


def _session(trust_env: bool) -> requests.Session:
    session = requests.Session()
    session.trust_env = trust_env
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _get_json(urls: list[str], params: dict[str, Any], timeout: int = 15) -> dict[str, Any]:
    errors: list[str] = []
    for url in urls:
        for trust_env in (True, False):
            try:
                response = _session(trust_env).get(url, params=params, headers=HEADERS, timeout=timeout)
                response.raise_for_status()
                response.encoding = "utf-8"
                payload = response.json()
                if int(payload.get("rc", 0)) not in {0}:
                    raise RuntimeError(f"eastmoney_rc_{payload.get('rc')}")
                return payload
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                errors.append(f"url={url},trust_env={trust_env}:{type(exc).__name__}:{str(exc)[:140]}")
    raise RuntimeError("; ".join(errors))


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


def fetch_intraday_snapshot(code: str, ndays: int = 5) -> IntradaySnapshot:
    secid = secid_for_code(code)
    payload = _get_json(
        TRENDS_URLS,
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ndays": max(1, min(int(ndays), 5)),
            "iscr": "0",
            "iscca": "0",
        },
    )
    data = payload.get("data") or {}
    bars = parse_trend_rows(data.get("trends") or [])
    if not bars:
        raise RuntimeError(f"eastmoney trends empty for {code}")
    latest_date = bars[-1].timestamp.date()
    today = [bar for bar in bars if bar.timestamp.date() == latest_date]
    prev_close = float(data.get("preClose") or data.get("prePrice") or 0)
    latest = today[-1]
    return IntradaySnapshot(
        secid=secid,
        code=str(data.get("code") or code),
        name=str(data.get("name") or code),
        trade_time=latest.timestamp,
        price=latest.close,
        prev_close=prev_close,
        pct_chg=((latest.close / prev_close - 1) * 100) if prev_close else 0.0,
        open=today[0].open,
        high=max(bar.high for bar in today),
        low=min(bar.low for bar in today),
        volume=sum(bar.volume for bar in today),
        amount=sum(bar.amount for bar in today),
        same_time_amount_ratio_5d=_same_time_amount_ratio(bars),
        bars=tuple(today),
    )


def fetch_money_flow(code: str, limit: int = 30) -> list[MoneyFlowPoint]:
    secid = secid_for_code(code)
    payload = _get_json(
        MONEY_FLOW_URLS,
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
            "klt": "1",
            "lmt": max(10, int(limit)),
        },
    )
    data = payload.get("data") or {}
    return parse_money_flow_rows(data.get("klines") or [])


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
