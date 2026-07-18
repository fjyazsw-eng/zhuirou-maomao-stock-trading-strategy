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

from scoring_system.mvp_score import active_members, cumulative_return, grade_for, score_band


ROOT = Path(__file__).resolve().parents[1]
SQLITE = database_path(ROOT)
SCORES = ROOT / "data" / "processed" / "scores"
REPORTS = ROOT / "reports" / "scoring"
MODEL_VERSION = "1.0.0-leader-mvp"
DEFAULT_TEST_SECTORS = ["半导体", "电子化学品Ⅱ", "军工电子Ⅱ", "光学光电子"]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_table(conn: sqlite3.Connection, table: str) -> pd.DataFrame:
    df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
    for col in ["trade_date", "ts_code", "index_code", "con_code", "list_date"]:
        if col in df.columns:
            df[col] = df[col].astype("string")
    return df


def sector_score_path(as_of: str) -> Path:
    calibrated = SCORES / f"sector_scores_{as_of}_calibrated.csv"
    plain = SCORES / f"sector_scores_{as_of}.csv"
    return calibrated if calibrated.exists() else plain


def select_target_sectors(sectors: pd.DataFrame, explicit_names: list[str]) -> pd.DataFrame:
    b_or_above = sectors[sectors["grade"].astype(str).str.startswith(("A", "B"))].copy()
    explicit = sectors[sectors["industry_name"].astype(str).isin(explicit_names)].copy()
    return pd.concat([b_or_above, explicit], ignore_index=True).drop_duplicates("index_code")


