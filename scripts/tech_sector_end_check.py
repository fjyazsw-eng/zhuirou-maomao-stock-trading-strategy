from __future__ import annotations
from scoring_system.tushare_client import credential_marker

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
from scoring_system import tushare_client as ts

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.industry_members import fetch_sw_index_members

DB = ROOT / "data" / "sqlite" / "market_120d.sqlite"
OUT = ROOT / "reports" / "tech_sector_end_check_20260701.json"
ASOF = "20260701"
WINDOWS = [5, 10, 20, 60]
MARKET_INDEX = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000688.SH": "科创50",
}
TARGETS = {
    "光学光电子": {"code": "801084.SI", "level": "L2"},
    "半导体材料": {"code": "850813.SI", "level": "L3"},
    "电子化学品": {"code": "850861.SI", "level": "L3"},
}


def pro_api():
    token = credential_marker()
    if not token:
        raise RuntimeError("HITHINK_FINANCE_API_KEY is not set")
    pro = ts.pro_api(token)
    try:
        pro._DataApi__timeout = 120
    except Exception:
        pass
    return pro


def retry_query(fn, tries: int = 4, sleep: float = 2.0):
    last_exc = None
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            time.sleep(sleep * (i + 1))
    raise last_exc


def read_sql(name: str) -> pd.DataFrame:
    with sqlite3.connect(DB) as con:
        return pd.read_sql_query(f"select * from {name}", con)


def as_num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def trade_dates(pro, start_date: str = "20260301") -> list[str]:
    cal = pro.trade_cal(exchange="", start_date=start_date, end_date=ASOF, is_open="1")
    dates = sorted(cal["cal_date"].astype(str).tolist())
    return [d for d in dates if d <= ASOF][-61:]


def load_daily(pro, dates: list[str]) -> pd.DataFrame:
    local = as_num(read_sql("daily"), ["open", "high", "low", "close", "pre_close", "pct_chg", "amount", "vol"])
    have = set(local["trade_date"].astype(str).unique())
    frames = [local[local["trade_date"].astype(str).isin(dates)]]
    missing = [d for d in dates if d not in have]
    for d in missing:
        df = retry_query(
            lambda d=d: pro.daily(
                trade_date=d,
                fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
            )
        )
        frames.append(as_num(df, ["open", "high", "low", "close", "pre_close", "pct_chg", "amount", "vol"]))
    return pd.concat(frames, ignore_index=True).drop_duplicates(["ts_code", "trade_date"])


def load_index_daily(pro, dates: list[str]) -> pd.DataFrame:
    local = as_num(read_sql("index_daily"), ["open", "high", "low", "close", "pre_close", "pct_chg", "amount", "vol"])
    frames = [local[local["trade_date"].astype(str).isin(dates)]]
    have = set(zip(local["ts_code"].astype(str), local["trade_date"].astype(str)))
    for code in MARKET_INDEX:
        missing = [d for d in dates if (code, d) not in have]
        if not missing:
            continue
        parts = []
        for d in missing:
            one = retry_query(
                lambda code=code, d=d: pro.index_daily(
                    ts_code=code,
                    trade_date=d,
                    fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
                )
            )
            parts.append(one)
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        frames.append(as_num(df, ["open", "high", "low", "close", "pre_close", "pct_chg", "amount", "vol"]))
    return pd.concat(frames, ignore_index=True).drop_duplicates(["ts_code", "trade_date"])


