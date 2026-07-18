from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.tushare_client import get_tushare_pro


REVIEW_DIR = ROOT / "reports" / "simulated_live_v1" / "review"
INPUT_MARKET_DATA_DIR = ROOT / "reports" / "simulated_live_v1" / "input" / "market_data"
HANDOFF_PATH = REVIEW_DIR / "stock_selection_to_trading_handoff_20260706.json"
OUTPUT_QUOTES_PATH = INPUT_MARKET_DATA_DIR / "handoff_latest_readonly_quotes_20260706.json"
OUTPUT_REVIEW_JSON_PATH = REVIEW_DIR / "handoff_latest_readonly_quotes_fetch_20260706.json"
OUTPUT_REVIEW_MD_PATH = REVIEW_DIR / "handoff_latest_readonly_quotes_fetch_20260706.md"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_trade_date(path: Path) -> str:
    match = re.search(r"_(\d{8})\.json$", path.name)
    return match.group(1) if match else ""


def resolve_handoff_path(review_dir: Path = REVIEW_DIR, handoff_path: Path | None = None) -> Path:
    if handoff_path is not None:
        return handoff_path
    candidates = sorted(
        review_dir.glob("stock_selection_to_trading_handoff_*.json"),
        key=lambda path: (extract_trade_date(path), path.stat().st_mtime),
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return HANDOFF_PATH


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def load_handoff_symbols(handoff_path: Path) -> list[dict[str, Any]]:
    handoff = read_json(handoff_path)
    return list(handoff["handoff_to_trading_model"])


def preferred_trade_date_from_handoff(handoff_path: Path, explicit_preferred_trade_date: str) -> str:
    if explicit_preferred_trade_date:
        return str(explicit_preferred_trade_date)
    handoff = read_json(handoff_path)
    return str(handoff.get("latest_completed_trade_date") or "")


def fetch_open_trade_dates(pro: Any, start_date: str, end_date: str) -> list[str]:
    calendar = pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date, is_open="1")
    if calendar is None or calendar.empty:
        return []
    return sorted(str(value) for value in calendar["cal_date"].astype(str).tolist())


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


def resolve_trade_date(pro: Any, preferred_trade_date: str) -> tuple[str, str, bool]:
    if preferred_trade_date:
        preferred_trade_date = str(preferred_trade_date)
        return preferred_trade_date, preferred_trade_date, False
    today = datetime.now()
    start_date = (today - timedelta(days=30)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")
    open_dates = fetch_open_trade_dates(pro, start_date=start_date, end_date=end_date)
    latest_completed_trade_date = choose_latest_completed_trade_date(open_dates)
    return latest_completed_trade_date, latest_completed_trade_date, False


def fetch_daily_row(pro: Any, ts_code: str, trade_date: str) -> dict[str, Any] | None:
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
        "price_adjustment_mode": "raw",
        "amount_unit": "thousand CNY",
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
            "price_adjustment_mode": "raw",
            "amount_unit": "thousand CNY",
        }
    return result


def fetch_history_rows(pro: Any, ts_code: str, end_date: str, bars: int = 30) -> list[dict[str, Any]]:
    start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=60)).strftime("%Y%m%d")
    daily_df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if daily_df is None or daily_df.empty:
        return []
    daily_df = daily_df.sort_values("trade_date").tail(bars)
    history: list[dict[str, Any]] = []
    closes: list[float] = []
    vols: list[float] = []
    highs: list[float] = []
    for _, row in daily_df.iterrows():
        close = safe_float(row.get("close"))
        vol = safe_float(row.get("vol"))
        high = safe_float(row.get("high"))
        if close is not None:
            closes.append(close)
        if vol is not None:
            vols.append(vol)
        if high is not None:
            highs.append(high)
        history.append(
            {
                "trade_date": str(row.get("trade_date")),
                "open": safe_float(row.get("open")),
                "high": high,
                "low": safe_float(row.get("low")),
                "close": close,
                "pre_close": safe_float(row.get("pre_close")),
                "pct_chg": safe_float(row.get("pct_chg")),
                "vol": vol,
                "amount": safe_float(row.get("amount")),
            }
        )
    return history


