"""Deep industry analysis with SW2021 L1/L2, turnover changes and moneyflow.

This is a production feature, not an interface smoke test. It builds:
- L1 industry analysis table
- L2 industry analysis table
- industry moneyflow table
- strong industry and leader-candidate report

No token printing. No brokerage access. No trading instruction.
"""

from __future__ import annotations
from scoring_system.tushare_client import credential_marker

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from scoring_system import tushare_client as ts

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from amount_units import tushare_amount_to_yi

RAW_DIR = PROJECT_ROOT / "data" / "raw"
BASIC_DIR = PROJECT_ROOT / "data" / "basic"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
ANALYSIS_DATE = "20260630"
SW_SRC = "SW2021"
SLEEP_SECONDS = 1.5

CLASSIFY_FIELDS = ["index_code", "industry_name", "level", "industry_code", "is_pub", "parent_code", "src"]
MEMBER_FIELDS = ["index_code", "index_name", "con_code", "con_name", "in_date", "out_date", "is_new"]
MONEYFLOW_FIELDS = ["ts_code", "trade_date", "net_mf_amount"]


def get_pro() -> object:
    token = credential_marker()
    if not token:
        raise RuntimeError("HITHINK_FINANCE_API_KEY 不存在")
    return ts.pro_api(token)


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"ts_code": "string", "trade_date": "string", "con_code": "string", "index_code": "string", "parent_code": "string"})


def complete(path: Path, fields: list[str], min_rows: int = 1) -> tuple[bool, pd.DataFrame | None]:
    if not path.exists():
        return False, None
    try:
        df = read_csv(path)
    except Exception:
        return False, None
    missing = [f for f in fields if f not in df.columns]
    return (not missing and len(df) >= min_rows), df


def recent_dates(end_date: str, needed: int = 5) -> list[str]:
    dates = []
    cur = datetime.strptime(end_date, "%Y%m%d")
    for offset in range(12):
        d = (cur - timedelta(days=offset)).strftime("%Y%m%d")
        if (RAW_DIR / f"daily_{d}.csv").exists():
            df = read_csv(RAW_DIR / f"daily_{d}.csv")
            if len(df) > 0:
                dates.append(d)
        if len(dates) >= needed:
            break
    if len(dates) < needed:
        raise RuntimeError(f"本地daily缓存不足{needed}个有效交易日")
    return dates


def load_daily_window(dates: list[str]) -> pd.DataFrame:
    frames = []
    for d in dates:
        df = read_csv(RAW_DIR / f"daily_{d}.csv")
        frames.append(df[["ts_code", "trade_date", "close", "pre_close", "pct_chg", "amount"]].copy())
    return pd.concat(frames, ignore_index=True)


def load_stock_names(date: str) -> pd.DataFrame:
    p = PROCESSED_DIR / f"daily_stock_master_{date}.csv"
    df = read_csv(p)
    return df[["ts_code", "symbol", "name"]].drop_duplicates("ts_code")


def load_or_fetch_classify(level: str, pro: object, sleep_seconds: float) -> pd.DataFrame:
    path = BASIC_DIR / f"industry_classify_{SW_SRC}_{level}.csv"
    ok, df = complete(path, CLASSIFY_FIELDS)
    if ok and df is not None:
        return df
    time.sleep(sleep_seconds)
    df = pro.index_classify(level=level, src=SW_SRC, fields=",".join(CLASSIFY_FIELDS))
    BASIC_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df


def member_path(level: str, index_code: str) -> Path:
    return BASIC_DIR / f"industry_members_{level}" / f"members_{index_code.replace('.', '_')}.csv"


def load_or_fetch_members(level: str, index_code: str, pro: object, sleep_seconds: float) -> pd.DataFrame:
    path = member_path(level, index_code)
    ok, df = complete(path, MEMBER_FIELDS, min_rows=0)
    if ok and df is not None:
        return df
    time.sleep(sleep_seconds)
    df = pro.index_member(index_code=index_code, fields=",".join(MEMBER_FIELDS))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df


