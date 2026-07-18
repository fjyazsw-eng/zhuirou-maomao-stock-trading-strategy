from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from requests.utils import get_environ_proxies

from scoring_system.env_loader import load_project_env
from scoring_system.network_env import clear_bad_tushare_proxy, proxy_snapshot
from scoring_system.tushare_client import get_tushare_pro, http_url_value, token_value

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "tushare"
LATEST_JSON = REPORT_DIR / "latest_tushare_status.json"

API_CATEGORY_MAP = {
    "stock_basic": "基础资料",
    "trade_cal": "基础资料",
    "daily": "行情",
    "daily_basic": "行情",
    "index_daily": "指数",
    "index_classify": "板块行业",
    "index_member": "板块行业",
    "moneyflow": "资金流",
    "adj_factor": "复权",
    "income": "财务",
    "fina_indicator": "财务",
}


def masked_token(token: str) -> str:
    if len(token) <= 6:
        return "***"
    return f"{token[:3]}***{token[-3:]}"


def probe_api_permission(name: str, fetcher) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        df = fetcher()
        rows = int(len(df)) if df is not None else 0
        return {
            "api_name": name,
            "ok": True,
            "rows": rows,
            "status": "PASS" if rows > 0 else "EMPTY",
            "message": "ok" if rows > 0 else "empty_result",
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        }
    except Exception as exc:
        return {
            "api_name": name,
            "ok": False,
            "rows": 0,
            "status": "FAIL",
            "message": f"{type(exc).__name__}: {str(exc)[:180]}",
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        }


def summarize_permissions(permission_checks: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [item["api_name"] for item in permission_checks if item.get("ok")]
    failed = [item["api_name"] for item in permission_checks if not item.get("ok")]
    return {
        "checked_count": len(permission_checks),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "passed_apis": passed,
        "failed_apis": failed,
        "all_passed": len(failed) == 0,
    }


def build_category_summary(permission_checks: list[dict[str, Any]]) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}
    for item in permission_checks:
        api_name = str(item.get("api_name", ""))
        category = API_CATEGORY_MAP.get(api_name, "其他")
        bucket = categories.setdefault(
            category,
            {
                "category": category,
                "checked_count": 0,
                "passed_count": 0,
                "failed_count": 0,
                "passed_apis": [],
                "failed_apis": [],
                "status": "未检测",
            },
        )
        bucket["checked_count"] += 1
        if item.get("ok"):
            bucket["passed_count"] += 1
            bucket["passed_apis"].append(api_name)
        else:
            bucket["failed_count"] += 1
            bucket["failed_apis"].append(api_name)
    for bucket in categories.values():
        if bucket["failed_count"] == 0 and bucket["passed_count"] > 0:
            bucket["status"] = "PASS"
        elif bucket["passed_count"] > 0:
            bucket["status"] = "PARTIAL"
        elif bucket["checked_count"] > 0:
            bucket["status"] = "FAIL"
    return categories


