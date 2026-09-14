"""Build Shenwan industry neighborhood map from cached market data.

Uses SW2021 industry classification where available. Local cache first; no token
printing; no industry guessing. Unmatched stocks are listed separately.
"""

from __future__ import annotations
from scoring_system.tushare_client import credential_marker

import argparse
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from scoring_system import tushare_client as ts

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
BASIC_DIR = PROJECT_ROOT / "data" / "basic"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
ANALYSIS_DATE = "20260630"
SW_SRC = "SW2021"
SLEEP_SECONDS = 1.5

DAILY_FIELDS = ["ts_code", "trade_date", "close", "pre_close", "pct_chg", "amount"]
CLASSIFY_FIELDS = ["index_code", "industry_name", "level", "industry_code", "is_pub", "parent_code", "src"]
MEMBER_FIELDS = ["index_code", "index_name", "con_code", "con_name", "in_date", "out_date", "is_new"]


def get_pro() -> object:
    token = credential_marker()
    if not token:
        raise RuntimeError("HITHINK_FINANCE_API_KEY 不存在")
    return ts.pro_api(token)


def read_csv_safe(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"ts_code": "string", "trade_date": "string", "con_code": "string", "index_code": "string"})


def complete(path: Path, fields: list[str], min_rows: int = 1) -> tuple[bool, pd.DataFrame | None]:
    if not path.exists():
        return False, None
    try:
        df = read_csv_safe(path)
    except Exception:
        return False, None
    missing = [field for field in fields if field not in df.columns]
    return (not missing and len(df) >= min_rows), df


def load_or_fetch_classify(pro: object, sleep_seconds: float = SLEEP_SECONDS) -> pd.DataFrame:
    path = BASIC_DIR / f"industry_classify_{SW_SRC}_L1.csv"
    ok, df = complete(path, CLASSIFY_FIELDS)
    if ok and df is not None:
        return df
    time.sleep(sleep_seconds)
    df = pro.index_classify(level="L1", src=SW_SRC, fields=",".join(CLASSIFY_FIELDS))
    BASIC_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df


def member_path(index_code: str) -> Path:
    return BASIC_DIR / "industry_members" / f"members_{index_code.replace('.', '_')}.csv"


def load_or_fetch_members(index_code: str, pro: object, sleep_seconds: float = SLEEP_SECONDS) -> pd.DataFrame:
    path = member_path(index_code)
    ok, df = complete(path, MEMBER_FIELDS, min_rows=0)
    if ok and df is not None:
        return df
    time.sleep(sleep_seconds)
    df = pro.index_member(index_code=index_code, fields=",".join(MEMBER_FIELDS))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df


def build_industry_members(pro: object, sleep_seconds: float = SLEEP_SECONDS) -> tuple[pd.DataFrame, pd.DataFrame]:
    classify = load_or_fetch_classify(pro, sleep_seconds)
    frames = []
    for row in classify.itertuples(index=False):
        index_code = str(row.index_code)
        members = load_or_fetch_members(index_code, pro, sleep_seconds)
        if len(members) == 0:
            continue
        members = members.copy()
        members["industry_code"] = index_code
        members["industry_name"] = str(row.industry_name)
        frames.append(members)
    all_members = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=MEMBER_FIELDS + ["industry_code", "industry_name"])
    return classify, all_members


def recent_daily_dates(end_date: str, needed: int = 5) -> list[str]:
    current = datetime.strptime(end_date, "%Y%m%d")
    dates = []
    for offset in range(12):
        d = (current - timedelta(days=offset)).strftime("%Y%m%d")
        path = RAW_DIR / f"daily_{d}.csv"
        ok, _df = complete(path, DAILY_FIELDS)
        if ok:
            dates.append(d)
        if len(dates) >= needed:
            break
    return dates


def load_daily_window(end_date: str) -> pd.DataFrame:
    dates = recent_daily_dates(end_date)
    if len(dates) < 5:
        raise RuntimeError(f"本地daily缓存不足5个有效交易日，仅找到{len(dates)}个")
    frames = []
    for d in dates:
        df = read_csv_safe(RAW_DIR / f"daily_{d}.csv")
        frames.append(df[DAILY_FIELDS].copy())
    return pd.concat(frames, ignore_index=True)


