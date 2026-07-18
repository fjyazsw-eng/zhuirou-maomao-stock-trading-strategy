"""Build major index weather evidence table.

This module prepares 20-trading-day index evidence for style judgment. It uses
local caches first, only calls Tushare when an index roster or index daily cache
is incomplete, and never prints or stores the token.
"""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd
import tushare as ts

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
BASIC_DIR = PROJECT_ROOT / "data" / "basic"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"

ANALYSIS_DATE = "20260630"
INDEX_DAILY_FIELDS = ["ts_code", "trade_date", "close", "open", "high", "low", "pre_close", "change", "pct_chg", "vol", "amount"]
INDEX_BASIC_FIELDS = ["ts_code", "name", "market", "publisher", "category", "base_date", "list_date"]
INDEX_TARGETS = [
    {"name": "上证指数", "markets": ["SSE"]},
    {"name": "深证成指", "markets": ["SZSE"]},
    {"name": "创业板指", "markets": ["SZSE"]},
    {"name": "科创50", "markets": ["SSE"]},
    {"name": "沪深300", "markets": ["SSE", "CSI"]},
    {"name": "中证1000", "markets": ["SSE", "CSI"]},
    {"name": "中证2000", "markets": ["CSI", "SSE"]},
]
MARKET_ROSTER_FILES = {
    "SSE": BASIC_DIR / "index_basic_SSE.csv",
    "SZSE": BASIC_DIR / "index_basic_SZSE.csv",
    "CSI": BASIC_DIR / "index_basic_CSI.csv",
}


@dataclass
class IndexResolveResult:
    name: str
    ts_code: str | None
    status: str
    roster_path: str


def read_csv_safe(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"ts_code": "string", "trade_date": "string", "list_date": "string"})


def complete_csv(path: Path, fields: list[str], min_rows: int = 1) -> tuple[bool, pd.DataFrame | None]:
    if not path.exists():
        return False, None
    try:
        df = read_csv_safe(path)
    except Exception:
        return False, None
    missing = [field for field in fields if field not in df.columns]
    return (not missing and len(df) >= min_rows), df


def get_pro() -> object:
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 不存在")
    return ts.pro_api(token)


def load_or_fetch_index_basic(market: str, pro: object, sleep_seconds: float = 1.5) -> pd.DataFrame:
    path = MARKET_ROSTER_FILES[market]
    complete, df = complete_csv(path, INDEX_BASIC_FIELDS)
    if complete and df is not None:
        return df
    time.sleep(sleep_seconds)
    df = pro.index_basic(market=market, fields=",".join(INDEX_BASIC_FIELDS))
    BASIC_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df


def resolve_indices(pro: object, sleep_seconds: float = 1.5) -> list[IndexResolveResult]:
    cache: dict[str, pd.DataFrame] = {}
    results: list[IndexResolveResult] = []
    for target in INDEX_TARGETS:
        found_code = None
        found_path = ""
        covered = False
        for market in target["markets"]:
            if market not in cache:
                cache[market] = load_or_fetch_index_basic(market, pro, sleep_seconds=sleep_seconds)
            df = cache[market]
            matches = df[df["name"].astype(str) == target["name"]] if "name" in df.columns else pd.DataFrame()
            if len(matches) > 0:
                found_code = str(matches.iloc[0]["ts_code"])
                found_path = str(MARKET_ROSTER_FILES[market])
                covered = True
                break
        results.append(
            IndexResolveResult(
                name=str(target["name"]),
                ts_code=found_code,
                status="已取得" if covered else "当前指数名册未覆盖",
                roster_path=found_path,
            )
        )
    return results


def index_cache_path(ts_code_value: str, end_date: str) -> Path:
    safe = ts_code_value.replace(".", "_")
    return RAW_DIR / f"index_daily_{safe}_{end_date}_20d.csv"


def load_or_fetch_index_daily(ts_code_value: str, end_date: str, pro: object, sleep_seconds: float = 1.5) -> pd.DataFrame:
    path = index_cache_path(ts_code_value, end_date)
    complete, df = complete_csv(path, INDEX_DAILY_FIELDS, min_rows=20)
    if complete and df is not None:
        return df.sort_values("trade_date", ascending=False).head(20).copy()
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    start_date = (end_dt - timedelta(days=45)).strftime("%Y%m%d")
    time.sleep(sleep_seconds)
    df = pro.index_daily(ts_code=ts_code_value, start_date=start_date, end_date=end_date, fields=",".join(INDEX_DAILY_FIELDS))
    df = df.sort_values("trade_date", ascending=False).head(20).copy()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df


def pct_return(df_desc: pd.DataFrame, days: int) -> float | None:
    if len(df_desc) < days:
        return None
    current = float(df_desc.iloc[0]["close"])
    base = float(df_desc.iloc[days - 1]["pre_close"])
    if base == 0:
        return None
    return (current / base - 1) * 100


