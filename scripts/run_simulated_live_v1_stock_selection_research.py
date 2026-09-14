from __future__ import annotations
from scoring_system.tushare_client import credential_marker

import argparse
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "reports" / "simulated_live_v1" / "review"
RAW_DIR = ROOT / "data" / "raw" / "tushare"
STOCK_BASIC_FILE = RAW_DIR / "stock_basic" / "stock_basic.csv"
SW_CLASSIFY_FILE = RAW_DIR / "index_classify" / "industry_classify_SW2021_L2.csv"
SW_MEMBER_DIR = RAW_DIR / "index_member" / "SW2021_L2"
INDEX_CODES = {
    "上证指数": "000001.SH",
    "深证成指": "399001.SZ",
    "创业板指": "399006.SZ",
    "科创50": "000688.SH",
    "北证50": "899050.BJ",
}
WINDOWS = [1, 3, 5, 10, 20, 60, 120]
RECENT_DAYS_FOR_DAILY = 25


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_tushare_pro() -> Any:
    load_dotenv()
    token = credential_marker() or credential_marker()
    if not token:
        raise RuntimeError("HITHINK_FINANCE_API_KEY 缺失，无法执行真实行情研究。")
    try:
        from scoring_system.network_env import clear_bad_tushare_proxy
    except Exception:
        clear_bad_tushare_proxy = None
    if clear_bad_tushare_proxy:
        clear_bad_tushare_proxy()
    from scoring_system import tushare_client as ts

    return ts.pro_api(token)


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def safe_float(value: Any, digits: int = 2) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        return round(float(value), digits)
    except Exception:
        return None


def latest_completed_trade_date(pro: Any) -> tuple[str, list[str]]:
    today = datetime.now().strftime("%Y%m%d")
    cal = pro.trade_cal(exchange="SSE", start_date="20251201", end_date=today, is_open="1")
    if cal is None or cal.empty:
        raise RuntimeError("trade_cal 未返回可用交易日。")
    dates = sorted(cal["cal_date"].astype(str).tolist())
    return dates[-1], dates


def get_trade_window(open_dates: list[str], end_date: str, needed_days: int) -> list[str]:
    usable = [d for d in open_dates if d <= end_date]
    if len(usable) < needed_days:
        raise RuntimeError(f"交易日不足：需要 {needed_days} 个，实际仅 {len(usable)} 个。")
    return usable[-needed_days:]


def anchor_dates(trade_dates: list[str]) -> dict[int, str]:
    latest_idx = len(trade_dates) - 1
    result = {0: trade_dates[latest_idx]}
    for window in WINDOWS:
        result[window] = trade_dates[latest_idx - window]
    return result


