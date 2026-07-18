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

from scoring_system.mvp_score import active_members, cumulative_return, grade_for, score_band


ROOT = Path(__file__).resolve().parents[1]
SQLITE = ROOT / "data" / "sqlite" / "market_120d.sqlite"
SCORES = ROOT / "data" / "processed" / "scores"
REPORTS = ROOT / "reports" / "scoring"
MODEL_VERSION = "1.0.0-stock-mvp"
DEFAULT_STOCKS = ["002409.SZ", "600206.SH", "688037.SH", "300346.SZ", "688019.SH", "300655.SZ"]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_table(conn: sqlite3.Connection, table: str) -> pd.DataFrame:
    df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
    for col in ["trade_date", "ts_code", "index_code", "con_code", "list_date"]:
        if col in df.columns:
            df[col] = df[col].astype("string")
    return df


def band_score_range(value: float | int | None, bands: list[dict[str, Any]]) -> tuple[float, str]:
    if value is None or pd.isna(value):
        return 0.0, "missing"
    x = float(value)
    for band in bands:
        min_value = band.get("min")
        max_value = band.get("max")
        if min_value is None:
            return float(band.get("points", 0)), str(band.get("label", ""))
        if x >= float(min_value) and (max_value is None or x <= float(max_value)):
            return float(band.get("points", 0)), str(band.get("label", ""))
    for band in bands:
        if band.get("min") is None:
            return float(band.get("points", 0)), str(band.get("label", ""))
    return 0.0, "unmatched"


