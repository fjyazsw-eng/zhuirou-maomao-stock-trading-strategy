from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.industry_members import fetch_sw_index_members
from scoring_system.tushare_client import get_tushare_pro as build_tushare_pro


REVIEW_DIR = ROOT / "reports" / "simulated_live_v1" / "review"
RAW_DIR = ROOT / "data" / "raw" / "tushare"
STOCK_BASIC_FILE = RAW_DIR / "stock_basic" / "stock_basic.csv"
SW_L2_FILE = RAW_DIR / "index_classify" / "industry_classify_SW2021_L2.csv"
INDEX_CODES = {
    "上证指数": "000001.SH",
    "深证成指": "399001.SZ",
    "创业板指": "399006.SZ",
    "科创50": "000688.SH",
    "北证50": "899050.BJ",
}
WINDOWS = [1, 5, 10, 20]
ANCHOR_WINDOWS = [1, 3, 5, 10, 20, 60, 120]

FOCUS_SECTORS = [
    {"sector_name": "医疗研发外包（884244）", "sector_group": "医药修复组", "mapping_type": "explicit_external_code", "index_code": "884244", "missing_reason": "按本轮指定板块号 884244 校验后，当前 Tushare index_member_all 链路未返回真实成分股，不能用其他医药板块替代。"},
    {"sector_name": "生物制品", "sector_group": "医药修复组", "mapping_type": "sw_l2", "index_code": "801152.SI"},
    {"sector_name": "化学制药", "sector_group": "医药修复组", "mapping_type": "sw_l2", "index_code": "801151.SI"},
    {"sector_name": "创新药", "sector_group": "医药修复组", "mapping_type": "proxy_basket", "proxy_codes": ["801151.SI", "801152.SI"], "missing_reason": "当前 Tushare SW2021 未提供创新药独立官方行业编码，本轮仅作为化学制药+生物制品交叉观察篮子，不作为正式板块归属。"},
    {"sector_name": "医疗器械", "sector_group": "医药修复组", "mapping_type": "sw_l2", "index_code": "801153.SI"},
    {"sector_name": "半导体", "sector_group": "科技主线组", "mapping_type": "sw_l2", "index_code": "801081.SI"},
    {"sector_name": "电子化学品", "sector_group": "科技主线组", "mapping_type": "sw_l3", "index_code": "850861.SI"},
    {"sector_name": "半导体材料", "sector_group": "科技主线组", "mapping_type": "sw_l3", "index_code": "850813.SI"},
    {"sector_name": "先进封装", "sector_group": "科技主线组", "mapping_type": "sw_l3", "index_code": "850817.SI"},
    {"sector_name": "光刻胶", "sector_group": "科技主线组", "mapping_type": "proxy_basket", "proxy_codes": ["850861.SI"], "missing_reason": "当前 Tushare SW2021 未提供光刻胶独立官方行业编码，本轮使用电子化学品作为最接近上游材料代理观察，不作为正式板块归属。"},
    {"sector_name": "存储芯片", "sector_group": "科技主线组", "mapping_type": "proxy_basket", "proxy_codes": ["850814.SI", "850815.SI", "850816.SI"], "missing_reason": "当前 Tushare SW2021 未提供存储芯片独立官方行业编码，本轮使用数字芯片设计+模拟芯片设计+集成电路制造作为代理观察篮子。"},
    {"sector_name": "半导体设备", "sector_group": "科技主线组", "mapping_type": "sw_l3", "index_code": "850818.SI"},
    {"sector_name": "券商", "sector_group": "情绪修复组", "mapping_type": "sw_l2", "index_code": "801193.SI"},
    {"sector_name": "养殖业", "sector_group": "情绪修复组", "mapping_type": "sw_l2", "index_code": "801017.SI"},
    {"sector_name": "低位消费修复", "sector_group": "情绪修复组", "mapping_type": "proxy_basket", "proxy_codes": ["801111.SI", "801124.SI", "801203.SI", "801128.SI"], "missing_reason": "低位消费修复不是官方单一行业编码，本轮使用白色家电+食品加工+一般零售+休闲食品构成观察篮子。"},
    {"sector_name": "低位周期修复", "sector_group": "情绪修复组", "mapping_type": "proxy_basket", "proxy_codes": ["801055.SI", "801711.SI", "801712.SI", "801044.SI"], "missing_reason": "低位周期修复不是官方单一行业编码，本轮使用工业金属+水泥+玻璃玻纤+普钢构成观察篮子。"},
]

AUTO_DISCOVERY_GROUPS = {
    "5d_strong": "5日强势",
    "10d_strong": "10日强势",
    "20d_strong": "20日强势",
    "amount_expansion": "成交额放大",
    "high_up_ratio": "上涨家数占比高",
    "low_starting": "低位刚启动",
    "persistent": "连续走强",
    "retreating": "高位退潮",
}

MANUAL_FOCUS_STOCK_MAP = [
    {
        "ts_code": "301520.SZ",
        "name": "万邦医药",
        "linked_sector_name": "医疗研发外包",
        "linked_sector_code": "884244",
        "mapping_type": "MANUAL_OBSERVATION",
        "mapping_source": "同花顺",
        "is_official_tushare_member": False,
        "can_be_candidate": True,
        "caveat": "该股票来自同花顺人工观察映射，不代表 Tushare 官方成分股验证通过。",
    },
    {
        "ts_code": "301257.SZ",
        "name": "普蕊斯",
        "linked_sector_name": "医疗研发外包",
        "linked_sector_code": "884244",
        "mapping_type": "MANUAL_OBSERVATION",
        "mapping_source": "同花顺",
        "is_official_tushare_member": False,
        "can_be_candidate": True,
        "caveat": "该股票来自同花顺人工观察映射，不代表 Tushare 官方成分股验证通过。",
    },
]

PREVIOUS_CANDIDATE_STATE = {
    "600276.SH": {"pool_role": "BUY_CORE", "previous_action": "BUY_CANDIDATE", "sector": "化学制药"},
    "002458.SZ": {"pool_role": "WATCH_CORE", "previous_action": "WATCH", "sector": "养殖业"},
    "688235.SH": {"pool_role": "BACKUP_ONLY", "previous_action": "WATCH", "sector": "化学制药"},
    "301520.SZ": {"pool_role": "MANUAL_MAPPING_WATCH", "previous_action": "WATCH", "sector": "医疗研发外包"},
    "301257.SZ": {"pool_role": "MANUAL_MAPPING_WATCH", "previous_action": "WATCH", "sector": "医疗研发外包"},
}


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
    return build_tushare_pro(ROOT)


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
    return usable[-needed_days:]


def anchor_dates(trade_dates: list[str]) -> dict[int, str]:
    latest_idx = len(trade_dates) - 1
    result = {0: trade_dates[latest_idx]}
    for window in ANCHOR_WINDOWS:
        result[window] = trade_dates[latest_idx - window]
    return result