def build_level_members(level: str, classify: pd.DataFrame, pro: object, sleep_seconds: float) -> pd.DataFrame:
    frames = []
    for row in classify.itertuples(index=False):
        idx = str(row.index_code)
        mem = load_or_fetch_members(level, idx, pro, sleep_seconds)
        if len(mem) == 0:
            continue
        mem = mem.copy()
        mem[f"{level.lower()}_code"] = idx
        mem[f"{level.lower()}_name"] = str(row.industry_name)
        if hasattr(row, "parent_code"):
            mem["parent_code"] = str(row.parent_code)
        frames.append(mem)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def active_map(members: pd.DataFrame, level: str, date: str) -> pd.DataFrame:
    if members.empty:
        return pd.DataFrame(columns=["ts_code", f"{level.lower()}_code", f"{level.lower()}_name"])
    m = members.copy()
    if "out_date" not in m.columns:
        m["out_date"] = pd.NA
    active = m[(m["out_date"].isna()) | (m["out_date"].astype(str).isin(["", "nan", "NaT"])) | (m["out_date"].astype(str) > date)]
    active = active.rename(columns={"con_code": "ts_code"})
    return active[["ts_code", f"{level.lower()}_code", f"{level.lower()}_name"]].drop_duplicates("ts_code")


def stock_returns(daily_window: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    today = dates[0]
    cur = daily_window[daily_window.trade_date.astype(str) == today].copy()
    cur = cur.rename(columns={"pct_chg": "return_1d_pct", "amount": "amount_today"})
    for n in [3, 5]:
        base = daily_window[daily_window.trade_date.astype(str) == dates[n - 1]][["ts_code", "pre_close"]].rename(columns={"pre_close": f"base_{n}d"})
        cur = cur.merge(base, on="ts_code", how="left")
        cur[f"return_{n}d_pct"] = (cur["close"] / cur[f"base_{n}d"] - 1) * 100
    return cur


def load_or_fetch_moneyflow(date: str, pro: object, sleep_seconds: float) -> pd.DataFrame:
    path = RAW_DIR / f"moneyflow_{date}.csv"
    ok, df = complete(path, MONEYFLOW_FIELDS)
    if ok and df is not None:
        return df
    time.sleep(sleep_seconds)
    df = pro.moneyflow(trade_date=date, fields=",".join(MONEYFLOW_FIELDS))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df


def load_moneyflow_window(dates: list[str], pro: object, sleep_seconds: float) -> pd.DataFrame:
    frames = [load_or_fetch_moneyflow(d, pro, sleep_seconds) for d in dates]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=MONEYFLOW_FIELDS)


def aggregate_moneyflow(moneyflow: pd.DataFrame, mapping: pd.DataFrame, level: str, dates: list[str], names: pd.DataFrame) -> pd.DataFrame:
    key_name = f"{level.lower()}_name"
    merged = moneyflow.merge(mapping, on="ts_code", how="left").merge(names, on="ts_code", how="left")
    rows = []
    for industry, g in merged[merged[key_name].notna()].groupby(key_name):
        by_date = g.groupby("trade_date")["net_mf_amount"].sum().reindex(dates, fill_value=0)
        signs = [1 if v > 0 else -1 if v < 0 else 0 for v in by_date.tolist()]
        streak = 0
        first_sign = signs[0] if signs else 0
        for s in signs:
            if s == first_sign and s != 0:
                streak += 1
            else:
                break
        today_g = g[g.trade_date.astype(str) == dates[0]].copy()
        top = today_g.sort_values("net_mf_amount", ascending=False).head(5)
        top_text = "; ".join(f"{r.name}({r.ts_code},{r.net_mf_amount:.2f})" for r in top.itertuples(index=False))
        rows.append({
            key_name: industry,
            "moneyflow_today": float(by_date.iloc[0]),
            "moneyflow_3d": float(by_date.iloc[:3].sum()),
            "moneyflow_5d": float(by_date.iloc[:5].sum()),
            "moneyflow_streak": streak if first_sign > 0 else -streak if first_sign < 0 else 0,
            "top5_money_inflow_stocks": top_text,
        })
    result = pd.DataFrame(rows)
    if not result.empty and key_name in result.columns:
        result = result.rename(columns={key_name: "industry_name"})
    return result


