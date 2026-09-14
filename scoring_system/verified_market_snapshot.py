from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scoring_system.tushare_client import get_tushare_pro
from scoring_system.tushare_freshness_agent import evaluate_freshness


ROOT = Path(__file__).resolve().parents[1]
FAST_CONTEXT_DIR = ROOT / "reports" / "fast_context"

CORE_INDEX_NAMES = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000688.SH": "科创50",
}


def _as_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _pct_column(frame: pd.DataFrame) -> str:
    if "pct_chg" in frame.columns:
        return "pct_chg"
    if "pct_change" in frame.columns:
        return "pct_change"
    return "pct_chg"


def market_state(avg_index_pct_chg: float | None, up_ratio: float | None) -> str:
    if avg_index_pct_chg is None or up_ratio is None:
        return "待确认"
    if avg_index_pct_chg <= -3.0 or up_ratio <= 0.2:
        return "极弱"
    if avg_index_pct_chg <= -1.0 or up_ratio <= 0.35:
        return "弱"
    if avg_index_pct_chg >= 1.0 and up_ratio >= 0.55:
        return "强"
    return "震荡"


def _market_breadth(daily: pd.DataFrame) -> dict[str, Any]:
    pct = pd.to_numeric(daily.get("pct_chg"), errors="coerce")
    count = int(pct.notna().sum())
    up = int((pct > 0).sum())
    down = int((pct < 0).sum())
    flat = int((pct == 0).sum())
    return {
        "up": up,
        "down": down,
        "flat": flat,
        "count": count,
        "up_ratio": up / count if count else None,
    }


def _core_indexes(index_daily: pd.DataFrame) -> tuple[list[dict[str, Any]], float | None]:
    rows: list[dict[str, Any]] = []
    frame = index_daily[index_daily["ts_code"].astype(str).isin(CORE_INDEX_NAMES)].copy()
    for _, row in frame.iterrows():
        rows.append(
            {
                "ts_code": str(row.get("ts_code", "")),
                "name": CORE_INDEX_NAMES.get(str(row.get("ts_code", "")), str(row.get("ts_code", ""))),
                "close": _as_float(row.get("close")),
                "pct_chg": _as_float(row.get("pct_chg")),
                "amount": _as_float(row.get("amount")),
            }
        )
    pct_values = [item["pct_chg"] for item in rows if item["pct_chg"] is not None]
    avg = sum(pct_values) / len(pct_values) if pct_values else None
    return rows, avg


def _top_sw_sectors(sw_daily: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    if sw_daily.empty:
        return []
    pct_col = _pct_column(sw_daily)
    name_col = "name" if "name" in sw_daily.columns else "industry_name"
    code_col = "ts_code" if "ts_code" in sw_daily.columns else "index_code"
    frame = sw_daily.copy()
    frame[pct_col] = pd.to_numeric(frame[pct_col], errors="coerce")
    if "amount" in frame.columns:
        frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    else:
        frame["amount"] = None
    frame = frame.sort_values([pct_col, "amount"], ascending=[False, False], na_position="last")
    result = []
    for _, row in frame.head(limit).iterrows():
        result.append(
            {
                "code": str(row.get(code_col, "")),
                "name": str(row.get(name_col, row.get(code_col, ""))),
                "pct_chg": _as_float(row.get(pct_col)),
                "amount": _as_float(row.get("amount")),
            }
        )
    return result


def build_verified_market_snapshot(
    pro: Any | None = None,
    freshness: dict[str, Any] | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    if pro is None:
        pro = get_tushare_pro()
    if freshness is None:
        freshness = evaluate_freshness(pro=pro, today=today)

    trade_date = str(freshness.get("latest_complete_trade_date") or "")
    snapshot: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "snapshot_status": "BLOCKED",
        "trade_date": trade_date,
        "data_source": "hithink-finance",
        "freshness": freshness,
        "formal_recommendation_allowed": bool(freshness.get("formal_recommendation_allowed")),
        "data_is_latest_complete": bool(freshness.get("data_is_latest_complete")),
        "required_api_rows": dict(freshness.get("required_api_rows") or {}),
        "market": {},
        "top_sw_sectors": [],
        "notes": [],
    }
    if not snapshot["formal_recommendation_allowed"] or not trade_date:
        snapshot["notes"].append("freshness gate failed; formal recommendation is blocked")
        return snapshot

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

    breadth = _market_breadth(daily)
    indexes, avg_index = _core_indexes(index_daily)
    snapshot["snapshot_status"] = "PASS"
    snapshot["market"] = {
        "state": market_state(avg_index, breadth.get("up_ratio")),
        "breadth": breadth,
        "core_indexes": indexes,
        "core_index_avg_pct_chg": avg_index,
        "daily_basic_rows": int(len(daily_basic)),
    }
    snapshot["top_sw_sectors"] = _top_sw_sectors(sw_daily)
    snapshot["loaded_rows"] = {
        "daily": int(len(daily)),
        "daily_basic": int(len(daily_basic)),
        "index_daily": int(len(index_daily)),
        "sw_daily": int(len(sw_daily)),
    }
    return snapshot


def write_verified_market_snapshot(
    snapshot: dict[str, Any],
    output_dir: Path = FAST_CONTEXT_DIR,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trade_date = str(snapshot.get("trade_date") or "unknown")
    dated = output_dir / f"verified_market_snapshot_{trade_date}.json"
    latest = output_dir / "latest_verified_market_snapshot.json"
    text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    dated.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    return {"dated": dated, "latest": latest}