def summarize_index(name: str, ts_code_value: str, df_desc: pd.DataFrame) -> dict[str, object]:
    if df_desc.empty:
        raise ValueError(f"{name} 无指数日线数据")
    current_close = float(df_desc.iloc[0]["close"])
    ordered_asc = df_desc.sort_values("trade_date", ascending=True)
    ma5 = float(ordered_asc["close"].tail(5).mean()) if len(ordered_asc) >= 5 else float("nan")
    ma10 = float(ordered_asc["close"].tail(10).mean()) if len(ordered_asc) >= 10 else float("nan")
    ma20 = float(ordered_asc["close"].tail(20).mean()) if len(ordered_asc) >= 20 else float("nan")
    return {
        "name": name,
        "ts_code": ts_code_value,
        "trade_date": str(df_desc.iloc[0]["trade_date"]),
        "close": current_close,
        "return_1d_pct": pct_return(df_desc, 1),
        "return_3d_pct": pct_return(df_desc, 3),
        "return_5d_pct": pct_return(df_desc, 5),
        "return_20d_pct": pct_return(df_desc, 20),
        "amount_5d_avg": float(df_desc.head(5)["amount"].mean()) if len(df_desc) >= 5 else None,
        "above_ma5": bool(current_close > ma5) if pd.notna(ma5) else False,
        "above_ma10": bool(current_close > ma10) if pd.notna(ma10) else False,
        "above_ma20": bool(current_close > ma20) if pd.notna(ma20) else False,
        "rows": len(df_desc),
        "cache_path": str(index_cache_path(ts_code_value, ANALYSIS_DATE)),
    }


def style_judgment(summary: pd.DataFrame) -> tuple[str, list[str]]:
    def row(name: str):
        matched = summary[summary["name"] == name]
        return matched.iloc[0] if len(matched) else None

    hs300 = row("沪深300")
    zz1000 = row("中证1000")
    zz2000 = row("中证2000")
    cyb = row("创业板指")
    kc50 = row("科创50")
    sz = row("深证成指")

    reasons: list[str] = []
    large_score = float(hs300["return_5d_pct"]) if hs300 is not None and pd.notna(hs300["return_5d_pct"]) else 0.0
    small_values = [float(x["return_5d_pct"]) for x in [zz1000, zz2000] if x is not None and pd.notna(x["return_5d_pct"])]
    tech_values = [float(x["return_5d_pct"]) for x in [cyb, kc50, sz] if x is not None and pd.notna(x["return_5d_pct"])]
    small_score = sum(small_values) / len(small_values) if small_values else 0.0
    tech_score = sum(tech_values) / len(tech_values) if tech_values else 0.0
    reasons.append(f"大盘代表沪深300近5日涨跌幅{large_score:.2f}%")
    reasons.append(f"小盘代表中证1000/中证2000近5日均值{small_score:.2f}%")
    reasons.append(f"科技成长代表创业板/科创50/深成指近5日均值{tech_score:.2f}%")
    best = max([("大盘", large_score), ("小盘", small_score), ("科技成长", tech_score)], key=lambda item: item[1])
    return f"当前市场风格更偏向{best[0]}，依据是该组近5日表现相对更强。", reasons


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "无"
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in df.itertuples(index=False, name=None):
        vals = []
        for value in row:
            if isinstance(value, float):
                vals.append(f"{value:.4f}")
            else:
                vals.append(str(value))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def run(end_date: str = ANALYSIS_DATE, sleep_seconds: float = 1.5) -> dict[str, object]:
    pro = get_pro()
    resolved = resolve_indices(pro, sleep_seconds=sleep_seconds)
    summaries: list[dict[str, object]] = []
    problems: list[str] = []
    for item in resolved:
        if not item.ts_code:
            problems.append(f"{item.name}: {item.status}")
            continue
        try:
            df = load_or_fetch_index_daily(item.ts_code, end_date, pro, sleep_seconds=sleep_seconds)
            if len(df) < 20:
                problems.append(f"{item.name}: 仅取得{len(df)}行指数日线，不足20行")
            summaries.append(summarize_index(item.name, item.ts_code, df))
        except Exception as exc:
            problems.append(f"{item.name}: {exc}")
    summary_df = pd.DataFrame(summaries)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = PROCESSED_DIR / f"major_index_weather_{end_date}.csv"
    out_report = REPORTS_DIR / f"major_index_weather_{end_date}.md"
    summary_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    judgment, reasons = style_judgment(summary_df) if not summary_df.empty else ("指数数据不足，暂无法判断风格。", [])
    report_lines = [
        f"# 主要指数天气表 {end_date}",
        "",
        "## 指数总表",
        markdown_table(summary_df),
        "",
        "## 风格判断",
        judgment,
        *[f"- {reason}" for reason in reasons],
        "",
        "## 问题记录",
        *(f"- {problem}" for problem in problems),
    ]
    out_report.write_text("\n".join(report_lines), encoding="utf-8")
    return {"summary": summary_df, "resolved": resolved, "problems": problems, "judgment": judgment, "csv": out_csv, "report": out_report}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=ANALYSIS_DATE)
    args = parser.parse_args()
    result = run(args.date)
    print(f"是否成功: {len(result['summary']) == 7}")
    print(f"取得指数数量: {len(result['summary'])}/7")
    print(f"风格判断: {result['judgment']}")
    print(f"输出CSV: {result['csv']}")
    print(f"输出报告: {result['report']}")
    if result["problems"]:
        print("问题: " + "；".join(result["problems"]))
    print("指数表现:")
    for row in result["summary"].itertuples(index=False):
        print(f"{row.name},{row.ts_code},1日{row.return_1d_pct:.2f}%,3日{row.return_3d_pct:.2f}%,5日{row.return_5d_pct:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