def top5_amount_stocks(g: pd.DataFrame) -> str:
    top = g.sort_values("amount_today", ascending=False).head(5)
    return "; ".join(f"{r.name}({r.ts_code},{r.return_1d_pct:.2f}%)" for r in top.itertuples(index=False))


def leader_candidates(g: pd.DataFrame, mf_today: pd.DataFrame) -> dict[str, str]:
    strongest_1d = g.sort_values("return_1d_pct", ascending=False).iloc[0]
    largest_amount = g.sort_values("amount_today", ascending=False).iloc[0]
    strongest_5d = g.sort_values("return_5d_pct", ascending=False).iloc[0]
    mf_map = mf_today.set_index("ts_code") if not mf_today.empty else pd.DataFrame()
    if not mf_map.empty:
        merged = g.merge(mf_today[["ts_code", "net_mf_amount"]], on="ts_code", how="left")
        flow_row = merged.sort_values("net_mf_amount", ascending=False).iloc[0]
    else:
        flow_row = strongest_1d
    candidates = [strongest_1d.ts_code, largest_amount.ts_code, strongest_5d.ts_code]
    if hasattr(flow_row, "ts_code"):
        candidates.append(flow_row.ts_code)
    counts = {c: candidates.count(c) for c in candidates}
    best_code = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[0][0]
    best = g[g.ts_code == best_code].iloc[0]
    return {
        "strongest_1d_stock": f"{strongest_1d.name}({strongest_1d.ts_code})",
        "largest_amount_stock": f"{largest_amount.name}({largest_amount.ts_code})",
        "strongest_5d_stock": f"{strongest_5d.name}({strongest_5d.ts_code})",
        "top_money_inflow_stock": f"{getattr(flow_row, 'name', '')}({getattr(flow_row, 'ts_code', '')})",
        "leader_candidate": f"{best['name']}({best['ts_code']})",
    }