def close_position(df: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    span = (high - low).replace(0, np.nan)
    return (close - low) / span


def rank_percentile(values: pd.Series) -> pd.Series:
    n = values.notna().sum()
    if n == 0:
        return pd.Series(np.nan, index=values.index)
    rank = values.rank(method="min", ascending=False, na_option="bottom")
    return ((n - rank + 1) / n).clip(lower=0, upper=1)


def classify_candidate(row: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    labels = []
    classes = cfg.get("candidate_classes", {})
    s = classes.get("sentiment_leader", {})
    if (
        row["score"] >= s.get("min_total_score", 999)
        and row["relative_sector_strength_score"] >= s.get("min_relative_score", 999)
        and row["stock_sector_sync_score"] >= s.get("min_sync_score", 999)
        and row["persistence_3_5d_score"] >= s.get("min_persistence_score", 999)
    ):
        labels.append(s.get("label", "情绪龙头"))
    s = classes.get("liquidity_core", {})
    if (
        row["score"] >= s.get("min_total_score", 999)
        and row["amount_position_score"] >= s.get("min_amount_score", 999)
        and row["amount_percentile_5d"] >= s.get("min_amount_percentile_5d", 999)
    ):
        labels.append(s.get("label", "容量核心"))
    s = classes.get("trend_core", {})
    if (
        row["score"] >= s.get("min_total_score", 999)
        and row["relative_return_3d"] >= s.get("min_relative_return_3d", 999)
        and row["relative_return_5d"] >= s.get("min_relative_return_5d", 999)
        and row["persistence_3_5d_score"] >= s.get("min_persistence_score", 999)
    ):
        labels.append(s.get("label", "趋势核心"))
    return labels


def score_sector_leaders(
    sector_row: pd.Series,
    daily: pd.DataFrame,
    stock_basic: pd.DataFrame,
    members: pd.DataFrame,
    classify: pd.DataFrame,
    dates: list[str],
    as_of: str,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    active = active_members(members, classify, as_of)
    active = active[active["index_code"].astype(str) == str(sector_row["index_code"])].copy()
    if cfg["filters"].get("exclude_bj", True):
        active = active[~active["con_code"].astype(str).str.endswith(".BJ")].copy()
    codes = active["con_code"].dropna().astype(str).unique().tolist()
    if not codes:
        return pd.DataFrame()

    window = daily[(daily["trade_date"].astype(str).isin(dates)) & (daily["ts_code"].astype(str).isin(codes))].copy()
    if window.empty:
        return pd.DataFrame()
    for col in ["return", "amount_yuan", "open", "high", "low", "close"]:
        window[col] = pd.to_numeric(window[col], errors="coerce")
    window["close_position"] = close_position(window)

    sector_by_date = window.groupby("trade_date").agg(
        sector_equal_return=("return", "mean"),
        sector_amount_yuan=("amount_yuan", "sum"),
        sector_up_ratio=("return", lambda x: float((x > 0).mean())),
    ).reset_index()
    window = window.merge(sector_by_date, on="trade_date", how="left")
    window["amount_percentile_1d_by_date"] = window.groupby("trade_date")["amount_yuan"].transform(rank_percentile)
    avg5 = window.groupby("ts_code")["amount_yuan"].mean().rename("amount_5d_avg").reset_index()
    today_amount_rank = avg5.copy()
    today_amount_rank["amount_percentile_5d"] = rank_percentile(today_amount_rank["amount_5d_avg"])
    window = window.merge(today_amount_rank, on="ts_code", how="left")

    rows = []
    for code, g in window.groupby("ts_code"):
        g = g.sort_values("trade_date")
        if len(g) < cfg["filters"].get("min_valid_days_5d", 5):
            continue
        last1 = g.tail(1)
        last3 = g.tail(3)
        last5 = g.tail(5)
        today = last1.iloc[0]
        stock_1d = cumulative_return(last1["return"])
        stock_3d = cumulative_return(last3["return"])
        stock_5d = cumulative_return(last5["return"])
        sector_1d = cumulative_return(last1["sector_equal_return"])
        sector_3d = cumulative_return(last3["sector_equal_return"])
        sector_5d = cumulative_return(last5["sector_equal_return"])
        rel_1d = stock_1d - sector_1d
        rel_3d = stock_3d - sector_3d
        rel_5d = stock_5d - sector_5d
        weights = cfg["components"]["relative_sector_strength"]["weights"]
        rel_comp = rel_1d * weights["relative_return_1d"] + rel_3d * weights["relative_return_3d"] + rel_5d * weights["relative_return_5d"]
        rel_score, rel_label = score_band(rel_comp, cfg["components"]["relative_sector_strength"]["bands"])
        spike = cfg["components"]["relative_sector_strength"].get("single_day_spike", {})
        flags = []
        if rel_1d >= spike.get("one_day_min", 999) and rel_3d <= spike.get("three_day_max", -999) and rel_5d <= spike.get("five_day_max", -999):
            rel_score = min(rel_score, float(spike.get("cap_points", rel_score)))
            flags.append("单日异动待确认")

        amount_share = float(today["amount_yuan"] / today["sector_amount_yuan"]) if today["sector_amount_yuan"] else np.nan
        amount_cfg = cfg["components"]["amount_position"]
        share_score = min(amount_share / amount_cfg.get("amount_share_scale", 0.08), 1.0) if not pd.isna(amount_share) else np.nan
        amount_composite = (
            float(today["amount_percentile_1d_by_date"]) * amount_cfg["weights"]["amount_percentile_1d"]
            + float(today["amount_percentile_5d"]) * amount_cfg["weights"]["amount_percentile_5d"]
            + float(share_score) * amount_cfg["weights"]["amount_share_score"]
        )
        amount_score, amount_label = score_band(amount_composite, amount_cfg["bands"])
        weak_cap = amount_cfg.get("weak_close_cap", {})
        if today["return"] <= weak_cap.get("return_max", -999) or today["close_position"] <= weak_cap.get("close_position_max", -999):
            amount_score = min(amount_score, float(weak_cap.get("cap_points", amount_score)))
            if today["amount_yuan"] > g["amount_yuan"].mean():
                flags.append("放量但收盘表现偏弱")

        outperform_days = int((last5["return"] > last5["sector_equal_return"]).sum())
        up_days = int((last5["return"] > 0).sum())
        amount_avg = float(last5["amount_yuan"].mean())
        amount_above_days = int((last5["amount_yuan"] > amount_avg).sum())
        same_direction = bool((stock_3d >= 0 and stock_5d >= 0) or (stock_3d < 0 and stock_5d < 0))
        persistence_cfg = cfg["components"]["persistence_3_5d"]
        persistence_score = 0.0
        persistence_detail = {}
        for key, value in [
            ("outperform_sector_days_5d", outperform_days),
            ("up_days_5d", up_days),
            ("amount_above_own_5d_avg_days", amount_above_days),
        ]:
            pts, label = score_band(value, persistence_cfg["subfeatures"][key]["bands"])
            persistence_detail[key] = {"score": pts, "value": value, "label": label}
            persistence_score += pts
        same_cfg = persistence_cfg["subfeatures"]["return_3_5_same_direction"]
        same_pts = float(same_cfg["true_points"] if same_direction else same_cfg["false_points"])
        persistence_detail["return_3_5_same_direction"] = {"score": same_pts, "value": same_direction}
        persistence_score += same_pts

        sync_cfg = cfg["components"]["stock_sector_sync"]
        stock_up = last5[last5["return"] > 0].copy()
        if len(stock_up):
            sync_ratio = float(((stock_up["sector_equal_return"] > 0) & (stock_up["sector_up_ratio"] >= sync_cfg["min_sector_breadth_for_sync"])).mean())
        else:
            sync_ratio = 0.0
        sync_score, sync_label = score_band(sync_ratio, sync_cfg["bands"])
        if sync_ratio < 0.4 and stock_5d > sector_5d:
            flags.append("独立行情")
        if sector_5d > 0 and stock_5d < sector_5d:
            flags.append("板块强但个股落后")

        total = round(float(rel_score + amount_score + persistence_score + sync_score), 2)
        basic = stock_basic[stock_basic["ts_code"].astype(str) == code].head(1)
        name = str(basic["name"].iloc[0]) if len(basic) and "name" in basic.columns else code
        list_date = str(basic["list_date"].iloc[0]) if len(basic) and "list_date" in basic.columns else ""
        data_quality = min(1.0, len(last5) / 5)
        if list_date and list_date.isdigit():
            age_days = (datetime.strptime(as_of, "%Y%m%d") - datetime.strptime(list_date, "%Y%m%d")).days
            if age_days < cfg["filters"].get("new_stock_calendar_days", 60):
                data_quality = min(data_quality, 0.69)
                flags.append("上市不足60日")

        row = {
            "trade_date": as_of,
            "sector_code": str(sector_row["index_code"]),
            "sector_name": str(sector_row["industry_name"]),
            "sector_score": float(sector_row["score"]),
            "sector_grade": str(sector_row["grade"]),
            "ts_code": code,
            "name": name,
            "score": total,
            "grade": grade_for(total, cfg["grades"]),
            "relative_sector_strength_score": rel_score,
            "amount_position_score": amount_score,
            "persistence_3_5d_score": persistence_score,
            "stock_sector_sync_score": sync_score,
            "relative_return_1d": rel_1d,
            "relative_return_3d": rel_3d,
            "relative_return_5d": rel_5d,
            "relative_strength_composite": rel_comp,
            "amount_percentile_1d": float(today["amount_percentile_1d_by_date"]),
            "amount_percentile_5d": float(today["amount_percentile_5d"]),
            "amount_share": amount_share,
            "outperform_sector_days_5d": outperform_days,
            "up_days_5d": up_days,
            "amount_above_own_5d_avg_days": amount_above_days,
            "return_3_5_same_direction": same_direction,
            "sync_ratio": sync_ratio,
            "data_quality": round(float(data_quality), 4),
            "basic_risk": "基础行情风险：" + ("；".join(flags) if flags else "未触发"),
            "event_risk": "事件风险：未检查或数据缺失",
            "sub_scores_json": json.dumps({
                "relative_sector_strength": {"score": rel_score, "label": rel_label, "value": rel_comp},
                "amount_position": {"score": amount_score, "label": amount_label, "value": amount_composite},
                "persistence_3_5d": {"score": persistence_score, "detail": persistence_detail},
                "stock_sector_sync": {"score": sync_score, "label": sync_label, "value": sync_ratio},
            }, ensure_ascii=False),
        }
        row["candidate_labels"] = "、".join(classify_candidate(row, cfg)) or "观察"
        rows.append(row)
    return pd.DataFrame(rows)


def write_outputs(as_of: str, leaders: pd.DataFrame, selected_sectors: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, str]:
    SCORES.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    csv_path = SCORES / f"leader_scores_{as_of}.csv"
    json_path = SCORES / f"leader_scores_{as_of}.json"
    md_path = REPORTS / f"leader_score_{as_of}.md"
    out = leaders.sort_values(["sector_score", "sector_code", "score"], ascending=[False, True, False]).copy()
    out.to_csv(csv_path, index=False, encoding="utf-8-sig")
    payload = {
        "as_of_date": as_of,
        "model_version": MODEL_VERSION,
        "config_version": cfg.get("version"),
        "selected_sectors": json.loads(selected_sectors.replace({np.nan: None}).to_json(orient="records", force_ascii=False)),
        "leader_candidates": json.loads(out.replace({np.nan: None}).to_json(orient="records", force_ascii=False)),
        "risk_note": "基础行情风险由行情触发；事件风险未检查或数据缺失。",
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 龙头评分MVP {as_of}",
        "",
        f"模型版本：{MODEL_VERSION}",
        "事件风险：未检查或数据缺失。",
        "",
    ]
    for sector in selected_sectors.sort_values("score", ascending=False).itertuples(index=False):
        block = out[out["sector_code"].astype(str) == str(sector.index_code)].head(5)
        lines.extend([
            f"## {sector.industry_name}（板块评分 {float(sector.score):.2f}，{sector.grade}）",
            "",
            "| 排名 | 股票 | 代码 | 总分 | 相对强度 | 成交额地位 | 持续性 | 同步性 | 标签 | 数据质量 | 风险提示 |",
            "|---:|---|---|---:|---:|---:|---:|---:|---|---:|---|",
        ])
        for i, row in enumerate(block.itertuples(index=False), start=1):
            lines.append(
                f"| {i} | {row.name} | {row.ts_code} | {row.score:.2f} | {row.relative_sector_strength_score:.2f} | {row.amount_position_score:.2f} | {row.persistence_3_5d_score:.2f} | {row.stock_sector_sync_score:.2f} | {row.candidate_labels} | {row.data_quality:.2%} | {row.basic_risk}；{row.event_risk} |"
            )
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"csv": str(csv_path), "json": str(json_path), "markdown": str(md_path)}


def run_leader_score(as_of: str = "20260630", explicit_names: list[str] | None = None) -> dict[str, Any]:
    cfg = load_yaml(ROOT / "config" / "leader_score.yaml")
    explicit_names = explicit_names or DEFAULT_TEST_SECTORS
    with sqlite3.connect(SQLITE) as conn:
        daily = read_table(conn, "daily")
        stock_basic = read_table(conn, "stock_basic")
        members = read_table(conn, "index_member")
        classify = read_table(conn, "index_classify")
    sector_scores = pd.read_csv(sector_score_path(as_of), dtype={"index_code": "string"})
    target = select_target_sectors(sector_scores, explicit_names)
    dates = sorted(daily["trade_date"].dropna().astype(str).unique().tolist())
    dates = [d for d in dates if d <= as_of][-5:]
    if len(dates) < 5:
        raise RuntimeError(f"Need at least 5 trading days before {as_of}, got {len(dates)}")
    frames = []
    for _, sector in target.iterrows():
        frame = score_sector_leaders(sector, daily, stock_basic, members, classify, dates, as_of, cfg)
        if not frame.empty:
            frames.append(frame.sort_values("score", ascending=False).head(20))
    leaders = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    paths = write_outputs(as_of, leaders, target, cfg)
    result = {
        "as_of_date": as_of,
        "sector_count": int(len(target)),
        "candidate_count": int(len(leaders)),
        "max_score": None if leaders.empty else float(leaders["score"].max()),
        "full_score_count": 0 if leaders.empty else int((leaders["score"] >= 100).sum()),
        "paths": paths,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default="")
    parser.add_argument("--sectors", default=",".join(DEFAULT_TEST_SECTORS))
    args = parser.parse_args()
    if not args.as_of:
        from scoring_system.report_freshness import freshness_snapshot

        args.as_of = freshness_snapshot().get("sector_score_date", "") or freshness_snapshot().get("market_score_date", "")
    names = [s.strip() for s in args.sectors.split(",") if s.strip()]
    run_leader_score(args.as_of, names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