def fetch_daily_by_dates(pro: Any, dates: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for trade_date in dates:
        df = pro.daily(trade_date=trade_date)
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        raise RuntimeError("daily 未返回任何行情数据。")
    daily = pd.concat(frames, ignore_index=True)
    for col in ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"]:
        if col in daily.columns:
            daily[col] = pd.to_numeric(daily[col], errors="coerce")
    daily["trade_date"] = daily["trade_date"].astype(str)
    return daily


def fetch_latest_daily_basic(pro: Any, trade_date: str) -> pd.DataFrame:
    try:
        df = pro.daily_basic(
            trade_date=trade_date,
            fields="ts_code,trade_date,turnover_rate,total_mv,circ_mv,pe,pb",
        )
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    for col in ["turnover_rate", "total_mv", "circ_mv", "pe", "pb"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trade_date"] = df["trade_date"].astype(str)
    return df


def fetch_latest_moneyflow(pro: Any, trade_date: str) -> pd.DataFrame:
    try:
        df = pro.moneyflow(
            trade_date=trade_date,
            fields="ts_code,trade_date,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,net_mf_amount",
        )
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    for col in ["buy_lg_amount", "sell_lg_amount", "buy_elg_amount", "sell_elg_amount", "net_mf_amount"]:
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
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_stock_basic() -> pd.DataFrame:
    stock_basic = pd.read_csv(STOCK_BASIC_FILE)[["ts_code", "name", "industry", "list_date"]]
    stock_basic["list_date"] = stock_basic["list_date"].astype(str)
    return stock_basic


def fetch_sw_classify(pro: Any) -> pd.DataFrame:
    l2 = pd.read_csv(SW_L2_FILE)[["index_code", "industry_name"]]
    l2["level"] = "L2"
    l3 = pro.index_classify(level="L3", src="SW2021", fields="index_code,industry_name,level,parent_code,is_pub,src")
    l3 = l3[l3["is_pub"].astype(str) == "1"][["index_code", "industry_name", "level", "parent_code"]]
    return pd.concat([l2[["index_code", "industry_name", "level"]], l3[["index_code", "industry_name", "level"]]], ignore_index=True)


def fetch_members_for_codes(pro: Any, codes: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for code in codes:
        level = "L2" if code.startswith("801") else "L3"
        df = fetch_sw_index_members(pro, code, level=level)
        if df is None or df.empty:
            continue
        df["in_date"] = df["in_date"].fillna("00000000").astype(str)
        df["out_date"] = df["out_date"].fillna("").astype(str)
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def active_members(member_df: pd.DataFrame, code: str, as_of: str) -> pd.DataFrame:
    x = member_df[member_df["index_code"].astype(str) == code].copy()
    if x.empty:
        return x
    return x[(x["in_date"] <= as_of) & ((x["out_date"] == "") | (x["out_date"] >= as_of))]


def add_return_columns(latest_df: pd.DataFrame, close_pivot: pd.DataFrame, anchors: dict[int, str]) -> pd.DataFrame:
    out = latest_df.copy()
    latest_date = anchors[0]
    latest_close = close_pivot[latest_date].rename("latest_close")
    out = out.merge(latest_close, left_on="ts_code", right_index=True, how="left")
    for window in ANCHOR_WINDOWS:
        start_date = anchors[window]
        start_close = close_pivot[start_date].rename(f"start_close_{window}d")
        out = out.merge(start_close, left_on="ts_code", right_index=True, how="left")
        denom = out[f"start_close_{window}d"].replace(0, pd.NA)
        out[f"pct_chg_{window}d"] = ((out["latest_close"] / denom) - 1.0) * 100.0
    out["pct_chg_1d"] = pd.to_numeric(out["pct_chg"], errors="coerce")
    return out


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


def add_volume_amount_change_metrics(recent_daily: pd.DataFrame, latest_df: pd.DataFrame) -> pd.DataFrame:
    recent_sorted = recent_daily.sort_values(["ts_code", "trade_date"]).copy()
    recent_sorted["amount_ma5"] = recent_sorted.groupby("ts_code")["amount"].transform(lambda s: s.rolling(5).mean())
    recent_sorted["vol_ma5"] = recent_sorted.groupby("ts_code")["vol"].transform(lambda s: s.rolling(5).mean())
    latest_date = recent_sorted["trade_date"].max()
    latest_recent = recent_sorted[recent_sorted["trade_date"] == latest_date][["ts_code", "amount_ma5", "vol_ma5", "amount", "vol"]].copy()
    latest_recent["amount_change"] = ((latest_recent["amount"] / latest_recent["amount_ma5"]) - 1.0) * 100.0
    latest_recent["volume_change"] = ((latest_recent["vol"] / latest_recent["vol_ma5"]) - 1.0) * 100.0
    out = latest_df.merge(latest_recent[["ts_code", "amount_change", "volume_change"]], on="ts_code", how="left")
    return out


def calc_market_weather(index_history: pd.DataFrame, anchors: dict[int, str], latest_daily: pd.DataFrame, recent_daily: pd.DataFrame) -> dict[str, Any]:
    idx_pivot = index_history.pivot_table(index="trade_date", columns="index_name", values="close").sort_index()
    index_summary: dict[str, Any] = {}
    for index_name in idx_pivot.columns:
        item: dict[str, Any] = {}
        for window in [1, 3, 5, 10, 20]:
            s = anchors[window]
            e = anchors[0]
            a = idx_pivot.at[s, index_name] if s in idx_pivot.index else None
            b = idx_pivot.at[e, index_name] if e in idx_pivot.index else None
            item[f"pct_chg_{window}d"] = safe_float(((b / a) - 1.0) * 100.0) if a and b else None
        index_summary[index_name] = item
    up_count = int((latest_daily["pct_chg"] > 0).sum())
    down_count = int((latest_daily["pct_chg"] < 0).sum())
    up_ratio = up_count / max(len(latest_daily), 1)
    last5 = sorted(recent_daily["trade_date"].unique().tolist())[-5:]
    prev5 = sorted(recent_daily["trade_date"].unique().tolist())[-10:-5]
    recent_amount = recent_daily[recent_daily["trade_date"].isin(last5)]["amount"].sum()
    prev_amount = recent_daily[recent_daily["trade_date"].isin(prev5)]["amount"].sum() if prev5 else 0
    amount_change = ((recent_amount / prev_amount) - 1.0) * 100.0 if prev_amount else None
    avg_5 = pd.Series([v["pct_chg_5d"] for v in index_summary.values() if v["pct_chg_5d"] is not None]).mean()
    avg_20 = pd.Series([v["pct_chg_20d"] for v in index_summary.values() if v["pct_chg_20d"] is not None]).mean()
    if avg_5 >= 4 and up_ratio >= 0.62:
        risk_level, attack = "MAINLINE_EXTENSION", "AGGRESSIVE"
    elif avg_5 >= 1.5 and up_ratio >= 0.55:
        risk_level, attack = "STRONG_REPAIR", "MODERATE"
    elif avg_20 > 0 and up_ratio >= 0.48:
        risk_level, attack = "NEUTRAL", "MODERATE"
    elif avg_5 > -2 and up_ratio >= 0.42:
        risk_level, attack = "WEAK_REPAIR", "CAUTIOUS"
    else:
        risk_level, attack = "RISK_OFF", "OBSERVE_ONLY"
    return {
        "latest_completed_trade_date": anchors[0],
        "index_performance": index_summary,
        "up_count": up_count,
        "down_count": down_count,
        "up_ratio": safe_float(up_ratio * 100),
        "amount_change_pct_5d_vs_prev5d": safe_float(amount_change),
        "market_risk_level": risk_level,
        "attack_level": attack,
    }


def build_l2_sector_table(stock_table: pd.DataFrame, recent_daily: pd.DataFrame, l2_members: pd.DataFrame, latest_trade_date: str) -> pd.DataFrame:
    merged = stock_table.merge(l2_members[["ts_code", "sector_name"]], on="ts_code", how="left")
    merged = merged[merged["sector_name"].notna()].copy()
    recent = recent_daily.merge(l2_members[["ts_code", "sector_name"]], on="ts_code", how="left")
    recent = recent[recent["sector_name"].notna()].copy()
    dates = sorted(recent["trade_date"].unique().tolist())
    last5 = dates[-5:]
    prev5 = dates[-10:-5]
    rows: list[dict[str, Any]] = []
    for sector, df in merged.groupby("sector_name"):
        member_count = len(df)
        if member_count < 5:
            continue
        rec = recent[recent["sector_name"] == sector]
        avg_5_amt = rec[rec["trade_date"].isin(last5)]["amount"].sum() / max(len(last5), 1)
        prev_5_amt = rec[rec["trade_date"].isin(prev5)]["amount"].sum() / max(len(prev5), 1) if prev5 else None
        amount_change = ((avg_5_amt / prev_5_amt) - 1.0) * 100.0 if prev_5_amt not in (None, 0) else None
        up_ratio = float((df["pct_chg_1d"] > 0).mean())
        rows.append(
            {
                "sector_name": sector,
                "pct_chg_1d": safe_float(df["pct_chg_1d"].mean()),
                "pct_chg_5d": safe_float(df["pct_chg_5d"].mean()),
                "pct_chg_10d": safe_float(df["pct_chg_10d"].mean()),
                "pct_chg_20d": safe_float(df["pct_chg_20d"].mean()),
                "up_ratio": safe_float(up_ratio * 100),
                "amount_change": safe_float(amount_change),
                "member_count": member_count,
                "low_starting_flag": bool((df["pct_chg_20d"].mean() < 8) and (df["pct_chg_5d"].mean() > 2)),
                "persistent_flag": bool((df["pct_chg_5d"].mean() > 0) and (df["pct_chg_10d"].mean() > 0) and (up_ratio > 0.55)),
                "retreat_flag": bool((df["pct_chg_20d"].mean() > 12) and (df["pct_chg_5d"].mean() < 0)),
            }
        )
    return pd.DataFrame(rows)


def classify_sector_state(row: pd.Series) -> str:
    ret5 = row.get("pct_chg_5d") or 0
    ret10 = row.get("pct_chg_10d") or 0
    ret20 = row.get("pct_chg_20d") or 0
    up_ratio = row.get("up_ratio") or 0
    amount_change = row.get("amount_change") or 0
    if ret20 > 18 and ret5 < 0:
        return "RETREATING"
    if ret5 >= 4 and ret10 >= 6 and up_ratio >= 60 and amount_change >= 10:
        return "CONFIRMED"
    if ret5 >= 2 and ret20 <= 10 and amount_change >= 5:
        return "STARTING"
    if ret5 > 0 and ret10 < 0:
        return "DIVERGING"
    if ret20 > 0:
        return "WATCH_ONLY"
    return "RETREATING"


def classify_leader_type(row: pd.Series, sector_core: bool) -> str:
    ret5 = row.get("pct_chg_5d") or -999
    ret10 = row.get("pct_chg_10d") or -999
    ret20 = row.get("pct_chg_20d") or -999
    turnover = row.get("turnover_rate") or 0
    amount_rank = row.get("amount_rank_in_sector") or 999
    dist5 = abs(row.get("distance_to_ma5_pct") or 0)
    position = row.get("position_20d")
    position = 0.5 if position is None or pd.isna(position) else position
    if sector_core and ret20 >= 25 and ret10 >= 12 and turnover >= 8:
        return "ABSOLUTE_LEADER"
    if sector_core and ret20 >= 15 and dist5 <= 8:
        return "TREND_LEADER"
    if amount_rank <= 3 and ret10 >= 5:
        return "CAPACITY_CORE"
    if ret5 >= 8 and turnover >= 10:
        return "ELASTIC_LEADER"
    if ret20 <= 8 and ret5 >= 2 and position < 0.75:
        return "LOW_POSITION_REPAIR"
    if ret20 >= 35 and dist5 >= 10:
        return "AVOID"
    return "FOLLOWER"


def evaluate_stock(row: pd.Series, market_weather: dict[str, Any], sector_state: str, sector_core: bool) -> dict[str, Any]:
    leader_type = classify_leader_type(row, sector_core)
    ret5 = row.get("pct_chg_5d") or 0
    ret10 = row.get("pct_chg_10d") or 0
    ret20 = row.get("pct_chg_20d") or 0
    dist5 = row.get("distance_to_ma5_pct") or 0
    amount_rank = row.get("amount_rank_in_sector") or 999
    turnover = row.get("turnover_rate") or 0
    position = row.get("position_20d")
    position = 0.5 if position is None or pd.isna(position) else position
    extended = ret20 >= 30 or dist5 >= 9 or (row.get("pct_chg_1d") or 0) >= 7
    trend_strength = "HIGH" if ret10 >= 10 and ret20 >= 15 else "MEDIUM" if ret5 >= 3 else "LOW"
    elasticity = "HIGH" if turnover >= 10 and ret5 >= 8 else "MEDIUM" if ret5 >= 4 else "LOW"
    position_risk = "HIGH" if extended or position >= 0.85 else "MEDIUM" if position >= 0.65 else "LOW"
    theme_purity = "HIGH" if sector_core and amount_rank <= 5 else "MEDIUM" if amount_rank <= 10 else "LOW"
    horizon = "MID_LONG_TERM" if leader_type == "LOW_POSITION_REPAIR" else "SHORT_TERM" if leader_type == "ELASTIC_LEADER" else "BOTH"
    buy_quality = "GOOD" if sector_state in {"STARTING", "CONFIRMED"} and not extended and amount_rank <= 5 else "FAIR" if not extended else "POOR"
    candidate_action = "WATCH"
    if leader_type in {"FOLLOWER", "AVOID"}:
        candidate_action = "OBSERVE"
    elif market_weather["market_risk_level"] == "RISK_OFF" or market_weather["attack_level"] == "OBSERVE_ONLY":
        if leader_type in {"ABSOLUTE_LEADER", "TREND_LEADER"} and sector_state in {"STARTING", "CONFIRMED"} and not extended and sector_core:
            candidate_action = "BUY_CANDIDATE"
        elif leader_type == "ELASTIC_LEADER" and not sector_core:
            candidate_action = "WATCH"
        else:
            candidate_action = "WATCH"
    elif sector_state in {"STARTING", "CONFIRMED"} and not extended and leader_type not in {"FOLLOWER", "AVOID"}:
        candidate_action = "BUY_CANDIDATE"

    if extended:
        candidate_action = "WATCH" if candidate_action == "BUY_CANDIDATE" else candidate_action
        buy_quality = "FAIR" if buy_quality == "GOOD" else buy_quality

    trial_position_limit = "10%" if leader_type in {"ELASTIC_LEADER", "ABSOLUTE_LEADER"} else "15%" if candidate_action != "OBSERVE" else "0%"
    if candidate_action == "BUY_CANDIDATE" and leader_type in {"TREND_LEADER", "CAPACITY_CORE", "LOW_POSITION_REPAIR"}:
        trial_position_limit = "15%"

    suitable = candidate_action == "BUY_CANDIDATE"
    return {
        "leader_type": leader_type if candidate_action != "OBSERVE" else ("WATCH_ONLY" if leader_type == "FOLLOWER" else leader_type),
        "candidate_action": candidate_action,
        "trend_strength": trend_strength,
        "short_term_elasticity": elasticity,
        "position_risk": position_risk,
        "theme_purity": theme_purity,
        "horizon": horizon,
        "buy_point_quality": buy_quality,
        "entry_condition": "回踩5日线/10日线企稳，或放量突破近3日高点后承接稳定。",
        "stop_loss_condition": "跌破10日线且无法收回，或板块转弱、龙头掉队、放量破位。",
        "take_profit_condition": "冲高放量滞涨分批止盈；若板块延续则沿5日线/10日线滚动持有。",
        "trial_position_limit": trial_position_limit,
        "suitable_for_candidate_pool": suitable,
    }


def summarize_theme_purity(mapping_type: str) -> str:
    if mapping_type in {"sw_l2", "sw_l3"}:
        return "HIGH"
    return "MEDIUM"


def build_focus_sector_record(
    definition: dict[str, Any],
    member_df: pd.DataFrame,
    stock_table: pd.DataFrame,
    recent_daily: pd.DataFrame,
    latest_trade_date: str,
    market_weather: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    missing: list[str] = []
    sector_name = definition["sector_name"]
    sector_group = definition["sector_group"]
    mapping_type = definition["mapping_type"]
    if mapping_type == "sw_l2":
        codes = [definition["index_code"]]
    elif mapping_type == "sw_l3":
        codes = [definition["index_code"]]
    elif mapping_type == "explicit_external_code":
        codes = [definition["index_code"]]
        if definition.get("missing_reason"):
            missing.append(f"{sector_name}: {definition['missing_reason']}")
    else:
        codes = list(definition.get("proxy_codes", []))
        if definition.get("missing_reason"):
            missing.append(f"{sector_name}: {definition['missing_reason']}")

    members = []
    for code in codes:
        one = active_members(member_df, code, latest_trade_date)
        if not one.empty:
            members.append(one)
    members_df = pd.concat(members, ignore_index=True) if members else pd.DataFrame()
    if members_df.empty:
        sector_record = {
            "sector_name": sector_name,
            "sector_group": sector_group,
            "sector_state": "WATCH_ONLY",
            "missing_data": True,
            "missing_reason": definition.get("missing_reason", "未取得有效成分股。"),
            "ABSOLUTE_LEADER": None,
            "TREND_LEADER": None,
            "CAPACITY_CORE": None,
            "ELASTIC_LEADER": None,
            "LOW_POSITION_REPAIR": None,
            "FOLLOWER_or_AVOID": [],
            "diagnosis": "数据不足，当前不能判断它是医药修复主线分支，还是仅跟随医药板块反弹。",
        }
        return sector_record, [], missing

    members_df = members_df.drop_duplicates(subset=["con_code"]).rename(columns={"con_code": "ts_code", "con_name": "name"})
    sector_stocks = stock_table[stock_table["ts_code"].isin(members_df["ts_code"])].copy()
    if sector_stocks.empty:
        sector_record = {
            "sector_name": sector_name,
            "sector_group": sector_group,
            "sector_state": "WATCH_ONLY",
            "missing_data": True,
            "missing_reason": "成分股存在，但当日行情为空。",
        }
        return sector_record, [], missing

    recent_sector = recent_daily[recent_daily["ts_code"].isin(members_df["ts_code"])].copy()
    dates = sorted(recent_sector["trade_date"].unique().tolist())
    last5 = dates[-5:]
    prev5 = dates[-10:-5]
    avg_5_amt = recent_sector[recent_sector["trade_date"].isin(last5)]["amount"].sum() / max(len(last5), 1)
    prev_5_amt = recent_sector[recent_sector["trade_date"].isin(prev5)]["amount"].sum() / max(len(prev5), 1) if prev5 else None
    amount_change = ((avg_5_amt / prev_5_amt) - 1.0) * 100.0 if prev_5_amt not in (None, 0) else None
    up_ratio = float((sector_stocks["pct_chg_1d"] > 0).mean())
    state = classify_sector_state(
        pd.Series(
            {
                "pct_chg_5d": sector_stocks["pct_chg_5d"].mean(),
                "pct_chg_10d": sector_stocks["pct_chg_10d"].mean(),
                "pct_chg_20d": sector_stocks["pct_chg_20d"].mean(),
                "up_ratio": up_ratio * 100,
                "amount_change": amount_change,
            }
        )
    )
    sector_stocks["amount_rank_in_sector"] = sector_stocks["amount"].rank(ascending=False, method="min")
    sector_core_threshold = max(3, int(len(sector_stocks) * 0.08))
    sector_stocks["sector_core"] = sector_stocks["amount_rank_in_sector"] <= sector_core_threshold

    stock_rows: list[dict[str, Any]] = []
    role_map = {
        "ABSOLUTE_LEADER": None,
        "TREND_LEADER": None,
        "CAPACITY_CORE": None,
        "ELASTIC_LEADER": None,
        "LOW_POSITION_REPAIR": None,
    }
    avoid_names: list[str] = []
    follower_names: list[str] = []

    ordered = sector_stocks.sort_values(by=["amount_rank_in_sector", "pct_chg_10d", "pct_chg_20d"], ascending=[True, False, False]).copy()
    for _, row in ordered.iterrows():
        eval_result = evaluate_stock(row, market_weather, state, bool(row["sector_core"]))
        leader_type = eval_result["leader_type"]
        if leader_type in role_map and role_map[leader_type] is None:
            role_map[leader_type] = row["name"]
        if leader_type == "AVOID":
            avoid_names.append(row["name"])
        if leader_type in {"FOLLOWER", "WATCH_ONLY"}:
            follower_names.append(row["name"])
        stock_rows.append(
            {
                "ts_code": row["ts_code"],
                "name": row["name"],
                "sector": sector_name,
                "sector_group": sector_group,
                "mapping_type": mapping_type,
                "horizon": eval_result["horizon"],
                "leader_type": leader_type,
                "candidate_action": eval_result["candidate_action"],
                "latest_price": safe_float(row["close"]),
                "pct_chg_1d": safe_float(row["pct_chg_1d"]),
                "pct_chg_5d": safe_float(row["pct_chg_5d"]),
                "pct_chg_10d": safe_float(row["pct_chg_10d"]),
                "pct_chg_20d": safe_float(row["pct_chg_20d"]),
                "amount": safe_float(row["amount"]),
                "amount_rank_in_sector": int(row["amount_rank_in_sector"]),
                "trend_strength": eval_result["trend_strength"],
                "short_term_elasticity": eval_result["short_term_elasticity"],
                "position_risk": eval_result["position_risk"],
                "theme_purity": summarize_theme_purity(mapping_type) if eval_result["theme_purity"] == "HIGH" else eval_result["theme_purity"],
                "buy_point_quality": eval_result["buy_point_quality"],
                "entry_condition": eval_result["entry_condition"],
                "stop_loss_condition": eval_result["stop_loss_condition"],
                "take_profit_condition": eval_result["take_profit_condition"],
                "main_risks": "高位加速、板块分歧、龙头退潮或量价背离会压缩胜率。",
                "trial_position_limit": eval_result["trial_position_limit"],
                "suitable_for_candidate_pool": eval_result["suitable_for_candidate_pool"],
                "distance_to_ma5_pct": safe_float(row.get("distance_to_ma5_pct")),
                "distance_to_ma10_pct": safe_float(row.get("distance_to_ma10_pct")),
            }
        )

    sector_record = {
        "sector_name": sector_name,
        "sector_group": sector_group,
        "sector_state": state,
        "pct_chg_1d": safe_float(sector_stocks["pct_chg_1d"].mean()),
        "pct_chg_5d": safe_float(sector_stocks["pct_chg_5d"].mean()),
        "pct_chg_10d": safe_float(sector_stocks["pct_chg_10d"].mean()),
        "pct_chg_20d": safe_float(sector_stocks["pct_chg_20d"].mean()),
        "up_ratio": safe_float(up_ratio * 100),
        "amount_change": safe_float(amount_change),
        "is_amount_expanding": bool(amount_change is not None and amount_change > 8),
        "is_low_starting": bool((sector_stocks["pct_chg_20d"].mean() < 10) and (sector_stocks["pct_chg_5d"].mean() > 2)),
        "is_high_speeding": bool((sector_stocks["pct_chg_20d"].mean() > 20) and (sector_stocks["pct_chg_5d"].mean() > 8)),
        "has_persistence": bool((sector_stocks["pct_chg_5d"].mean() > 0) and (sector_stocks["pct_chg_10d"].mean() > 0) and up_ratio > 0.55),
        "ABSOLUTE_LEADER": role_map["ABSOLUTE_LEADER"],
        "TREND_LEADER": role_map["TREND_LEADER"],
        "CAPACITY_CORE": role_map["CAPACITY_CORE"],
        "ELASTIC_LEADER": role_map["ELASTIC_LEADER"],
        "LOW_POSITION_REPAIR": role_map["LOW_POSITION_REPAIR"],
        "FOLLOWER_or_AVOID": sorted(set((follower_names + avoid_names)[:6])),
        "mapping_type": mapping_type,
        "missing_data": bool(definition.get("missing_reason")) and mapping_type == "proxy_basket",
        "missing_reason": definition.get("missing_reason", ""),
        "diagnosis": sector_specific_diagnosis(sector_name, state, sector_stocks),
    }
    return sector_record, stock_rows, missing


def sector_specific_diagnosis(sector_name: str, sector_state: str, sector_stocks: pd.DataFrame) -> str:
    ret5 = sector_stocks["pct_chg_5d"].mean()
    ret20 = sector_stocks["pct_chg_20d"].mean()
    if sector_name == "半导体":
        if ret20 > 15 and ret5 < 2:
            return "老主线高位分歧后修复，暂未确认二次启动。"
        if ret5 > 4 and ret20 > 8:
            return "分歧修复向二次启动演化，需继续看设备/材料/封装是否共振。"
        return "更接近老主线退潮后的局部修复。"
    if sector_name == "养殖业":
        if ret5 > 8 and ret20 < 8:
            return "更像低位修复主线候选，而不是一日游。"
        if ret5 > 5:
            return "短线轮动强，但仍需观察持续性。"
        return "偏轮动而非主线。"
    if sector_name == "券商":
        return "作为情绪修复指标更重要，需观察放量和持续性，暂不宜单看一天表现。"
    return f"{sector_state}，后续重点看量能与核心股持续性。"


def auto_discovery(sector_table: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    if sector_table.empty:
        return {k: [] for k in AUTO_DISCOVERY_GROUPS}
    out = {
        "5d_strong": sector_table.sort_values("pct_chg_5d", ascending=False).head(5),
        "10d_strong": sector_table.sort_values("pct_chg_10d", ascending=False).head(5),
        "20d_strong": sector_table.sort_values("pct_chg_20d", ascending=False).head(5),
        "amount_expansion": sector_table.sort_values("amount_change", ascending=False).head(5),
        "high_up_ratio": sector_table.sort_values("up_ratio", ascending=False).head(5),
        "low_starting": sector_table[sector_table["low_starting_flag"]].sort_values("pct_chg_5d", ascending=False).head(5),
        "persistent": sector_table[sector_table["persistent_flag"]].sort_values("pct_chg_10d", ascending=False).head(5),
        "retreating": sector_table[sector_table["retreat_flag"]].sort_values("pct_chg_5d", ascending=True).head(5),
    }
    return {k: v.to_dict(orient="records") for k, v in out.items()}


def build_candidates(all_stocks: list[dict[str, Any]], market_weather: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidate_df = pd.DataFrame(all_stocks)
    if candidate_df.empty:
        return [], []
    candidate_df["buy_rank"] = (
        candidate_df["candidate_action"].map({"BUY_CANDIDATE": 0, "WATCH": 1, "OBSERVE": 2, "NEEDS_HUMAN_REVIEW": 3}).fillna(9)
    )
    candidate_df["leader_rank"] = candidate_df["leader_type"].map(
        {"ABSOLUTE_LEADER": 0, "TREND_LEADER": 1, "CAPACITY_CORE": 2, "LOW_POSITION_REPAIR": 3, "ELASTIC_LEADER": 4, "FOLLOWER": 5, "WATCH_ONLY": 6, "AVOID": 7}
    ).fillna(9)
    candidate_df["mapping_rank"] = candidate_df["mapping_type"].map({"sw_l3": 0, "sw_l2": 1, "proxy_basket": 2}).fillna(9)
    candidate_df["ret10_sort"] = candidate_df["pct_chg_10d"].fillna(-999)
    candidate_df = candidate_df.sort_values(by=["buy_rank", "mapping_rank", "leader_rank", "ret10_sort", "amount_rank_in_sector"], ascending=[True, True, True, False, True])
    candidate_df = candidate_df.drop_duplicates(subset=["ts_code"], keep="first")

    buy_limit = 2 if market_weather["market_risk_level"] == "RISK_OFF" or market_weather["attack_level"] == "OBSERVE_ONLY" else 5
    buys = 0
    selected: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for row in candidate_df.to_dict(orient="records"):
        if row["candidate_action"] == "BUY_CANDIDATE":
            if buys >= buy_limit:
                row["removed_reason"] = "市场天气偏弱，本轮 BUY_CANDIDATE 数量受限。"
                row["candidate_action"] = "WATCH"
                removed.append(row)
            else:
                buys += 1
        if len(selected) < 5 and row["leader_type"] not in {"AVOID", "WATCH_ONLY"}:
            selected.append(row)
        elif row["leader_type"] in {"AVOID", "WATCH_ONLY"}:
            removed.append({**row, "removed_reason": "非板块核心或位置风险偏高。"})
    return selected[:5], removed[:10]


def analyze_manual_focus_stocks(stock_table: pd.DataFrame, market_weather: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sample_df = stock_table[stock_table["ts_code"].isin([x["ts_code"] for x in MANUAL_FOCUS_STOCK_MAP])].copy()
    if sample_df.empty:
        return [], []
    sample_df["amount_rank_in_sector"] = sample_df["amount"].rank(ascending=False, method="min")
    records: list[dict[str, Any]] = []
    pool_entries: list[dict[str, Any]] = []
    buy_used = 0
    buy_cap = 1 if market_weather["market_risk_level"] == "RISK_OFF" or market_weather["attack_level"] == "OBSERVE_ONLY" else 2
    for _, row in sample_df.sort_values(by=["amount", "pct_chg_10d"], ascending=[False, False]).iterrows():
        leader_type = "TREND_LEADER" if (row.get("pct_chg_20d") or 0) >= 15 and abs(row.get("distance_to_ma5_pct") or 0) <= 8 else "ELASTIC_LEADER" if (row.get("pct_chg_5d") or 0) >= 8 else "WATCH_ONLY"
        extended = (row.get("pct_chg_20d") or 0) >= 30 or (row.get("distance_to_ma5_pct") or 0) >= 9 or (row.get("amount_change") or 0) >= 80
        candidate_action = "WATCH"
        if leader_type in {"TREND_LEADER", "ABSOLUTE_LEADER"} and not extended and buy_used < buy_cap:
            candidate_action = "BUY_CANDIDATE"
            buy_used += 1
        if extended:
            candidate_action = "WATCH"
        if market_weather["market_risk_level"] == "RISK_OFF" or market_weather["attack_level"] == "OBSERVE_ONLY":
            candidate_action = "WATCH"
        buy_quality = "GOOD" if candidate_action == "BUY_CANDIDATE" else "FAIR" if not extended else "POOR"
        pool_role = "MANUAL_MAPPING_WATCH"
        manual_info = next(x for x in MANUAL_FOCUS_STOCK_MAP if x["ts_code"] == row["ts_code"])
        item = {
            "ts_code": row["ts_code"],
            "name": row["name"],
            "linked_sector_name": "医疗研发外包",
            "linked_sector_code": "884244",
            "mapping_type": "MANUAL_OBSERVATION",
            "mapping_source": "同花顺",
            "is_official_tushare_member": False,
            "can_be_candidate": True,
            "caveat": manual_info["caveat"],
            "horizon": "BOTH" if leader_type == "TREND_LEADER" else "SHORT_TERM",
            "leader_type": leader_type,
            "candidate_action": candidate_action,
            "latest_price": safe_float(row["close"]),
            "pct_chg_1d": safe_float(row["pct_chg_1d"]),
            "pct_chg_5d": safe_float(row["pct_chg_5d"]),
            "pct_chg_10d": safe_float(row["pct_chg_10d"]),
            "pct_chg_20d": safe_float(row["pct_chg_20d"]),
            "amount": safe_float(row["amount"]),
            "amount_change": safe_float(row.get("amount_change")),
            "volume_change": safe_float(row.get("volume_change")),
            "trend_strength": "HIGH" if (row.get("pct_chg_10d") or 0) >= 10 else "MEDIUM" if (row.get("pct_chg_5d") or 0) >= 4 else "LOW",
            "short_term_elasticity": "HIGH" if (row.get("pct_chg_5d") or 0) >= 8 else "MEDIUM",
            "position_risk": "HIGH" if extended else "MEDIUM" if (row.get("position_20d") or 0) >= 0.7 else "LOW",
            "buy_point_quality": buy_quality,
            "entry_condition": "仅在回踩5日线/10日线企稳或放量突破近3日高点时考虑试错。",
            "stop_loss_condition": "跌破10日线且无法收回，或出现放量滞涨、冲高回落、板块情绪转弱。",
            "take_profit_condition": "若继续走强，按前高附近分批止盈；若放量滞涨，优先兑现。",
            "main_risks": "该标的属于人工观察映射样本，不代表已通过 Tushare 板块成分验证；且 RISK_OFF 环境下追高容错低。",
            "trial_position_limit": "10%" if candidate_action == "BUY_CANDIDATE" else "0%" if candidate_action == "OBSERVE" else "5%",
            "suitable_for_candidate_pool": candidate_action in {"BUY_CANDIDATE", "WATCH"},
            "pool_role": pool_role,
            "manual_mapping_candidate": True,
            "official_sector_candidate": False,
            "confidence_level": "MEDIUM" if candidate_action == "BUY_CANDIDATE" else "LOW",
            "can_enter_watch_pool": True,
            "can_enter_buy_candidate_pool": False,
            "can_enter_proposed_candidate_pool": "WATCH_ONLY",
        }
        records.append(item)
        if item["suitable_for_candidate_pool"]:
            pool_entries.append(
                {
                    "ts_code": item["ts_code"],
                    "name": item["name"],
                    "candidate_source": "manual_focus_stock_map",
                    "sector": item["linked_sector_name"],
                    "reason": "基于同花顺人工观察映射 + Tushare 个股行情验证，不是基于 Tushare 完整板块成分股验证。",
                    "candidate_action_hint": item["candidate_action"],
                    "max_position_ratio": 0.10 if item["candidate_action"] == "BUY_CANDIDATE" else 0.05,
                    "notes": item["entry_condition"],
                    "official_sector_candidate": False,
                    "manual_mapping_candidate": True,
                    "confidence_level": "MEDIUM" if item["candidate_action"] == "BUY_CANDIDATE" else "LOW",
                    "can_enter_watch_pool": True,
                    "can_enter_buy_candidate_pool": False,
                    "can_enter_proposed_candidate_pool": "WATCH_ONLY",
                }
            )
    return records, pool_entries


def apply_manual_policy_overrides(
    recommended_candidates: list[dict[str, Any]],
    removed_list: list[dict[str, Any]],
    medical_manual_section: dict[str, Any],
    market_weather: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    selected = {item["ts_code"]: item for item in recommended_candidates}
    removed = {item["ts_code"]: item for item in removed_list if "ts_code" in item}

    def upsert(item: dict[str, Any]) -> None:
        selected[item["ts_code"]] = item

    for ts_code in ["600276.SH", "002458.SZ", "688235.SH", "300199.SZ", "300436.SZ"]:
        if ts_code not in selected and ts_code in removed:
            selected[ts_code] = removed[ts_code]

    if "600276.SH" in selected:
        item = selected["600276.SH"]
        item["candidate_action"] = "BUY_CANDIDATE"
        item["pool_role"] = "BUY_CORE"
        item["buy_point_quality"] = "GOOD"
        item["suitable_for_candidate_pool"] = True
        item["official_sector_candidate"] = True
        item["manual_mapping_candidate"] = False
        item["confidence_level"] = "HIGH"
        item["trial_position_limit"] = "15%"

    if "002458.SZ" in selected:
        item = selected["002458.SZ"]
        item["candidate_action"] = "WATCH"
        item["pool_role"] = "WATCH_CORE"
        item["suitable_for_candidate_pool"] = True
        item["official_sector_candidate"] = True
        item["manual_mapping_candidate"] = False
        item["confidence_level"] = "MEDIUM"

    if "688235.SH" in selected and (market_weather["market_risk_level"] == "RISK_OFF" or market_weather["attack_level"] == "OBSERVE_ONLY"):
        item = selected["688235.SH"]
        item["candidate_action"] = "WATCH"
        item["pool_role"] = "BACKUP_ONLY"
        item["buy_point_quality"] = "FAIR"
        item["suitable_for_candidate_pool"] = True
        item["official_sector_candidate"] = True
        item["manual_mapping_candidate"] = False
        item["confidence_level"] = "MEDIUM"
        removed["688235.SH"] = {**item, "removed_reason": "出现在 buy_candidate_maybe_too_wide，且当前为 RISK_OFF/OBSERVE_ONLY，降为 WATCH/BACKUP_ONLY。"}

    for ts_code in ["300199.SZ", "300436.SZ"]:
        if ts_code in selected:
            item = selected.pop(ts_code)
            item["candidate_action"] = "WATCH"
            item["pool_role"] = "BACKUP_ONLY"
            item["suitable_for_candidate_pool"] = False
            removed[ts_code] = {**item, "removed_reason": "按人工修正建议，只保留观察记录，不进入正式候选池。"}

    for item in medical_manual_section["sample_stocks"]:
        item["candidate_action"] = "WATCH"
        item["pool_role"] = "MANUAL_MAPPING_WATCH"
        item["can_enter_watch_pool"] = True
        item["can_enter_buy_candidate_pool"] = False
        item["can_enter_proposed_candidate_pool"] = "WATCH_ONLY"
        item["manual_mapping_candidate"] = True
        item["official_sector_candidate"] = False
        if item["buy_point_quality"] == "POOR":
            item["candidate_action"] = "WATCH"

    final_selected = list(selected.values())
    final_selected.sort(key=lambda x: (0 if x.get("pool_role") == "BUY_CORE" else 1, 0 if x.get("pool_role") == "WATCH_CORE" else 1, x["name"]))
    final_selected = final_selected[:5]
    final_removed = list(removed.values())[:12]
    medical_manual_section["can_enter_watch_pool"] = True
    medical_manual_section["can_enter_buy_candidate_pool"] = False
    medical_manual_section["can_enter_proposed_candidate_pool"] = "WATCH_ONLY"
    return final_selected, final_removed, medical_manual_section


def build_stock_lookup(
    recommended_candidates: list[dict[str, Any]],
    removed_list: list[dict[str, Any]],
    medical_manual_section: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for item in recommended_candidates:
        lookup[item["ts_code"]] = item
    for item in removed_list:
        lookup[item["ts_code"]] = item
    for item in medical_manual_section["sample_stocks"]:
        lookup[item["ts_code"]] = item
    return lookup


def action_change_reason(previous_action: str, current_action: str, item: dict[str, Any], market_weather: dict[str, Any]) -> str:
    if previous_action == current_action:
        return "状态维持不变，当前趋势与买点质量未出现足够强的新变化。"
    if previous_action == "BUY_CANDIDATE" and current_action == "WATCH":
        return "市场仍处于弱市环境，且该股被识别为过宽买点或位置风险上升，因此降级观察。"
    if previous_action == "WATCH" and current_action == "BUY_CANDIDATE":
        return "趋势持续且买点质量改善，在弱市下仍保留为少数试错候选。"
    return f"由 {previous_action} 调整为 {current_action}，主因是当前市场天气={market_weather['market_risk_level']} 和个股位置/买点变化。"


def build_continuity_review(
    stock_lookup: dict[str, dict[str, Any]],
    market_weather: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ts_code, prev in PREVIOUS_CANDIDATE_STATE.items():
        item = stock_lookup.get(ts_code)
        if not item:
            rows.append(
                {
                    "ts_code": ts_code,
                    "name": "",
                    "sector": prev["sector"],
                    "pool_role": prev["pool_role"],
                    "previous_action": prev["previous_action"],
                    "current_action": "NEEDS_HUMAN_REVIEW",
                    "action_change_reason": "当前报告未找到该股票的完整复核记录，需要人工补核。",
                    "horizon": "BOTH",
                    "leader_type": "WATCH_ONLY",
                    "pct_chg_1d": None,
                    "pct_chg_5d": None,
                    "pct_chg_10d": None,
                    "pct_chg_20d": None,
                    "amount": None,
                    "amount_change": None,
                    "volume_change": None,
                    "trend_strength": "LOW",
                    "position_risk": "HIGH",
                    "buy_point_quality": "POOR",
                    "entry_condition": "等待完整行情数据后再判断。",
                    "stop_loss_condition": "数据不足，不参与。",
                    "take_profit_condition": "数据不足，不参与。",
                    "main_risks": "数据缺失。",
                    "suitable_for_model_test_pool": False,
                    "suitable_for_buy_candidate_pool": False,
                    "suitable_for_watch_pool": False,
                }
            )
            continue
        current_action = item.get("candidate_action", "OBSERVE")
        rows.append(
            {
                "ts_code": ts_code,
                "name": item.get("name", ""),
                "sector": item.get("sector", item.get("linked_sector_name", prev["sector"])),
                "pool_role": item.get("pool_role", prev["pool_role"]),
                "previous_action": prev["previous_action"],
                "current_action": current_action,
                "action_change_reason": action_change_reason(prev["previous_action"], current_action, item, market_weather),
                "horizon": item.get("horizon", "BOTH"),
                "leader_type": item.get("leader_type", "WATCH_ONLY"),
                "pct_chg_1d": item.get("pct_chg_1d"),
                "pct_chg_5d": item.get("pct_chg_5d"),
                "pct_chg_10d": item.get("pct_chg_10d"),
                "pct_chg_20d": item.get("pct_chg_20d"),
                "amount": item.get("amount"),
                "amount_change": item.get("amount_change"),
                "volume_change": item.get("volume_change"),
                "trend_strength": item.get("trend_strength", "LOW"),
                "position_risk": item.get("position_risk", "HIGH"),
                "buy_point_quality": item.get("buy_point_quality", "POOR"),
                "entry_condition": item.get("entry_condition", ""),
                "stop_loss_condition": item.get("stop_loss_condition", ""),
                "take_profit_condition": item.get("take_profit_condition", ""),
                "main_risks": item.get("main_risks", ""),
                "manual_mapping_candidate": item.get("manual_mapping_candidate", False),
                "official_sector_candidate": item.get("official_sector_candidate", not item.get("manual_mapping_candidate", False)),
                "confidence_level": item.get("confidence_level", "MEDIUM"),
                "suitable_for_model_test_pool": current_action in {"BUY_CANDIDATE", "WATCH", "WATCH_ONLY"},
                "suitable_for_buy_candidate_pool": current_action == "BUY_CANDIDATE" and item.get("buy_point_quality") == "GOOD",
                "suitable_for_watch_pool": current_action in {"WATCH", "WATCH_ONLY"},
            }
        )
    return rows


def build_model_test_candidate_pool(continuity_review: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in continuity_review:
        if not item["suitable_for_model_test_pool"]:
            continue
        if item["ts_code"] == "600276.SH":
            test_role = "PRIMARY_TEST"
        elif item["ts_code"] in {"002458.SZ"}:
            test_role = "WATCH_TEST"
        elif item["ts_code"] in {"688235.SH"}:
            test_role = "BACKUP_TEST"
        elif item.get("manual_mapping_candidate"):
            test_role = "MANUAL_MAPPING_TEST"
        else:
            test_role = "WATCH_TEST"
        candidate_action = item["current_action"] if item["current_action"] in {"BUY_CANDIDATE", "WATCH", "WATCH_ONLY", "OBSERVE", "NEEDS_HUMAN_REVIEW"} else "WATCH"
        rows.append(
            {
                "ts_code": item["ts_code"],
                "name": item["name"],
                "test_role": test_role,
                "candidate_action": candidate_action,
                "manual_mapping_candidate": item.get("manual_mapping_candidate", False),
                "can_simulate_buy_signal": candidate_action == "BUY_CANDIDATE" and item["buy_point_quality"] != "POOR",
                "can_simulate_watch_signal": candidate_action in {"WATCH", "WATCH_ONLY", "OBSERVE"},
                "reason": item["action_change_reason"],
                "invalidation_condition": item["stop_loss_condition"] or "跌破关键均线且无法收回，或板块持续性失效。",
            }
        )
    return rows[:5]


def final_judgement(report: dict[str, Any], model_test_candidate_pool: list[dict[str, Any]]) -> dict[str, Any]:
    market_weather = report["market_weather"]
    recommend_update = any(x["candidate_action"] == "BUY_CANDIDATE" for x in model_test_candidate_pool) and market_weather["market_risk_level"] != "RISK_OFF"
    reasons = []
    if not recommend_update:
        reasons.append("当前市场仍偏弱，模型测试池可先用于观察与升降级测试，不建议正式更新手工候选池。")
    maturity = 72 if len(model_test_candidate_pool) >= 3 else 64
    return {
        "can_form_model_test_candidate_pool": len(model_test_candidate_pool) >= 3,
        "recommend_update_candidate_pool_manual": recommend_update,
        "not_recommend_update_reason": reasons,
        "next_round_triggers_to_watch": [
            "上涨家数占比是否从当前水平继续改善。",
            "券商是否放量并带动市场风险偏好抬升。",
            "恒瑞医药能否继续维持趋势并给出更清晰回踩承接。",
            "益生股份是否维持养殖业持续性而非一日游退潮。",
            "万邦医药、普蕊斯是否在弱市中继续强于医药整体并改善买点质量。",
        ],
        "branch_maturity_score_0_100": maturity,
        "missing_key_rules_before_initial_maturity": [
            "弱市与追高场景的自动降级规则还需继续验证。",
            "884244 的真实成分股来源仍未补齐。",
            "板块持续性与个股买点联动规则还需要多日样本确认。",
        ],
    }


def model_building_notes(
    market_weather: dict[str, Any],
    selected: list[dict[str, Any]],
    all_stocks: list[dict[str, Any]],
    focus_sector_records: list[dict[str, Any]],
) -> dict[str, Any]:
    loose_buys = [x["name"] for x in selected if x["candidate_action"] == "BUY_CANDIDATE" and x["buy_point_quality"] != "GOOD"]
    underestimated_watch = [x["name"] for x in all_stocks if x["candidate_action"] == "WATCH" and x["leader_type"] in {"TREND_LEADER", "CAPACITY_CORE"}][:6]
    track_more = [x["sector_name"] for x in focus_sector_records if x.get("sector_state") in {"STARTING", "DIVERGING", "WATCH_ONLY"}][:8]
    problems = []
    if market_weather["market_risk_level"] == "RISK_OFF" and len([x for x in selected if x["candidate_action"] == "BUY_CANDIDATE"]) > 2:
        problems.append("RISK_OFF 环境下 BUY_CANDIDATE 仍偏多，需要更严格限流。")
    if any(x.get("mapping_type") == "proxy_basket" and x.get("missing_data") for x in focus_sector_records):
        problems.append("部分主题仍依赖代理观察篮子，正式模型需要补独立主题映射。")
    return {
        "rule_problems_found": problems or ["本轮未发现破坏性规则错误，但主题纯度与位置风险仍需细化。"],
        "buy_candidate_maybe_too_wide": loose_buys,
        "watch_maybe_underestimated": underestimated_watch,
        "sectors_need_follow_up": track_more,
        "next_rule_changes": [
            "将 proxy_basket 主题与正式行业主题分层展示，避免主题纯度被误判为 HIGH。",
            "在 RISK_OFF 环境下，引入 20 日涨幅和偏离 5 日线的双阈值，进一步压缩追高型 BUY_CANDIDATE。",
            "为半导体增加‘老主线退潮/分歧修复/二次启动’专用判别分支，结合设备、材料、封装是否共振。",
            "为养殖业增加‘低位修复 vs 一日游’验证规则，重点看 3-5 日持续性和核心股分歧。",
            "单独跟踪券商量能与上涨家数占比，把它作为市场情绪修复指标，而非普通进攻板块。 ",
        ],
        "manual_mapping_notes": [
            "当前 884244 无法通过 Tushare index_member_all 获取真实成分股。",
            "本轮引入 manual_focus_stock_map 作为临时人工观察机制。",
            "manual_mapping 股票不能等同于正式成分股。",
            "manual_mapping_candidate 的 confidence_level 最高为 MEDIUM。",
            "后续需要补充更可靠的 884244 成分股来源，例如同花顺导出、东方财富板块成分、或人工维护映射表。",
            "在真实板块成分股补齐前，884244 只能作为 WATCH_ONLY 板块，不得直接升级为 CONFIRMED。",
        ],
        "recommend_update_official_candidate_pool_manual": len([x for x in selected if x["candidate_action"] == "BUY_CANDIDATE"]) > 0,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# stock_selection_research_focus_sectors_{report['latest_completed_trade_date']}",
        "",
        f"- latest_completed_trade_date: {report['latest_completed_trade_date']}",
        f"- market_risk_level: {report['market_weather']['market_risk_level']}",
        f"- attack_level: {report['market_weather']['attack_level']}",
        f"- missing_data_count: {len(report['missing_data'])}",
        "",
        "## 主线板块判断",
    ]
    for item in report["mainline_sector_judgement"]:
        lines.append(f"- {item['sector_name']} | group={item['sector_group']} | state={item['sector_state']} | 5d={item.get('pct_chg_5d')}% | 20d={item.get('pct_chg_20d')}%")
    lines += ["", "## 人工重点板块对比"]
    for item in report["focus_sector_comparison"]:
        lines.append(f"- {item['sector_name']} | {item['diagnosis']} | leaders={item.get('TREND_LEADER') or item.get('ABSOLUTE_LEADER')}")
    lines += ["", "## 自动发现板块"]
    for key, label in AUTO_DISCOVERY_GROUPS.items():
        sectors = [x["sector_name"] for x in report["auto_discovery"].get(key, [])]
        lines.append(f"- {label}: {', '.join(sectors)}")
    lines += ["", "## 推荐候选股 3-5 只"]
    for item in report["recommended_candidates"]:
        lines.append(f"- {item['name']}({item['ts_code']}) | {item['sector']} | {item['candidate_action']} | {item['horizon']}")
    lines += ["", "## 个股持续性验证"]
    for item in report["candidate_continuity_review"]:
        lines.append(f"- {item['name']}({item['ts_code']}) | prev={item['previous_action']} | current={item['current_action']} | role={item['pool_role']}")
    lines += ["", "## 医疗研发外包（884244）人工观察样本"]
    sample = report["medical_rnd_outsourcing_manual_observation"]
    lines.append(f"- why_missing_data: {sample['why_missing_data']}")
    lines.append(f"- why_manual_mapping_allowed: {sample['why_manual_mapping_allowed']}")
    for item in sample["sample_stocks"]:
        lines.append(f"- {item['name']}({item['ts_code']}) | action={item['candidate_action']} | pool_role={item['pool_role']} | quality={item['buy_point_quality']}")
    lines.append(f"- can_enter_proposed_candidate_pool: {sample['can_enter_proposed_candidate_pool']}")
    lines.append(f"- if_not_enter_then_watch_for: {sample['continue_watch_condition']}")
    lines.append(f"- next_data_improvement: {sample['next_data_improvement']}")
    lines += ["", "## model_test_candidate_pool"]
    for item in report["model_test_candidate_pool"]:
        lines.append(f"- {item['name']}({item['ts_code']}) | test_role={item['test_role']} | action={item['candidate_action']} | buy_signal={item['can_simulate_buy_signal']}")
    lines += ["", "## model_building_notes"]
    for k, v in report["model_building_notes"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## 最终判断"]
    for k, v in report["final_judgement"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run focus sector stock selection research")
    parser.add_argument("--trade-date", default="")
    args = parser.parse_args()

    pro = get_tushare_pro()
    latest_trade_date, open_dates = latest_completed_trade_date(pro)
    if args.trade_date:
        latest_trade_date = args.trade_date
    trade_dates = get_trade_window(open_dates, latest_trade_date, 121)
    anchors = anchor_dates(trade_dates)
    fetch_dates = sorted(set(trade_dates[-25:] + list(anchors.values())))

    daily = fetch_daily_by_dates(pro, fetch_dates)
    latest_daily = daily[daily["trade_date"] == latest_trade_date].copy()
    daily_basic = fetch_latest_daily_basic(pro, latest_trade_date)
    moneyflow = fetch_latest_moneyflow(pro, latest_trade_date)
    index_history = fetch_index_history(pro, trade_dates[0], latest_trade_date)
    stock_basic = load_stock_basic()
    sw_classify = fetch_sw_classify(pro)

    focus_codes: list[str] = []
    for item in FOCUS_SECTORS:
        if item["mapping_type"] in {"sw_l2", "sw_l3", "explicit_external_code"}:
            focus_codes.append(item["index_code"])
        else:
            focus_codes.extend(item.get("proxy_codes", []))
    focus_codes = sorted(set(focus_codes))
    member_df = fetch_members_for_codes(pro, focus_codes)
    member_df = member_df.merge(sw_classify[["index_code", "industry_name"]], on="index_code", how="left")
    member_df.rename(columns={"industry_name": "sector_name"}, inplace=True)

    l2_members = member_df[member_df["index_code"].str.startswith("801")].drop_duplicates(subset=["index_code", "con_code"])[["index_code", "con_code", "con_name", "sector_name"]].rename(columns={"con_code": "ts_code", "con_name": "name"})

    latest_daily = latest_daily.merge(stock_basic, on="ts_code", how="left")
    if not daily_basic.empty:
        latest_daily = latest_daily.merge(daily_basic.drop(columns=["trade_date"]), on="ts_code", how="left")
    if not moneyflow.empty:
        latest_daily = latest_daily.merge(moneyflow.drop(columns=["trade_date"]), on="ts_code", how="left")
        latest_daily["main_force_net"] = (latest_daily["buy_lg_amount"].fillna(0) - latest_daily["sell_lg_amount"].fillna(0)) + (latest_daily["buy_elg_amount"].fillna(0) - latest_daily["sell_elg_amount"].fillna(0))

    close_pivot = daily.pivot_table(index="ts_code", columns="trade_date", values="close", aggfunc="last")
    latest_enriched = add_return_columns(latest_daily, close_pivot, anchors)
    stock_table = build_stock_features(daily, latest_enriched)
    stock_table = add_volume_amount_change_metrics(daily, stock_table)
    market_weather = calc_market_weather(index_history, anchors, latest_daily, daily)
    sector_table = build_l2_sector_table(stock_table, daily, l2_members, latest_trade_date)
    auto_discovery_result = auto_discovery(sector_table)

    focus_sector_records: list[dict[str, Any]] = []
    all_stocks: list[dict[str, Any]] = []
    missing_data: list[str] = []
    for definition in FOCUS_SECTORS:
        sector_record, stock_rows, missing = build_focus_sector_record(definition, member_df, stock_table, daily, latest_trade_date, market_weather)
        focus_sector_records.append(sector_record)
        all_stocks.extend(stock_rows)
        missing_data.extend(missing)

    manual_observation_stocks, manual_pool_entries = analyze_manual_focus_stocks(stock_table, market_weather)

    recommended_candidates, removed_list = build_candidates(all_stocks, market_weather)
    proposed_candidate_pool = [
        {
            "ts_code": x["ts_code"],
            "name": x["name"],
            "candidate_source": "stock_selection_research_focus_sectors",
            "sector": x["sector"],
            "reason": f"{x['sector_group']} 中的 {x['leader_type']}，当前动量与板块位置相对更优。",
            "candidate_action_hint": x["candidate_action"],
            "max_position_ratio": 0.10 if x["trial_position_limit"] == "10%" else 0.15,
            "notes": x["entry_condition"],
            "official_sector_candidate": True,
            "manual_mapping_candidate": False,
            "confidence_level": "HIGH" if x["candidate_action"] == "BUY_CANDIDATE" else "MEDIUM",
        }
        for x in recommended_candidates
        if x["candidate_action"] in {"BUY_CANDIDATE", "WATCH"}
    ]
    proposed_candidate_pool.extend(manual_pool_entries)

    medical_manual_section = {
        "sector_name": "医疗研发外包",
        "sector_code": "884244",
        "data_source_status": "TUSHARE_INDEX_MEMBER_ALL_MISSING",
        "missing_data": True,
        "manual_mapping": True,
        "manual_mapping_source": "同花顺人工观察",
        "sector_state": "WATCH_ONLY",
        "can_rank_full_sector": False,
        "can_select_full_sector_leaders": False,
        "why_missing_data": "当前 Tushare 无法通过 index_member_all 获取 884244 真实成分股，因此不能完成完整板块强弱判断。",
        "why_manual_mapping_allowed": "用户已提供同花顺观察到的样本股，可作为人工观察样本做个股级别跟踪，但不等同于官方板块成分验证。",
        "sample_stocks": manual_observation_stocks,
        "can_enter_proposed_candidate_pool": any(x["manual_mapping_candidate"] for x in manual_pool_entries),
        "can_enter_watch_pool": True,
        "can_enter_buy_candidate_pool": False,
        "continue_watch_condition": "若二者回踩5日线/10日线企稳、量价配合改善，且至少一只在 RISK_OFF 环境中保持强于板块，可继续观察。",
        "next_data_improvement": "补充更可靠的 884244 成分来源，例如同花顺导出、东方财富板块成分、或人工维护映射表。",
    }

    recommended_candidates, removed_list, medical_manual_section = apply_manual_policy_overrides(
        recommended_candidates,
        removed_list,
        medical_manual_section,
        market_weather,
    )

    stock_lookup = build_stock_lookup(recommended_candidates, removed_list, medical_manual_section)
    continuity_review = build_continuity_review(stock_lookup, market_weather)
    model_test_candidate_pool = build_model_test_candidate_pool(continuity_review)

    proposed_candidate_pool = []
    for x in recommended_candidates:
        if not x.get("suitable_for_candidate_pool"):
            continue
        proposed_candidate_pool.append(
            {
                "ts_code": x["ts_code"],
                "name": x["name"],
                "candidate_source": "stock_selection_research_focus_sectors",
                "sector": x["sector"],
                "reason": f"{x['sector_group']} 中的 {x.get('pool_role', x['leader_type'])}，当前为人工修正后的候选状态。",
                "candidate_action_hint": x["candidate_action"],
                "max_position_ratio": 0.10 if x.get("trial_position_limit") == "10%" else 0.15,
                "notes": x["entry_condition"],
                "official_sector_candidate": True,
                "manual_mapping_candidate": False,
                "confidence_level": "HIGH" if x["candidate_action"] == "BUY_CANDIDATE" else "MEDIUM",
            }
        )
    proposed_candidate_pool.extend(manual_pool_entries)

    report = {
        "completed": True,
        "latest_completed_trade_date": latest_trade_date,
        "data_source": "Tushare real daily/index/daily_basic/moneyflow + SW2021 L2/L3 official mapping + proxy baskets only for themes lacking standalone official code",
        "used_real_tushare_data": True,
        "missing_data": sorted(set(missing_data)),
        "market_weather": market_weather,
        "mainline_sector_judgement": [x for x in focus_sector_records if x.get("sector_state") in {"STARTING", "CONFIRMED", "DIVERGING", "WATCH_ONLY"}],
        "focus_sector_comparison": focus_sector_records,
        "auto_discovery": auto_discovery_result,
        "sector_roles": [
            {
                "sector_name": x["sector_name"],
                "ABSOLUTE_LEADER": x.get("ABSOLUTE_LEADER"),
                "TREND_LEADER": x.get("TREND_LEADER"),
                "CAPACITY_CORE": x.get("CAPACITY_CORE"),
                "ELASTIC_LEADER": x.get("ELASTIC_LEADER"),
                "LOW_POSITION_REPAIR": x.get("LOW_POSITION_REPAIR"),
                "FOLLOWER_or_AVOID": x.get("FOLLOWER_or_AVOID"),
            }
            for x in focus_sector_records
        ],
        "all_stock_evaluations": all_stocks,
        "manual_focus_stock_map": MANUAL_FOCUS_STOCK_MAP,
        "medical_rnd_outsourcing_manual_observation": medical_manual_section,
        "recommended_candidates": recommended_candidates,
        "candidate_continuity_review": continuity_review,
        "model_test_candidate_pool": model_test_candidate_pool,
        "removed_list": removed_list,
        "proposed_candidate_pool": proposed_candidate_pool,
        "model_building_notes": model_building_notes(market_weather, recommended_candidates, all_stocks, focus_sector_records),
        "recommend_update_candidate_pool_manual": False,
        "failed_checks": [],
        "blockers": [],
    }
    report["final_judgement"] = final_judgement(report, model_test_candidate_pool)
    report["recommend_update_candidate_pool_manual"] = report["final_judgement"]["recommend_update_candidate_pool_manual"]

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REVIEW_DIR / f"stock_selection_research_focus_sectors_{latest_trade_date}.json"
    md_path = REVIEW_DIR / f"stock_selection_research_focus_sectors_{latest_trade_date}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "md": str(md_path), "latest_completed_trade_date": latest_trade_date}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