def aggregate_industry(stock_df: pd.DataFrame, daily_window: pd.DataFrame, moneyflow: pd.DataFrame, mapping: pd.DataFrame, level: str, dates: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    key = f"{level.lower()}_name"
    market_amount_today = stock_df["amount_today"].sum()
    market_amount_by_date = daily_window.groupby("trade_date")["amount"].sum().reindex(dates)
    mf_today = moneyflow[moneyflow.trade_date.astype(str) == dates[0]] if not moneyflow.empty else pd.DataFrame(columns=MONEYFLOW_FIELDS)
    rows = []
    leaders = []
    for industry, g in stock_df[stock_df[key].notna()].groupby(key):
        codes = set(g.ts_code.astype(str))
        hist = daily_window[daily_window.ts_code.astype(str).isin(codes)]
        amount_by_date = hist.groupby("trade_date")["amount"].sum().reindex(dates, fill_value=0)
        amount_today = float(amount_by_date.iloc[0])
        amount_yesterday = float(amount_by_date.iloc[1]) if len(amount_by_date) > 1 else 0.0
        amount_5d_avg = float(amount_by_date.iloc[:5].mean())
        share_by_date = amount_by_date / market_amount_by_date.replace(0, pd.NA)
        leader = leader_candidates(g, mf_today)
        row = {
            "industry_name": industry,
            "stock_count": len(g),
            "up_count": int((g.return_1d_pct > 0).sum()),
            "down_count": int((g.return_1d_pct < 0).sum()),
            "up_ratio": float((g.return_1d_pct > 0).mean()),
            "avg_1d_pct": float(g.return_1d_pct.mean()),
            "median_1d_pct": float(g.return_1d_pct.median()),
            "amount_today_yi": tushare_amount_to_yi(amount_today),
            "amount_yesterday_yi": tushare_amount_to_yi(amount_yesterday),
            "amount_5d_avg_yi": tushare_amount_to_yi(amount_5d_avg),
            "amount_vs_yesterday_yi": tushare_amount_to_yi(amount_today - amount_yesterday),
            "amount_vs_5d_avg_yi": tushare_amount_to_yi(amount_today - amount_5d_avg),
            "amount_market_share": float(amount_today / market_amount_today) if market_amount_today else 0.0,
            "amount_share_5d_change": float(share_by_date.iloc[0] - share_by_date.iloc[-1]) if len(share_by_date) >= 5 else 0.0,
            "return_1d_pct": float(g.return_1d_pct.mean()),
            "return_3d_pct": float(g.return_3d_pct.mean()),
            "return_5d_pct": float(g.return_5d_pct.mean()),
            "up_ge_5_count": int((g.return_1d_pct >= 5).sum()),
            "down_le_neg5_count": int((g.return_1d_pct <= -5).sum()),
            "top5_amount_stocks": top5_amount_stocks(g),
            **leader,
        }
        row["rank_reason"] = (
            f"1/3/5日表现{row['return_1d_pct']:.2f}/{row['return_3d_pct']:.2f}/{row['return_5d_pct']:.2f}，"
            f"上涨占比{row['up_ratio']:.2%}，成交额较昨日{row['amount_vs_yesterday_yi']:.2f}亿元，"
            f"较5日均值{row['amount_vs_5d_avg_yi']:.2f}亿元，大涨{row['up_ge_5_count']}只，大跌{row['down_le_neg5_count']}只，"
            f"班长候选{row['leader_candidate']}。"
        )
        rows.append(row)
        leaders.append({"industry_name": industry, **leader})
    out = pd.DataFrame(rows)
    if out.empty:
        return out, pd.DataFrame(leaders)
    mf = aggregate_moneyflow(moneyflow, mapping, level, dates, stock_df[["ts_code", "symbol", "name"]].drop_duplicates("ts_code"))
    out = out.merge(mf, on="industry_name", how="left")
    for col in ["moneyflow_today", "moneyflow_3d", "moneyflow_5d", "moneyflow_streak"]:
        if col in out.columns:
            out[col] = out[col].fillna(0)
    out["strength_score"] = (
        out.return_1d_pct * 1.0 + out.return_3d_pct * 0.7 + out.return_5d_pct * 0.5 + out.up_ratio * 5
        + out.amount_vs_yesterday_yi.clip(lower=-100, upper=100) * 0.01
        + out.moneyflow_today.fillna(0).clip(lower=-100000, upper=100000) / 100000 * 2
        + out.up_ge_5_count * 0.03 - out.down_le_neg5_count * 0.03
    )
    return out.sort_values("strength_score", ascending=False), pd.DataFrame(leaders)


def classify(stats: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cont = stats[(stats.return_1d_pct > 0) & (stats.return_3d_pct > 0) & (stats.return_5d_pct > 0)].copy()
    bounce = stats[(stats.return_1d_pct > 2) & (stats.return_3d_pct <= 0)].copy()
    weak = stats[(stats.return_1d_pct < 0) & (stats.return_3d_pct < 0)].copy()
    return cont, bounce, weak


def markdown_table(df: pd.DataFrame, cols: list[str] | None = None, n: int | None = None) -> str:
    if cols:
        df = df[cols]
    if n:
        df = df.head(n)
    if df.empty:
        return "无"
    columns = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in df.itertuples(index=False, name=None):
        vals = [f"{v:.4f}" if isinstance(v, float) else str(v) for v in row]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def run(date: str = ANALYSIS_DATE, sleep_seconds: float = SLEEP_SECONDS) -> dict[str, object]:
    pro = get_pro()
    dates = recent_dates(date)
    daily_window = load_daily_window(dates)
    names = load_stock_names(date)
    returns = stock_returns(daily_window, dates).merge(names, on="ts_code", how="left")

    l1_class = load_or_fetch_classify("L1", pro, sleep_seconds)
    l2_class = load_or_fetch_classify("L2", pro, sleep_seconds)
    l1_members = build_level_members("L1", l1_class, pro, sleep_seconds)
    l2_members = build_level_members("L2", l2_class, pro, sleep_seconds)
    l1_map = active_map(l1_members, "L1", date)
    l2_map = active_map(l2_members, "L2", date)
    l1_stock = returns.merge(l1_map, on="ts_code", how="left")
    l2_stock = returns.merge(l2_map, on="ts_code", how="left")
    moneyflow = load_moneyflow_window(dates, pro, sleep_seconds)

    l1_stats, l1_leaders = aggregate_industry(l1_stock, daily_window, moneyflow, l1_map, "L1", dates)
    l2_stats, l2_leaders = aggregate_industry(l2_stock, daily_window, moneyflow, l2_map, "L2", dates)
    l2_cont, l2_bounce, l2_weak = classify(l2_stats)
    unmatched = l2_stock[l2_stock.l2_name.isna()][["ts_code", "symbol", "name", "return_1d_pct", "amount_today"]].copy()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "l1": PROCESSED_DIR / f"industry_l1_analysis_{date}.csv",
        "l2": PROCESSED_DIR / f"industry_l2_analysis_{date}.csv",
        "moneyflow": PROCESSED_DIR / f"industry_moneyflow_{date}.csv",
        "leaders": PROCESSED_DIR / f"industry_leader_candidates_{date}.csv",
        "unmatched": PROCESSED_DIR / f"industry_unmatched_{date}.csv",
        "report": REPORTS_DIR / f"industry_strength_and_leaders_{date}.md",
    }
    l1_stats.to_csv(paths["l1"], index=False, encoding="utf-8-sig")
    l2_stats.to_csv(paths["l2"], index=False, encoding="utf-8-sig")
    l2_stats[["industry_name", "moneyflow_today", "moneyflow_3d", "moneyflow_5d", "moneyflow_streak", "top5_money_inflow_stocks"]].to_csv(paths["moneyflow"], index=False, encoding="utf-8-sig")
    l2_leaders.to_csv(paths["leaders"], index=False, encoding="utf-8-sig")
    unmatched.to_csv(paths["unmatched"], index=False, encoding="utf-8-sig")

    semi = l2_stats[l2_stats.industry_name.astype(str).str.contains("半导体", na=False)]
    report = [
        f"# 强势行业和班长候选报告 {date}", "",
        "说明：资金流为辅助证据，不能单独作为交易依据。", "",
        "## 二级行业前10", markdown_table(l2_stats, n=10), "",
        "## 持续走强行业", markdown_table(l2_cont, n=30), "",
        "## 单日反弹行业", markdown_table(l2_bounce, n=30), "",
        "## 正在转弱行业", markdown_table(l2_weak, n=30), "",
        "## 半导体", markdown_table(semi), "",
        "## 未匹配股票样例", markdown_table(unmatched, n=100),
    ]
    paths["report"].write_text("\n".join(report), encoding="utf-8")
    return {"l1": l1_stats, "l2": l2_stats, "continuous": l2_cont, "bounce": l2_bounce, "weak": l2_weak, "semi": semi, "unmatched": unmatched, "paths": paths, "dates": dates}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=ANALYSIS_DATE)
    args = parser.parse_args()
    result = run(args.date)
    semi = result["semi"]
    print(f"是否成功: {not result['l2'].empty}")
    if not semi.empty:
        rank = int(result["l2"].reset_index(drop=True).index[result["l2"].industry_name == semi.iloc[0].industry_name][0]) + 1
        s = semi.iloc[0]
        print(f"半导体排名: {rank}")
        print(f"半导体表现: 1日{s.return_1d_pct:.2f}%,3日{s.return_3d_pct:.2f}%,5日{s.return_5d_pct:.2f}%")
        print(f"半导体成交额变化: 较昨日{s.amount_vs_yesterday_yi:.2f}亿元,较5日均值{s.amount_vs_5d_avg_yi:.2f}亿元")
        print(f"半导体资金: 今日{s.moneyflow_today:.2f},3日{s.moneyflow_3d:.2f},5日{s.moneyflow_5d:.2f}")
    print("当前最强前10二级行业:")
    for r in result["l2"].head(10).itertuples(index=False):
        print(f"{r.industry_name},{r.return_1d_pct:.2f}%,{r.return_3d_pct:.2f}%,{r.return_5d_pct:.2f}%,班长{r.leader_candidate}")
    print("持续走强: " + ",".join(result["continuous"].head(20).industry_name.astype(str).tolist()))
    print("单日反弹: " + ",".join(result["bounce"].head(20).industry_name.astype(str).tolist()))
    print("未匹配数量: " + str(len(result["unmatched"])))
    print("文件: " + ";".join(str(p) for p in result["paths"].values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