def close_position(df: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    span = (high - low).replace(0, np.nan)
    return (close - low) / span


def upper_shadow_ratio(df: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    open_ = pd.to_numeric(df["open"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    span = (high - low).replace(0, np.nan)
    return (high - pd.concat([open_, close], axis=1).max(axis=1)) / span


def percentile_last(values: pd.Series, latest: float) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty or pd.isna(latest):
        return np.nan
    return float((clean <= latest).mean())


def stock_sector_map(members: pd.DataFrame, classify: pd.DataFrame, as_of: str) -> pd.DataFrame:
    active = active_members(members, classify, as_of)
    active = active[~active["con_code"].astype(str).str.endswith(".BJ")].copy()
    return active[["index_code", "industry_name", "con_code"]].drop_duplicates()


def sector_equal_returns(daily: pd.DataFrame, members: pd.DataFrame, classify: pd.DataFrame, as_of: str, dates: list[str]) -> pd.DataFrame:
    active = stock_sector_map(members, classify, as_of)
    day = daily[daily["trade_date"].astype(str).isin(dates)][["ts_code", "trade_date", "return"]].copy()
    merged = active.merge(day, left_on="con_code", right_on="ts_code", how="inner")
    return merged.groupby(["index_code", "trade_date"])["return"].mean().reset_index(name="sector_equal_return")


def select_default_stocks(leader: pd.DataFrame) -> list[str]:
    selected = list(DEFAULT_STOCKS)
    for sector in ["半导体", "电子化学品Ⅱ"]:
        pool = leader[leader["sector_name"].astype(str) == sector].sort_values("score", ascending=True)
        for code in pool["ts_code"].astype(str).head(2):
            if code not in selected:
                selected.append(code)
    weak = leader.sort_values("score", ascending=True)
    for code in weak["ts_code"].astype(str).head(3):
        if code not in selected:
            selected.append(code)
            break
    return selected


def score_stock(
    code: str,
    as_of: str,
    daily: pd.DataFrame,
    daily_basic: pd.DataFrame,
    stock_basic: pd.DataFrame,
    sector_map: pd.DataFrame,
    sector_returns: pd.DataFrame,
    market: dict[str, Any],
    sectors: pd.DataFrame,
    leader: pd.DataFrame,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    risks: list[str] = []
    advantages: list[str] = []
    wait_conditions: list[str] = []
    terminate_conditions: list[str] = []

    if cfg["filters"].get("exclude_bj", True) and code.endswith(".BJ"):
        return insufficient_row(code, as_of, "北交所股票暂不纳入第一版")

    hist = daily[(daily["ts_code"].astype(str) == code) & (daily["trade_date"].astype(str) <= as_of)].copy().sort_values("trade_date")
    basic_hist = daily_basic[(daily_basic["ts_code"].astype(str) == code) & (daily_basic["trade_date"].astype(str) <= as_of)].copy().sort_values("trade_date")
    if len(hist) < cfg["filters"]["min_valid_days"] or len(hist.tail(5)) < cfg["filters"]["min_valid_days_5d"]:
        return insufficient_row(code, as_of, "有效行情不足")

    hist = hist.tail(30).copy()
    for col in ["open", "high", "low", "close", "return", "amount_yuan"]:
        hist[col] = pd.to_numeric(hist[col], errors="coerce")
    hist["close_position"] = close_position(hist)
    hist["upper_shadow"] = upper_shadow_ratio(hist)
    hist["ma5"] = hist["close"].rolling(5).mean()
    hist["ma10"] = hist["close"].rolling(10).mean()
    hist["ma20"] = hist["close"].rolling(20).mean()
    today = hist[hist["trade_date"].astype(str) == as_of]
    if today.empty:
        return insufficient_row(code, as_of, "当日无行情，可能停牌")
    today = today.iloc[0]
    last5 = hist.tail(5)
    last10 = hist.tail(10)
    last20 = hist.tail(20)

    basic_today = basic_hist[basic_hist["trade_date"].astype(str) == as_of].tail(1)
    stock_info = stock_basic[stock_basic["ts_code"].astype(str) == code].head(1)
    name = str(stock_info["name"].iloc[0]) if len(stock_info) and "name" in stock_info.columns else code
    list_date = str(stock_info["list_date"].iloc[0]) if len(stock_info) and "list_date" in stock_info.columns else ""
    data_quality = 1.0
    if list_date and list_date.isdigit():
        age_days = (datetime.strptime(as_of, "%Y%m%d") - datetime.strptime(list_date, "%Y%m%d")).days
        if age_days < cfg["filters"]["new_stock_calendar_days"]:
            data_quality = min(data_quality, 0.69)
            risks.append("上市不足60日")

    smap = sector_map[sector_map["con_code"].astype(str) == code].head(1)
    sector_code = str(smap["index_code"].iloc[0]) if len(smap) else ""
    sector_name = str(smap["industry_name"].iloc[0]) if len(smap) else "未知板块"
    sector_row = sectors[sectors["index_code"].astype(str) == sector_code].head(1)
    sector_grade = str(sector_row["grade"].iloc[0]) if len(sector_row) else "缺失"
    sector_score = float(sector_row["score"].iloc[0]) if len(sector_row) and not pd.isna(sector_row["score"].iloc[0]) else np.nan
    leader_row = leader[leader["ts_code"].astype(str) == code].head(1)
    leader_score = float(leader_row["score"].iloc[0]) if len(leader_row) else np.nan
    leader_labels = str(leader_row["candidate_labels"].iloc[0]) if len(leader_row) else "非核心候选"

    sector_ret = sector_returns[sector_returns["index_code"].astype(str) == sector_code].sort_values("trade_date")
    sector_5d = cumulative_return(sector_ret.tail(5)["sector_equal_return"]) if len(sector_ret) else np.nan
    stock_3d = cumulative_return(hist.tail(3)["return"])
    stock_5d = cumulative_return(last5["return"])
    stock_10d = cumulative_return(last10["return"])
    stock_20d = cumulative_return(last20["return"])
    rel_sector_5d = stock_5d - sector_5d if not pd.isna(sector_5d) else np.nan

    trend_score, trend_detail = score_trend(today, hist, stock_3d, stock_5d, cfg, risks, advantages)
    vp_score, vp_detail = score_volume_price(today, hist, last5, basic_today, cfg, risks, advantages)
    position_score, position_detail = score_position(today, last5, last10, last20, stock_5d, stock_10d, stock_20d, cfg, risks, advantages, wait_conditions)
    tradability_score, tradability_detail = score_tradability(today, last5, basic_today, cfg, risks, advantages)

    detect_risks(today, hist, last5, stock_5d, sector_5d, rel_sector_5d, sector_grade, cfg, risks, wait_conditions, terminate_conditions)
    total = round(float(trend_score + vp_score + position_score + tradability_score), 2)

    status = execution_status(total, risks, market, sector_grade, leader_labels, cfg)
    if status == "READY":
        advantages.append("趋势、量价、位置和可交易性整体匹配")
    if "非核心候选" in leader_labels:
        wait_conditions.append("非核心候选，需要更强的个股确认")
    if status in {"WAIT_PULLBACK", "OVERHEATED"}:
        wait_conditions.append("等待乖离率和成交热度回落")
    if status in {"WEAK_STRUCTURE", "AVOID"}:
        terminate_conditions.append("重新站回MA10/MA20前不做主动执行")

    if market["market_score"] < cfg["status_rules"]["market_score_ready_floor"] and status == "READY":
        status = "WAIT_CONFIRM"
        wait_conditions.append("市场低于门控阈值，READY降级为WAIT_CONFIRM")
    if not sector_grade.startswith(("A", "B", "C")) and status == "READY":
        status = "WAIT_CONFIRM"
        wait_conditions.append("板块低于C级，READY降级为WAIT_CONFIRM")

    return {
        "trade_date": as_of,
        "ts_code": code,
        "name": name,
        "sector_code": sector_code,
        "sector_name": sector_name,
        "market_score": market["market_score"],
        "market_grade": market["market_grade"],
        "sector_score": None if pd.isna(sector_score) else sector_score,
        "sector_grade": sector_grade,
        "leader_score": None if pd.isna(leader_score) else leader_score,
        "leader_labels": leader_labels,
        "stock_score": total,
        "grade": grade_for(total, cfg["grades"]),
        "trend_structure_score": trend_score,
        "volume_price_quality_score": vp_score,
        "position_heat_score": position_score,
        "tradability_score": tradability_score,
        "execution_status": status,
        "basic_risk": "基础行情风险：" + ("；".join(dict.fromkeys(risks)) if risks else "未触发"),
        "event_risk": "事件风险：未检查或数据缺失",
        "data_quality": round(data_quality, 4),
        "advantages": "；".join(dict.fromkeys(advantages)) or "暂无突出优势",
        "wait_or_stop_conditions": "；".join(dict.fromkeys(wait_conditions + terminate_conditions)) or "按既定风控观察",
        "sub_scores_json": json.dumps({
            "trend_structure": trend_detail,
            "volume_price_quality": vp_detail,
            "position_heat": position_detail,
            "tradability": tradability_detail,
        }, ensure_ascii=False),
    }


def insufficient_row(code: str, as_of: str, reason: str) -> dict[str, Any]:
    return {
        "trade_date": as_of,
        "ts_code": code,
        "name": code,
        "sector_code": "",
        "sector_name": "未知",
        "market_score": None,
        "market_grade": "缺失",
        "sector_score": None,
        "sector_grade": "缺失",
        "leader_score": None,
        "leader_labels": "非核心候选",
        "stock_score": None,
        "grade": "数据不足",
        "trend_structure_score": 0,
        "volume_price_quality_score": 0,
        "position_heat_score": 0,
        "tradability_score": 0,
        "execution_status": "DATA_INSUFFICIENT",
        "basic_risk": f"基础行情风险：{reason}",
        "event_risk": "事件风险：未检查或数据缺失",
        "data_quality": 0,
        "advantages": "无",
        "wait_or_stop_conditions": reason,
        "sub_scores_json": "{}",
    }


def score_trend(today: pd.Series, hist: pd.DataFrame, stock_3d: float, stock_5d: float, cfg: dict[str, Any], risks: list[str], advantages: list[str]) -> tuple[float, dict[str, Any]]:
    c = cfg["components"]["trend_structure"]
    close = float(today["close"])
    ma5, ma10, ma20 = float(today["ma5"]), float(today["ma10"]), float(today["ma20"])
    ma_position = int(close > ma5) + int(close > ma10) + int(close > ma20)
    ma_alignment = int(ma5 > ma10) + int(ma10 > ma20)
    recent_direction = int(stock_3d > 0) + int(stock_5d > 0)
    low20, high20 = float(hist.tail(20)["low"].min()), float(hist.tail(20)["high"].max())
    range_pos = (close - low20) / (high20 - low20) if high20 > low20 else np.nan
    items = {
        "ma_position": ma_position,
        "ma_alignment": ma_alignment,
        "recent_direction": recent_direction,
        "high_low_structure": range_pos,
    }
    total = 0.0
    detail = {}
    for key, value in items.items():
        pts, label = score_band(value, c["subfeatures"][key]["bands"])
        detail[key] = {"score": pts, "value": value, "label": label}
        total += pts
    if close < ma20:
        total = min(total, float(c["break_ma20_cap"]))
        risks.append("跌破MA20")
    elif close < ma10:
        total = min(total, float(c["break_ma10_cap"]))
        risks.append("跌破MA10")
    if ma_position == 3 and ma_alignment == 2:
        advantages.append("均线结构多头")
    return round(total, 2), detail


def score_volume_price(today: pd.Series, hist: pd.DataFrame, last5: pd.DataFrame, basic_today: pd.DataFrame, cfg: dict[str, Any], risks: list[str], advantages: list[str]) -> tuple[float, dict[str, Any]]:
    c = cfg["components"]["volume_price_quality"]
    amount_avg5 = float(last5["amount_yuan"].mean())
    amount_ratio = float(today["amount_yuan"] / amount_avg5) if amount_avg5 else np.nan
    close_pos = float(today["close_position"])
    vol_price_days = int(((hist.tail(3)["return"] > 0) & (hist.tail(3)["amount_yuan"] >= hist.tail(5)["amount_yuan"].mean())).sum())
    turnover = np.nan
    if len(basic_today):
        turnover = float(pd.to_numeric(basic_today["turnover_rate"], errors="coerce").iloc[0])
    values = {
        "amount_vs_5d_avg": amount_ratio,
        "close_position": close_pos,
        "volume_price_3d": vol_price_days,
        "turnover_quality": turnover,
    }
    total = 0.0
    detail = {}
    for key, value in values.items():
        pts, label = band_score_range(value, c["subfeatures"][key]["bands"])
        detail[key] = {"score": pts, "value": value, "label": label}
        total += pts
    if today["return"] < 0 and amount_ratio >= 1.3:
        total = min(total, float(c["volume_down_cap"]))
        risks.append("放量下跌")
    if abs(float(today["return"])) <= 0.01 and amount_ratio >= 1.8:
        total = min(total, float(c["stagnation_cap"]))
        risks.append("放量滞涨")
    if amount_ratio >= 1.8 and close_pos <= 0.45:
        total = min(total, float(c["weak_close_expansion_cap"]))
        risks.append("放量但收盘位置弱")
    if today["return"] > 0 and 1.0 <= amount_ratio <= 2.5 and close_pos >= 0.55:
        advantages.append("量价配合较好")
    return round(total, 2), detail


def score_position(today: pd.Series, last5: pd.DataFrame, last10: pd.DataFrame, last20: pd.DataFrame, r5: float, r10: float, r20: float, cfg: dict[str, Any], risks: list[str], advantages: list[str], wait_conditions: list[str]) -> tuple[float, dict[str, Any]]:
    c = cfg["components"]["position_heat"]
    close = float(today["close"])
    bias_ma5 = close / float(today["ma5"]) - 1 if today["ma5"] else np.nan
    bias_ma10 = close / float(today["ma10"]) - 1 if today["ma10"] else np.nan
    price_pct = percentile_last(last20["close"], close)
    amount_pct = percentile_last(last20["amount_yuan"], float(today["amount_yuan"]))
    values = {
        "ma_distance": bias_ma10,
        "short_return_heat": r5,
        "price_percentile_20d": price_pct,
        "amount_percentile_20d": amount_pct,
    }
    total = 0.0
    detail = {}
    for key, value in values.items():
        pts, label = band_score_range(value, c["subfeatures"][key]["bands"])
        detail[key] = {"score": pts, "value": value, "label": label}
        total += pts
    over = c["overheat_rules"]
    if (
        bias_ma5 >= over["bias_ma5_min"]
        or r5 >= over["return_5d_min"]
        or (price_pct >= over["price_percentile_20d_min"] and amount_pct >= over["amount_percentile_20d_min"])
    ):
        risks.append("位置过热")
        wait_conditions.append("等待价格贴近MA5/MA10或成交热度降温")
    if 0 <= bias_ma10 <= 0.08 and 0.45 <= price_pct <= 0.85:
        advantages.append("位置相对合理")
    return round(total, 2), detail


def score_tradability(today: pd.Series, last5: pd.DataFrame, basic_today: pd.DataFrame, cfg: dict[str, Any], risks: list[str], advantages: list[str]) -> tuple[float, dict[str, Any]]:
    c = cfg["components"]["tradability"]
    amount = float(today["amount_yuan"])
    circ_mv = np.nan
    if len(basic_today):
        circ_mv = float(pd.to_numeric(basic_today["circ_mv_yuan"], errors="coerce").iloc[0])
    amount_mean = float(last5["amount_yuan"].mean())
    amount_std = float(last5["amount_yuan"].std())
    stability = 1 - amount_std / amount_mean if amount_mean else np.nan
    values = {"amount_liquidity": amount, "market_cap": circ_mv, "amount_stability_5d": stability}
    total = 0.0
    detail = {}
    for key, value in values.items():
        pts, label = score_band(value, c["subfeatures"][key]["bands"])
        detail[key] = {"score": pts, "value": value, "label": label}
        total += pts
    if amount < cfg["risk_rules"]["low_liquidity"]["amount_yuan_min"]:
        risks.append("流动性不足")
    if amount >= 300000000:
        advantages.append("成交额满足执行流动性")
    return round(total, 2), detail


def detect_risks(today: pd.Series, hist: pd.DataFrame, last5: pd.DataFrame, stock_5d: float, sector_5d: float, rel_sector_5d: float, sector_grade: str, cfg: dict[str, Any], risks: list[str], wait_conditions: list[str], terminate_conditions: list[str]) -> None:
    r = cfg["risk_rules"]
    amount_ratio = float(today["amount_yuan"] / last5["amount_yuan"].mean()) if last5["amount_yuan"].mean() else np.nan
    if today["return"] <= r["volume_down"]["return_max"] and amount_ratio >= r["volume_down"]["amount_vs_5d_avg_min"]:
        risks.append("放量下跌")
        terminate_conditions.append("放量下跌后等待重新转强")
    if today["close_position"] <= r["high_fade"]["close_position_max"] and today["upper_shadow"] >= r["high_fade"]["upper_shadow_min"]:
        risks.append("冲高回落")
    fade_days = int(((hist.tail(r["consecutive_high_fade"]["days_lookback"])["close_position"] <= r["high_fade"]["close_position_max"]) & (hist.tail(r["consecutive_high_fade"]["days_lookback"])["upper_shadow"] >= r["high_fade"]["upper_shadow_min"])).sum())
    if fade_days >= r["consecutive_high_fade"]["min_days"]:
        risks.append("连续冲高回落")
    if abs(float(today["return"])) <= r["stagnation"]["abs_return_max"] and amount_ratio >= r["stagnation"]["amount_vs_5d_avg_min"] and today["close_position"] <= r["stagnation"]["close_position_max"]:
        risks.append("放量滞涨")
    if float(today["close"]) < float(today["ma10"]):
        risks.append("跌破MA10")
    if float(today["close"]) < float(today["ma20"]):
        risks.append("跌破MA20")
    high5, low5 = float(last5["high"].max()), float(last5["low"].min())
    if low5 and (high5 / low5 - 1) >= r["volatility_5d"]["max_range"]:
        risks.append("最近5日波动过大")
    if today["return"] >= r["single_day_spike"]["return_min"] and today["close_position"] >= r["single_day_spike"]["close_position_min"]:
        risks.append("单日异动待确认")
        wait_conditions.append("等待次日承接确认")
    if any(str(sector_grade).startswith(p) for p in r["lagging_strong_sector"]["sector_grade_prefix"]) and rel_sector_5d <= r["lagging_strong_sector"]["relative_to_sector_5d_max"]:
        risks.append("板块强但个股明显落后")
    if stock_5d >= r["independent_move"]["stock_return_5d_min"] and (pd.isna(sector_5d) or sector_5d <= r["independent_move"]["sector_return_5d_max"]):
        risks.append("个股独涨但板块不同步")


def execution_status(total: float, risks: list[str], market: dict[str, Any], sector_grade: str, leader_labels: str, cfg: dict[str, Any]) -> str:
    s = cfg["status_rules"]
    if "流动性不足" in risks:
        return s["low_liquidity_status"]
    if "放量下跌" in risks:
        return s["volume_down_status"]
    if "跌破MA20" in risks:
        return s["break_ma20_status"]
    if "跌破MA10" in risks:
        return s["break_ma10_status"]
    if "位置过热" in risks:
        return s["pullback_when_overheated_and_strong"] if total >= s["wait_confirm_min_score"] else s["overheat_status"]
    if total >= s["ready_min_score"]:
        return "READY"
    if total >= s["wait_confirm_min_score"]:
        return "WAIT_CONFIRM"
    if total <= s["weak_structure_max_score"]:
        return "AVOID" if "板块强但个股明显落后" in risks else "WEAK_STRUCTURE"
    return "WAIT_CONFIRM"


def load_upstream(as_of: str) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    market_json = SCORES / f"market_sector_score_{as_of}_calibrated.json"
    market_payload = json.loads(market_json.read_text(encoding="utf-8"))
    market = {"market_score": float(market_payload["market_score"]["score"]), "market_grade": market_payload["market_score"]["grade"]}
    sectors = pd.read_csv(SCORES / f"sector_scores_{as_of}_calibrated.csv", dtype={"index_code": "string"})
    leader = pd.read_csv(SCORES / f"leader_scores_{as_of}.csv", dtype={"sector_code": "string"})
    return market, sectors, leader


def write_outputs(as_of: str, rows: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, str]:
    SCORES.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    csv_path = SCORES / f"stock_scores_{as_of}.csv"
    json_path = SCORES / f"stock_scores_{as_of}.json"
    md_path = REPORTS / f"stock_score_{as_of}.md"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    payload = {
        "as_of_date": as_of,
        "model_version": MODEL_VERSION,
        "config_version": cfg.get("version"),
        "stock_scores": json.loads(df.replace({np.nan: None}).to_json(orient="records", force_ascii=False)),
        "risk_note": "基础行情风险由行情触发；事件风险未检查或数据缺失。",
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# 个股执行评分MVP {as_of}",
        "",
        f"模型版本：{MODEL_VERSION}",
        "说明：市场、板块、龙头只作为执行门控，不重复计入个股100分。",
        "",
        "| 股票 | 代码 | 板块 | 市场等级 | 板块等级 | 龙头分/分类 | 执行分 | 趋势 | 量价 | 位置 | 可交易 | 状态 | 风险 | 主要优势 | 等待或终止条件 |",
        "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|",
    ]
    for row in rows:
        leader_text = f"{row['leader_score'] if row['leader_score'] is not None else '无'} / {row['leader_labels']}"
        lines.append(
            f"| {row['name']} | {row['ts_code']} | {row['sector_name']} | {row['market_grade']} | {row['sector_grade']} | {leader_text} | {'' if row['stock_score'] is None else f'{row['stock_score']:.2f}'} | {row['trend_structure_score']:.2f} | {row['volume_price_quality_score']:.2f} | {row['position_heat_score']:.2f} | {row['tradability_score']:.2f} | {row['execution_status']} | {row['basic_risk']}；{row['event_risk']} | {row['advantages']} | {row['wait_or_stop_conditions']} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"csv": str(csv_path), "json": str(json_path), "markdown": str(md_path)}


def run_stock_score(as_of: str = "20260630", stocks: list[str] | None = None, no_api: bool = True) -> dict[str, Any]:
    cfg = load_yaml(ROOT / "config" / "stock_score.yaml")
    market, sectors, leader = load_upstream(as_of)
    if stocks is None:
        stocks = select_default_stocks(leader)
    with sqlite3.connect(SQLITE) as conn:
        daily = read_table(conn, "daily")
        daily_basic = read_table(conn, "daily_basic")
        stock_basic = read_table(conn, "stock_basic")
        members = read_table(conn, "index_member")
        classify = read_table(conn, "index_classify")
    dates = sorted(daily["trade_date"].dropna().astype(str).unique().tolist())
    dates = [d for d in dates if d <= as_of][-30:]
    sector_map = stock_sector_map(members, classify, as_of)
    sector_returns = sector_equal_returns(daily, members, classify, as_of, dates)
    rows = [score_stock(code, as_of, daily, daily_basic, stock_basic, sector_map, sector_returns, market, sectors, leader, cfg) for code in stocks]
    paths = write_outputs(as_of, rows, cfg)
    df = pd.DataFrame(rows)
    result = {
        "as_of_date": as_of,
        "stock_count": int(len(df)),
        "max_score": None if df["stock_score"].dropna().empty else float(df["stock_score"].max()),
        "full_score_count": int((pd.to_numeric(df["stock_score"], errors="coerce") >= 100).sum()),
        "status_counts": df["execution_status"].value_counts().to_dict(),
        "paths": paths,
        "no_api": no_api,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default="20260630")
    parser.add_argument("--stocks", default="")
    parser.add_argument("--no-api", action="store_true", help="显式离线运行；本脚本不会调用Tushare")
    args = parser.parse_args()
    stocks = [s.strip() for s in args.stocks.split(",") if s.strip()] or None
    run_stock_score(args.as_of, stocks, no_api=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