def stock_returns(daily_window: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    today = dates[0]
    current = daily_window[daily_window["trade_date"].astype(str) == today].copy()
    current = current.rename(columns={"pct_chg": "return_1d_pct", "amount": "amount_today"})
    for n in [3, 5]:
        base_date = dates[n - 1]
        base = daily_window[daily_window["trade_date"].astype(str) == base_date][["ts_code", "pre_close"]].rename(columns={"pre_close": f"base_pre_close_{n}d"})
        current = current.merge(base, on="ts_code", how="left")
        current[f"return_{n}d_pct"] = (current["close"] / current[f"base_pre_close_{n}d"] - 1) * 100
    return current


def active_member_map(members: pd.DataFrame, date: str) -> pd.DataFrame:
    if members.empty:
        return pd.DataFrame(columns=["ts_code", "industry_code", "industry_name"])
    m = members.copy()
    m["out_date"] = m.get("out_date", pd.Series([pd.NA] * len(m))).astype("string")
    active = m[(m["out_date"].isna()) | (m["out_date"] == "") | (m["out_date"].astype(str) > date)]
    active = active.rename(columns={"con_code": "ts_code"})
    active = active[["ts_code", "industry_code", "industry_name"]].drop_duplicates(subset=["ts_code"])
    return active


def top5_names(group: pd.DataFrame) -> str:
    top = group.sort_values("amount_today", ascending=False).head(5)
    names = []
    for row in top.itertuples(index=False):
        names.append(f"{row.name}({row.ts_code},{row.return_1d_pct:.2f}%)")
    return "; ".join(names)


def build_stats(master: pd.DataFrame) -> pd.DataFrame:
    matched = master[master["industry_name"].notna()].copy()
    rows = []
    for industry, group in matched.groupby("industry_name", dropna=False):
        rows.append({
            "industry_name": industry,
            "stock_count": len(group),
            "up_count": int((group["return_1d_pct"] > 0).sum()),
            "down_count": int((group["return_1d_pct"] < 0).sum()),
            "up_ratio": float((group["return_1d_pct"] > 0).mean()) if len(group) else 0,
            "avg_1d_pct": float(group["return_1d_pct"].mean()),
            "median_1d_pct": float(group["return_1d_pct"].median()),
            "amount_total": float(group["amount_today"].sum()),
            "return_1d_pct": float(group["return_1d_pct"].mean()),
            "return_3d_pct": float(group["return_3d_pct"].mean()),
            "return_5d_pct": float(group["return_5d_pct"].mean()),
            "up_ge_5_count": int((group["return_1d_pct"] >= 5).sum()),
            "down_le_neg5_count": int((group["return_1d_pct"] <= -5).sum()),
            "top5_amount_stocks": top5_names(group),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["strength_score"] = df["return_1d_pct"] + df["return_3d_pct"] * 0.7 + df["return_5d_pct"] * 0.5 + df["up_ratio"] * 5
    return df.sort_values("strength_score", ascending=False)


def classify_industries(stats: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    continuous = stats[(stats["return_1d_pct"] > 0) & (stats["return_3d_pct"] > 0) & (stats["return_5d_pct"] > 0)].copy()
    one_day = stats[(stats["return_1d_pct"] > 2) & (stats["return_3d_pct"] <= 0)].copy()
    weakening = stats[(stats["return_1d_pct"] < 0) & (stats["return_3d_pct"] < 0)].copy()
    return continuous, one_day, weakening


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "无"
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in df.itertuples(index=False, name=None):
        vals = []
        for v in row:
            vals.append(f"{v:.4f}" if isinstance(v, float) else str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def run(date: str = ANALYSIS_DATE, sleep_seconds: float = SLEEP_SECONDS) -> dict[str, object]:
    pro = get_pro()
    classify, members = build_industry_members(pro, sleep_seconds)
    dates = recent_daily_dates(date)
    daily_window = load_daily_window(date)
    returns = stock_returns(daily_window, dates)
    stock_master = pd.read_csv(PROCESSED_DIR / f"daily_stock_master_{date}.csv", dtype={"ts_code": "string", "symbol": "string"})
    names = stock_master[["ts_code", "symbol", "name"]].drop_duplicates("ts_code")
    mapping = active_member_map(members, date)
    combined = returns.merge(names, on="ts_code", how="left").merge(mapping, on="ts_code", how="left")
    stats = build_stats(combined)
    unmatched = combined[combined["industry_name"].isna()][["ts_code", "symbol", "name", "return_1d_pct", "amount_today"]].copy()
    continuous, one_day, weakening = classify_industries(stats)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stats_path = PROCESSED_DIR / f"industry_map_{date}.csv"
    matched_path = PROCESSED_DIR / f"stock_industry_matched_{date}.csv"
    unmatched_path = PROCESSED_DIR / f"stock_industry_unmatched_{date}.csv"
    report_path = REPORTS_DIR / f"industry_map_{date}.md"
    stats.to_csv(stats_path, index=False, encoding="utf-8-sig")
    combined.to_csv(matched_path, index=False, encoding="utf-8-sig")
    unmatched.to_csv(unmatched_path, index=False, encoding="utf-8-sig")

    matched_count = int(combined["industry_name"].notna().sum())
    match_rate = matched_count / len(combined) if len(combined) else 0
    report = [
        f"# 行业街区地图 {date}", "",
        f"行业分类来源：申万 {SW_SRC}",
        f"股票总数：{len(combined)}；成功匹配：{matched_count}；未匹配：{len(unmatched)}；匹配率：{match_rate:.2%}", "",
        "## 当前最强前10行业", markdown_table(stats.head(10)), "",
        "## 连续走强行业", markdown_table(continuous.head(20)), "",
        "## 单日反弹但持续性不足", markdown_table(one_day.head(20)), "",
        "## 正在转弱行业", markdown_table(weakening.head(20)), "",
        "## 未匹配股票样例", markdown_table(unmatched.head(100)),
    ]
    report_path.write_text("\n".join(report), encoding="utf-8")
    return {
        "stats": stats,
        "combined": combined,
        "unmatched": unmatched,
        "continuous": continuous,
        "one_day": one_day,
        "weakening": weakening,
        "match_rate": match_rate,
        "paths": {"stats": stats_path, "matched": matched_path, "unmatched": unmatched_path, "report": report_path},
        "dates": dates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=ANALYSIS_DATE)
    args = parser.parse_args()
    result = run(args.date)
    print(f"是否成功: {len(result['stats']) > 0}")
    print(f"行业匹配率: {result['match_rate']:.2%}")
    print(f"未匹配股票数量: {len(result['unmatched'])}")
    print("当前最强前10行业:")
    for row in result["stats"].head(10).itertuples(index=False):
        print(f"{row.industry_name},{row.return_1d_pct:.2f}%,{row.return_3d_pct:.2f}%,{row.return_5d_pct:.2f}%")
    print("持续走强行业: " + ",".join(result["continuous"].head(20)["industry_name"].astype(str).tolist()))
    print("单日反弹行业: " + ",".join(result["one_day"].head(20)["industry_name"].astype(str).tolist()))
    print("输出: " + ";".join(str(p) for p in result["paths"].values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
