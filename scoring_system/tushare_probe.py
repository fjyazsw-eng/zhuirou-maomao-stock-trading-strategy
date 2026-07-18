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
LATEST_SUCCESS_JSON = REPORT_DIR / "latest_tushare_success_status.json"

API_CATEGORY_MAP = {
    "stock_basic": "基础资料",
    "trade_cal": "基础资料",
    "daily": "行情",
    "daily_basic": "行情",
    "index_daily": "指数",
    "index_weight": "指数",
    "index_classify": "板块行业",
    "index_member_all": "板块行业",
    "ci_index_member": "板块行业",
    "moneyflow": "资金流",
    "adj_factor": "复权",
    "stock_company": "公司基本面",
    "income": "财务",
    "balancesheet": "财务",
    "cashflow": "财务",
    "fina_indicator": "财务",
    "forecast": "业绩预告",
    "express": "业绩快报",
    "anns_d": "公告新闻",
    "major_news": "公告新闻",
    "news": "公告新闻",
    "realtime_quote": "实时价格",
    "stk_mins": "实时价格",
}

CORE_REQUIRED_APIS = {
    "stock_basic",
    "trade_cal",
    "daily",
    "daily_basic",
    "index_daily",
    "index_classify",
    "index_member_all",
    "ci_index_member",
}

FEATURE_GROUPS = {
    "基础资料": ["stock_basic", "trade_cal"],
    "行情": ["daily", "daily_basic"],
    "指数": ["index_daily", "index_weight"],
    "行业成分": ["index_classify", "index_member_all", "ci_index_member"],
    "资金流": ["moneyflow"],
    "复权": ["adj_factor"],
    "公司基本面": ["stock_company", "income", "balancesheet", "cashflow", "fina_indicator"],
    "业绩预告快报": ["forecast", "express"],
    "公告新闻": ["anns_d", "major_news", "news"],
    "实时价格": ["realtime_quote", "stk_mins"],
}


def masked_token(token: str) -> str:
    if len(token) <= 6:
        return "***"
    return f"{token[:3]}***{token[-3:]}"


def probe_api_permission(name: str, fetcher, critical: bool | None = None) -> dict[str, Any]:
    started_at = time.perf_counter()
    is_critical = name in CORE_REQUIRED_APIS if critical is None else critical
    try:
        df = fetcher()
        rows = int(len(df)) if df is not None else 0
        return {
            "api_name": name,
            "ok": True,
            "critical": is_critical,
            "rows": rows,
            "status": "PASS" if rows > 0 else "EMPTY",
            "message": "ok" if rows > 0 else "empty_result",
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        }
    except Exception as exc:
        return {
            "api_name": name,
            "ok": False,
            "critical": is_critical,
            "rows": 0,
            "status": "FAIL",
            "message": f"{type(exc).__name__}: {str(exc)[:180]}",
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        }