def fetch_daily_by_dates(pro: Any, dates: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for trade_date in dates:
        df = pro.daily(trade_date=trade_date)
        if df is None or df.empty:
            continue
        frames.append(df)
    if not frames:
        raise RuntimeError("daily 未返回任何行情数据。")
    daily = pd.concat(frames, ignore_index=True)
    numeric_cols = ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"]
    for col in numeric_cols:
        if col in daily.columns:
            daily[col] = pd.to_numeric(daily[col], errors="coerce")
    daily["trade_date"] = daily["trade_date"].astype(str)
    return daily


def fetch_latest_daily_basic(pro: Any, trade_date: str) -> pd.DataFrame:
    try:
        df = pro.daily_basic(
            trade_date=trade_date,
            fields="ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,total_share,float_share,free_share,total_mv,circ_mv,pe,pb",
        )
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    for col in ["turnover_rate", "turnover_rate_f", "volume_ratio", "total_share", "float_share", "free_share", "total_mv", "circ_mv", "pe", "pb"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trade_date"] = df["trade_date"].astype(str)
    return df


def fetch_latest_moneyflow(pro: Any, trade_date: str) -> pd.DataFrame:
    try:
        df = pro.moneyflow(
            trade_date=trade_date,
            fields="ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,net_mf_amount",
        )
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    for col in [c for c in df.columns if c.endswith("_amount") or c == "net_mf_amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trade_date"] = df["trade_date"].astype(str)
    return df


def fetch_index_history(pro: Any, start_date: str, end_date: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for name, ts_code in INDEX_CODES.items():
        try:
            df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        df = df.copy()
        df["index_name"] = name
        frames.append(df)
    if not frames:
        raise RuntimeError("index_daily 未返回指数行情。")
    out = pd.concat(frames, ignore_index=True)
    for col in ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out["trade_date"] = out["trade_date"].astype(str)
    return out


def load_sector_members(as_of: str) -> pd.DataFrame:
    classify = read_csv(SW_CLASSIFY_FILE)[["index_code", "industry_name"]]
    frames: list[pd.DataFrame] = []
    for path in sorted(SW_MEMBER_DIR.glob("members_*.csv")):
        df = read_csv(path)
        if df.empty:
            continue
        df["in_date"] = df["in_date"].fillna("00000000").astype(str)
        df["out_date"] = df["out_date"].fillna("").astype(str)
        active = df[(df["in_date"] <= as_of) & ((df["out_date"] == "") | (df["out_date"] >= as_of))].copy()
        if not active.empty:
            frames.append(active[["index_code", "con_code", "con_name"]])
    if not frames:
        raise RuntimeError("本地 SW2021_L2 成分映射为空。")
    members = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["index_code", "con_code"])
    members = members.merge(classify, on="index_code", how="left")
    members.rename(columns={"con_code": "ts_code", "con_name": "name", "industry_name": "sector"}, inplace=True)
    return members


def load_stock_basic() -> pd.DataFrame:
    stock_basic = read_csv(STOCK_BASIC_FILE)[["ts_code", "name", "industry", "list_date"]]
    stock_basic["list_date"] = stock_basic["list_date"].astype(str)
    return stock_basic


def add_return_columns(latest_df: pd.DataFrame, close_pivot: pd.DataFrame, anchors: dict[int, str]) -> pd.DataFrame:
    out = latest_df.copy()
    latest_date = anchors[0]
    latest_close = close_pivot[latest_date].rename("latest_close")
    out = out.merge(latest_close, left_on="ts_code", right_index=True, how="left")
    for window in WINDOWS:
        start_date = anchors[window]
        start_close = close_pivot[start_date].rename(f"start_close_{window}d")
        out = out.merge(start_close, left_on="ts_code", right_index=True, how="left")
        denom = out[f"start_close_{window}d"].replace(0, pd.NA)
        out[f"pct_chg_{window}d"] = ((out["latest_close"] / denom) - 1.0) * 100.0
    out["pct_chg_1d"] = pd.to_numeric(out["pct_chg"], errors="coerce")
    return out


def calc_market_weather(index_history: pd.DataFrame, anchors: dict[int, str], latest_daily: pd.DataFrame, recent_daily: pd.DataFrame) -> dict[str, Any]:
    index_summary: dict[str, Any] = {}
    latest_date = anchors[0]
    idx_pivot = index_history.pivot_table(index="trade_date", columns="index_name", values="close").sort_index()
    for index_name in idx_pivot.columns:
        item: dict[str, Any] = {}
        for window in [1, 3, 5, 10, 20]:
            start_date = anchors[window]
            start_close = idx_pivot.at[start_date, index_name] if start_date in idx_pivot.index else None
            end_close = idx_pivot.at[latest_date, index_name] if latest_date in idx_pivot.index else None
            item[f"pct_chg_{window}d"] = safe_float(((end_close / start_close) - 1.0) * 100.0) if start_close and end_close else None
        index_summary[index_name] = item

    up_count = int((latest_daily["pct_chg"] > 0).sum())
    down_count = int((latest_daily["pct_chg"] < 0).sum())
    total_count = max(len(latest_daily), 1)
    up_ratio = up_count / total_count

    recent_amount = recent_daily[recent_daily["trade_date"].isin(list(anchors.values())[:5])]["amount"].sum()
    prev_dates = sorted(recent_daily["trade_date"].unique().tolist())[-10:-5]
    prev_amount = recent_daily[recent_daily["trade_date"].isin(prev_dates)]["amount"].sum() if prev_dates else 0.0
    amount_change_pct = ((recent_amount / prev_amount) - 1.0) * 100.0 if prev_amount else None

    avg_idx_5d = pd.Series([item["pct_chg_5d"] for item in index_summary.values() if item["pct_chg_5d"] is not None]).mean()
    avg_idx_20d = pd.Series([item["pct_chg_20d"] for item in index_summary.values() if item["pct_chg_20d"] is not None]).mean()

    if avg_idx_5d >= 4 and up_ratio >= 0.62:
        risk_level = "MAINLINE_EXTENSION"
        attack_level = "AGGRESSIVE"
    elif avg_idx_5d >= 1.5 and up_ratio >= 0.55:
        risk_level = "STRONG_REPAIR"
        attack_level = "MODERATE"
    elif avg_idx_20d > 0 and up_ratio >= 0.48:
        risk_level = "NEUTRAL"
        attack_level = "MODERATE"
    elif avg_idx_5d > -2 and up_ratio >= 0.42:
        risk_level = "WEAK_REPAIR"
        attack_level = "CAUTIOUS"
    else:
        risk_level = "RISK_OFF"
        attack_level = "OBSERVE_ONLY"

    return {
        "latest_completed_trade_date": latest_date,
        "index_performance": index_summary,
        "up_count": up_count,
        "down_count": down_count,
        "up_ratio": safe_float(up_ratio * 100),
        "total_amount_latest_yi": safe_float(latest_daily["amount"].sum() / 100000),
        "amount_change_pct_5d_vs_prev5d": safe_float(amount_change_pct),
        "market_risk_level": risk_level,
        "attack_level": attack_level,
    }


def build_sector_table(
    enriched_latest: pd.DataFrame,
    recent_daily: pd.DataFrame,
    sector_members: pd.DataFrame,
    market_weather: dict[str, Any],
) -> pd.DataFrame:
    latest_trade_date = market_weather["latest_completed_trade_date"]
    merged = enriched_latest.copy()
    if "sector" not in merged.columns:
        merged = merged.merge(sector_members[["ts_code", "sector"]], on="ts_code", how="left")
    merged = merged[merged["sector"].notna()].copy()

    recent = recent_daily.merge(sector_members[["ts_code", "sector"]], on="ts_code", how="left")
    recent = recent[recent["sector"].notna()].copy()
    recent_dates = sorted(recent["trade_date"].unique().tolist())
    last5 = recent_dates[-5:]
    prev5 = recent_dates[-10:-5]

    rows: list[dict[str, Any]] = []
    for sector, sector_df in merged.groupby("sector"):
        member_count = int(len(sector_df))
        if member_count < 5:
            continue
        recent_sector = recent[recent["sector"] == sector].copy()
        last_day_amount = recent_sector[recent_sector["trade_date"] == latest_trade_date]["amount"].sum()
        avg_5_amount = recent_sector[recent_sector["trade_date"].isin(last5)]["amount"].sum() / max(len(last5), 1)
        prev_5_amount = recent_sector[recent_sector["trade_date"].isin(prev5)]["amount"].sum() / max(len(prev5), 1) if prev5 else None
        amount_change = ((avg_5_amount / prev_5_amount) - 1.0) * 100.0 if prev_5_amount not in (None, 0) else None
        up_ratio = float((sector_df["pct_chg_1d"] > 0).mean())
        strong_count = int(((sector_df["pct_chg_5d"] >= 8) & (sector_df["pct_chg_1d"] >= 0)).sum())
        rel_1 = sector_df["pct_chg_1d"].mean()
        rel_3 = sector_df["pct_chg_3d"].mean()
        rel_5 = sector_df["pct_chg_5d"].mean()
        rel_10 = sector_df["pct_chg_10d"].mean()
        rel_20 = sector_df["pct_chg_20d"].mean()
        rel_60 = sector_df["pct_chg_60d"].mean()
        persistence = sum(
            [
                rel_3 > 0,
                rel_5 > 0,
                rel_10 > 0,
                up_ratio >= 0.55,
                strong_count >= max(2, member_count * 0.06),
            ]
        )
        score = (
            rel_1 * 0.10
            + rel_3 * 0.15
            + rel_5 * 0.20
            + rel_10 * 0.15
            + rel_20 * 0.15
            + rel_60 * 0.10
            + (amount_change or 0) * 0.05
            + up_ratio * 100 * 0.10
        )
        if rel_20 >= 18 and up_ratio < 0.52:
            state = "OVERHEATED"
        elif rel_10 >= 6 and rel_20 >= 10 and up_ratio >= 0.58:
            state = "MAINLINE"
        elif rel_5 >= 3 and rel_10 >= 0 and amount_change is not None and amount_change >= 8:
            state = "STARTING"
        elif rel_20 > 0:
            state = "REPAIR"
        elif rel_5 > -2:
            state = "WEAK"
        else:
            state = "RETREAT"
        next_mainline_candidate = state in {"STARTING", "MAINLINE", "REPAIR"} and persistence >= 3
        rows.append(
            {
                "sector": sector,
                "member_count": member_count,
                "pct_chg_1d": safe_float(rel_1),
                "pct_chg_3d": safe_float(rel_3),
                "pct_chg_5d": safe_float(rel_5),
                "pct_chg_10d": safe_float(rel_10),
                "pct_chg_20d": safe_float(rel_20),
                "pct_chg_60d": safe_float(rel_60),
                "amount_change_pct": safe_float(amount_change),
                "latest_amount_yi": safe_float(last_day_amount / 100000),
                "up_ratio": safe_float(up_ratio * 100),
                "strong_stock_count": strong_count,
                "persistence_score": persistence,
                "sector_state": state,
                "next_mainline_candidate": next_mainline_candidate,
                "composite_score": safe_float(score),
            }
        )
    sector_table = pd.DataFrame(rows).sort_values(
        by=["next_mainline_candidate", "composite_score", "pct_chg_5d", "pct_chg_20d"],
        ascending=[False, False, False, False],
    )
    return sector_table


def classify_leader_type(row: pd.Series) -> str:
    ret20 = row.get("pct_chg_20d") or -999
    ret5 = row.get("pct_chg_5d") or -999
    turnover = row.get("turnover_rate") or 0
    latest_amount = row.get("amount") or 0
    dist_ma5 = abs(row.get("distance_to_ma5_pct") or 0)
    if ret20 >= 25 and ret5 >= 8 and turnover >= 8:
        return "ABSOLUTE_LEADER"
    if ret20 >= 15 and dist_ma5 <= 8:
        return "TREND_LEADER"
    if latest_amount >= 300000 and ret10_or_zero(row) >= 8:
        return "CAPACITY_CORE"
    if ret5 >= 10 and turnover >= 12:
        return "ELASTIC_LEADER"
    if ret20 <= 8 and ret5 >= 3:
        return "LOW_POSITION_REPAIR"
    return "FOLLOWER"


def ret10_or_zero(row: pd.Series) -> float:
    value = row.get("pct_chg_10d")
    return float(value) if value is not None and not pd.isna(value) else 0.0


def score_stock(row: pd.Series, sector_strength: float) -> float:
    ret3 = row.get("pct_chg_3d") or 0
    ret5 = row.get("pct_chg_5d") or 0
    ret10 = row.get("pct_chg_10d") or 0
    ret20 = row.get("pct_chg_20d") or 0
    turnover = row.get("turnover_rate") or 0
    amount = row.get("amount") or 0
    dist_ma5 = abs(row.get("distance_to_ma5_pct") or 0)
    position = row.get("position_20d") if row.get("position_20d") is not None else 0.5
    return (
        ret3 * 0.10
        + ret5 * 0.20
        + ret10 * 0.20
        + ret20 * 0.15
        + sector_strength * 0.20
        + min(turnover, 25) * 0.30
        + min(amount / 100000, 500) * 0.05
        - dist_ma5 * 0.10
        + (0.6 - abs(position - 0.6)) * 10
    )


def build_stock_features(recent_daily: pd.DataFrame, latest_enriched: pd.DataFrame) -> pd.DataFrame:
    recent_sorted = recent_daily.sort_values(["ts_code", "trade_date"]).copy()
    recent_sorted["ma5"] = recent_sorted.groupby("ts_code")["close"].transform(lambda s: s.rolling(5).mean())
    recent_sorted["ma10"] = recent_sorted.groupby("ts_code")["close"].transform(lambda s: s.rolling(10).mean())
    recent_sorted["ma20"] = recent_sorted.groupby("ts_code")["close"].transform(lambda s: s.rolling(20).mean())
    recent_sorted["high20"] = recent_sorted.groupby("ts_code")["high"].transform(lambda s: s.rolling(20).max())
    recent_sorted["low20"] = recent_sorted.groupby("ts_code")["low"].transform(lambda s: s.rolling(20).min())
    latest_date = recent_sorted["trade_date"].max()
    latest_recent = recent_sorted[recent_sorted["trade_date"] == latest_date][["ts_code", "ma5", "ma10", "ma20", "high20", "low20"]]
    out = latest_enriched.merge(latest_recent, on="ts_code", how="left")
    out["distance_to_ma5_pct"] = ((out["close"] / out["ma5"]) - 1.0) * 100.0
    out["distance_to_ma10_pct"] = ((out["close"] / out["ma10"]) - 1.0) * 100.0
    out["position_20d"] = (out["close"] - out["low20"]) / (out["high20"] - out["low20"])
    return out


def build_leaders_and_candidates(stock_table: pd.DataFrame, sector_table: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    sector_strength_map = sector_table.set_index("sector")["composite_score"].to_dict()
    leader_rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    watch_list: list[dict[str, Any]] = []

    candidate_sectors = sector_table[sector_table["next_mainline_candidate"]].head(3)["sector"].tolist()
    for sector in candidate_sectors:
        sector_df = stock_table[stock_table["sector"] == sector].copy()
        if sector_df.empty:
            continue
        strength = float(sector_strength_map.get(sector, 0) or 0)
        sector_df["stock_score"] = sector_df.apply(lambda row: score_stock(row, strength), axis=1)
        sector_df = sector_df.sort_values(by=["stock_score", "pct_chg_5d", "pct_chg_20d"], ascending=False)

        top_leader = sector_df.iloc[0].copy()
        top_leader["leader_type"] = classify_leader_type(top_leader)
        leader_rows.append(
            {
                "sector": sector,
                "ts_code": top_leader["ts_code"],
                "name": top_leader["name"],
                "leader_type": top_leader["leader_type"],
                "latest_price": safe_float(top_leader["close"]),
                "pct_chg_5d": safe_float(top_leader["pct_chg_5d"]),
                "pct_chg_20d": safe_float(top_leader["pct_chg_20d"]),
            }
        )

        for _, row in sector_df.head(4).iterrows():
            leader_type = classify_leader_type(row)
            is_extended = (row.get("distance_to_ma5_pct") or 0) >= 8 or (row.get("pct_chg_1d") or 0) >= 7
            is_repair = (row.get("pct_chg_20d") or 0) <= 10 and (row.get("pct_chg_5d") or 0) >= 2
            recommendation_type = "MID_LONG_TERM" if is_repair and leader_type in {"LOW_POSITION_REPAIR", "CAPACITY_CORE"} else "SHORT_TERM"
            if leader_type in {"TREND_LEADER", "CAPACITY_CORE"} and recommendation_type == "SHORT_TERM":
                recommendation_type = "BOTH"

            if is_extended:
                candidate_action = "WATCH"
                buy_point_quality = "FAIR"
                why_not_buy = "短线偏离5日线较多或当日涨幅偏大，只观察，不追。"
            elif (row.get("pct_chg_5d") or 0) >= 3 and (row.get("distance_to_ma10_pct") or 0) >= -2:
                candidate_action = "BUY_CANDIDATE"
                buy_point_quality = "GOOD"
                why_not_buy = ""
            else:
                candidate_action = "OBSERVE"
                buy_point_quality = "POOR"
                why_not_buy = "趋势尚未完全成形，等待回踩确认或放量突破。"

            suggested_trial_position = "低风险且逻辑强不超过20%" if candidate_action == "BUY_CANDIDATE" and recommendation_type != "SHORT_TERM" else "中等风险不超过15%"
            if leader_type in {"ELASTIC_LEADER", "ABSOLUTE_LEADER"}:
                suggested_trial_position = "高风险不超过10%" if candidate_action != "OBSERVE" else "中等风险不超过15%"

            stop_loss_reference = row.get("ma10") if row.get("ma10") and not pd.isna(row.get("ma10")) else row.get("ma5")
            entry_condition = "回踩5日线附近缩量企稳，或放量突破近3日高点后承接稳定。"
            trigger = "次日不高开过度，盘中回踩不破5日线并重新走强。"
            if recommendation_type == "MID_LONG_TERM":
                entry_condition = "回踩10日线/20日线止跌，且板块继续修复。"
                trigger = "10日线附近止跌两日以上并重新放量。"
            take_profit_plan = "若板块延续，先看前高附近分批止盈；若冲高放量滞涨或龙头转弱，减仓锁定利润。"
            if recommendation_type == "MID_LONG_TERM":
                take_profit_plan = "趋势延续则沿10日线持有，若20日线之上放量滞涨分批兑现。"

            item = {
                "ts_code": row["ts_code"],
                "name": row["name"],
                "sector": row["sector"],
                "recommendation_type": recommendation_type,
                "candidate_action": candidate_action,
                "latest_price": safe_float(row["close"]),
                "pct_chg_1d": safe_float(row["pct_chg_1d"]),
                "pct_chg_3d": safe_float(row["pct_chg_3d"]),
                "pct_chg_5d": safe_float(row["pct_chg_5d"]),
                "pct_chg_10d": safe_float(row["pct_chg_10d"]),
                "pct_chg_20d": safe_float(row["pct_chg_20d"]),
                "pct_chg_60d": safe_float(row["pct_chg_60d"]),
                "amount": safe_float(row["amount"]),
                "turnover_rate": safe_float(row.get("turnover_rate")),
                "ma5": safe_float(row.get("ma5")),
                "ma10": safe_float(row.get("ma10")),
                "ma20": safe_float(row.get("ma20")),
                "distance_to_ma5_pct": safe_float(row.get("distance_to_ma5_pct")),
                "distance_to_ma10_pct": safe_float(row.get("distance_to_ma10_pct")),
                "buy_point_quality": buy_point_quality,
                "risk_reward_quality": "GOOD" if candidate_action == "BUY_CANDIDATE" else "FAIR" if candidate_action == "WATCH" else "POOR",
                "is_chasing": is_extended,
                "suitable_for_small_trial": candidate_action in {"BUY_CANDIDATE", "WATCH"},
                "suggested_trial_position": suggested_trial_position,
                "suggested_entry_condition": entry_condition,
                "invalidation_condition": "跌破10日线且次日无法收回，或板块退潮、龙头明显走弱。",
                "what_would_trigger_buy": trigger,
                "why_not_buy": why_not_buy,
                "stop_loss_reference": safe_float(stop_loss_reference),
                "stop_loss_trigger": "跌破5日线且无法收回可先减仓；有效跌破10日线、板块退潮或放量破位则执行止损。",
                "take_profit_plan": take_profit_plan,
                "why_selected": f"{sector} 内强度靠前，兼具 {leader_type} 属性，且相对板块具有持续性。",
                "main_risks": "若板块轮动失败、龙头分歧放大或个股高位放量滞涨，短线收益兑现难度会提升。",
                "leader_type": leader_type,
                "stock_score": safe_float(row["stock_score"]),
            }
            if candidate_action in {"BUY_CANDIDATE", "WATCH"} and len(candidates) < 5:
                candidates.append(item)
            else:
                watch_list.append(item)

    # Keep a balanced 3-5 stock list.
    final_candidates: list[dict[str, Any]] = []
    short_added = 0
    trend_added = 0
    mid_added = 0
    for item in candidates:
        if item["recommendation_type"] == "SHORT_TERM" and short_added < 2:
            final_candidates.append(item)
            short_added += 1
        elif item["recommendation_type"] == "MID_LONG_TERM" and mid_added < 1:
            final_candidates.append(item)
            mid_added += 1
        elif item["recommendation_type"] == "BOTH" and trend_added < 2:
            final_candidates.append(item)
            trend_added += 1
        elif len(final_candidates) < 5:
            final_candidates.append(item)
        if len(final_candidates) >= 5:
            break
    if len(final_candidates) < 3:
        for item in watch_list:
            if item["ts_code"] in {x["ts_code"] for x in final_candidates}:
                continue
            final_candidates.append(item)
            if len(final_candidates) >= 3:
                break

    high_risk_removed = [
        {
            "ts_code": item["ts_code"],
            "name": item["name"],
            "sector": item["sector"],
            "reason": "短线涨幅过快、偏离5日线较大，不适合作为当前人工候选池优先项。 ",
        }
        for item in watch_list
        if item["is_chasing"] and (item["pct_chg_5d"] or 0) >= 12
    ][:8]
    return leader_rows, final_candidates, high_risk_removed


def make_report(
    latest_trade_date: str,
    missing_data: list[str],
    market_weather: dict[str, Any],
    sector_table: pd.DataFrame,
    leaders: list[dict[str, Any]],
    final_candidates: list[dict[str, Any]],
    watch_candidates: list[dict[str, Any]],
    high_risk_removed: list[dict[str, Any]],
) -> dict[str, Any]:
    next_mainline_sectors = sector_table[sector_table["next_mainline_candidate"]].head(3).to_dict(orient="records")
    proposed_candidate_pool = [
        {
            "ts_code": item["ts_code"],
            "name": item["name"],
            "candidate_source": "stock_selection_research",
            "sector": item["sector"],
            "reason": item["why_selected"],
            "candidate_action_hint": item["candidate_action"],
            "max_position_ratio": 0.10 if item["suggested_trial_position"] == "高风险不超过10%" else 0.15 if item["suggested_trial_position"] == "中等风险不超过15%" else 0.20,
            "notes": item["suggested_entry_condition"],
        }
        for item in final_candidates
    ]
    return {
        "completed": True,
        "data_source": "Tushare real-time daily/index_daily/daily_basic/moneyflow + local SW2021_L2 mapping",
        "latest_completed_trade_date": latest_trade_date,
        "used_real_tushare_data": True,
        "missing_data": missing_data,
        "market_weather": market_weather,
        "strong_sector_ranking": sector_table.head(15).to_dict(orient="records"),
        "next_mainline_candidate_sectors": next_mainline_sectors,
        "sector_leaders": leaders,
        "final_recommendations": final_candidates,
        "watch_only_stocks": watch_candidates[:10],
        "removed_high_risk_stocks": high_risk_removed,
        "recommend_update_candidate_pool_manual": len(final_candidates) >= 3,
        "proposed_candidate_pool": proposed_candidate_pool,
        "failed_checks": [],
        "blockers": [],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# stock_selection_research_{report['latest_completed_trade_date']}",
        "",
        f"- completed: {report['completed']}",
        f"- data_source: {report['data_source']}",
        f"- latest_completed_trade_date: {report['latest_completed_trade_date']}",
        f"- used_real_tushare_data: {report['used_real_tushare_data']}",
        f"- missing_data: {', '.join(report['missing_data']) if report['missing_data'] else 'none'}",
        "",
        "## 市场天气",
        f"- market_risk_level: {report['market_weather']['market_risk_level']}",
        f"- attack_level: {report['market_weather']['attack_level']}",
        f"- up_count: {report['market_weather']['up_count']}",
        f"- down_count: {report['market_weather']['down_count']}",
        f"- up_ratio_pct: {report['market_weather']['up_ratio']}",
        f"- amount_change_pct_5d_vs_prev5d: {report['market_weather']['amount_change_pct_5d_vs_prev5d']}",
        "",
        "## 下一阶段主线候选板块",
    ]
    for item in report["next_mainline_candidate_sectors"]:
        lines.append(
            f"- {item['sector']} | state={item['sector_state']} | 5d={item['pct_chg_5d']}% | 20d={item['pct_chg_20d']}% | up_ratio={item['up_ratio']}%"
        )
    lines += ["", "## 板块龙头"]
    for item in report["sector_leaders"]:
        lines.append(
            f"- {item['sector']}: {item['name']}({item['ts_code']}) | {item['leader_type']} | 5d={item['pct_chg_5d']}% | 20d={item['pct_chg_20d']}%"
        )
    lines += ["", "## 最终推荐 3-5 只股票"]
    for item in report["final_recommendations"]:
        lines.extend(
            [
                f"- {item['name']}({item['ts_code']}) | sector={item['sector']} | type={item['recommendation_type']} | action={item['candidate_action']}",
                f"  latest_price={item['latest_price']} | 1d={item['pct_chg_1d']}% | 5d={item['pct_chg_5d']}% | 20d={item['pct_chg_20d']}%",
                f"  buy_point_quality={item['buy_point_quality']} | trial_position={item['suggested_trial_position']}",
                f"  entry={item['suggested_entry_condition']}",
                f"  stop_loss={item['stop_loss_trigger']}",
                f"  take_profit={item['take_profit_plan']}",
            ]
        )
    lines += ["", "## 是否建议更新 candidate_pool_MANUAL.json", f"- {report['recommend_update_candidate_pool_manual']}"]
    lines += ["", "## failed_checks / blockers", f"- failed_checks={report['failed_checks']}", f"- blockers={report['blockers']}", ""]
    return "\n".join(lines)


def write_report(report: dict[str, Any]) -> tuple[Path, Path]:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    date = report["latest_completed_trade_date"]
    json_path = REVIEW_DIR / f"stock_selection_research_{date}.json"
    md_path = REVIEW_DIR / f"stock_selection_research_{date}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run standalone stock selection research for simulated_live_v1")
    parser.add_argument("--trade-date", default="", help="Optional trade date, defaults to latest completed trade date")
    args = parser.parse_args()

    pro = get_tushare_pro()
    latest_trade_date, open_dates = latest_completed_trade_date(pro)
    target_trade_date = args.trade_date.strip() or latest_trade_date
    if target_trade_date != latest_trade_date:
        if target_trade_date not in open_dates or target_trade_date > latest_trade_date:
            raise RuntimeError(f"请求交易日 {target_trade_date} 无效，最新完整交易日为 {latest_trade_date}。")
        latest_trade_date = target_trade_date

    trade_dates = get_trade_window(open_dates, latest_trade_date, 121)
    anchors = anchor_dates(trade_dates)
    recent_trade_dates = trade_dates[-RECENT_DAYS_FOR_DAILY:]
    all_fetch_dates = sorted(set(recent_trade_dates + list(anchors.values())))

    daily = fetch_daily_by_dates(pro, all_fetch_dates)
    latest_daily = daily[daily["trade_date"] == latest_trade_date].copy()
    daily_basic = fetch_latest_daily_basic(pro, latest_trade_date)
    moneyflow = fetch_latest_moneyflow(pro, latest_trade_date)
    index_history = fetch_index_history(pro, trade_dates[0], latest_trade_date)

    stock_basic = load_stock_basic()
    sector_members = load_sector_members(latest_trade_date)
    latest_daily = latest_daily.merge(stock_basic, on="ts_code", how="left")
    latest_daily = latest_daily.merge(sector_members[["ts_code", "sector"]], on="ts_code", how="left")
    if not daily_basic.empty:
        latest_daily = latest_daily.merge(daily_basic.drop(columns=["trade_date"]), on="ts_code", how="left")
    if not moneyflow.empty:
        latest_daily = latest_daily.merge(moneyflow.drop(columns=["trade_date"]), on="ts_code", how="left")

    close_pivot = daily.pivot_table(index="ts_code", columns="trade_date", values="close", aggfunc="last")
    latest_enriched = add_return_columns(latest_daily, close_pivot, anchors)
    latest_enriched = build_stock_features(daily, latest_enriched)

    market_weather = calc_market_weather(index_history, anchors, latest_daily, daily)
    sector_table = build_sector_table(latest_enriched, daily, sector_members, market_weather)
    stock_table = latest_enriched[latest_enriched["sector"].notna()].copy()
    leaders, final_candidates, high_risk_removed = build_leaders_and_candidates(stock_table, sector_table)
    watch_candidates = [
        item
        for item in sorted(final_candidates + high_risk_removed, key=lambda x: (x.get("candidate_action") != "BUY_CANDIDATE", x.get("pct_chg_5d", 0)), reverse=False)
        if isinstance(item, dict) and "candidate_action" in item
    ]

    missing_data: list[str] = []
    if daily_basic.empty:
        missing_data.append("daily_basic")
    if moneyflow.empty:
        missing_data.append("moneyflow")
    if "北证50" not in set(index_history["index_name"].astype(str)):
        missing_data.append("北证50指数行情")

    report = make_report(
        latest_trade_date=latest_trade_date,
        missing_data=missing_data,
        market_weather=market_weather,
        sector_table=sector_table,
        leaders=leaders,
        final_candidates=final_candidates,
        watch_candidates=watch_candidates,
        high_risk_removed=high_risk_removed,
    )
    json_path, md_path = write_report(report)
    print(json.dumps({"json": str(json_path), "md": str(md_path), "latest_completed_trade_date": latest_trade_date}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
