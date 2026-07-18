from __future__ import annotations

from datetime import datetime
from typing import Any

import requests


EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EASTMONEY_FIELDS = "f57,f58,f43,f44,f45,f46,f47,f48,f60,f169,f170,f111,f86,f124"


def secid_for_code(code: str) -> str:
    normalized = "".join(ch for ch in str(code or "") if ch.isdigit())[:6]
    if not normalized:
        raise ValueError("missing stock code")
    if normalized.startswith(("6", "9")):
        return f"1.{normalized}"
    return f"0.{normalized}"


def _price(value: Any) -> str:
    try:
        return f"{float(value) / 100:.2f}"
    except Exception:
        return "-"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) / 100:.2f}%"
    except Exception:
        return "-"


def _amount(value: Any) -> str:
    try:
        return f"{float(value):.0f}"
    except Exception:
        return "-"


def _trade_date_from_ts(value: Any) -> str:
    try:
        ts = int(value)
        if ts <= 0:
            return "-"
        return datetime.fromtimestamp(ts).strftime("%Y%m%d")
    except Exception:
        return "-"


def fetch_realtime_quote(code: str) -> dict[str, str]:
    secid = secid_for_code(code)
    response = requests.get(
        EASTMONEY_QUOTE_URL,
        params={"secid": secid, "fields": EASTMONEY_FIELDS, "invt": "2", "fltt": "1"},
        timeout=15,
        headers={"User-Agent": "stock-ai-assistant/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or {}
    if not data:
        raise RuntimeError("eastmoney quote empty")
    return {
        "source": "eastmoney_realtime",
        "ts_code": str(data.get("f57") or code),
        "name": str(data.get("f58") or code),
        "trade_date": _trade_date_from_ts(data.get("f124")) if _trade_date_from_ts(data.get("f124")) != "-" else _trade_date_from_ts(data.get("f86")),
        "price": _price(data.get("f43")),
        "pct_chg": _pct(data.get("f170")),
        "open": _price(data.get("f46")),
        "high": _price(data.get("f44")),
        "low": _price(data.get("f45")),
        "prev_close": _price(data.get("f60")),
        "amount": _amount(data.get("f48")),
    }