def summarize_permissions(permission_checks: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [item["api_name"] for item in permission_checks if item.get("ok")]
    failed = [item["api_name"] for item in permission_checks if not item.get("ok")]
    critical = [item for item in permission_checks if item.get("critical")]
    critical_failed = [item["api_name"] for item in critical if not item.get("ok")]
    return {
        "checked_count": len(permission_checks),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "passed_apis": passed,
        "failed_apis": failed,
        "critical_checked_count": len(critical),
        "critical_failed_count": len(critical_failed),
        "critical_failed_apis": critical_failed,
        "all_passed": len(failed) == 0,
        "core_passed": len(critical_failed) == 0 and bool(critical),
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


def build_feature_summary(permission_checks: list[dict[str, Any]]) -> dict[str, Any]:
    checks = {str(item.get("api_name", "")): item for item in permission_checks}
    features: dict[str, Any] = {}
    for feature_name, api_names in FEATURE_GROUPS.items():
        items = [checks[name] for name in api_names if name in checks]
        passed = [item for item in items if item.get("ok")]
        failed = [item for item in items if not item.get("ok")]
        empty = [item for item in items if item.get("status") == "EMPTY"]
        if not items:
            status = "未检测"
        elif failed:
            status = "FAIL"
        elif empty:
            status = "WARN"
        else:
            status = "PASS"
        features[feature_name] = {
            "feature": feature_name,
            "status": status,
            "checked_count": len(items),
            "passed_count": len(passed),
            "failed_count": len(failed),
            "empty_count": len(empty),
            "apis": api_names,
            "passed_apis": [str(item.get("api_name")) for item in passed],
            "failed_apis": [str(item.get("api_name")) for item in failed],
            "empty_apis": [str(item.get("api_name")) for item in empty],
        }
    return features


def classify_probe_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if "winerror 10013" in lowered or "以一种访问权限不允许" in text:
        return "LOCAL_NETWORK_PERMISSION_BLOCKED"
    if "proxyerror" in lowered or "proxy" in lowered:
        return "PROXY_ERROR"
    if "http_429" in lowered or "并发请求过多" in text or "rate limit" in lowered or "too many requests" in lowered:
        return "RATE_LIMITED"
    if "timed out" in lowered or "read timed out" in lowered or "timeout" in lowered:
        return "TIMEOUT"
    if "name resolution" in lowered or "getaddrinfo" in lowered or "dns" in lowered:
        return "DNS_ERROR"
    if "token" in lowered or "token不对" in text:
        return "TOKEN_ERROR"
    return "UNKNOWN_ERROR"


def load_last_success() -> dict[str, Any] | None:
    if not LATEST_SUCCESS_JSON.exists():
        return None
    try:
        return json.loads(LATEST_SUCCESS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None


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
        "error_category": "",
        "connection_ok": False,
        "last_success": None,
        "latest_has_daily": False,
        "latest_has_daily_basic": False,
        "permission_checks": [],
        "permission_summary": {
            "checked_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "passed_apis": [],
            "failed_apis": [],
            "critical_checked_count": 0,
            "critical_failed_count": 0,
            "critical_failed_apis": [],
            "all_passed": False,
            "core_passed": False,
        },
        "permission_categories": {},
        "feature_summary": {},
    }
    if not token:
        result["message"] = "TUSHARE_TOKEN missing"
        result["error_category"] = "TOKEN_ERROR"
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        LATEST_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    started_at = time.perf_counter()
    try:
        pro = get_tushare_pro()
        stock_basic = pro.stock_basic(list_status="L", fields="ts_code,name,list_date")
        result["connection_ok"] = True
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
                probe_api_permission("index_weight", lambda: pro.index_weight(index_code="000300.SH", start_date=sorted_dates[-10], end_date=latest, fields="index_code,con_code,trade_date,weight").head(3), critical=False),
                probe_api_permission("index_classify", lambda: pro.index_classify(level="L1", src="SW2021", fields="index_code,industry_name,level").head(3)),
                probe_api_permission("index_member_all", lambda: pro.query("index_member_all", ts_code="600276.SH", is_new="Y", fields="l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,in_date,out_date,is_new").head(3)),
                probe_api_permission("ci_index_member", lambda: pro.query("ci_index_member", ts_code="600276.SH", is_new="Y", fields="l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,in_date,out_date,is_new").head(3)),
                probe_api_permission("moneyflow", lambda: pro.moneyflow(ts_code=sample_code, trade_date=latest, fields="ts_code,trade_date,buy_sm_vol,sell_sm_vol").head(3)),
                probe_api_permission("adj_factor", lambda: pro.adj_factor(ts_code=sample_code, trade_date=latest, fields="ts_code,trade_date,adj_factor").head(3)),
                probe_api_permission("stock_company", lambda: pro.stock_company(ts_code=sample_code, fields="ts_code,chairman,manager,secretary,reg_capital,setup_date,province,city,main_business").head(3), critical=False),
                probe_api_permission("income", lambda: pro.income(ts_code=sample_code, fields="ts_code,ann_date,end_date,total_revenue", limit=3)),
                probe_api_permission("balancesheet", lambda: pro.balancesheet(ts_code=sample_code, fields="ts_code,ann_date,end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int", limit=3), critical=False),
                probe_api_permission("cashflow", lambda: pro.cashflow(ts_code=sample_code, fields="ts_code,ann_date,end_date,n_cashflow_act,n_cashflow_inv_act,n_cash_flows_fnc_act", limit=3), critical=False),
                probe_api_permission("fina_indicator", lambda: pro.fina_indicator(ts_code=sample_code, fields="ts_code,ann_date,end_date,roe", limit=3)),
                probe_api_permission("forecast", lambda: pro.forecast(ts_code=sample_code, fields="ts_code,ann_date,end_date,type,p_change_min,p_change_max,net_profit_min,net_profit_max", limit=3), critical=False),
                probe_api_permission("express", lambda: pro.express(ts_code=sample_code, fields="ts_code,ann_date,end_date,revenue,total_profit,n_income", limit=3), critical=False),
                probe_api_permission("anns_d", lambda: pro.anns_d(ts_code=sample_code, start_date=latest, end_date=latest, fields="ts_code,ann_date,title,url", limit=3), critical=False),
                probe_api_permission("major_news", lambda: pro.major_news(src="sina", start_date=datetime.now().strftime("%Y-%m-%d"), end_date=datetime.now().strftime("%Y-%m-%d"), fields="title,content,pub_time,src", limit=3), critical=False),
                probe_api_permission("news", lambda: pro.news(src="sina", start_date=f"{datetime.now().strftime('%Y-%m-%d')} 09:00:00", end_date=f"{datetime.now().strftime('%Y-%m-%d')} 23:59:59", fields="datetime,content,title,channels", limit=3), critical=False),
                probe_api_permission("realtime_quote", lambda: pro.realtime_quote(ts_code=sample_code).head(3), critical=False),
                probe_api_permission("stk_mins", lambda: pro.stk_mins(ts_code=sample_code, start_date=f"{latest[:4]}-{latest[4:6]}-{latest[6:]} 09:30:00", end_date=f"{latest[:4]}-{latest[4:6]}-{latest[6:]} 15:00:00", freq="1min", fields="ts_code,trade_time,open,close,high,low,vol,amount", limit=3), critical=False),
            ]
            result["permission_checks"] = permission_checks
            result["permission_summary"] = summarize_permissions(permission_checks)
            result["permission_categories"] = build_category_summary(permission_checks)
            result["feature_summary"] = build_feature_summary(permission_checks)
            critical_failed = result["permission_summary"]["critical_failed_apis"]
            if critical_failed:
                result["status"] = "WARN" if result["daily_rows"] and result["daily_basic_rows"] else "BLOCKED"
                result["message"] = f"核心接口异常: {','.join(critical_failed)}"
        else:
            result["status"] = "WARN"
            result["message"] = "no open trade date returned"
    except Exception as exc:
        result["error_category"] = classify_probe_error(exc)
        result["message"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        result["last_success"] = load_last_success()
    finally:
        result["probe_seconds"] = round(time.perf_counter() - started_at, 3)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.get("status") == "PASS":
        LATEST_SUCCESS_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
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
        f"连接分类: {result.get('error_category') or ('OK' if result.get('connection_ok') else '-')}",
        "",
        "分类权限结论",
    ]
    last_success = result.get("last_success") or {}
    if result.get("status") == "BLOCKED" and last_success:
        lines.extend([
            "",
            "最近一次成功探测",
            f"- 时间: {last_success.get('timestamp', '-')}",
            f"- 状态: {last_success.get('status', '-')}",
            f"- 最新交易日: {last_success.get('latest_trade_date', '-')}",
        ])
    if categories:
        for category in ["行情", "实时价格", "资金流", "公司基本面", "财务", "业绩预告", "业绩快报", "公告新闻", "板块行业", "指数", "复权", "基础资料", "其他"]:
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
        "功能情况",
    ])
    features = result.get("feature_summary") or {}
    if features:
        for feature in ["基础资料", "行情", "指数", "行业成分", "资金流", "复权", "公司基本面", "业绩预告快报", "公告新闻", "实时价格"]:
            item = features.get(feature)
            if not item:
                continue
            lines.append(
                f"- {feature}: {item.get('status')} | 通过 {item.get('passed_count', 0)}/{item.get('checked_count', 0)} | "
                f"可用={','.join(item.get('passed_apis', [])) or '-'} | 异常={','.join(item.get('failed_apis', [])) or '-'} | 空返回={','.join(item.get('empty_apis', [])) or '-'}"
            )
    else:
        lines.append("- 暂无功能情况")
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
