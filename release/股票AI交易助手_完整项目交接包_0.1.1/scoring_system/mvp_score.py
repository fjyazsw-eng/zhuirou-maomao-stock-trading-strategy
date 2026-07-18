from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scoring_system.project_paths import database_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQLITE_PATH = database_path(PROJECT_ROOT)
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "scores"
REPORTS_DIR = PROJECT_ROOT / "reports" / "scoring"
MODEL_VERSION = "1.0.1-mvp1-calibrated"
INDEX_CODES = ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH"]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_table(conn: sqlite3.Connection, table: str) -> pd.DataFrame:
    df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
    for col in ["trade_date", "ts_code", "index_code", "con_code"]:
        if col in df.columns:
            df[col] = df[col].astype("string")
    return df


def latest_date(daily: pd.DataFrame) -> str:
    if daily.empty:
        raise RuntimeError("daily table is empty")
    return str(daily["trade_date"].dropna().astype(str).max())


def previous_trade_date(dates: list[str], as_of: str) -> str | None:
    before = [d for d in sorted(dates) if d < as_of]
    return before[-1] if before else None


def score_band(value: float | int | None, bands: list[dict[str, Any]]) -> tuple[float, str]:
    if value is None or pd.isna(value):
        return 0.0, "missing"
    for band in bands:
        min_value = band.get("min")
        if min_value is None or float(value) >= float(min_value):
            return float(band.get("points", 0)), str(band.get("label", ""))
    return 0.0, "unmatched"


