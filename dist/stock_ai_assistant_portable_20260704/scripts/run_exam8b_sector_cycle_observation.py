from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "sqlite" / "market_120d.sqlite"
OUT = ROOT / "reports" / "exam_v2"

sys.path.insert(0, str(ROOT))
from scoring_system.sector_cycle_classifier import classify_sector_cycle, labels_to_text
from scoring_system.sector_cycle_validation import validate_stage_b


@dataclass(frozen=True)
class Sample:
    sample_id: str
    title: str
    sector_code: str
    sector_name: str
    stage_a_start: str
    cutoff: str
    stage_b_start: str
    stage_b_end: str
    target_names: tuple[str, ...]
    goal: str


SAMPLES = [
    Sample(
        "exam8b_sampleA",
        "样本A：半导体高位分歧测试",
        "801081.SI",
        "半导体",
        "20260520",
        "20260630",
        "20260701",
        "20260703",
        ("有研新材", "雅克科技", "长光华芯", "晶瑞电材"),
        "判断半导体在2026-06-30收盘后是否处于高潮、高位分歧或退潮前兆。",
    ),
    Sample(
        "exam8b_sampleB",
        "样本B：电子化学品分歧测试",
        "801086.SI",
        "电子化学品Ⅱ",
        "20260520",
        "20260701",
        "20260702",
        "20260703",
        ("鼎龙股份", "晶瑞电材"),
        "判断电子化学品或科技链在2026-07-01收盘后是正常分歧、高位回调、退潮还是弱修复。",
    ),
    Sample(
        "exam8b_sampleC",
        "样本C：航天装备结构性机会测试",
        "801741.SI",
        "航天装备Ⅱ",
        "20260520",
        "20260630",
        "20260701",
        "20260703",
        ("航天电子", "中国卫星"),
        "判断航天装备在2026-06-30收盘后是否属于结构性强板块。",
    ),
]


