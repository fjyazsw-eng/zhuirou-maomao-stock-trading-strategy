from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from scoring_system.decision_engine import decision_for_row, write_outputs as write_decision_outputs
from scoring_system.leader_score import run_leader_score
from scoring_system.mvp_score import run_score
from scoring_system.mvp_update import run_update
from scoring_system.stock_score import run_stock_score


ROOT = Path(__file__).resolve().parents[1]
SQLITE = ROOT / "data" / "sqlite" / "market_120d.sqlite"
SCORES = ROOT / "data" / "processed" / "scores"
SIM_DIR = ROOT / "data" / "simulation"
REPORTS = ROOT / "reports" / "simulation"
MODEL_VERSION = "1.0.0-simulation-mvp"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_table(conn: sqlite3.Connection, table: str) -> pd.DataFrame:
    df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
    for col in ["trade_date", "ts_code", "index_code", "con_code"]:
        if col in df.columns:
            df[col] = df[col].astype("string")
    return df


def available_dates() -> list[str]:
    with sqlite3.connect(SQLITE) as conn:
        rows = conn.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()
    return [str(r[0]) for r in rows]


def select_replay_dates(end_date: str | None, days: int) -> list[str]:
    dates = available_dates()
    if end_date:
        dates = [d for d in dates if d <= end_date]
    return dates[-days:]