def cumulative_return(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return np.nan
    return float((1 + clean).prod() - 1)


def grade_for(score: float | None, grades: list[dict[str, Any]]) -> str:
    if score is None or pd.isna(score):
        return "数据不足"
    for band in grades:
        min_value = band.get("min")
        if min_value is None or float(score) >= float(min_value):
            return str(band["grade"])
    return "未分级"


def exclude_bj(df: pd.DataFrame, code_col: str = "ts_code") -> pd.DataFrame:
    if df.empty or code_col not in df.columns:
        return df
    return df[~df[code_col].astype(str).str.endswith(".BJ")].copy()


def compute_market(daily: pd.DataFrame, index_daily: pd.DataFrame, as_of: str, cfg: dict[str, Any]) -> dict[str, Any]:
    dates = sorted(daily["trade_date"].dropna().astype(str).unique().tolist())
    last5 = [d for d in dates if d <= as_of][-5:]
    today = exclude_bj(daily[daily["trade_date"].astype(str) == as_of])
    valid_today = today[pd.to_numeric(today["return"], errors="coerce").notna()].copy()
    amount_by_date = exclude_bj(daily[daily["trade_date"].astype(str).isin(last5)]).groupby("trade_date")["amount_yuan"].sum().sort_index()
    market_equal_by_date = exclude_bj(daily[daily["trade_date"].astype(str).isin(last5)]).groupby("trade_date")["return"].mean().sort_index()

    market_amount_today = float(amount_by_date.get(as_of, np.nan))
    amount_5d_avg = float(amount_by_date.mean()) if len(amount_by_date) else np.nan
    amount_vs_5d_avg = market_amount_today / amount_5d_avg if amount_5d_avg and not pd.isna(amount_5d_avg) else np.nan
    up_ratio = float((valid_today["return"] > 0).mean()) if len(valid_today) else np.nan
    market_equal_return = float(valid_today["return"].mean()) if len(valid_today) else np.nan

    idx_window = index_daily[(index_daily["trade_date"].astype(str).isin(last5)) & (index_daily["ts_code"].astype(str).isin(INDEX_CODES))].copy()
    idx_window["return"] = pd.to_numeric(idx_window["return"], errors="coerce")
    idx_today = idx_window[idx_window["trade_date"].astype(str) == as_of].copy()
    index_trend_return = float(idx_today["return"].mean()) if len(idx_today) else np.nan
    index_return_1d = index_trend_return
    last3 = last5[-3:]
    idx_return_3d_by_code = idx_window[idx_window["trade_date"].astype(str).isin(last3)].groupby("ts_code")["return"].apply(cumulative_return)
    idx_return_5d_by_code = idx_window.groupby("ts_code")["return"].apply(cumulative_return)
    index_return_3d = float(idx_return_3d_by_code.mean()) if len(idx_return_3d_by_code) else np.nan
    index_return_5d = float(idx_return_5d_by_code.mean()) if len(idx_return_5d_by_code) else np.nan
    index_trend_composite = (
        index_return_1d * 0.2 + index_return_3d * 0.3 + index_return_5d * 0.5
        if not any(pd.isna(v) for v in [index_return_1d, index_return_3d, index_return_5d])
        else np.nan
    )
    index_positive_ratio = float((idx_today["return"] > 0).mean()) if len(idx_today) else np.nan
    index_dispersion = float(idx_today["return"].max() - idx_today["return"].min()) if len(idx_today) else np.nan
    turnover_quality = amount_vs_5d_avg
    if not pd.isna(turnover_quality) and market_equal_return <= 0:
        turnover_quality = turnover_quality * 0.5

    features = {
        "index_trend_return": index_trend_return,
        "index_return_1d": index_return_1d,
        "index_return_3d": index_return_3d,
        "index_return_5d": index_return_5d,
        "index_trend_composite": index_trend_composite,
        "index_positive_ratio": index_positive_ratio,
        "index_dispersion": index_dispersion,
        "amount_vs_5d_avg": amount_vs_5d_avg,
        "turnover_quality": turnover_quality,
        "up_ratio": up_ratio,
        "market_equal_return": market_equal_return,
        "market_amount_today_yuan": market_amount_today,
        "amount_5d_avg_yuan": amount_5d_avg,
        "up_count": int((valid_today["return"] > 0).sum()) if len(valid_today) else 0,
        "down_count": int((valid_today["return"] < 0).sum()) if len(valid_today) else 0,
        "flat_count": int((valid_today["return"] == 0).sum()) if len(valid_today) else 0,
        "stock_count": int(len(valid_today)),
        "index_count": int(len(idx_today)),
        "last5_dates": last5,
        "market_equal_by_date": {str(k): float(v) for k, v in market_equal_by_date.items()},
    }

    sub_scores = {}
    total = 0.0
    for name, item in cfg["components"].items():
        value = features.get(item["feature"])
        points, label = score_band(value, item["bands"])
        sub_scores[name] = {"score": points, "label": label, "value": None if pd.isna(value) else value, "max_points": item["max_points"]}
        total += points
    data_quality = min(1.0, (len(valid_today) / 5000 if len(valid_today) else 0) * 0.7 + (len(idx_today) / len(INDEX_CODES)) * 0.3)
    return {
        "score": round(total, 2),
        "grade": grade_for(total, cfg["grades"]),
        "sub_scores": sub_scores,
        "features": features,
        "data_quality": round(float(data_quality), 4),
    }


def normalize_date_value(series: pd.Series) -> pd.Series:
    s = series.astype("string").fillna("")
    s = s.str.replace(".0", "", regex=False)
    s = s.replace({"<NA>": "", "nan": "", "None": "", "NaT": ""})
    return s


def active_members(members: pd.DataFrame, classify: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    m = members.copy()
    if m.empty:
        return m
    m["in_date"] = normalize_date_value(m["in_date"])
    m["out_date"] = normalize_date_value(m["out_date"])
    active = m[(m["in_date"] <= trade_date) & ((m["out_date"] == "") | (m["out_date"] > trade_date))].copy()
    l2 = classify[(classify["level"].astype(str) == "L2") & (classify["src"].astype(str) == "SW2021")].copy()
    l2 = l2[["index_code", "industry_name"]].drop_duplicates("index_code")
    active = active.merge(l2, on="index_code", how="left", suffixes=("", "_class"))
    if "industry_name_class" in active.columns:
        active["industry_name"] = active["industry_name_class"].combine_first(active.get("index_name"))
    elif "industry_name" in active.columns:
        active["industry_name"] = active["industry_name"].combine_first(active.get("index_name"))
    else:
        active["industry_name"] = active.get("index_name")
    return active


def sector_daily_metrics(daily: pd.DataFrame, daily_basic: pd.DataFrame, members: pd.DataFrame, classify: pd.DataFrame, trade_date: str, prev_date: str | None, market_amount: float) -> pd.DataFrame:
    active = active_members(members, classify, trade_date)
    if active.empty:
        return pd.DataFrame()
    active = active[~active["con_code"].astype(str).str.endswith(".BJ")].copy()
    day = exclude_bj(daily[daily["trade_date"].astype(str) == trade_date]).copy()
    day = day[["ts_code", "trade_date", "return", "amount_yuan"]].copy()
    merged = active.merge(day, left_on="con_code", right_on="ts_code", how="left")
    if prev_date:
        prev_basic = daily_basic[daily_basic["trade_date"].astype(str) == prev_date][["ts_code", "circ_mv_yuan"]].copy()
        merged = merged.merge(prev_basic.rename(columns={"ts_code": "con_code", "circ_mv_yuan": "circ_mv_t_minus_1_yuan"}), on="con_code", how="left")
    else:
        merged["circ_mv_t_minus_1_yuan"] = np.nan

    rows = []
    for (index_code, industry_name), g in merged.groupby(["index_code", "industry_name"], dropna=False):
        total_constituents = int(g["con_code"].nunique())
        quote = g[pd.to_numeric(g["return"], errors="coerce").notna()].copy()
        quote_count = int(len(quote))
        quote_coverage = quote_count / total_constituents if total_constituents else 0
        equal_return = float(quote["return"].mean()) if quote_count else np.nan
        up_ratio = float((quote["return"] > 0).mean()) if quote_count else np.nan
        amount = float(pd.to_numeric(quote["amount_yuan"], errors="coerce").sum(skipna=True)) if quote_count else np.nan
        amount_share = amount / market_amount if market_amount and not pd.isna(amount) else np.nan
        weighted_pool = quote[pd.to_numeric(quote["circ_mv_t_minus_1_yuan"], errors="coerce").notna() & (pd.to_numeric(quote["circ_mv_t_minus_1_yuan"], errors="coerce") > 0)].copy()
        weighted_mv_coverage = len(weighted_pool) / quote_count if quote_count else 0
        if len(weighted_pool) and weighted_mv_coverage >= 0.7:
            w = pd.to_numeric(weighted_pool["circ_mv_t_minus_1_yuan"], errors="coerce")
            r = pd.to_numeric(weighted_pool["return"], errors="coerce")
            weighted_return = float((r * w).sum() / w.sum()) if w.sum() else np.nan
            return_used = weighted_return
            return_used_type = "weighted_t_minus_1_mv"
        else:
            weighted_return = np.nan
            return_used = equal_return
            return_used_type = "equal_return_fallback"
        formal_allowed = total_constituents >= 5 and quote_coverage >= 0.7
        data_quality = min(quote_coverage, weighted_mv_coverage if return_used_type.startswith("weighted") else quote_coverage)
        if return_used_type == "equal_return_fallback":
            data_quality = min(data_quality, 0.69 if weighted_mv_coverage < 0.7 else data_quality)
        rows.append({
            "trade_date": trade_date,
            "index_code": str(index_code),
            "industry_name": str(industry_name),
            "total_constituents": total_constituents,
            "quote_count": quote_count,
            "quote_coverage": quote_coverage,
            "weighted_mv_coverage": weighted_mv_coverage,
            "weighted_return": weighted_return,
            "equal_return": equal_return,
            "return_used": return_used,
            "return_used_type": return_used_type,
            "amount_yuan": amount,
            "amount_share": amount_share,
            "up_ratio": up_ratio,
            "formal_score_allowed": formal_allowed,
            "data_quality": float(data_quality) if not pd.isna(data_quality) else 0.0,
        })
    return pd.DataFrame(rows)


def compute_sector_scores(daily: pd.DataFrame, daily_basic: pd.DataFrame, members: pd.DataFrame, classify: pd.DataFrame, market: dict[str, Any], as_of: str, cfg: dict[str, Any]) -> pd.DataFrame:
    dates = sorted(daily["trade_date"].dropna().astype(str).unique().tolist())
    last5 = [d for d in dates if d <= as_of][-5:]
    market_amount_by_date = exclude_bj(daily[daily["trade_date"].astype(str).isin(last5)]).groupby("trade_date")["amount_yuan"].sum().to_dict()
    daily_metrics = []
    for d in last5:
        prev = previous_trade_date(dates, d)
        daily_metrics.append(sector_daily_metrics(daily, daily_basic, members, classify, d, prev, float(market_amount_by_date.get(d, np.nan))))
    all_metrics = pd.concat([m for m in daily_metrics if not m.empty], ignore_index=True) if daily_metrics else pd.DataFrame()
    if all_metrics.empty:
        return all_metrics
    market_equal_by_date = market["features"].get("market_equal_by_date", {})
    all_metrics["market_equal_return"] = all_metrics["trade_date"].astype(str).map(market_equal_by_date)
    all_metrics["relative_return_daily"] = all_metrics["return_used"] - all_metrics["market_equal_return"]
    all_metrics["outperform_market"] = all_metrics["equal_return"] > all_metrics["market_equal_return"]
    all_metrics["breadth_ge_50"] = all_metrics["up_ratio"] >= 0.5
    all_metrics = all_metrics.sort_values(["index_code", "trade_date"])
    all_metrics["amount_share_up"] = all_metrics.groupby("index_code")["amount_share"].diff() > 0

    persistence = all_metrics.groupby("index_code").agg(
        outperform_market_days_5d=("outperform_market", "sum"),
        breadth_ge_50_days_5d=("breadth_ge_50", "sum"),
        amount_share_up_days_5d=("amount_share_up", "sum"),
        amount_share_5d_avg=("amount_share", "mean"),
    ).reset_index()
    today = all_metrics[all_metrics["trade_date"].astype(str) == as_of].copy().merge(persistence, on="index_code", how="left")
    today["relative_return"] = today["return_used"] - float(market["features"].get("market_equal_return", np.nan))
    today["amount_share_change_ratio"] = today["amount_share"] / today["amount_share_5d_avg"].replace(0, np.nan)

    rel_rows = []
    for code, g in all_metrics.groupby("index_code"):
        g = g.sort_values("trade_date")
        last_1 = g.tail(1)
        last_3 = g.tail(3)
        last_5 = g.tail(5)
        sector_1d = cumulative_return(last_1["return_used"])
        sector_3d = cumulative_return(last_3["return_used"])
        sector_5d = cumulative_return(last_5["return_used"])
        market_1d = cumulative_return(last_1["market_equal_return"])
        market_3d = cumulative_return(last_3["market_equal_return"])
        market_5d = cumulative_return(last_5["market_equal_return"])
        rel_1d = sector_1d - market_1d
        rel_3d = sector_3d - market_3d
        rel_5d = sector_5d - market_5d
        rel_rows.append({
            "index_code": code,
            "sector_return_1d": sector_1d,
            "sector_return_3d": sector_3d,
            "sector_return_5d": sector_5d,
            "market_return_1d": market_1d,
            "market_return_3d": market_3d,
            "market_return_5d": market_5d,
            "relative_return_1d": rel_1d,
            "relative_return_3d": rel_3d,
            "relative_return_5d": rel_5d,
            "relative_strength_composite": rel_1d * 0.2 + rel_3d * 0.3 + rel_5d * 0.5,
        })
    today = today.merge(pd.DataFrame(rel_rows), on="index_code", how="left")

    scores = []
    for row in today.to_dict(orient="records"):
        sub = {}
        total = 0.0
        if not row["formal_score_allowed"]:
            score_value = None
            grade = "数据不足"
        else:
            for name, item in cfg["components"].items():
                if "bands" in item:
                    value = row.get(item["feature"])
                    points, label = score_band(value, item["bands"])
                    if name == "amount_concentration" and (pd.isna(row.get("return_used")) or row.get("return_used") <= 0):
                        points = min(points, 6.0)
                        label = f"{label}_capped_by_nonpositive_return"
                    sub[name] = {"score": points, "label": label, "value": None if pd.isna(value) else value, "max_points": item["max_points"]}
                    total += points
                else:
                    sub_total = 0.0
                    detail = {}
                    for sf, sf_cfg in item["subfeatures"].items():
                        value = row.get(sf)
                        points, label = score_band(value, sf_cfg["bands"])
                        detail[sf] = {"score": points, "label": label, "value": None if pd.isna(value) else int(value), "max_points": sf_cfg["max_points"]}
                        sub_total += points
                    sub[name] = {"score": sub_total, "detail": detail, "max_points": item["max_points"]}
                    total += sub_total
            score_value = round(total, 2)
            grade = grade_for(score_value, cfg["grades"])
        row["score"] = score_value
        row["grade"] = grade
        row["sub_scores_json"] = json.dumps(sub, ensure_ascii=False)
        row["risk_tips"] = build_sector_risk_tip(row)
        scores.append(row)
    result = pd.DataFrame(scores)
    return result.sort_values(["score", "data_quality"], ascending=[False, False], na_position="last")


def build_sector_risk_tip(row: dict[str, Any]) -> str:
    tips = []
    if not row.get("formal_score_allowed"):
        tips.append("数据覆盖不足，不输出正式评分")
    if float(row.get("quote_coverage") or 0) < 0.7:
        tips.append("行情覆盖率低于70%")
    if row.get("return_used_type") == "equal_return_fallback":
        tips.append("T-1流通市值覆盖不足，已改用等权收益")
    if float(row.get("up_ratio") or 0) < 0.4:
        tips.append("板块扩散度偏弱")
    base = "基础行情风险：" + ("；".join(tips) if tips else "未触发")
    return base + "；事件风险：未检查或数据缺失"


def write_outputs(as_of: str, market: dict[str, Any], sectors: pd.DataFrame) -> dict[str, str]:
    SCORES_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = SCORES_DIR / f"sector_scores_{as_of}_calibrated.csv"
    json_path = SCORES_DIR / f"market_sector_score_{as_of}_calibrated.json"
    md_path = REPORTS_DIR / f"market_sector_score_{as_of}_calibrated.md"

    csv_cols = [
        "trade_date", "index_code", "industry_name", "score", "grade", "relative_return", "relative_strength_composite",
        "relative_return_1d", "relative_return_3d", "relative_return_5d", "amount_share", "amount_share_5d_avg",
        "amount_share_change_ratio", "up_ratio",
        "outperform_market_days_5d", "breadth_ge_50_days_5d", "amount_share_up_days_5d", "quote_coverage", "weighted_mv_coverage",
        "return_used_type", "formal_score_allowed", "data_quality", "risk_tips", "sub_scores_json",
    ]
    sectors[csv_cols].to_csv(csv_path, index=False, encoding="utf-8-sig")

    top10 = sectors[sectors["formal_score_allowed"] == True].head(10).copy()
    sector_records = json.loads(sectors.replace({np.nan: None}).to_json(orient="records", force_ascii=False))
    payload = {
        "as_of_date": as_of,
        "model_version": MODEL_VERSION,
        "data_quality": {
            "market": market["data_quality"],
            "sector_min_top10": float(top10["data_quality"].min()) if len(top10) else None,
            "formal_score_allowed": bool(market["data_quality"] >= 0.7 and len(top10) > 0),
        },
        "market_score": market,
        "sector_rankings": sector_records,
        "top10_sectors": json.loads(top10.replace({np.nan: None}).to_json(orient="records", force_ascii=False)),
        "leader_candidates": [],
        "stock_scores": [],
        "risk_flags": list(sectors[~sectors["risk_tips"].str.startswith("基础行情风险：未触发")]["risk_tips"].drop_duplicates().head(20)),
        "missing_fields": infer_missing_fields(market, sectors),
        "source_status": {
            "daily": "ok",
            "daily_basic": "ok_or_partial",
            "index_daily": "ok_or_partial",
            "index_classify": "ok",
            "index_member": "ok",
            "announcements": "not_used_in_mvp1",
        },
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 市场与申万L2板块评分 {as_of}",
        "",
        f"模型版本：{MODEL_VERSION}",
        f"市场评分：{market['score']:.2f}；等级：{market['grade']}；数据质量：{market['data_quality']:.2%}",
        "",
        "## 市场特征",
        f"- 指数1/3/5日综合趋势：{fmt_pct(market['features']['index_trend_composite'])}",
        f"- 指数1日/3日/5日表现：{fmt_pct(market['features']['index_return_1d'])} / {fmt_pct(market['features']['index_return_3d'])} / {fmt_pct(market['features']['index_return_5d'])}",
        f"- 全市场成交额/5日均值：{fmt_num(market['features']['amount_vs_5d_avg'])}",
        f"- 上涨家数占比：{fmt_pct(market['features']['up_ratio'])}",
        f"- 全市场等权收益：{fmt_pct(market['features']['market_equal_return'])}",
        f"- 上涨/下跌/平盘：{market['features']['up_count']} / {market['features']['down_count']} / {market['features']['flat_count']}",
        "",
        "## 前10名申万L2板块",
        "| 排名 | 板块 | 评分 | 等级 | 综合相对强度 | 成交占比变化 | 成交占比 | 扩散度 | 跑赢天数 | 扩散>=50%天数 | 成交占比上升天数 | 风险提示 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i, row in enumerate(top10.itertuples(index=False), start=1):
        lines.append(
            f"| {i} | {row.industry_name} | {row.score:.2f} | {row.grade} | {fmt_pct(row.relative_strength_composite)} | {fmt_num(row.amount_share_change_ratio)} | {fmt_pct(row.amount_share)} | {fmt_pct(row.up_ratio)} | {int(row.outperform_market_days_5d)} | {int(row.breadth_ge_50_days_5d)} | {int(row.amount_share_up_days_5d)} | {row.risk_tips} |"
        )
    lines.extend([
        "",
        "## 数据缺失和风险提示",
    ])
    missing = infer_missing_fields(market, sectors)
    if missing:
        lines.extend([f"- {m}" for m in missing])
    else:
        lines.append("- 核心字段未发现阻断性缺失。")
    lines.extend([
        "",
        "说明：MVP Phase 1 不使用主力资金、平台龙头标签、人气排名、新闻热度和公告评分。",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "markdown": str(md_path)}


def infer_missing_fields(market: dict[str, Any], sectors: pd.DataFrame) -> list[str]:
    missing = []
    if market["features"].get("index_count", 0) < len(INDEX_CODES):
        missing.append("核心指数行情不足4个指数。")
    if len(sectors) == 0:
        missing.append("申万L2板块聚合结果为空。")
    if len(sectors) and (sectors["return_used_type"] == "equal_return_fallback").any():
        missing.append("部分板块缺少T-1流通市值覆盖，市值加权收益降级为等权收益。")
    if len(sectors) and (sectors["formal_score_allowed"] == False).any():
        missing.append("部分板块因有效成分数或行情覆盖率不足未输出正式评分。")
    return missing


def fmt_pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "缺失"
    return f"{float(value) * 100:.2f}%"


def fmt_num(value: Any) -> str:
    if value is None or pd.isna(value):
        return "缺失"
    return f"{float(value):.3f}"


def run_score(as_of: str | None = None) -> dict[str, Any]:
    if not SQLITE_PATH.exists():
        raise RuntimeError(f"SQLite not found: {SQLITE_PATH}")
    market_cfg = load_yaml(PROJECT_ROOT / "config" / "market_score.yaml")
    sector_cfg = load_yaml(PROJECT_ROOT / "config" / "sector_score.yaml")
    with sqlite3.connect(SQLITE_PATH) as conn:
        daily = read_table(conn, "daily")
        daily_basic = read_table(conn, "daily_basic")
        index_daily = read_table(conn, "index_daily")
        classify = read_table(conn, "index_classify")
        members = read_table(conn, "index_member")
    if as_of is None:
        as_of = latest_date(daily)
    market = compute_market(daily, index_daily, as_of, market_cfg)
    sectors = compute_sector_scores(daily, daily_basic, members, classify, market, as_of, sector_cfg)
    paths = write_outputs(as_of, market, sectors)
    result = {"as_of_date": as_of, "market_score": market["score"], "market_grade": market["grade"], "sector_count": int(len(sectors)), "paths": paths}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()
    run_score(args.as_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