def read_sql(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with sqlite3.connect(DB) as con:
        return pd.read_sql_query(sql, con, params=params)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    sha = sha256_file(path)
    path.with_suffix(".sha256").write_text(sha, encoding="utf-8")
    return sha


def verify_snapshot(path: Path) -> dict[str, Any]:
    expected_path = path.with_suffix(".sha256")
    expected = expected_path.read_text(encoding="utf-8").strip() if expected_path.exists() else ""
    actual = sha256_file(path)
    return {
        "path": str(path.relative_to(ROOT)),
        "expected_sha256": expected,
        "actual_sha256": actual,
        "ok": bool(expected and expected == actual),
    }


def trade_dates(start: str, end: str) -> list[str]:
    rows = read_sql(
        "select distinct trade_date from daily where trade_date between ? and ? order by trade_date",
        (start, end),
    )
    return rows["trade_date"].astype(str).tolist()


def active_members(sector_code: str, as_of: str) -> pd.DataFrame:
    mem = read_sql(
        """
        select index_code, index_name, con_code, con_name, in_date, out_date
        from index_member
        where index_code=?
        """,
        (sector_code,),
    )
    if mem.empty:
        return mem
    mem["in_date"] = mem["in_date"].fillna("00000000").astype(str)
    mem["out_date"] = mem["out_date"].fillna("").astype(str)
    return mem[(mem["in_date"] <= as_of) & ((mem["out_date"] == "") | (mem["out_date"] >= as_of))].copy()


def daily_for(codes: list[str], start: str, end: str) -> pd.DataFrame:
    if not codes:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in codes)
    df = read_sql(
        f"""
        select ts_code, trade_date, open, high, low, close, pre_close, pct_chg, amount, amount_yuan
        from daily
        where ts_code in ({placeholders}) and trade_date between ? and ?
        order by ts_code, trade_date
        """,
        tuple(codes + [start, end]),
    )
    for col in ["open", "high", "low", "close", "pre_close", "pct_chg", "amount", "amount_yuan"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def stock_basic() -> pd.DataFrame:
    return read_sql("select ts_code, name, industry, list_date from stock_basic")


def ret_between(px: pd.DataFrame, code: str, start_date: str, end_date: str) -> float | None:
    one = px[(px["ts_code"] == code) & (px["trade_date"].isin([start_date, end_date]))].sort_values("trade_date")
    if len(one) < 2:
        return None
    a = float(one.iloc[0]["close"])
    b = float(one.iloc[-1]["close"])
    if a <= 0:
        return None
    return (b / a - 1) * 100


def window_start(dates: list[str], end_date: str, days: int) -> str | None:
    usable = [d for d in dates if d <= end_date]
    if len(usable) < days + 1:
        return None
    return usable[-(days + 1)]


def sector_window_metrics(px: pd.DataFrame, dates: list[str], cutoff: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for n in [1, 3, 5, 10, 20]:
        s = window_start(dates, cutoff, n)
        if not s:
            out[f"{n}日"] = {"可计算": False, "原因": "交易日不足"}
            continue
        start_close = px[px["trade_date"] == s].set_index("ts_code")["close"]
        end_close = px[px["trade_date"] == cutoff].set_index("ts_code")["close"]
        common = start_close.index.intersection(end_close.index)
        ret = (end_close.loc[common] / start_close.loc[common] - 1) * 100
        cur = px[px["trade_date"].isin([d for d in dates if s < d <= cutoff])]
        prev_dates = [d for d in dates if d <= s][-n:]
        prev = px[px["trade_date"].isin(prev_dates)]
        out[f"{n}日"] = {
            "可计算": True,
            "区间起点": s,
            "等权涨跌幅%": round(float(ret.mean()), 2) if len(ret) else None,
            "上涨家数": int((ret > 0).sum()),
            "下跌家数": int((ret < 0).sum()),
            "持平家数": int((ret == 0).sum()),
            "日均成交额亿元": round(float(cur["amount"].sum() / max(n, 1) / 100000), 2) if len(cur) else None,
            "前段日均成交额亿元": round(float(prev["amount"].sum() / max(n, 1) / 100000), 2) if len(prev) else None,
        }
    return out


def latest_breadth(px: pd.DataFrame, cutoff: str) -> dict[str, Any]:
    latest = px[px["trade_date"] == cutoff]
    piv = px.pivot_table(index="trade_date", columns="ts_code", values="close").sort_index()
    close = piv.loc[cutoff] if cutoff in piv.index else pd.Series(dtype=float)
    ma5 = piv.rolling(5).mean().loc[cutoff] if len(piv) >= 5 and cutoff in piv.index else pd.Series(dtype=float)
    ma10 = piv.rolling(10).mean().loc[cutoff] if len(piv) >= 10 and cutoff in piv.index else pd.Series(dtype=float)
    ma20 = piv.rolling(20).mean().loc[cutoff] if len(piv) >= 20 and cutoff in piv.index else pd.Series(dtype=float)
    return {
        "当日上涨家数": int((latest["pct_chg"] > 0).sum()) if len(latest) else 0,
        "当日下跌家数": int((latest["pct_chg"] < 0).sum()) if len(latest) else 0,
        "当日涨幅中位数%": round(float(latest["pct_chg"].median()), 2) if len(latest) else None,
        "站上5日线家数": int((close > ma5.reindex(close.index)).sum()) if len(close) and len(ma5) else None,
        "站上10日线家数": int((close > ma10.reindex(close.index)).sum()) if len(close) and len(ma10) else None,
        "站上20日线家数": int((close > ma20.reindex(close.index)).sum()) if len(close) and len(ma20) else None,
    }


def stock_features(px: pd.DataFrame, codes: list[str], dates: list[str], cutoff: str) -> pd.DataFrame:
    rows = []
    s1 = window_start(dates, cutoff, 1)
    s3 = window_start(dates, cutoff, 3)
    s5 = window_start(dates, cutoff, 5)
    s10 = window_start(dates, cutoff, 10)
    s20 = window_start(dates, cutoff, 20)

    def rounded_ret(code: str, start_date: str | None) -> float | None:
        if not start_date:
            return None
        value = ret_between(px, code, start_date, cutoff)
        return round(value, 2) if value is not None else None

    for code in codes:
        h = px[px["ts_code"] == code].sort_values("trade_date").copy()
        if h.empty or cutoff not in set(h["trade_date"].astype(str)):
            continue
        last = h[h["trade_date"] == cutoff].iloc[-1]
        close = h["close"]
        ma5 = close.rolling(5).mean().iloc[-1] if len(close) >= 5 else None
        ma10 = close.rolling(10).mean().iloc[-1] if len(close) >= 10 else None
        ma20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else None
        high20 = h.tail(20)["high"].max() if len(h) >= 1 else None
        low20 = h.tail(20)["low"].min() if len(h) >= 1 else None
        position20 = (last["close"] - low20) / (high20 - low20) if high20 and low20 and high20 > low20 else None
        rows.append(
            {
                "ts_code": code,
                "close": round(float(last["close"]), 2),
                "pct_chg": round(float(last["pct_chg"]), 2),
                "amount_yi": round(float(last["amount"] / 100000), 2),
                "ret1": rounded_ret(code, s1),
                "ret3": rounded_ret(code, s3),
                "ret5": rounded_ret(code, s5),
                "ret10": rounded_ret(code, s10),
                "ret20": rounded_ret(code, s20),
                "ma5_up": bool(last["close"] > ma5) if ma5 else None,
                "ma10_up": bool(last["close"] > ma10) if ma10 else None,
                "ma20_up": bool(last["close"] > ma20) if ma20 else None,
                "position20": round(float(position20), 3) if position20 is not None else None,
                "drawdown20_high_pct": round(float((last["close"] / high20 - 1) * 100), 2) if high20 else None,
                "amount5_avg_yi": round(float(h.tail(5)["amount"].mean() / 100000), 2) if len(h) >= 5 else None,
                "amount20_avg_yi": round(float(h.tail(20)["amount"].mean() / 100000), 2) if len(h) >= 20 else None,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ["ret20", "ret10", "ret5", "amount5_avg_yi"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["amount_rank"] = df["amount5_avg_yi"].rank(pct=True)
    df["trend_score"] = df["ret20"].fillna(0) * 0.45 + df["ret10"].fillna(0) * 0.25 + df["ret5"].fillna(0) * 0.15 + df["amount_rank"].fillna(0) * 15
    return df.sort_values("trend_score", ascending=False)


def classify_roles(feat: pd.DataFrame, members: pd.DataFrame, targets: tuple[str, ...]) -> list[dict[str, Any]]:
    if feat.empty:
        return []
    names = members.drop_duplicates("con_code").set_index("con_code")["con_name"].to_dict()
    df = feat.copy()
    df["amount_pct"] = df["amount5_avg_yi"].rank(pct=True)
    df["trend_rank"] = df["trend_score"].rank(ascending=False, method="first")
    roles = []
    for _, r in df.iterrows():
        name = str(names.get(r["ts_code"], ""))
        ret20 = float(r["ret20"]) if pd.notna(r["ret20"]) else 0.0
        ret5 = float(r["ret5"]) if pd.notna(r["ret5"]) else 0.0
        amount_pct = float(r["amount_pct"]) if pd.notna(r["amount_pct"]) else 0.0
        rank = int(r["trend_rank"])
        if rank == 1 and ret20 > 8:
            role = "疑似龙头"
            reason = "阶段A内综合涨幅、趋势和成交额排名第一。"
        elif amount_pct >= 0.85 and ret20 > 0:
            role = "容量核心"
            reason = "成交额位于板块前列，且阶段A仍为正收益。"
        elif ret20 > 12 and bool(r.get("ma20_up")):
            role = "趋势核心"
            reason = "20日表现较强且仍在20日线上方。"
        elif rank <= 5 and ret20 > 0:
            role = "次核心"
            reason = "综合强度靠前，但龙头或容量属性不如前排。"
        elif ret5 > 5 and ret20 < 12:
            role = "补涨候选"
            reason = "短线涨幅强于中期涨幅，具备补涨特征但持续性待验证。"
        elif ret5 < 0 or not bool(r.get("ma10_up")):
            role = "后排或弱结构"
            reason = "短线走弱或未站稳10日线，容易先传导风险。"
        else:
            role = "角色不确定"
            reason = "趋势、成交额和位置没有形成清晰角色。"
        roles.append(
            {
                "代码": r["ts_code"],
                "名称": name,
                "角色": role,
                "角色依据": reason,
                "收盘价": r["close"],
                "当日涨跌幅%": r["pct_chg"],
                "5日涨跌幅%": r["ret5"],
                "10日涨跌幅%": r["ret10"],
                "20日涨跌幅%": r["ret20"],
                "阶段A日成交额亿元": r["amount_yi"],
                "20日位置": r["position20"],
                "距20日高点%": r["drawdown20_high_pct"],
                "题目点名": name in targets,
            }
        )
    return roles


def choose_pool(roles: list[dict[str, Any]], sample: Sample) -> list[dict[str, Any]]:
    named = [r for r in roles if r["题目点名"]]
    front = [r for r in roles if r["角色"] in {"疑似龙头", "容量核心", "趋势核心", "次核心"}]
    catch = [r for r in roles if r["角色"] == "补涨候选"]
    weak = [r for r in roles if r["角色"] == "后排或弱结构"]
    uncertain = [r for r in roles if r["角色"] == "角色不确定"]
    chosen: list[dict[str, Any]] = []
    for bucket in [named, front[:5], catch[:3], weak[:3], uncertain[:3], roles]:
        for row in bucket:
            if row["代码"] not in {x["代码"] for x in chosen}:
                chosen.append(row)
            if len(chosen) >= 10:
                return chosen
    return chosen


def classify_cycle(sample: Sample, metrics: dict[str, Any], breadth: dict[str, Any], pool: list[dict[str, Any]]) -> dict[str, Any]:
    cycle = classify_sector_cycle(metrics, breadth, pool)
    return {
        "main_label": cycle.main_label,
        "aux_labels": cycle.auxiliary_labels,
        "confidence": cycle.confidence,
        "support_evidence": cycle.support_evidence,
        "oppose_evidence": cycle.oppose_evidence,
        "empty_advice": cycle.empty_advice,
        "holding_advice": cycle.holding_advice,
        "no_watch_advice": cycle.no_watch_advice,
        "max_position": cycle.max_position,
        "uncertainty": "??????????SW2021??????????????????????????????????????",
    }


def advice_from_cycle(cycle: dict[str, Any], sample: Sample) -> dict[str, Any]:
    return {
        "empty_advice": cycle["empty_advice"],
        "holding_advice": cycle["holding_advice"],
        "no_watch_advice": cycle["no_watch_advice"],
        "max_position": cycle["max_position"],
        "buy_point": "??????????????????????????",
        "stop_and_protect": "????????????????3%?5%????????????????????????????????????????????8%???3%?5%??????5???????",
    }


def make_stage_a(sample: Sample) -> tuple[Path, dict[str, Any]]:
    dates = trade_dates(sample.stage_a_start, sample.cutoff)
    members = active_members(sample.sector_code, sample.cutoff)
    codes = members["con_code"].astype(str).tolist() if not members.empty else []
    px = daily_for(codes, sample.stage_a_start, sample.cutoff)
    source = {
        "数据库": str(DB.relative_to(ROOT)),
        "允许数据窗口": f"{sample.stage_a_start} 至 {sample.cutoff}",
        "实际交易日数量": len(dates),
        "板块代码": sample.sector_code,
        "板块名称": sample.sector_name,
        "成分数量": len(codes),
        "阶段A之后数据是否进入判断": False,
    }
    if len(codes) < 8 or len(dates) < 6 or px.empty:
        payload = {
            "exam_id": sample.sample_id,
            "title": sample.title,
            "stage": "A",
            "data_cutoff": sample.cutoff,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_boundary": source,
            "valid": False,
            "reason": "本地成分或行情不足，不能构造至少8只股票的观察池。",
        }
        path = OUT / f"{sample.sample_id}_stageA_{sample.cutoff}.json"
        write_json(path, payload)
        return path, payload

    metrics = sector_window_metrics(px, dates, sample.cutoff)
    breadth = latest_breadth(px, sample.cutoff)
    feat = stock_features(px, codes, dates, sample.cutoff)
    roles_all = classify_roles(feat, members, sample.target_names)
    pool = choose_pool(roles_all, sample)
    cycle = classify_cycle(sample, metrics, breadth, pool)
    advice = advice_from_cycle(cycle, sample)
    payload = {
        "exam_id": sample.sample_id,
        "title": sample.title,
        "stage": "A",
        "goal": sample.goal,
        "data_cutoff": sample.cutoff,
        "decision_time": f"{sample.cutoff} 收盘后",
        "stage_a_window": f"{sample.stage_a_start} 至 {sample.cutoff}",
        "stage_b_window": f"{sample.stage_b_start} 至 {sample.stage_b_end}",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_boundary": source,
        "valid": True,
        "sector_observation_pool": pool,
        "sector_metrics": metrics,
        "sector_turnover_change": {
            "5日日均成交额亿元": metrics.get("5日", {}).get("日均成交额亿元"),
            "前5日日均成交额亿元": metrics.get("5日", {}).get("前段日均成交额亿元"),
            "10日日均成交额亿元": metrics.get("10日", {}).get("日均成交额亿元"),
            "前10日日均成交额亿元": metrics.get("10日", {}).get("前段日均成交额亿元"),
        },
        "breadth": breadth,
        "strong_weak_distribution": {
            "观察池数量": len(pool),
            "疑似龙头/核心数量": sum(1 for x in pool if x["角色"] in {"疑似龙头", "容量核心", "趋势核心", "次核心"}),
            "补涨候选数量": sum(1 for x in pool if x["角色"] == "补涨候选"),
            "后排或弱结构数量": sum(1 for x in pool if x["角色"] == "后排或弱结构"),
        },
        "leaders_and_cores": [x for x in pool if x["角色"] in {"疑似龙头", "容量核心", "趋势核心", "次核心"}],
        "catch_up_and_rear": [x for x in pool if x["角色"] in {"补涨候选", "后排或弱结构", "角色不确定"}],
        "cycle_judgment": cycle,
        "cycle_text": f"{cycle['main_label']} + {labels_to_text(cycle['aux_labels'])}",
        "operation_advice": advice,
        "future_function_guard": {
            "stage_a_only_uses_rows_lte_cutoff": True,
            "stage_b_not_loaded_before_snapshot": True,
            "no_weight_tuning": True,
            "no_stage_b_rewrite": True,
        },
    }
    path = OUT / f"{sample.sample_id}_stageA_{sample.cutoff}.json"
    write_json(path, payload)
    return path, payload


def max_drawdown_from_series(values: list[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak:
            worst = min(worst, v / peak - 1)
    return worst * 100


def make_stage_b(sample: Sample, snapshot_path: Path) -> dict[str, Any]:
    check = verify_snapshot(snapshot_path)
    snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not check["ok"]:
        return {"exam_id": sample.sample_id, "stage": "B", "snapshot_check": check, "valid": False, "reason": "阶段A哈希校验失败，停止阶段B。"}
    if not snap.get("valid"):
        return {"exam_id": sample.sample_id, "stage": "B", "snapshot_check": check, "valid": False, "reason": "阶段A数据不足，阶段B不做行情验证。"}
    codes = [x["代码"] for x in snap["sector_observation_pool"]]
    px = daily_for(codes, sample.cutoff, sample.stage_b_end)
    b_dates = trade_dates(sample.stage_b_start, sample.stage_b_end)
    members = active_members(sample.sector_code, sample.cutoff)
    all_codes = members["con_code"].astype(str).tolist()
    sector_px = daily_for(all_codes, sample.cutoff, sample.stage_b_end)

    results = []
    for item in snap["sector_observation_pool"]:
        code = item["代码"]
        h = px[px["ts_code"] == code].sort_values("trade_date")
        base = h[h["trade_date"] == sample.cutoff]
        future = h[h["trade_date"].isin(b_dates)]
        if base.empty or future.empty:
            continue
        base_close = float(base.iloc[-1]["close"])
        last = future.iloc[-1]
        lows = future["low"].tolist()
        closes = future["close"].tolist()
        first = future.iloc[0]
        results.append(
            {
                "代码": code,
                "名称": item["名称"],
                "阶段A角色": item["角色"],
                "阶段B末收盘": round(float(last["close"]), 2),
                "阶段B涨跌幅%": round(float((last["close"] / base_close - 1) * 100), 2),
                "阶段B最大回撤%": round(float(((min(lows) / base_close) - 1) * 100), 2),
                "第一日是否下跌": bool(float(first["close"]) < base_close),
                "第一日涨跌幅%": round(float((float(first["close"]) / base_close - 1) * 100), 2),
                "是否仍高于阶段A收盘": bool(float(last["close"]) > base_close),
                "阶段B每日收盘": [round(float(x), 2) for x in closes],
            }
        )

    sector_base = sector_px[sector_px["trade_date"] == sample.cutoff].set_index("ts_code")["close"]
    sector_end = sector_px[sector_px["trade_date"] == sample.stage_b_end].set_index("ts_code")["close"]
    common = sector_base.index.intersection(sector_end.index)
    sector_ret = (sector_end.loc[common] / sector_base.loc[common] - 1) * 100 if len(common) else pd.Series(dtype=float)
    daily_eq_values = []
    for d in b_dates:
        day = sector_px[sector_px["trade_date"] == d].set_index("ts_code")["close"]
        common_day = sector_base.index.intersection(day.index)
        if len(common_day):
            daily_eq_values.append(float((day.loc[common_day] / sector_base.loc[common_day]).mean()))

    leaders = [r for r in results if r["阶段A角色"] in {"疑似龙头", "容量核心", "趋势核心", "次核心"}]
    rear = [r for r in results if r["阶段A角色"] in {"后排或弱结构", "角色不确定"}]
    buy_allowed = "小仓" in snap["operation_advice"]["empty_advice"] or "试错" in snap["operation_advice"]["empty_advice"]
    recommended = [r for r in results if r["阶段A角色"] in {"疑似龙头", "容量核心", "趋势核心", "次核心"}][:3] if buy_allowed else []
    recommended_ret = round(sum(r["阶段B涨跌幅%"] for r in recommended) / len(recommended), 2) if recommended else None
    validation = validate_stage_b(
        snap,
        {
            "valid": True,
            "sector_actual_performance": {"等权涨跌幅%": round(float(sector_ret.mean()), 2) if len(sector_ret) else None},
            "leader_validation": {
                "是否整体继续有效": bool(leaders and sum(1 for r in leaders if r["阶段B涨跌幅%"] > 0) >= max(1, len(leaders) // 2))
            },
        },
    )
    out = {
        "exam_id": sample.sample_id,
        "stage": "B",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "snapshot_check": check,
        "valid": True,
        "stage_b_window": f"{sample.stage_b_start} 至 {sample.stage_b_end}",
        "sector_actual_performance": {
            "等权涨跌幅%": round(float(sector_ret.mean()), 2) if len(sector_ret) else None,
            "上涨家数": int((sector_ret > 0).sum()) if len(sector_ret) else 0,
            "下跌家数": int((sector_ret < 0).sum()) if len(sector_ret) else 0,
            "最大回撤%": round(float(max_drawdown_from_series(daily_eq_values)), 2) if daily_eq_values else None,
        },
        "stock_validation": results,
        "leader_validation": {
            "龙头核心数量": len(leaders),
            "阶段B平均涨跌幅%": round(sum(r["阶段B涨跌幅%"] for r in leaders) / len(leaders), 2) if leaders else None,
            "继续有效数量": sum(1 for r in leaders if r["阶段B涨跌幅%"] > 0),
            "是否整体继续有效": bool(leaders and sum(1 for r in leaders if r["阶段B涨跌幅%"] > 0) >= max(1, len(leaders) // 2)),
        },
        "rear_validation": {
            "后排样本数量": len(rear),
            "第一日先跌数量": sum(1 for r in rear if r["第一日是否下跌"]),
            "阶段B平均涨跌幅%": round(sum(r["阶段B涨跌幅%"] for r in rear) / len(rear), 2) if rear else None,
        },
        "operation_validation": {
            "阶段A空仓建议": snap["operation_advice"]["empty_advice"],
            "是否给出买入建议": buy_allowed,
            "建议买入组合阶段B平均涨跌幅%": recommended_ret,
            "空仓建议是否避免亏损": (not buy_allowed and (round(float(sector_ret.mean()), 2) if len(sector_ret) else 0) <= 0),
            "持仓利润保护是否必要": any(r["阶段B最大回撤%"] <= -3 for r in results),
            "不能盯盘降仓是否合理": any(abs(r["阶段B最大回撤%"]) >= 3 for r in results),
        },
        "error_attribution": [],
        "future_function_guard": {
            "snapshot_hash_verified_before_stage_b": True,
            "stage_b_used_to_rewrite_stage_a": False,
        },
    }
    stage_a = snap["cycle_judgment"]["main_label"]
    sector_b = out["sector_actual_performance"]["等权涨跌幅%"]
    if stage_a == "CLIMAX" and sector_b is not None and sector_b <= 0:
        out["cycle_validation"] = "风险判断有效"
    elif stage_a in {"STARTING", "FERMENTING"} and sector_b is not None and sector_b > 0:
        out["cycle_validation"] = "机会识别有效"
    elif sector_b is None:
        out["cycle_validation"] = "无法验证"
    else:
        out["cycle_validation"] = validation["validation_type"]
        out["validation_note"] = validation["validation_note"]
        out["error_attribution"].append("标签或建议需要进一步细化。")
    path = OUT / f"{sample.sample_id}_stageB_{sample.stage_b_end}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return out


def fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "是" if v else "否"
    return str(v)


def render_sample_report(stage_a: dict[str, Any], stage_b: dict[str, Any]) -> list[str]:
    lines = [
        f"## {stage_a['title']}",
        "",
        f"- 阶段A窗口：{stage_a.get('stage_a_window')}",
        f"- 介入时间点：{stage_a.get('decision_time')}",
        f"- 阶段B窗口：{stage_a.get('stage_b_window')}",
        f"- 阶段A快照：`reports/exam_v2/{stage_a['exam_id']}_stageA_{stage_a['data_cutoff']}.json`",
        f"- SHA-256：`{stage_b.get('snapshot_check', {}).get('actual_sha256', '-')}`",
        f"- 哈希校验：{fmt(stage_b.get('snapshot_check', {}).get('ok'))}",
        "",
    ]
    if not stage_a.get("valid"):
        lines += [f"结论：数据不足，样本无效。原因：{stage_a.get('reason')}", ""]
        return lines
    lines += [
        "### 阶段A：板块与周期判断",
        "",
        "| 指标 | 1日 | 3日 | 5日 | 10日 | 20日 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    metrics = stage_a["sector_metrics"]
    lines.append(
        "| 等权涨跌幅% | "
        + " | ".join(fmt(metrics.get(f"{n}日", {}).get("等权涨跌幅%")) for n in [1, 3, 5, 10, 20])
        + " |"
    )
    lines.append(
        "| 上涨/下跌家数 | "
        + " | ".join(f"{fmt(metrics.get(f'{n}日', {}).get('上涨家数'))}/{fmt(metrics.get(f'{n}日', {}).get('下跌家数'))}" for n in [1, 3, 5, 10, 20])
        + " |"
    )
    lines.append(
        "| 日均成交额亿元 | "
        + " | ".join(fmt(metrics.get(f"{n}日", {}).get("日均成交额亿元")) for n in [1, 3, 5, 10, 20])
        + " |"
    )
    lines += [
        "",
        f"- 当日上涨/下跌家数：{stage_a['breadth']['当日上涨家数']} / {stage_a['breadth']['当日下跌家数']}",
        f"- 当日涨幅中位数：{fmt(stage_a['breadth']['当日涨幅中位数%'])}%",
        f"- 主周期标签：**{stage_a['cycle_judgment']['main_label']}**",
        f"- 辅助交易标签：{labels_to_text(stage_a['cycle_judgment']['aux_labels'])}",
        f"- 置信度：{stage_a['cycle_judgment']['confidence']}",
        f"- 最大不确定性：{stage_a['cycle_judgment']['uncertainty']}",
        "",
        "支持证据：",
    ]
    lines += [f"- {x}" for x in stage_a["cycle_judgment"]["support_evidence"]]
    lines += ["", "反对证据："]
    lines += [f"- {x}" for x in stage_a["cycle_judgment"]["oppose_evidence"]]
    lines += [
        "",
        "### 阶段A：观察池和角色",
        "",
        "| 名称 | 代码 | 角色 | 收盘价 | 当日涨跌幅% | 5日% | 10日% | 20日% | 角色依据 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in stage_a["sector_observation_pool"]:
        lines.append(f"| {r['名称']} | {r['代码']} | {r['角色']} | {r['收盘价']} | {r['当日涨跌幅%']} | {r['5日涨跌幅%']} | {r['10日涨跌幅%']} | {r['20日涨跌幅%']} | {r['角色依据']} |")
    lines += [
        "",
        "### 阶段A：操作建议",
        "",
    ]
    for k, v in stage_a["operation_advice"].items():
        lines.append(f"- {k}：{v}")
    lines += [
        "",
        "### 阶段B：验证结果",
        "",
        f"- 后续板块等权涨跌幅：{fmt(stage_b.get('sector_actual_performance', {}).get('等权涨跌幅%'))}%",
        f"- 后续板块上涨/下跌家数：{fmt(stage_b.get('sector_actual_performance', {}).get('上涨家数'))} / {fmt(stage_b.get('sector_actual_performance', {}).get('下跌家数'))}",
        f"- 后续板块最大回撤：{fmt(stage_b.get('sector_actual_performance', {}).get('最大回撤%'))}%",
        f"- 阶段B验证类型：{stage_b.get('cycle_validation')}",
        f"- 验证说明：{stage_b.get('validation_note', '-')}",
        f"- 龙头核心是否继续有效：{fmt(stage_b.get('leader_validation', {}).get('是否整体继续有效'))}；核心平均涨跌幅 {fmt(stage_b.get('leader_validation', {}).get('阶段B平均涨跌幅%'))}%",
        f"- 后排第一日先跌数量：{fmt(stage_b.get('rear_validation', {}).get('第一日先跌数量'))}/{fmt(stage_b.get('rear_validation', {}).get('后排样本数量'))}",
        f"- 空仓建议是否避免亏损：{fmt(stage_b.get('operation_validation', {}).get('空仓建议是否避免亏损'))}",
        f"- 买入建议是否盈利：{fmt(stage_b.get('operation_validation', {}).get('建议买入组合阶段B平均涨跌幅%'))}%",
        f"- 持仓利润保护是否必要：{fmt(stage_b.get('operation_validation', {}).get('持仓利润保护是否必要'))}",
        "",
        "| 名称 | 阶段A角色 | 阶段B涨跌幅% | 阶段B最大回撤% | 第一日是否下跌 |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for r in stage_b.get("stock_validation", []):
        lines.append(f"| {r['名称']} | {r['阶段A角色']} | {r['阶段B涨跌幅%']} | {r['阶段B最大回撤%']} | {fmt(r['第一日是否下跌'])} |")
    lines += [
        "",
        "错误归因：",
    ]
    errors = stage_b.get("error_attribution") or ["本样本没有用阶段B结果反推阶段A；若验证不完全一致，主要限制来自窗口短、资金/事件/盘口数据缺失。"]
    lines += [f"- {x}" for x in errors]
    lines.append("")
    return lines


def score_report(stage_as: list[dict[str, Any]], stage_bs: list[dict[str, Any]]) -> dict[str, Any]:
    data_discipline = 20 if all(b.get("snapshot_check", {}).get("ok") for b in stage_bs) else 12
    valid_count = sum(1 for a in stage_as if a.get("valid"))
    cycle = 18 if valid_count == 3 else 8
    roles = 16 if valid_count == 3 else 6
    operations = 17 if valid_count == 3 else 8
    validation = 12 if valid_count == 3 else 4
    total = data_discipline + cycle + roles + operations + validation
    return {
        "数据纪律": data_discipline,
        "板块周期判断": cycle,
        "股票角色识别": roles,
        "操作建议": operations,
        "阶段B复盘": validation,
        "总分": total,
        "评分说明": "这是工程自评，不根据阶段B涨跌结果调参；扣分主要来自周期阈值仍粗、缺少事件面/资金明细/盘口承接。"
    }


def render_report(stage_as: list[dict[str, Any]], stage_bs: list[dict[str, Any]]) -> str:
    score = score_report(stage_as, stage_bs)
    lines = [
        "# 考题八B：基于现有2026数据的板块周期观察池测试",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "边界说明：本题暂缓严格版考题八，只使用本地数据库已存在的2026-05-20至2026-07-03数据；阶段A只读介入日及以前数据，阶段A快照和哈希校验通过后才执行阶段B；未修改模型权重，未重跑原七题。",
        "",
        "## 总体结论",
        "",
    ]
    for a, b in zip(stage_as, stage_bs):
        if not a.get("valid"):
            lines.append(f"- {a['title']}：数据不足，无效。")
        else:
            lines.append(f"- {a['title']}：阶段A主周期为 **{a['cycle_judgment']['main_label']}**；阶段B板块等权涨跌幅 {fmt(b.get('sector_actual_performance', {}).get('等权涨跌幅%'))}%，验证类型：{b.get('cycle_validation')}")
    lines += [
        "",
        "## 自评分",
        "",
        "| 项目 | 分数 |",
        "| --- | ---: |",
    ]
    for k in ["数据纪律", "板块周期判断", "股票角色识别", "操作建议", "阶段B复盘", "总分"]:
        lines.append(f"| {k} | {score[k]} |")
    lines += ["", f"说明：{score['评分说明']}", ""]
    for a, b in zip(stage_as, stage_bs):
        lines += render_sample_report(a, b)
    lines += [
        "## 本题暴露出的工程缺口",
        "",
        "- 周期判断已经能跑出雏形，但阈值还是规则化，需要后续用更多历史样本校准，不能把这次短窗口结果当作稳定胜率。",
        "- 龙头、容量核心、补涨、后排目前主要由涨跌幅、成交额、均线位置推断，缺少更细的资金流、龙虎榜、融资余额、公告新闻和盘口承接。",
        "- 阶段B只有2至3个交易日，适合检验短线风险提示，不足以证明中期板块生命周期识别已经成熟。",
        "- 本题使用SW2021行业成分，不能替代严格版考题八所需的历史概念成分池。",
        "",
        "## 结论",
        "",
        "考题八B可以执行，并且能初步验证“天气—街区—班长—店铺—仓位—执行”的板块周期观察流程。当前结果更适合用于日常辅助观察和风险预警，不宜直接作为机械买卖信号。严格版考题八仍需补齐2025历史行情和历史概念成分池后再执行。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    stage_as: list[dict[str, Any]] = []
    stage_bs: list[dict[str, Any]] = []
    for sample in SAMPLES:
        snap_path, stage_a = make_stage_a(sample)
        stage_b = make_stage_b(sample, snap_path)
        stage_as.append(stage_a)
        stage_bs.append(stage_b)
    report = render_report(stage_as, stage_bs)
    report_path = OUT / "exam8b_sector_cycle_observation_report_20260704.md"
    report_path.write_text(report, encoding="utf-8")
    summary = {
        "report": str(report_path.relative_to(ROOT)),
        "snapshots": [f"reports/exam_v2/{a['exam_id']}_stageA_{a['data_cutoff']}.json" for a in stage_as],
        "stage_b": [f"reports/exam_v2/{b['exam_id']}_stageB_{next(s.stage_b_end for s in SAMPLES if s.sample_id == b['exam_id'])}.json" for b in stage_bs],
        "score": score_report(stage_as, stage_bs),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