def load_score_frames(as_of: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sectors = pd.read_csv(SCORES / f"sector_scores_{as_of}_calibrated.csv", dtype={"index_code": "string"})
    leaders = pd.read_csv(SCORES / f"leader_scores_{as_of}.csv", dtype={"sector_code": "string", "ts_code": "string"})
    stocks = pd.read_csv(SCORES / f"stock_scores_{as_of}.csv", dtype={"sector_code": "string", "ts_code": "string"})
    return sectors, leaders, stocks


def choose_stock_universe(as_of: str, cfg: dict[str, Any]) -> list[str]:
    sectors = pd.read_csv(SCORES / f"sector_scores_{as_of}_calibrated.csv", dtype={"index_code": "string"})
    leaders = pd.read_csv(SCORES / f"leader_scores_{as_of}.csv", dtype={"sector_code": "string", "ts_code": "string"})
    top_sectors = sectors[sectors["formal_score_allowed"] == True].sort_values("score", ascending=False).head(int(cfg["sample_scope"]["top_sector_count"]))
    codes: list[str] = []
    for sector_code in top_sectors["index_code"].astype(str):
        block = leaders[leaders["sector_code"].astype(str) == sector_code].sort_values("score", ascending=False).head(int(cfg["sample_scope"]["leaders_per_top_sector"]))
        codes.extend(block["ts_code"].astype(str).tolist())
    for code in leaders.sort_values("score", ascending=False)["ts_code"].astype(str):
        if len(dict.fromkeys(codes)) >= int(cfg["sample_scope"]["min_focus_stocks"]):
            break
        codes.append(code)
    return list(dict.fromkeys(codes))


def build_decisions(as_of: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    decision_cfg = load_yaml(ROOT / "config" / "decision_rules.yaml")
    _, leaders, stocks = load_score_frames(as_of)
    decisions = [decision_for_row(row, leaders, decision_cfg) for _, row in stocks.iterrows()]
    keep = set(cfg["sample_scope"]["include_final_decisions"])
    selected = [d for d in decisions if d["final_decision"] in keep]
    write_decision_outputs(as_of, selected, decision_cfg)
    return selected


def cumulative_sector_return(daily: pd.DataFrame, members: pd.DataFrame, sector_code: str, as_of: str, dates: list[str]) -> float:
    active = members.copy()
    active["in_date"] = active["in_date"].astype("string").fillna("")
    active["out_date"] = active["out_date"].astype("string").fillna("")
    active = active[(active["index_code"].astype(str) == sector_code) & (active["in_date"] <= as_of) & ((active["out_date"] == "") | (active["out_date"] > as_of))]
    codes = active["con_code"].dropna().astype(str).unique().tolist()
    if not codes:
        return np.nan
    result = 1.0
    used = 0
    for date in dates:
        day = daily[(daily["trade_date"].astype(str) == date) & (daily["ts_code"].astype(str).isin(codes))]
        value = pd.to_numeric(day["return"], errors="coerce").mean()
        if pd.isna(value):
            continue
        result *= 1 + float(value)
        used += 1
    return np.nan if used == 0 else result - 1


def compute_verification(as_of: str, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with sqlite3.connect(SQLITE) as conn:
        daily = read_table(conn, "daily")
        members = read_table(conn, "index_member")
    dates = sorted(daily["trade_date"].dropna().astype(str).unique().tolist())
    if as_of not in dates:
        return decisions
    idx = dates.index(as_of)
    codes = [d["ts_code"] for d in decisions]
    daily["return"] = pd.to_numeric(daily["return"], errors="coerce")
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    market_return_by_date = daily.groupby("trade_date")["return"].mean().to_dict()
    for d in decisions:
        code = d["ts_code"]
        hist = daily[daily["ts_code"].astype(str) == code].sort_values("trade_date")
        close_t = get_close(hist, as_of)
        d["close_price"] = close_t
        d["result_status"] = "PENDING"
        for field in [
            "next_day_return", "t3_return", "t5_return",
            "next_day_excess_return", "t3_excess_return", "t5_excess_return",
            "next_day_market_excess_return", "t3_market_excess_return", "t5_market_excess_return",
            "max_drawdown_t5",
        ]:
            d[field] = None

        complete_count = 0
        for label, offset in [("next_day", 1), ("t3", 3), ("t5", 5)]:
            if idx + offset >= len(dates) or close_t is None:
                continue
            target_date = dates[idx + offset]
            close_future = get_close(hist, target_date)
            if close_future is None:
                continue
            ret = close_future / close_t - 1
            horizon_dates = dates[idx + 1: idx + offset + 1]
            market_ret = cumulative_market_return(market_return_by_date, horizon_dates)
            sector_ret = cumulative_sector_return(daily, members, str(d["sector_code"]), as_of, horizon_dates)
            d[f"{label}_return"] = ret
            d[f"{label}_market_excess_return"] = None if pd.isna(market_ret) else ret - market_ret
            d[f"{label}_excess_return"] = None if pd.isna(sector_ret) else ret - sector_ret
            complete_count += 1
        if idx + 1 < len(dates) and close_t is not None:
            future_dates = dates[idx + 1: min(idx + 6, len(dates))]
            future = hist[hist["trade_date"].astype(str).isin(future_dates)].copy()
            if len(future):
                d["max_drawdown_t5"] = min(0.0, float((future["close"] / close_t - 1).min()))
        if complete_count >= 3:
            d["result_status"] = "COMPLETE"
        elif complete_count > 0:
            d["result_status"] = "PARTIAL"
    return decisions


def get_close(hist: pd.DataFrame, date: str) -> float | None:
    row = hist[hist["trade_date"].astype(str) == date]
    if row.empty:
        return None
    value = pd.to_numeric(row["close"], errors="coerce").iloc[0]
    return None if pd.isna(value) else float(value)


def cumulative_market_return(market_return_by_date: dict[str, float], dates: list[str]) -> float:
    values = [market_return_by_date.get(d) for d in dates]
    clean = [float(v) for v in values if v is not None and not pd.isna(v)]
    if not clean:
        return np.nan
    result = 1.0
    for value in clean:
        result *= 1 + value
    return result - 1


def snapshot_rows(as_of: str, decisions: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for d in decisions:
        rows.append({
            "as_of_date": as_of,
            "stock_code": d["ts_code"],
            "stock_name": d["name"],
            "market_score": d["market_score"],
            "market_level": d["market_grade"],
            "sector_name": d["sector_name"],
            "sector_score": d["sector_score"],
            "sector_level": d["sector_grade"],
            "leader_score": d["leader_score"],
            "core_identity": d["core_identity"],
            "stock_execution_score": d["stock_score"],
            "stock_execution_status": d["stock_execution_status"],
            "final_decision": d["final_decision"],
            "risk_flags": "；".join(d.get("risks", [])),
            "close_price": d.get("close_price"),
            "next_day_return": d.get("next_day_return"),
            "t3_return": d.get("t3_return"),
            "t5_return": d.get("t5_return"),
            "next_day_excess_return": d.get("next_day_excess_return"),
            "t3_excess_return": d.get("t3_excess_return"),
            "t5_excess_return": d.get("t5_excess_return"),
            "next_day_market_excess_return": d.get("next_day_market_excess_return"),
            "t3_market_excess_return": d.get("t3_market_excess_return"),
            "t5_market_excess_return": d.get("t5_market_excess_return"),
            "max_drawdown_t5": d.get("max_drawdown_t5"),
            "result_status": d.get("result_status"),
        })
    return pd.DataFrame(rows)


def write_daily_snapshot(as_of: str, df: pd.DataFrame) -> dict[str, str]:
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    csv_path = SIM_DIR / f"daily_snapshot_{as_of}.csv"
    json_path = SIM_DIR / f"daily_snapshot_{as_of}.json"
    md_path = REPORTS / f"daily_simulation_{as_of}.md"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(json.dumps(json.loads(df.replace({np.nan: None}).to_json(orient="records", force_ascii=False)), ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# 每日模拟快照 {as_of}",
        "",
        f"样本数：{len(df)}",
        "",
        "| 股票 | 代码 | 板块 | 龙头身份 | 执行状态 | 最终结论 | T+1 | T+3 | T+5 | 5日最大回撤 | 结果状态 |",
        "|---|---|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in df.itertuples(index=False):
        lines.append(
            f"| {row.stock_name} | {row.stock_code} | {row.sector_name} | {row.core_identity} | {row.stock_execution_status} | {row.final_decision} | {fmt_pct(row.next_day_return)} | {fmt_pct(row.t3_return)} | {fmt_pct(row.t5_return)} | {fmt_pct(row.max_drawdown_t5)} | {row.result_status} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"csv": str(csv_path), "json": str(json_path), "markdown": str(md_path)}


def update_history(all_snapshots: list[pd.DataFrame]) -> pd.DataFrame:
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    history_path = SIM_DIR / "simulation_history.csv"
    old = pd.read_csv(history_path, dtype={"as_of_date": "string", "stock_code": "string"}) if history_path.exists() else pd.DataFrame()
    new = pd.concat(all_snapshots, ignore_index=True) if all_snapshots else pd.DataFrame()
    combined = pd.concat([old, new], ignore_index=True, sort=False) if len(old) else new
    if len(combined):
        combined["as_of_date"] = combined["as_of_date"].astype(str)
        combined["stock_code"] = combined["stock_code"].astype(str)
        combined = combined.drop_duplicates(["as_of_date", "stock_code"], keep="last").sort_values(["as_of_date", "stock_code"])
    combined.to_csv(history_path, index=False, encoding="utf-8-sig")
    with sqlite3.connect(SIM_DIR / "simulation_history.sqlite") as conn:
        combined.to_sql("simulation_history", conn, if_exists="replace", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sim_history_date_code ON simulation_history(as_of_date, stock_code)")
        conn.commit()
    return combined


def write_latest_run_status(run_date: str, online_success: bool | None, online_error: str | None) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / "latest_run_status.md"
    latest = available_dates()[-1] if available_dates() else ""
    market_score = ""
    market_grade = ""
    top5_text = "无"
    counts = {}
    missing = []
    market_path = SCORES / f"market_sector_score_{run_date}_calibrated.json"
    sector_path = SCORES / f"sector_scores_{run_date}_calibrated.csv"
    decision_path = SIM_DIR / f"daily_snapshot_{run_date}.csv"
    if market_path.exists():
        payload = json.loads(market_path.read_text(encoding="utf-8"))
        market_score = payload.get("market_score", {}).get("score", "")
        market_grade = payload.get("market_score", {}).get("grade", "")
    else:
        missing.append("市场评分文件缺失")
    if sector_path.exists():
        sectors = pd.read_csv(sector_path)
        top5 = sectors.sort_values("score", ascending=False).head(5)
        top5_text = "；".join([f"{r.industry_name}({float(r.score):.1f})" for r in top5.itertuples(index=False)])
    else:
        missing.append("板块评分文件缺失")
    if decision_path.exists():
        snap = pd.read_csv(decision_path)
        counts = snap["final_decision"].value_counts().to_dict()
    else:
        missing.append("当日模拟快照缺失")
    manual_check = bool(missing or online_error)
    lines = [
        "# 最新每日模拟运行状态",
        "",
        f"- 运行日期：{run_date}",
        f"- 数据最新交易日：{latest}",
        f"- 是否在线更新成功：{'未执行在线更新' if online_success is None else ('是' if online_success else '否')}",
        f"- 在线更新错误：{online_error or '无'}",
        f"- 市场评分：{market_score}；等级：{market_grade}",
        f"- 前5板块：{top5_text}",
        f"- READY_CORE数量：{counts.get('READY_CORE', 0)}",
        f"- READY_SECONDARY数量：{counts.get('READY_SECONDARY', 0)}",
        f"- WAIT_PULLBACK_CORE数量：{counts.get('WAIT_PULLBACK_CORE', 0)}",
        f"- WEAK_STRUCTURE数量：{counts.get('WEAK_STRUCTURE', 0)}",
        f"- AVOID数量：{counts.get('AVOID', 0)}",
        f"- 数据缺失：{'；'.join(missing) if missing else '无'}",
        f"- 是否需要人工检查：{'是' if manual_check else '否'}",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_summary(history: pd.DataFrame, cfg: dict[str, Any]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / "simulation_summary.md"
    days = int(history["as_of_date"].nunique()) if len(history) else 0
    total_records = int(len(history))
    unique_stocks = int(history["stock_code"].nunique()) if len(history) else 0
    repeat_counts = history.groupby("stock_code")["as_of_date"].nunique().sort_values(ascending=False) if len(history) else pd.Series(dtype="int64")
    repeated_stock_count = int((repeat_counts > 1).sum()) if len(repeat_counts) else 0
    max_repeat = int(repeat_counts.max()) if len(repeat_counts) else 0
    counts = history["final_decision"].value_counts().to_dict() if len(history) else {}
    decision_unique = history.groupby("final_decision")["stock_code"].nunique().to_dict() if len(history) else {}
    trajectories = stock_trajectories(history)
    anomalies = anomaly_cases(history, cfg)
    wait_stats, wait_examples = wait_pullback_stats(history, cfg)
    lines = [
        "# 连续模拟累计报告",
        "",
        f"模型版本：{MODEL_VERSION}",
        f"已模拟交易日数量：{days}",
        f"总记录数：{total_records}",
        f"独立股票数量：{unique_stocks}",
        f"重复股票数量：{repeated_stock_count}",
        f"单只股票最大重复次数：{max_repeat}",
        "",
        "样本不足，以下仅供观察，尚未验证，不能判断模型有效，需要继续模拟。",
        "",
        "## 重复样本说明",
        "",
        "同一股票连续多日入选会形成多条记录，因此不得把总记录数直接视为独立样本数。",
        "",
        "## 各结论记录数和独立股票数",
        "",
        "| 结论 | 记录数 | 独立股票数 |",
        "|---|---:|---:|",
    ]
    for key, value in counts.items():
        lines.append(f"| {key} | {value} | {decision_unique.get(key, 0)} |")
    lines.extend(["", "## 各股票状态变化轨迹", ""])
    lines.append("| 股票 | 代码 | 出现次数 | 状态轨迹 |")
    lines.append("|---|---|---:|---|")
    for row in trajectories[:30]:
        lines.append(f"| {row['stock_name']} | {row['stock_code']} | {row['count']} | {row['trajectory']} |")
    lines.extend(["", "## 事后表现初步统计", ""])
    metric_cols = ["next_day_return", "t3_return", "t5_return", "max_drawdown_t5"]
    grouped = history.groupby("final_decision") if len(history) else []
    lines.append("| 结论 | T+1均值 | T+1中位数 | T+1市场超额均值 | T+1板块超额均值 | T+1正收益 | T+1跑赢市场 | T+1跑赢板块 | T+3均值 | T+3中位数 | T+5均值 | T+5中位数 | 回撤均值 | 回撤中位数 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for decision, g in grouped:
        lines.append(
            f"| {decision} | {fmt_pct(g['next_day_return'].mean())} | {fmt_pct(g['next_day_return'].median())} | {fmt_pct(g['next_day_market_excess_return'].mean())} | {fmt_pct(g['next_day_excess_return'].mean())} | {fmt_pct(win_rate(g['next_day_return']))} | {fmt_pct(win_rate(g['next_day_market_excess_return']))} | {fmt_pct(win_rate(g['next_day_excess_return']))} | {fmt_pct(g['t3_return'].mean())} | {fmt_pct(g['t3_return'].median())} | {fmt_pct(g['t5_return'].mean())} | {fmt_pct(g['t5_return'].median())} | {fmt_pct(g['max_drawdown_t5'].mean())} | {fmt_pct(g['max_drawdown_t5'].median())} |"
        )
    lines.extend(["", "## T+3/T+5补充统计", ""])
    lines.append("| 结论 | T+3市场超额均值 | T+3板块超额均值 | T+3正收益 | T+3跑赢市场 | T+3跑赢板块 | T+5市场超额均值 | T+5板块超额均值 | T+5正收益 | T+5跑赢市场 | T+5跑赢板块 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for decision, g in grouped:
        lines.append(
            f"| {decision} | {fmt_pct(g['t3_market_excess_return'].mean())} | {fmt_pct(g['t3_excess_return'].mean())} | {fmt_pct(win_rate(g['t3_return']))} | {fmt_pct(win_rate(g['t3_market_excess_return']))} | {fmt_pct(win_rate(g['t3_excess_return']))} | {fmt_pct(g['t5_market_excess_return'].mean())} | {fmt_pct(g['t5_excess_return'].mean())} | {fmt_pct(win_rate(g['t5_return']))} | {fmt_pct(win_rate(g['t5_market_excess_return']))} | {fmt_pct(win_rate(g['t5_excess_return']))} |"
        )
    lines.extend(["", "## 异常样本检查", ""])
    for title, rows in anomalies.items():
        lines.extend([f"### {title}", ""])
        if not rows:
            lines.append("- 暂无符合条件样本。")
            lines.append("")
            continue
        lines.append("| 股票 | T日 | 结论 | 市场/板块/龙头/个股 | T+1 | T+3 | T+5 | 市场超额T+1/T+3 | 板块超额T+1/T+3 | 风险标记 | 初步可能原因 |")
        lines.append("|---|---|---|---|---:|---:|---:|---|---|---|---|")
        for r in rows[:5]:
            lines.append(
                f"| {r['stock_name']} | {r['as_of_date']} | {r['final_decision']} | {fmt_num(r['market_score'])}/{fmt_num(r['sector_score'])}/{fmt_num(r['leader_score'])}/{fmt_num(r['stock_execution_score'])} | {fmt_pct(r['next_day_return'])} | {fmt_pct(r['t3_return'])} | {fmt_pct(r['t5_return'])} | {fmt_pct(r['next_day_market_excess_return'])}/{fmt_pct(r['t3_market_excess_return'])} | {fmt_pct(r['next_day_excess_return'])}/{fmt_pct(r['t3_excess_return'])} | {r['risk_flags']} | {r['reason']} |"
            )
        lines.append("")
    lines.extend(["## WAIT_PULLBACK专项验证", ""])
    lines.append("| 分类 | 数量 |")
    lines.append("|---|---:|")
    for key, value in wait_stats.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "典型样本：", ""])
    if wait_examples:
        lines.append("| 股票 | T日 | 分类 | 最大回撤 | 继续上涨幅度 | T+1 | T+3 | 风险标记 |")
        lines.append("|---|---|---|---:|---:|---:|---:|---|")
        for r in wait_examples[:10]:
            lines.append(f"| {r['stock_name']} | {r['as_of_date']} | {r['pullback_result']} | {fmt_pct(r['max_drawdown_t5'])} | {fmt_pct(r['continue_up_return'])} | {fmt_pct(r['next_day_return'])} | {fmt_pct(r['t3_return'])} | {r['risk_flags']} |")
    else:
        lines.append("- 数据不足。")
    missing = {col: int(history[col].isna().sum()) for col in metric_cols if col in history.columns}
    lines.extend([
        "",
        "## 数据缺失情况",
        "",
        f"- 收益字段缺失数量：{missing}",
        f"- 当前样本量是否足够：{'否，少于20个交易日' if days < int(cfg['reporting']['insufficient_days_threshold']) else '仍需谨慎观察'}",
        "",
        "说明：本报告不得据此下“模型有效”“稳定盈利”“胜率可靠”或“可以实盘重仓”等结论。",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def stock_trajectories(history: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    if history.empty:
        return rows
    for code, g in history.sort_values("as_of_date").groupby("stock_code"):
        rows.append({
            "stock_code": code,
            "stock_name": str(g["stock_name"].iloc[-1]),
            "count": int(len(g)),
            "trajectory": " → ".join([f"{r.as_of_date}:{r.final_decision}" for r in g.itertuples(index=False)]),
        })
    return sorted(rows, key=lambda x: (-x["count"], x["stock_code"]))


def anomaly_cases(history: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    a = cfg.get("anomaly_checks", {})
    cases = {
        "READY_CORE后续明显下跌": history[(history["final_decision"] == "READY_CORE") & (pd.to_numeric(history["next_day_return"], errors="coerce") <= a.get("ready_core_drop_threshold", -0.03))].copy(),
        "READY_SECONDARY后续大跌": history[(history["final_decision"] == "READY_SECONDARY") & (pd.to_numeric(history["next_day_return"], errors="coerce") <= a.get("ready_secondary_drop_threshold", -0.05))].copy(),
        "WEAK_STRUCTURE后续明显上涨": history[(history["final_decision"] == "WEAK_STRUCTURE") & (pd.to_numeric(history["t3_return"], errors="coerce") >= a.get("weak_structure_rise_threshold", 0.05))].copy(),
        "WAIT_PULLBACK_CORE未回调继续大涨": history[(history["final_decision"] == "WAIT_PULLBACK_CORE") & (pd.to_numeric(history["max_drawdown_t5"], errors="coerce") >= 0) & (pd.to_numeric(history["t3_return"], errors="coerce") >= a.get("wait_pullback_continue_up_threshold", 0.05))].copy(),
        "AVOID后续上涨": history[(history["final_decision"] == "AVOID") & (pd.to_numeric(history["t3_return"], errors="coerce") >= a.get("avoid_rise_threshold", 0.05))].copy(),
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for title, df in cases.items():
        if len(df):
            df = df.sort_values(["t3_return", "next_day_return"], ascending=False, na_position="last")
        rows = []
        for row in df.head(5).to_dict(orient="records"):
            row["reason"] = preliminary_reason(row)
            rows.append(row)
        result[title] = rows
    return result


def preliminary_reason(row: dict[str, Any]) -> str:
    risks = str(row.get("risk_flags") or "")
    if "位置过热" in risks:
        return "T日已有过热风险，后续波动需要继续观察"
    if "跌破" in risks:
        return "弱结构样本可能出现短线修复，不代表趋势确认"
    if "流动性不足" in risks:
        return "流动性风险样本，单日波动解释力有限"
    return "样本不足，仅记录异常表现"


def wait_pullback_stats(history: pd.DataFrame, cfg: dict[str, Any]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    wcfg = cfg.get("wait_pullback_validation", {})
    pullback_threshold = float(wcfg.get("pullback_threshold", -0.005))
    continue_threshold = float(wcfg.get("continue_up_threshold", 0.05))
    subset = history[history["final_decision"] == "WAIT_PULLBACK_CORE"].copy()
    stats = {"等待回调正确": 0, "未回调但继续上涨，可能错失机会": 0, "回调后转弱": 0, "数据不足": 0}
    examples = []
    for row in subset.to_dict(orient="records"):
        max_dd = pd.to_numeric(pd.Series([row.get("max_drawdown_t5")]), errors="coerce").iloc[0]
        t3 = pd.to_numeric(pd.Series([row.get("t3_return")]), errors="coerce").iloc[0]
        t1 = pd.to_numeric(pd.Series([row.get("next_day_return")]), errors="coerce").iloc[0]
        if pd.isna(max_dd):
            label = "数据不足"
            cont = np.nan
        elif max_dd <= pullback_threshold and (not pd.isna(t3) and t3 > 0):
            label = "等待回调正确"
            cont = t3
        elif max_dd <= pullback_threshold:
            label = "回调后转弱"
            cont = t3
        elif (not pd.isna(t3) and t3 >= continue_threshold) or (not pd.isna(t1) and t1 >= continue_threshold):
            label = "未回调但继续上涨，可能错失机会"
            cont = max(v for v in [t1, t3] if not pd.isna(v))
        else:
            label = "数据不足"
            cont = t3
        stats[label] += 1
        row["pullback_result"] = label
        row["continue_up_return"] = cont
        examples.append(row)
    examples = sorted(examples, key=lambda x: (x["pullback_result"], str(x["as_of_date"]), str(x["stock_code"])))
    return stats, examples


def fmt_num(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{float(value):.2f}"


def fmt_pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{float(value) * 100:.2f}%"


def win_rate(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return np.nan
    return float((clean > 0).mean())


def run_one_day(as_of: str, cfg: dict[str, Any], no_api: bool) -> pd.DataFrame:
    run_score(as_of)
    top_sectors = pd.read_csv(SCORES / f"sector_scores_{as_of}_calibrated.csv").sort_values("score", ascending=False).head(int(cfg["sample_scope"]["top_sector_count"]))
    run_leader_score(as_of, explicit_names=top_sectors["industry_name"].dropna().astype(str).tolist())
    universe = choose_stock_universe(as_of, cfg)
    run_stock_score(as_of, stocks=universe, no_api=True)
    decisions = build_decisions(as_of, cfg)
    decisions = compute_verification(as_of, decisions)
    snap = snapshot_rows(as_of, decisions)
    write_daily_snapshot(as_of, snap)
    return snap


def run_simulation(end_date: str | None = None, replay_days: int | None = None, no_api: bool = True, online_update: bool = False) -> dict[str, Any]:
    cfg = load_yaml(ROOT / "config" / "simulation_rules.yaml")
    online_success: bool | None = None
    online_error: str | None = None
    if online_update and not no_api:
        try:
            run_update(end_date=end_date, window=int(cfg["replay"]["window_days_for_update"]), use_api=True)
            online_success = True
        except Exception as exc:
            online_success = False
            online_error = f"{type(exc).__name__}: {str(exc)[:180]}"
            print(f"WARN online update failed; continue with existing cache: {online_error}")
    days = replay_days or int(cfg["replay"]["default_days"])
    dates = select_replay_dates(end_date, days)
    snapshots = []
    for as_of in dates:
        snapshots.append(run_one_day(as_of, cfg, no_api=no_api))
    history = update_history(snapshots)
    summary_path = write_summary(history, cfg)
    latest_status_path = write_latest_run_status(dates[-1] if dates else "", online_success, online_error)
    result = {
        "model_version": MODEL_VERSION,
        "replay_dates": dates,
        "snapshot_count": int(sum(len(s) for s in snapshots)),
        "history_rows": int(len(history)),
        "summary_path": str(summary_path),
        "latest_run_status_path": str(latest_status_path),
        "no_api": no_api,
        "online_update_success": online_success,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--replay-days", type=int, default=None)
    parser.add_argument("--no-api", action="store_true", help="纯离线模式，不更新在线数据")
    parser.add_argument("--online-update", action="store_true", help="先在线增量更新，再运行模拟")
    args = parser.parse_args()
    no_api = bool(args.no_api or not args.online_update)
    run_simulation(end_date=args.end_date, replay_days=args.replay_days, no_api=no_api, online_update=args.online_update)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