def classify_and_members(pro, level: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if level == "L2":
        cls = read_sql("index_classify")
        cls = cls[(cls["level"] == "L2") & (cls["is_pub"].astype(str) == "1")].copy()
        mem = read_sql("index_member")
        mem = mem[mem["index_code"].isin(cls["index_code"])].copy()
        return cls, mem
    cls = retry_query(lambda: pro.index_classify(level="L3", src="SW2021", fields="index_code,industry_name,level,industry_code,is_pub,parent_code,src"))
    cls = cls[cls["is_pub"].astype(str) == "1"].copy()
    frames = []
    for code in cls["index_code"].astype(str):
        try:
            df = retry_query(lambda code=code: fetch_sw_index_members(pro, code, level="L3"), tries=3)
            frames.append(df)
        except Exception as exc:
            print("member fetch failed", code, exc)
    return cls, pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def active_members(mem: pd.DataFrame, code: str) -> pd.DataFrame:
    m = mem[mem["index_code"].astype(str) == code].copy()
    m["out_date"] = m["out_date"].fillna("")
    m["in_date"] = m["in_date"].fillna("00000000").astype(str)
    return m[(m["in_date"] <= ASOF) & ((m["out_date"].astype(str) == "") | (m["out_date"].astype(str) >= ASOF))]


def ret_between(price: pd.DataFrame, start: str, end: str) -> pd.Series:
    a = price[price["trade_date"] == start].set_index("ts_code")["close"]
    b = price[price["trade_date"] == end].set_index("ts_code")["close"]
    return (b / a - 1) * 100


def industry_metrics(daily: pd.DataFrame, dates: list[str], cls: pd.DataFrame, mem: pd.DataFrame, code: str) -> dict:
    members = active_members(mem, code)
    stocks = set(members["con_code"].astype(str))
    px = daily[daily["ts_code"].isin(stocks)].copy()
    end = dates[-1]
    result = {"member_count": len(stocks), "windows": {}, "leaders": []}
    for n in WINDOWS:
        if len(dates) < n + 1:
            continue
        win = dates[-(n + 1):]
        r = ret_between(px, win[0], end).dropna()
        cur = px[px["trade_date"].isin(win[1:])]
        prev = px[px["trade_date"].isin(dates[-(2 * n + 1):-(n + 1)])] if len(dates) >= 2 * n + 1 else pd.DataFrame()
        end_day = px[px["trade_date"] == end]
        hist = px[px["trade_date"].isin(win[1:])]
        highs = hist.groupby("ts_code")["close"].max()
        lows = hist.groupby("ts_code")["close"].min()
        end_close = end_day.set_index("ts_code")["close"]
        result["windows"][str(n)] = {
            "ret_pct_equal_weight": round(float(r.mean()), 2) if len(r) else None,
            "up": int((r > 0).sum()),
            "down": int((r < 0).sum()),
            "flat": int((r == 0).sum()),
            "avg_daily_amount_yi": round(float(cur["amount"].sum() / n / 100000), 2) if len(cur) else None,
            "prev_avg_daily_amount_yi": round(float(prev["amount"].sum() / n / 100000), 2) if len(prev) else None,
            "new_high_count": int((end_close >= highs.reindex(end_close.index)).sum()),
            "new_low_count": int((end_close <= lows.reindex(end_close.index)).sum()),
        }
    latest = px.pivot(index="trade_date", columns="ts_code", values="close").sort_index()
    amt = px.pivot(index="trade_date", columns="ts_code", values="amount").sort_index()
    if len(latest) >= 21:
        ma20 = latest.rolling(20).mean().iloc[-1]
        ma60 = latest.rolling(min(60, len(latest))).mean().iloc[-1]
        close = latest.iloc[-1]
        result["breadth"] = {
            "below_ma20": int((close < ma20).sum()),
            "below_ma60": int((close < ma60).sum()),
            "below_ma20_ratio": round(float((close < ma20).mean()), 3),
            "below_ma60_ratio": round(float((close < ma60).mean()), 3),
        }
    score = pd.DataFrame({"ts_code": list(stocks)})
    for n, weight in [(20, 0.45), (60, 0.25)]:
        if len(dates) >= n + 1:
            rr = ret_between(px, dates[-(n + 1)], end).rename(f"ret{n}")
            score = score.merge(rr, on="ts_code", how="left")
    amt_share = px[px["trade_date"].isin(dates[-20:])].groupby("ts_code")["amount"].sum()
    score = score.merge(amt_share.rename("amount20"), on="ts_code", how="left")
    score["amount_rank"] = score["amount20"].rank(pct=True)
    score["leader_score"] = score.get("ret20", 0).fillna(0) * 0.45 + score.get("ret60", 0).fillna(0) * 0.25 + score["amount_rank"].fillna(0) * 30
    names = members.drop_duplicates("con_code").set_index("con_code")["con_name"]
    for ts_code in score.sort_values("leader_score", ascending=False)["ts_code"].head(3):
        s = px[px["ts_code"] == ts_code].sort_values("trade_date").copy()
        c = s["close"]
        a = s["amount"]
        last3 = s.tail(3)
        result["leaders"].append({
            "ts_code": ts_code,
            "name": str(names.get(ts_code, "")),
            "ret20": round(float((c.iloc[-1] / c.iloc[-21] - 1) * 100), 2) if len(c) >= 21 else None,
            "ret60": round(float((c.iloc[-1] / c.iloc[0] - 1) * 100), 2) if len(c) >= 2 else None,
            "above_ma20": bool(c.iloc[-1] > c.rolling(20).mean().iloc[-1]) if len(c) >= 20 else None,
            "above_ma60": bool(c.iloc[-1] > c.rolling(min(60, len(c))).mean().iloc[-1]) if len(c) >= 20 else None,
            "drawdown_from_60d_high_pct": round(float((c.iloc[-1] / c.max() - 1) * 100), 2),
            "last3_all_down": bool((last3["pct_chg"] < 0).all()),
            "last3_amount_vs_20d_avg": round(float(last3["amount"].mean() / a.tail(20).mean()), 2) if len(a) >= 20 else None,
        })
    return result


def rank_table(daily: pd.DataFrame, dates: list[str], cls: pd.DataFrame, mem: pd.DataFrame) -> dict[str, dict[str, int | None]]:
    ranks: dict[str, dict[str, int | None]] = {}
    total = len(cls)
    for n in WINDOWS:
        if len(dates) < n + 1:
            continue
        vals = []
        for _, row in cls.iterrows():
            stocks = set(active_members(mem, str(row["index_code"]))["con_code"].astype(str))
            px = daily[daily["ts_code"].isin(stocks)]
            r = ret_between(px, dates[-(n + 1)], dates[-1]).dropna()
            if len(r) >= 3:
                vals.append((str(row["index_code"]), float(r.mean())))
        ranked = pd.DataFrame(vals, columns=["code", "ret"]).sort_values("ret", ascending=False)
        ranked["rank"] = range(1, len(ranked) + 1)
        for code, rank in zip(ranked["code"], ranked["rank"]):
            ranks.setdefault(code, {})[str(n)] = int(rank)
        ranks["_total_" + str(n)] = {"total": int(len(ranked)), "classify_total": int(total)}
    return ranks


def market_metrics(daily: pd.DataFrame, idx: pd.DataFrame, dates: list[str]) -> dict:
    out = {"indices": {}, "market": {}}
    for code, name in MARKET_INDEX.items():
        p = idx[idx["ts_code"] == code].sort_values("trade_date")
        item = {}
        for n in WINDOWS:
            if len(p) >= n + 1:
                item[str(n)] = round(float((p.iloc[-1]["close"] / p.iloc[-(n + 1)]["close"] - 1) * 100), 2)
        out["indices"][name] = item
    for n in WINDOWS:
        if len(dates) >= n + 1:
            cur = daily[daily["trade_date"].isin(dates[-n:])]
            prev = daily[daily["trade_date"].isin(dates[-(2 * n):-n])] if len(dates) >= 2 * n else pd.DataFrame()
            last = daily[daily["trade_date"] == dates[-1]]
            out["market"][str(n)] = {
                "avg_daily_amount_yi": round(float(cur["amount"].sum() / n / 100000), 2),
                "prev_avg_daily_amount_yi": round(float(prev["amount"].sum() / n / 100000), 2) if len(prev) else None,
                "last_up": int((last["pct_chg"] > 0).sum()),
                "last_down": int((last["pct_chg"] < 0).sum()),
                "window_up_days_avg": round(float(daily[daily["trade_date"].isin(dates[-n:])].groupby("trade_date")["pct_chg"].apply(lambda s: (s > 0).sum()).mean()), 1),
                "window_down_days_avg": round(float(daily[daily["trade_date"].isin(dates[-n:])].groupby("trade_date")["pct_chg"].apply(lambda s: (s < 0).sum()).mean()), 1),
            }
    return out


def main() -> None:
    pro = pro_api()
    dates = trade_dates(pro)
    daily = load_daily(pro, dates)
    idx = load_index_daily(pro, dates)
    l2_cls, l2_mem = classify_and_members(pro, "L2")
    l3_cls, l3_mem = classify_and_members(pro, "L3")
    ranks_l2 = rank_table(daily, dates, l2_cls, l2_mem)
    ranks_l3 = rank_table(daily, dates, l3_cls, l3_mem)
    sectors = {}
    for name, info in TARGETS.items():
        cls, mem, ranks = (l2_cls, l2_mem, ranks_l2) if info["level"] == "L2" else (l3_cls, l3_mem, ranks_l3)
        metrics = industry_metrics(daily, dates, cls, mem, info["code"])
        metrics["rank"] = ranks.get(info["code"], {})
        metrics["rank_total"] = {k.replace("_total_", ""): v for k, v in ranks.items() if k.startswith("_total_")}
        metrics["code"] = info["code"]
        metrics["level"] = info["level"]
        sectors[name] = metrics
    result = {
        "asof": ASOF,
        "trade_dates": {"start": dates[0], "end": dates[-1], "count": len(dates)},
        "market": market_metrics(daily, idx, dates),
        "sectors": sectors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
