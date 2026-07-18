from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.tushare_client import get_tushare_pro


BASE_DIR = ROOT / "reports" / "simulated_live_v1"
INPUT_DIR = BASE_DIR / "input"
MARKET_DATA_DIR = INPUT_DIR / "market_data"
CANDIDATE_POOL_DIR = INPUT_DIR / "candidate_pool"
REVIEW_DIR = BASE_DIR / "review"

MANUAL_CANDIDATE_POOL_FILE = CANDIDATE_POOL_DIR / "candidate_pool_MANUAL.json"
MANUAL_CANDIDATE_POOL_TEMPLATE_FILE = CANDIDATE_POOL_DIR / "candidate_pool_MANUAL_TEMPLATE.json"

INDEX_CODE_MAP = {
    "sh_index": "000001.SH",
    "sz_index": "399001.SZ",
    "cyb_index": "399006.SZ",
    "kcb50_index": "000688.SH",
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_text() -> str:
    return datetime.now().strftime("%Y%m%d")


def ensure_directories() -> None:
    for directory in [INPUT_DIR, MARKET_DATA_DIR, CANDIDATE_POOL_DIR, REVIEW_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def manual_candidate_pool_template() -> list[dict[str, Any]]:
    return [
        {
            "ts_code": "000001.SZ",
            "name": "样例候选",
            "candidate_source": "manual_watchlist",
            "sector": "",
            "reason": "manual input only",
            "max_position_ratio": 0.2,
            "notes": "not auto-selected",
        }
    ]


def ensure_manual_candidate_pool_template() -> None:
    if not MANUAL_CANDIDATE_POOL_TEMPLATE_FILE.exists():
        write_json(MANUAL_CANDIDATE_POOL_TEMPLATE_FILE, manual_candidate_pool_template())


def load_candidate_pool(candidate_pool_arg: str | None) -> tuple[list[dict[str, Any]], Path, bool]:
    if candidate_pool_arg:
        path = Path(candidate_pool_arg)
        if path.exists():
            return list(read_json(path)), path, True
        return [], path, False
    if MANUAL_CANDIDATE_POOL_FILE.exists():
        return list(read_json(MANUAL_CANDIDATE_POOL_FILE)), MANUAL_CANDIDATE_POOL_FILE, True
    ensure_manual_candidate_pool_template()
    return [], MANUAL_CANDIDATE_POOL_TEMPLATE_FILE, False


def choose_latest_completed_trade_date(open_dates: list[str]) -> str:
    if not open_dates:
        raise RuntimeError("trade_cal 未返回可用交易日")
    now_dt = datetime.now()
    today = now_dt.strftime("%Y%m%d")
    after_close_cutoff = now_dt.hour >= 18
    if today in open_dates and after_close_cutoff:
        return today
    eligible = [date for date in open_dates if date < today]
    return eligible[-1] if eligible else open_dates[-1]


def fetch_open_trade_dates(pro: Any, start_date: str, end_date: str) -> list[str]:
    calendar = pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date, is_open="1")
    if calendar is None or calendar.empty:
        return []
    dates = sorted(str(value) for value in calendar["cal_date"].astype(str).tolist())
    return dates


def resolve_trade_date(pro: Any, requested_trade_date: str | None) -> tuple[str, str, bool]:
    if requested_trade_date:
        requested_trade_date = str(requested_trade_date)
        return requested_trade_date, requested_trade_date, False
    today = datetime.now()
    start_date = (today - timedelta(days=30)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")
    open_dates = fetch_open_trade_dates(pro, start_date=start_date, end_date=end_date)
    latest_completed_trade_date = choose_latest_completed_trade_date(open_dates)
    return latest_completed_trade_date, latest_completed_trade_date, False


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def fetch_index_snapshot(pro: Any, trade_date: str) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = {
        "sh_index": None,
        "sz_index": None,
        "cyb_index": None,
        "kcb50_index": None,
        "up_count": None,
        "down_count": None,
        "total_amount": None,
        "market_state": "UNKNOWN",
    }
    context = {
        "short_term_trend": "UNKNOWN",
        "risk_appetite": "UNKNOWN",
        "volume_state": "UNKNOWN",
    }
    try:
        index_df = pro.index_daily(trade_date=trade_date)
    except Exception:
        return snapshot, context
    if index_df is None or index_df.empty:
        return snapshot, context
    for key, ts_code in INDEX_CODE_MAP.items():
        matched = index_df[index_df["ts_code"] == ts_code]
        if matched.empty:
            continue
        snapshot[key] = safe_float(matched.iloc[0].get("close"))
    return snapshot, context


def fetch_symbol_daily(pro: Any, ts_code: str, trade_date: str) -> dict[str, Any] | None:
    daily_df = pro.daily(ts_code=ts_code, start_date=trade_date, end_date=trade_date)
    if daily_df is None or daily_df.empty:
        return None
    row = daily_df.iloc[0]
    return {
        "ts_code": ts_code,
        "trade_date": str(row.get("trade_date", trade_date)),
        "open": safe_float(row.get("open")),
        "high": safe_float(row.get("high")),
        "low": safe_float(row.get("low")),
        "close": safe_float(row.get("close")),
        "pre_close": safe_float(row.get("pre_close")),
        "change": safe_float(row.get("change")),
        "pct_chg": safe_float(row.get("pct_chg")),
        "vol": safe_float(row.get("vol")),
        "amount": safe_float(row.get("amount")),
    }


def fetch_trade_date_daily_map(pro: Any, trade_date: str) -> dict[str, dict[str, Any]]:
    daily_df = pro.daily(trade_date=trade_date)
    if daily_df is None or daily_df.empty:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for _, row in daily_df.iterrows():
        ts_code = str(row.get("ts_code", "")).strip()
        if not ts_code:
            continue
        result[ts_code] = {
            "ts_code": ts_code,
            "trade_date": str(row.get("trade_date", trade_date)),
            "open": safe_float(row.get("open")),
            "high": safe_float(row.get("high")),
            "low": safe_float(row.get("low")),
            "close": safe_float(row.get("close")),
            "pre_close": safe_float(row.get("pre_close")),
            "change": safe_float(row.get("change")),
            "pct_chg": safe_float(row.get("pct_chg")),
            "vol": safe_float(row.get("vol")),
            "amount": safe_float(row.get("amount")),
        }
    return result


def fetch_candidate_quotes(
    pro: Any,
    trade_date: str,
    candidate_pool: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    loaded: list[dict[str, Any]] = []
    missing: list[str] = []
    daily_map = fetch_trade_date_daily_map(pro, trade_date)
    for item in candidate_pool:
        ts_code = str(item.get("ts_code", "")).strip()
        if not ts_code:
            continue
        row = daily_map.get(ts_code)
        if row is None:
            try:
                row = fetch_symbol_daily(pro, ts_code=ts_code, trade_date=trade_date)
            except Exception:
                row = None
        if row is None:
            missing.append(ts_code)
            continue
        row["name"] = item.get("name", "")
        row["candidate_source"] = item.get("candidate_source", "manual_watchlist")
        row["sector"] = item.get("sector", "")
        row["reason"] = item.get("reason", "")
        row["notes"] = item.get("notes", "")
        loaded.append(row)
    return loaded, missing


def build_market_data_payload(
    *,
    trade_date: str,
    latest_completed_trade_date: str,
    data_source: str,
    is_real_market_data: bool,
    market_snapshot: dict[str, Any],
    index_context: dict[str, Any],
    target_symbols_ohlc: list[dict[str, Any]],
    tushare_available: bool,
    candidate_pool_loaded: bool,
    symbols_requested: int,
    symbols_loaded: int,
    missing_symbols: list[str],
    notes: list[str],
    requested_trade_date: str | None,
    fallback_to_latest_completed_trade_date: bool,
) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "requested_trade_date": requested_trade_date or "",
        "latest_completed_trade_date": latest_completed_trade_date,
        "fallback_to_latest_completed_trade_date": fallback_to_latest_completed_trade_date,
        "data_source": data_source,
        "is_sample_data": False,
        "is_real_market_data": is_real_market_data,
        "generated_at": now_text(),
        "market_snapshot": market_snapshot,
        "index_context": index_context,
        "target_symbols_ohlc": target_symbols_ohlc,
        "data_quality": {
            "tushare_available": tushare_available,
            "candidate_pool_loaded": candidate_pool_loaded,
            "symbols_requested": symbols_requested,
            "symbols_loaded": symbols_loaded,
            "missing_symbols": missing_symbols,
            "notes": notes,
        },
        "boundary_flags": {
            "real_account_connected": False,
            "auto_trading_enabled": False,
            "full_pipeline_enabled": False,
            "news_module_enabled": False,
            "auto_selection_enabled": False,
            "trade_decision_generated": False,
        },
    }


def render_review_markdown(report: dict[str, Any]) -> str:
    lines = [f"# market_data_readonly_fetch_{report['latest_completed_trade_date']}", ""]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def update_engineering_manifest(review_report_path: Path) -> Path:
    manifest_path = REVIEW_DIR / f"simulated_live_v1_engineering_review_manifest_{today_text()}.md"
    content = "\n".join(
        [
            "# simulated_live_v1 engineering review manifest",
            "",
            "## Historical note",
            "- real market readonly stub was requested but not fully implemented: historical status before this round",
            "",
            "## Current status",
            "- dedicated real market readonly fetch script implemented: True",
            "- script: scripts/fetch_simulated_live_v1_market_data_readonly.py",
            f"- latest readonly fetch review: {review_report_path}",
            "",
            "## Boundary check",
            "- no_auto_selection: True",
            "- no_trade_decision_generated: True",
            "- official simulated_account_state preserved: True",
            "- real_account_connected: False",
            "- auto_trading_enabled: False",
            "- full_pipeline_enabled: False",
            "- news_module_enabled: False",
            "",
        ]
    )
    manifest_path.write_text(content, encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch simulated_live_v1 market data in readonly mode")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--candidate-pool", default="")
    parser.add_argument("--output-dir", default=str(MARKET_DATA_DIR))
    args = parser.parse_args()

    ensure_directories()
    ensure_manual_candidate_pool_template()

    requested_trade_date = args.trade_date.strip() or None
    candidate_pool, candidate_pool_file, candidate_pool_loaded = load_candidate_pool(args.candidate_pool or None)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tushare_available = False
    latest_completed_trade_date = requested_trade_date or today_text()
    resolved_trade_date = latest_completed_trade_date
    fallback_to_latest_completed_trade_date = False
    market_snapshot = {
        "sh_index": None,
        "sz_index": None,
        "cyb_index": None,
        "kcb50_index": None,
        "up_count": None,
        "down_count": None,
        "total_amount": None,
        "market_state": "UNKNOWN",
    }
    index_context = {
        "short_term_trend": "UNKNOWN",
        "risk_appetite": "UNKNOWN",
        "volume_state": "UNKNOWN",
    }
    target_symbols_ohlc: list[dict[str, Any]] = []
    missing_symbols: list[str] = []
    notes: list[str] = []
    data_source = "local_manual_required"
    is_real_market_data = False

    try:
        pro = get_tushare_pro(ROOT)
        tushare_available = True
        resolved_trade_date, latest_completed_trade_date, fallback_to_latest_completed_trade_date = resolve_trade_date(
            pro, requested_trade_date
        )
        market_snapshot, index_context = fetch_index_snapshot(pro, resolved_trade_date)
        symbols_requested = len([item for item in candidate_pool if str(item.get("ts_code", "")).strip()])
        target_symbols_ohlc, missing_symbols = fetch_candidate_quotes(pro, resolved_trade_date, candidate_pool)
        if target_symbols_ohlc or any(value is not None for key, value in market_snapshot.items() if key.endswith("_index")):
            data_source = "tushare_readonly"
            is_real_market_data = True
        else:
            data_source = "local_manual_required"
            is_real_market_data = False
            notes.append("Tushare 可用，但当前未取到可写入的候选股或指数行情。")
    except Exception as exc:
        symbols_requested = len([item for item in candidate_pool if str(item.get("ts_code", "")).strip()])
        notes.append(f"Tushare 不可用，已优雅降级：{type(exc).__name__}: {exc}")
        fallback_to_latest_completed_trade_date = False
    else:
        if fallback_to_latest_completed_trade_date:
            notes.append("请求日期不是已完成交易日，已回退到 latest_completed_trade_date。")
        if not candidate_pool_loaded:
            notes.append("未提供固定手工候选池，当前仅生成 MANUAL_TEMPLATE。")
        elif symbols_requested == 0:
            notes.append("固定手工候选池已读取，但 symbols_requested=0。")
        if missing_symbols:
            notes.append("部分候选股未成功加载行情。")

    market_data_payload = build_market_data_payload(
        trade_date=resolved_trade_date,
        latest_completed_trade_date=latest_completed_trade_date,
        data_source=data_source,
        is_real_market_data=is_real_market_data,
        market_snapshot=market_snapshot,
        index_context=index_context,
        target_symbols_ohlc=target_symbols_ohlc,
        tushare_available=tushare_available,
        candidate_pool_loaded=candidate_pool_loaded,
        symbols_requested=len([item for item in candidate_pool if str(item.get("ts_code", "")).strip()]),
        symbols_loaded=len(target_symbols_ohlc),
        missing_symbols=missing_symbols,
        notes=notes,
        requested_trade_date=requested_trade_date,
        fallback_to_latest_completed_trade_date=fallback_to_latest_completed_trade_date,
    )

    market_data_file_path = output_dir / f"market_data_{resolved_trade_date}.json"
    write_json(market_data_file_path, market_data_payload)

    review_report = {
        "market_data_readonly_fetch_completed": True,
        "dedicated_fetch_script_exists": True,
        "latest_completed_trade_date": latest_completed_trade_date,
        "requested_trade_date": requested_trade_date or "",
        "resolved_trade_date": resolved_trade_date,
        "fallback_to_latest_completed_trade_date": fallback_to_latest_completed_trade_date,
        "market_data_file_generated": True,
        "market_data_file_path": str(market_data_file_path),
        "data_source": data_source,
        "tushare_available": tushare_available,
        "candidate_pool_loaded": candidate_pool_loaded,
        "candidate_pool_file_used": str(candidate_pool_file),
        "symbols_requested": market_data_payload["data_quality"]["symbols_requested"],
        "symbols_loaded": market_data_payload["data_quality"]["symbols_loaded"],
        "missing_symbols": missing_symbols,
        "is_real_market_data": is_real_market_data,
        "no_auto_selection": True,
        "no_trade_decision_generated": True,
        "official_state_preserved": True,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "recommended_next_step": "connect readonly market_data_<trade_date>.json into daily report input path without generating trade decisions",
        "generated_at": now_text(),
    }

    review_json_path = REVIEW_DIR / f"market_data_readonly_fetch_{resolved_trade_date}.json"
    review_md_path = REVIEW_DIR / f"market_data_readonly_fetch_{resolved_trade_date}.md"
    write_json(review_json_path, review_report)
    review_md_path.write_text(render_review_markdown(review_report), encoding="utf-8")

    manifest_path = update_engineering_manifest(review_md_path)

    print(
        json.dumps(
            {
                "market_data_file_path": str(market_data_file_path),
                "review_json_path": str(review_json_path),
                "review_md_path": str(review_md_path),
                "manifest_path": str(manifest_path),
                "resolved_trade_date": resolved_trade_date,
                "latest_completed_trade_date": latest_completed_trade_date,
                "data_source": data_source,
                "tushare_available": tushare_available,
                "candidate_pool_loaded": candidate_pool_loaded,
                "symbols_requested": review_report["symbols_requested"],
                "symbols_loaded": review_report["symbols_loaded"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