def build_payload(
    handoff_rows: list[dict[str, Any]],
    trade_date: str,
    latest_completed_trade_date: str,
    fallback_to_latest_completed_trade_date: bool,
    loaded_rows: list[dict[str, Any]],
    missing_symbols: list[str],
) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "requested_trade_date": trade_date,
        "latest_completed_trade_date": latest_completed_trade_date,
        "fallback_to_latest_completed_trade_date": fallback_to_latest_completed_trade_date,
        "data_source": "tushare_readonly",
        "is_sample_data": False,
        "is_real_market_data": True,
        "generated_at": now_text(),
        "scope": {
            "source": "stock_selection_to_trading_handoff",
            "scope_size": len(handoff_rows),
            "allowed_symbols": [row["ts_code"] for row in handoff_rows],
            "auto_selection_enabled": False,
        },
        "target_symbols_ohlc": loaded_rows,
        "data_quality": {
            "tushare_available": True,
            "symbols_requested": len(handoff_rows),
            "symbols_loaded": len(loaded_rows),
            "missing_symbols": missing_symbols,
            "price_adjustment_mode": "raw",
            "amount_unit": "thousand CNY",
            "notes": [],
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


def build_failure_review(handoff_path: Path, requested_trade_date: str, error: Exception) -> dict[str, Any]:
    return {
        "handoff_latest_readonly_quotes_fetch_completed": False,
        "handoff_path": str(handoff_path),
        "requested_trade_date": requested_trade_date,
        "latest_completed_trade_date": requested_trade_date,
        "resolved_trade_date": requested_trade_date,
        "readonly_quote_fetch_attempted": True,
        "readonly_quote_loaded_symbols": [],
        "missing_data_symbols": [],
        "data_quality": {
            "tushare_available": False,
            "notes": ["数据异常，优先怀疑 Tushare 接入或返回问题。"],
        },
        "message": f"数据异常，优先怀疑 Tushare 接入或返回问题。错误：{type(error).__name__}: {error}",
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "generated_at": now_text(),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# handoff_latest_readonly_quotes_fetch_{report['latest_completed_trade_date']}", ""]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch latest readonly quotes for handoff five-stock scope")
    parser.add_argument("--handoff-path", default="")
    parser.add_argument("--preferred-trade-date", default="")
    parser.add_argument("--output-path", default="")
    parser.add_argument("--review-json-path", default="")
    parser.add_argument("--review-md-path", default="")
    args = parser.parse_args()

    handoff_path = resolve_handoff_path(handoff_path=Path(args.handoff_path) if args.handoff_path else None)

    handoff_rows = load_handoff_symbols(handoff_path)
    pro = get_tushare_pro(ROOT)
    preferred_trade_date = preferred_trade_date_from_handoff(handoff_path, args.preferred_trade_date)
    resolved_trade_date, latest_completed_trade_date, fallback = resolve_trade_date(pro, preferred_trade_date)
    output_path = Path(args.output_path) if args.output_path else INPUT_MARKET_DATA_DIR / f"handoff_latest_readonly_quotes_{resolved_trade_date}.json"
    review_json_path = Path(args.review_json_path) if args.review_json_path else REVIEW_DIR / f"handoff_latest_readonly_quotes_fetch_{resolved_trade_date}.json"
    review_md_path = Path(args.review_md_path) if args.review_md_path else REVIEW_DIR / f"handoff_latest_readonly_quotes_fetch_{resolved_trade_date}.md"

    loaded_rows: list[dict[str, Any]] = []
    missing_symbols: list[str] = []
    try:
        daily_map = fetch_trade_date_daily_map(pro, resolved_trade_date)
        for item in handoff_rows:
            ts_code = str(item["ts_code"])
            quote = daily_map.get(ts_code)
            if quote is None:
                quote = fetch_daily_row(pro, ts_code, resolved_trade_date)
            if quote is None:
                missing_symbols.append(ts_code)
                continue
            quote["name"] = item.get("name", "")
            quote["sector"] = item.get("sector", "")
            quote["candidate_action"] = item.get("candidate_action", "")
            quote["can_trading_model_simulate_buy"] = bool(item.get("can_trading_model_simulate_buy", False))
            quote["can_trading_model_watch"] = bool(item.get("can_trading_model_watch", False))
            quote["history_daily_raw"] = fetch_history_rows(pro, ts_code, resolved_trade_date, bars=30)
            loaded_rows.append(quote)
    except Exception as exc:
        failure = build_failure_review(handoff_path, resolved_trade_date, exc)
        write_json(review_json_path, failure)
        review_md_path.write_text(render_markdown(failure), encoding="utf-8")
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 2

    payload = build_payload(
        handoff_rows=handoff_rows,
        trade_date=resolved_trade_date,
        latest_completed_trade_date=latest_completed_trade_date,
        fallback_to_latest_completed_trade_date=fallback,
        loaded_rows=loaded_rows,
        missing_symbols=missing_symbols,
    )
    write_json(output_path, payload)

    review = {
        "handoff_latest_readonly_quotes_fetch_completed": True,
        "handoff_path": str(handoff_path),
        "requested_trade_date": args.preferred_trade_date,
        "latest_completed_trade_date": latest_completed_trade_date,
        "resolved_trade_date": resolved_trade_date,
        "fallback_to_latest_completed_trade_date": fallback,
        "readonly_quote_fetch_attempted": True,
        "readonly_quote_output_path": str(output_path),
        "readonly_quote_loaded_symbols": [row["ts_code"] for row in loaded_rows],
        "missing_data_symbols": missing_symbols,
        "symbols_requested": len(handoff_rows),
        "symbols_loaded": len(loaded_rows),
        "price_adjustment_mode": "raw",
        "amount_unit": "thousand CNY",
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "generated_at": now_text(),
    }
    write_json(review_json_path, review)
    review_md_path.write_text(render_markdown(review), encoding="utf-8")

    print(
        json.dumps(
            {
                "readonly_quote_output_path": str(output_path),
                "review_json_path": str(review_json_path),
                "review_md_path": str(review_md_path),
                "latest_completed_trade_date": latest_completed_trade_date,
                "resolved_trade_date": resolved_trade_date,
                "readonly_quote_loaded_symbols": review["readonly_quote_loaded_symbols"],
                "missing_data_symbols": missing_symbols,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
