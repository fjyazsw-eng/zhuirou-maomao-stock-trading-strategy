from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scoring_system.env_loader import load_project_env
from scoring_system.network_env import clear_bad_tushare_proxy
from scoring_system.tushare_client import get_tushare_pro, http_url_value


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "tushare"
LATEST_FRESHNESS_JSON = REPORT_DIR / "latest_freshness_status.json"

REQUIRED_API_ORDER = ["daily", "daily_basic", "index_daily", "sw_daily"]


def classify_freshness_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if "http_429" in lowered or "并发请求过多" in text or "rate limit" in lowered or "too many requests" in lowered:
        return "RATE_LIMITED"
    if "proxy" in lowered:
        return "PROXY_ERROR"
    if "timeout" in lowered or "timed out" in lowered:
        return "TIMEOUT"
    if "token" in lowered or "token不对" in text:
        return "TOKEN_ERROR"
    return "UNKNOWN_ERROR"


def rows_for_required_apis(pro: Any, trade_date: str) -> dict[str, int]:
    daily = pro.daily(
        trade_date=trade_date,
        fields="ts_code,trade_date,open,high,low,close,pct_chg,vol,amount",
    )
    daily_basic = pro.daily_basic(
        trade_date=trade_date,
        fields="ts_code,trade_date,turnover_rate,volume_ratio,pe,pb,total_mv,circ_mv",
    )
    index_daily = pro.index_daily(
        trade_date=trade_date,
        fields="ts_code,trade_date,close,pct_chg,amount",
    )
    sw_daily = pro.query("sw_daily", trade_date=trade_date)
    return {
        "daily": int(len(daily)) if daily is not None else 0,
        "daily_basic": int(len(daily_basic)) if daily_basic is not None else 0,
        "index_daily": int(len(index_daily)) if index_daily is not None else 0,
        "sw_daily": int(len(sw_daily)) if sw_daily is not None else 0,
    }


def required_rows_complete(rows: dict[str, int], min_daily_rows: int, min_index_rows: int, min_sw_rows: int) -> bool:
    return (
        rows.get("daily", 0) >= min_daily_rows
        and rows.get("daily_basic", 0) >= min_daily_rows
        and rows.get("index_daily", 0) >= min_index_rows
        and rows.get("sw_daily", 0) >= min_sw_rows
    )


def _open_trade_dates(pro: Any, today: str, lookback_start: str) -> list[str]:
    cal = pro.trade_cal(exchange="SSE", start_date=lookback_start, end_date=today, is_open="1")
    if cal is None or len(cal) == 0:
        return []
    return sorted({str(x) for x in cal["cal_date"].dropna().tolist()})


def _default_lookback_start(today: str) -> str:
    year = int(today[:4])
    month = int(today[4:6])
    if month <= 2:
        return f"{year - 1}1201"
    return f"{year}{month - 2:02d}01"


def evaluate_freshness(
    pro: Any | None = None,
    today: str | None = None,
    min_daily_rows: int = 5000,
    min_index_rows: int = 3,
    min_sw_rows: int = 100,
    lookback_days: int = 10,
) -> dict[str, Any]:
    if today is None:
        today = datetime.now().strftime("%Y%m%d")
    if pro is None:
        load_project_env(override=True)
        clear_bad_tushare_proxy()
        pro = get_tushare_pro()

    started = time.perf_counter()
    result: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "endpoint": http_url_value() or "default_tushare_sdk",
        "status": "BLOCKED",
        "error_category": "",
        "message": "",
        "latest_trade_date": "",
        "latest_complete_trade_date": "",
        "data_is_latest_complete": False,
        "formal_recommendation_allowed": False,
        "required_api_rows": {api: 0 for api in REQUIRED_API_ORDER},
        "latest_trade_date_rows": {api: 0 for api in REQUIRED_API_ORDER},
        "checked_dates": [],
        "min_rows": {
            "daily": min_daily_rows,
            "daily_basic": min_daily_rows,
            "index_daily": min_index_rows,
            "sw_daily": min_sw_rows,
        },
        "probe_seconds": 0.0,
    }

    try:
        open_dates = _open_trade_dates(pro, today=today, lookback_start=_default_lookback_start(today))
        if not open_dates:
            result["status"] = "BLOCKED"
            result["message"] = "trade_cal returned no open trade dates"
            return result

        latest_trade_date = open_dates[-1]
        result["latest_trade_date"] = latest_trade_date
        recent_dates = list(reversed(open_dates[-lookback_days:]))
        for trade_date in recent_dates:
            rows = rows_for_required_apis(pro, trade_date)
            result["checked_dates"].append({"trade_date": trade_date, "required_api_rows": rows})
            if trade_date == latest_trade_date:
                result["required_api_rows"] = dict(rows)
                result["latest_trade_date_rows"] = dict(rows)
            if required_rows_complete(rows, min_daily_rows, min_index_rows, min_sw_rows):
                result["latest_complete_trade_date"] = trade_date
                if trade_date != latest_trade_date and result["required_api_rows"] == {api: 0 for api in REQUIRED_API_ORDER}:
                    result["required_api_rows"] = dict(rows)
                break

        complete_date = str(result.get("latest_complete_trade_date") or "")
        if complete_date == latest_trade_date:
            result["status"] = "PASS"
            result["data_is_latest_complete"] = True
            result["formal_recommendation_allowed"] = True
            result["message"] = "latest trade date has complete Tushare rows"
        elif complete_date:
            result["status"] = "WARN"
            result["data_is_latest_complete"] = False
            result["formal_recommendation_allowed"] = False
            result["message"] = "latest trade date missing complete Tushare rows; formal recommendation is blocked"
        else:
            result["status"] = "BLOCKED"
            result["message"] = "no complete Tushare trade date found in recent lookback"
    except Exception as exc:  # noqa: BLE001 - probe must summarize all data failures.
        result["status"] = "BLOCKED"
        result["error_category"] = classify_freshness_error(exc)
        result["message"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    finally:
        result["probe_seconds"] = round(time.perf_counter() - started, 3)
    return result


def write_freshness_status(result: dict[str, Any], path: Path = LATEST_FRESHNESS_JSON) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_freshness_probe(today: str | None = None, output_path: Path = LATEST_FRESHNESS_JSON) -> dict[str, Any]:
    result = evaluate_freshness(today=today)
    write_freshness_status(result, output_path)
    return result