def probe_tushare() -> dict[str, Any]:
    load_project_env(override=True)
    before = proxy_snapshot()
    fixed = clear_bad_tushare_proxy()
    after = proxy_snapshot()
    token = token_value()
    http_url = http_url_value()
    result: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "python": sys.executable,
        "endpoint": http_url or "default_tushare_sdk",
        "token_present": bool(token),
        "token_masked": masked_token(token) if token else "",
        "proxy_before": before,
        "proxy_removed": list(fixed["removed"].keys()),
        "proxy_after": after,
        "requests_proxy_after": get_environ_proxies("http://api.waditu.com/dataapi/trade_cal"),
        "stock_basic_ok": False,
        "stock_basic_rows": 0,
        "trade_cal_ok": False,
        "latest_trade_date": "",
        "data_trade_date": "",
        "daily_rows": 0,
        "daily_basic_rows": 0,
        "history_20d_ok": False,
        "history_20d_rows": 0,
        "history_30d_ok": False,
        "history_30d_rows": 0,
        "probe_seconds": 0.0,
        "status": "BLOCKED",
        "message": "",
        "latest_has_daily": False,
        "latest_has_daily_basic": False,
        "permission_checks": [],
        "permission_summary": {
            "checked_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "passed_apis": [],
            "failed_apis": [],
            "all_passed": False,
        },
        "permission_categories": {},
    }
    if not token:
        result["message"] = "TUSHARE_TOKEN missing"
        return result

    started_at = time.perf_counter()
    try:
        pro = get_tushare_pro()
        stock_basic = pro.stock_basic(list_status="L", fields="ts_code,name,list_date")
        result["stock_basic_ok"] = len(stock_basic) > 0
        result["stock_basic_rows"] = int(len(stock_basic))
        today = datetime.now().strftime("%Y%m%d")
        cal = pro.trade_cal(exchange="SSE", start_date="20240101", end_date=today, is_open="1")
        result["trade_cal_ok"] = True
        latest = str(cal["cal_date"].max()) if len(cal) else ""
        result["latest_trade_date"] = latest
        if latest and len(cal):
            sorted_dates = sorted({str(x) for x in cal["cal_date"].tolist()})
            recent_dates = list(reversed(sorted_dates[-10:]))
            for trade_date in recent_dates:
                daily = pro.daily(trade_date=trade_date)
                basic = pro.daily_basic(trade_date=trade_date)
                if trade_date == latest:
                    result["latest_has_daily"] = bool(len(daily))
                    result["latest_has_daily_basic"] = bool(len(basic))
                if len(daily) or len(basic) or trade_date == latest:
                    result["data_trade_date"] = trade_date
                    result["daily_rows"] = int(len(daily))
                    result["daily_basic_rows"] = int(len(basic))
                if len(daily) and len(basic):
                    break
            history_code = "600276.SH"
            history_start = sorted_dates[-30] if len(sorted_dates) >= 30 else sorted_dates[0]
            history = pro.daily(
                ts_code=history_code,
                start_date=history_start,
                end_date=latest,
                fields="ts_code,trade_date,close,pct_chg,amount",
            )
            result["history_20d_rows"] = int(min(len(history), 20))
            result["history_30d_rows"] = int(min(len(history), 30))
            result["history_20d_ok"] = len(history) >= 20
            result["history_30d_ok"] = len(history) >= 30
            if (
                result["daily_rows"]
                and result["daily_basic_rows"]
                and result["data_trade_date"] == latest
                and result["latest_has_daily"]
                and result["latest_has_daily_basic"]
            ):
                result["status"] = "PASS"
                result["message"] = "ok"
            else:
                result["status"] = "WARN"
                result["message"] = (
                    f"latest trade date {latest} missing daily/daily_basic; "
                    f"latest complete data is {result['data_trade_date'] or '-'}"
                )

            sample_code = "600276.SH"
            permission_checks = [
                probe_api_permission("stock_basic", lambda: pro.stock_basic(list_status="L", fields="ts_code,name,list_date").head(3)),
                probe_api_permission("trade_cal", lambda: pro.trade_cal(exchange="SSE", start_date=latest, end_date=latest, is_open="1")),
                probe_api_permission("daily", lambda: pro.daily(trade_date=latest, fields="ts_code,trade_date,close,pct_chg").head(3)),
                probe_api_permission("daily_basic", lambda: pro.daily_basic(trade_date=latest, fields="ts_code,trade_date,turnover_rate,total_mv").head(3)),
                probe_api_permission("index_daily", lambda: pro.index_daily(ts_code="000001.SH", trade_date=latest, fields="ts_code,trade_date,close,pct_chg").head(3)),
                probe_api_permission("index_classify", lambda: pro.index_classify(level="L1", src="SW2021", fields="index_code,industry_name,level").head(3)),
                probe_api_permission("index_member", lambda: pro.index_member(index_code="801001.SI", fields="index_code,con_code,in_date").head(3)),
                probe_api_permission("moneyflow", lambda: pro.moneyflow(ts_code=sample_code, trade_date=latest, fields="ts_code,trade_date,buy_sm_vol,sell_sm_vol").head(3)),
                probe_api_permission("adj_factor", lambda: pro.adj_factor(ts_code=sample_code, trade_date=latest, fields="ts_code,trade_date,adj_factor").head(3)),
                probe_api_permission("income", lambda: pro.income(ts_code=sample_code, fields="ts_code,ann_date,end_date,total_revenue", limit=3)),
                probe_api_permission("fina_indicator", lambda: pro.fina_indicator(ts_code=sample_code, fields="ts_code,ann_date,end_date,roe", limit=3)),
            ]
            result["permission_checks"] = permission_checks
            result["permission_summary"] = summarize_permissions(permission_checks)
            result["permission_categories"] = build_category_summary(permission_checks)
        else:
            result["status"] = "WARN"
            result["message"] = "no open trade date returned"
    except Exception as exc:
        result["message"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    finally:
        result["probe_seconds"] = round(time.perf_counter() - started_at, 3)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def format_probe_text(result: dict[str, Any]) -> str:
    checks = result.get("permission_checks") or []
    categories = result.get("permission_categories") or {}
    lines = [
        f"状态: {result.get('status', '-')}",
        f"最新交易日: {result.get('latest_trade_date', '-')}",
        f"行情落点: {result.get('data_trade_date', '-')}",
        f"接口地址: {result.get('endpoint', '-')}",
        f"探测耗时: {result.get('probe_seconds', '-')}",
        "",
        "分类权限结论",
    ]
    if categories:
        for category in ["行情", "资金流", "财务", "板块行业", "指数", "复权", "基础资料", "其他"]:
            item = categories.get(category)
            if not item:
                continue
            lines.append(
                f"- {category}: {item.get('status')} | 通过 {item.get('passed_count', 0)}/{item.get('checked_count', 0)} | "
                f"通过接口={','.join(item.get('passed_apis', [])) or '-'} | 失败接口={','.join(item.get('failed_apis', [])) or '-'}"
            )
    else:
        lines.append("- 暂无分类结果")
    lines.extend([
        "",
        "已验证接口权限",
    ])
    if checks:
        for item in checks:
            lines.append(
                f"- {item.get('api_name')}: {item.get('status')} | rows={item.get('rows', 0)} | {item.get('message', '-')}"
            )
    else:
        lines.append("- 暂无权限矩阵")
    lines.extend(["", "完整JSON", json.dumps(result, ensure_ascii=False, indent=2)])
    return "\n".join(lines)
