from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any
from scoring_system.project_paths import database_path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.execution_decision_engine import decide_execution_from_dict
from scoring_system.account_position_manager import (
    candidate_from_dict,
    decide_account_position,
    decision_to_dict,
    holding_from_dict,
)
from scoring_system.holding_management import decide_holding_from_dict
from scoring_system.sector_cycle_classifier import classify_sector_cycle
from scoring_system.stock_role_classifier import classify_stock_role_from_dict

DECISIONS_DIR = ROOT / "data" / "processed" / "decisions"
SCORES_DIR = ROOT / "data" / "processed" / "scores"
SQLITE_PATH = database_path(ROOT)
REPORTS_DIR = ROOT / "reports" / "advice"


def latest_date() -> str:
    dates: list[str] = []
    for path in DECISIONS_DIR.glob("decision_results_*.csv"):
        dates.extend([p for p in path.stem.split("_") if p.isdigit() and len(p) == 8])
    if not dates:
        raise FileNotFoundError("No decision files found")
    return max(dates)


def read_decisions(as_of: str) -> pd.DataFrame:
    return pd.read_csv(DECISIONS_DIR / f"decision_results_{as_of}.csv", dtype={"ts_code": "string"})


def read_stocks(as_of: str) -> pd.DataFrame:
    path = SCORES_DIR / f"stock_scores_{as_of}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"ts_code": "string", "sector_code": "string"})


def read_sector_source(as_of: str) -> pd.DataFrame:
    market_path = SCORES_DIR / f"market_sector_score_{as_of}_calibrated.json"
    if market_path.exists():
        payload = json.loads(market_path.read_text(encoding="utf-8"))
        rankings = pd.DataFrame(payload.get("sector_rankings", []))
        if not rankings.empty:
            return rankings
    sector_path = SCORES_DIR / f"sector_scores_{as_of}_calibrated.csv"
    if sector_path.exists():
        return pd.read_csv(sector_path, dtype={"sector_code": "string", "index_code": "string"})
    return pd.DataFrame()


def read_quotes(as_of: str) -> pd.DataFrame:
    if not SQLITE_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(SQLITE_PATH) as conn:
        df = pd.read_sql_query(
            """
            SELECT d.ts_code, d.close, d.pct_chg, d.amount_yuan, b.turnover_rate, b.circ_mv_yuan
            FROM daily d
            LEFT JOIN daily_basic b
              ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            WHERE d.trade_date = ?
            """,
            conn,
            params=(as_of,),
        )
    for col in ["close", "pct_chg", "amount_yuan", "turnover_rate", "circ_mv_yuan"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fmt(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}"


def pct(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}%"


def money_yi(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value)/1e8:.{digits}f} 亿"


def parse_holding(value: str) -> dict[str, Any]:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid holding format: {value}")
    return {"ts_code": parts[0].strip().upper(), "shares": float(parts[1]), "cost": float(parts[2])}


def split_text(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []
    text = str(value).replace("基础行情风险：", "").replace("事件风险：", "")
    parts: list[str] = []
    for item in text.replace(",", "；").split("；"):
        item = item.strip()
        if item and item not in {"未触发", "未检查或数据缺失", "nan"}:
            parts.append(item)
    return parts


def sector_cycle_for_code(code: str, sector_source: pd.DataFrame, stocks: pd.DataFrame) -> dict[str, Any]:
    sector = pd.Series(dtype="object")
    if code and not sector_source.empty:
        for key in ["index_code", "sector_code"]:
            if key in sector_source.columns:
                matched = sector_source[sector_source[key].astype(str) == str(code)]
                if not matched.empty:
                    sector = matched.iloc[0]
                    break

    raw_ret = sector.get("equal_return") if not sector.empty else None
    if raw_ret is None or pd.isna(raw_ret):
        raw_ret = sector.get("return_used") if not sector.empty else None
    ret_pct = float(raw_ret) * 100 if raw_ret is not None and not pd.isna(raw_ret) else None
    score = sector.get("score", sector.get("sector_score")) if not sector.empty else None
    score_value = float(score) if score is not None and not pd.isna(score) else None
    metrics = {
        "1日": {"等权涨跌幅%": ret_pct},
        "3日": {"等权涨跌幅%": ret_pct},
        "5日": {"等权涨跌幅%": ret_pct},
        "10日": {"等权涨跌幅%": score_value / 10 if score_value is not None else None},
        "20日": {"等权涨跌幅%": score_value / 8 if score_value is not None else None},
    }
    breadth = {
        "当日上涨家数": 1 if ret_pct is not None and ret_pct > 0 else 0,
        "当日下跌家数": 1 if ret_pct is not None and ret_pct < 0 else 0,
    }
    pool: list[dict[str, Any]] = []
    if code and not stocks.empty and "sector_code" in stocks.columns:
        sector_stocks = stocks[stocks["sector_code"].astype(str) == str(code)].copy()
        if not sector_stocks.empty:
            ranked = sector_stocks.sort_values(["stock_score", "leader_score"], ascending=False).head(8)
            for _, item in ranked.iterrows():
                stock_score = pd.to_numeric(pd.Series([item.get("stock_score")]), errors="coerce").iloc[0]
                leader_score = pd.to_numeric(pd.Series([item.get("leader_score")]), errors="coerce").iloc[0]
                role = "角色不确定"
                if not pd.isna(leader_score) and float(leader_score) >= 75:
                    role = "疑似龙头"
                elif not pd.isna(stock_score) and float(stock_score) >= 70:
                    role = "趋势核心"
                elif not pd.isna(stock_score) and float(stock_score) < 55:
                    role = "后排或弱结构"
                pool.append({"角色": role, "20日位置": None})
    result = classify_sector_cycle(metrics, breadth, pool)
    return {
        "main_label": result.main_label,
        "aux_labels": result.auxiliary_labels,
        "confidence": result.confidence,
    }


def execution_for_row(row: pd.Series, sector_source: pd.DataFrame, stocks: pd.DataFrame, user_state: str) -> dict[str, Any]:
    cycle = sector_cycle_for_code(str(row.get("sector_code", "")), sector_source, stocks)
    risks = "；".join(split_text(row.get("basic_risk")) + split_text(row.get("risks")))
    role = classify_stock_role_from_dict({
        "ts_code": row.get("ts_code", ""),
        "name": row.get("name", ""),
        "stock_score": row.get("stock_score"),
        "leader_score": row.get("leader_score", row.get("leader_score_decision")),
        "trend_structure_score": row.get("trend_structure_score"),
        "volume_price_quality_score": row.get("volume_price_quality_score"),
        "position_heat_score": row.get("position_heat_score"),
        "tradability_score": row.get("tradability_score"),
        "pct_chg": row.get("pct_chg"),
        "turnover_rate": row.get("turnover_rate"),
        "sector_cycle": cycle["main_label"],
        "leader_labels": row.get("leader_labels", row.get("leader_labels_decision", "")),
        "risk_text": risks,
        "execution_status": row.get("final_decision", row.get("execution_status", "")),
        "sub_scores_json": row.get("sub_scores_json"),
    })
    payload = {
        "ts_code": row.get("ts_code", ""),
        "name": row.get("name", ""),
        "stock_score": row.get("stock_score"),
        "leader_score": row.get("leader_score", row.get("leader_score_decision")),
        "original_status": row.get("final_decision", row.get("execution_status", "-")),
        "sector_name": row.get("sector_name", ""),
        "sector_cycle": cycle["main_label"],
        "sector_aux_labels": cycle["aux_labels"],
        "sector_confidence": cycle["confidence"],
        "risk_text": risks,
        "leader_labels": row.get("leader_labels", row.get("leader_labels_decision", "")),
        "core_identity": row.get("core_identity", ""),
        "stock_role": role["role"],
        "user_state": user_state,
        "can_watch": True,
        "has_alert": True,
        "latest_price": row.get("close"),
    }
    result = decide_execution_from_dict(payload)
    return {
        "original_status": result.original_status,
        "final_label": result.final_label,
        "allow_buy": result.allow_buy,
        "max_position_pct": result.max_position_pct,
        "holding_advice": result.holding_advice,
        "empty_advice": result.empty_advice,
        "no_watch_advice": result.no_watch_advice,
        "stop_advice": result.stop_advice,
        "profit_protection_advice": result.profit_protection_advice,
        "downgrade_reasons": result.downgrade_reasons,
        "sector_cycle_text": result.sector_cycle_text,
        "sector_cycle": cycle["main_label"],
        "sector_aux_labels": cycle["aux_labels"],
        "sector_confidence": result.sector_confidence,
        "stock_role": role,
    }


def execution_summary(exec_decision: dict[str, Any]) -> str:
    return (
        f"最终执行标签 {exec_decision['final_label']}，"
        f"允许买：{'是' if exec_decision['allow_buy'] else '否'}，"
        f"最大仓位 {exec_decision['max_position_pct']}%。"
        f"原因：{'；'.join(exec_decision.get('downgrade_reasons', [])[:2]) or '-'}。"
    )


def strip_end_punctuation(value: Any) -> str:
    return str(value or "-").rstrip("。；; ")


def advise_empty_position(cash: float, ranked: pd.DataFrame) -> list[str]:
    lines = [f"- 当前现金：{cash:.2f} 元"]
    if ranked.empty:
        lines.append("- 当前没有足够强的候选，优先空仓观察。")
        return lines
    top = ranked.head(5)
    lines.append("- 建议先从最强候选里做观察名单，而不是一次性全面出手。")
    for _, row in top.iterrows():
        final_label = row.get("final_execution_label", row.get("final_decision", row.get("execution_status", "-")))
        allow_buy = "是" if bool(row.get("allow_buy", False)) else "否"
        max_position = row.get("max_position_pct", 0)
        reason = strip_end_punctuation(row.get("execution_reason", row.get("current_stage", "-")))
        role_text = f"{row.get('stock_role', '-')}（{row.get('stock_role_name', '-')}，{row.get('stock_role_confidence', '-')}）"
        lines.append(
            f"- {row['name']} {row['ts_code']}：原始状态 {row.get('final_decision', row.get('execution_status', '-'))}，新角色 {role_text}，最终执行标签 {final_label}，允许买：{allow_buy}，最大仓位 {max_position}%，最新价 {fmt(row.get('close'))}，涨跌幅 {pct(row.get('pct_chg'))}。原因：{reason}。"
        )
    return lines


def stock_role_for_row(row: dict[str, Any]) -> str:
    role = row.get("stock_role_detail")
    if isinstance(role, dict):
        return str(role.get("role", "UNCERTAIN_ROLE"))
    return str(row.get("stock_role", "UNCERTAIN_ROLE"))


def yes_no(value: bool) -> str:
    return "是" if value else "否"


def money(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}"


def advise_holdings(holdings: list[dict[str, Any]], merged: pd.DataFrame, can_watch: bool = True) -> list[str]:
    lines = []
    if not holdings:
        return lines
    row_map = merged.set_index("ts_code").to_dict("index")
    for item in holdings:
        ts_code = item["ts_code"]
        row = row_map.get(ts_code)
        if not row:
            lines.append(f"- {ts_code}：当前模型没有对应评分结果，建议先补齐数据再判断。")
            continue
        close = row.get("close")
        pnl_pct = ((close - item["cost"]) / item["cost"] * 100) if close and item["cost"] else None
        final_label = row.get("holding_final_execution_label", row.get("final_execution_label", row.get("final_decision", row.get("execution_status", "-"))))
        holding_reason = strip_end_punctuation(row.get("holding_reason", "-"))
        holding_decision = decide_holding_from_dict({
            "ts_code": ts_code,
            "name": row.get("name", ""),
            "cost": item.get("cost"),
            "current_price": close,
            "original_status": row.get("final_decision", row.get("execution_status", "-")),
            "final_execution_label": final_label,
            "sector_cycle": row.get("holding_sector_cycle", row.get("sector_cycle", "UNKNOWN")),
            "sector_aux_labels": row.get("holding_sector_aux_labels", []),
            "sector_confidence": row.get("holding_sector_confidence", row.get("sector_confidence", "LOW")),
            "can_watch": can_watch,
            "stock_role": stock_role_for_row(row),
            "recent_change_pct": row.get("pct_chg"),
            "ma_signal": row.get("basic_risk", row.get("risks", "")),
        })
        reasons = "；".join(holding_decision.main_reasons[:3])
        role_text = f"{row.get('stock_role', '-')}（{row.get('stock_role_name', '-')}，{row.get('stock_role_confidence', '-')}）"
        lines.append(
            f"- {row['name']} {ts_code}：成本 {item['cost']:.2f}，最新价 {fmt(close)}，浮动 {pct(pnl_pct)}，"
            f"原始状态 {row.get('final_decision', row.get('execution_status', '-'))}，新角色 {role_text}，最终执行标签 {final_label}，"
            f"持仓处理标签 {holding_decision.holding_label}（{holding_decision.holding_label_name}）。"
            f"继续持有：{yes_no(holding_decision.continue_hold)}，减仓：{yes_no(holding_decision.reduce_position)}，退出：{yes_no(holding_decision.exit_position)}，"
            f"允许加仓：{yes_no(holding_decision.allow_add)}，建议保留仓位：当前仓位的 {holding_decision.suggested_retain_pct}%以内。"
            f"利润保护线：{holding_decision.profit_protection_line}；止损线：{holding_decision.stop_loss_line}。"
            f"触发减仓：{holding_decision.reduce_trigger} 触发退出：{holding_decision.exit_trigger} "
            f"不能盯盘处理：{holding_decision.no_watch_action} 原因：{holding_reason}；{reasons}。"
        )
    return lines


def market_weather_from_data(merged: pd.DataFrame) -> str:
    if not merged.empty and "market_grade" in merged.columns:
        value = merged["market_grade"].dropna()
        if not value.empty:
            return str(value.iloc[0])
    return "普通环境"


def account_holdings_from_rows(holdings: list[dict[str, Any]], merged: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not holdings or merged.empty:
        return rows
    row_map = merged.set_index("ts_code").to_dict("index")
    for item in holdings:
        ts_code = item["ts_code"]
        row = row_map.get(ts_code)
        if not row:
            continue
        close = row.get("close") or item.get("cost")
        final_label = row.get("holding_final_execution_label", row.get("final_execution_label", "OBSERVE_ONLY"))
        holding_decision = decide_holding_from_dict({
            "ts_code": ts_code,
            "name": row.get("name", ""),
            "cost": item.get("cost"),
            "current_price": close,
            "original_status": row.get("final_decision", row.get("execution_status", "-")),
            "final_execution_label": final_label,
            "sector_cycle": row.get("holding_sector_cycle", row.get("sector_cycle", "UNKNOWN")),
            "sector_aux_labels": row.get("holding_sector_aux_labels", []),
            "sector_confidence": row.get("holding_sector_confidence", row.get("sector_confidence", "LOW")),
            "can_watch": True,
            "stock_role": row.get("stock_role", "UNCERTAIN_ROLE"),
            "recent_change_pct": row.get("pct_chg"),
            "ma_signal": row.get("basic_risk", row.get("risks", "")),
        })
        rows.append({
            "ts_code": ts_code,
            "name": row.get("name", ts_code),
            "shares": item.get("shares", 0),
            "cost": item.get("cost", 0),
            "current_price": close,
            "sector_code": row.get("sector_code", ""),
            "sector_name": row.get("sector_name", ""),
            "stock_role": row.get("stock_role", "UNCERTAIN_ROLE"),
            "final_execution_label": final_label,
            "holding_label": holding_decision.holding_label,
            "sector_cycle": row.get("holding_sector_cycle", row.get("sector_cycle", "UNKNOWN")),
            "sector_aux_labels": row.get("holding_sector_aux_labels", []),
            "sector_confidence": row.get("holding_sector_confidence", row.get("sector_confidence", "LOW")),
        })
    return rows


def account_candidates_from_rows(ranked: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if ranked.empty:
        return rows
    for _, row in ranked.head(limit).iterrows():
        rows.append({
            "ts_code": row.get("ts_code", ""),
            "name": row.get("name", ""),
            "sector_code": row.get("sector_code", ""),
            "sector_name": row.get("sector_name", ""),
            "stock_role": row.get("stock_role", "UNCERTAIN_ROLE"),
            "final_execution_label": row.get("final_execution_label", "OBSERVE_ONLY"),
            "sector_cycle": row.get("sector_cycle", "UNKNOWN"),
            "sector_aux_labels": row.get("sector_aux_labels", []),
            "sector_confidence": row.get("sector_confidence", "LOW"),
            "latest_price": row.get("close"),
        })
    return rows


def account_section_lines(account: dict[str, Any], simulated: bool = True) -> list[str]:
    prefix = "当前为模拟账户数据，不代表真实账户。" if simulated else "当前为用户提供账户数据。"
    labels = " / ".join(account.get("risk_labels", [])) or "-"
    names = " / ".join(account.get("risk_label_names", [])) or "-"
    lines = [
        f"- {prefix}",
        f"- 账户总资产：{money(account.get('total_asset'))} 元",
        f"- 当前现金：{money(account.get('cash'))} 元",
        f"- 当前总仓位：{pct(account.get('total_position_pct'))}",
        f"- 现金比例：{pct(account.get('cash_pct'))}",
        f"- 大盘天气：{account.get('market_weather', '-')}",
        f"- 总仓位建议上限：{pct(account.get('total_position_limit_pct'))}",
        f"- 账户风险标签：{labels}（{names}）",
        f"- 是否允许新增买入：{yes_no(bool(account.get('allow_new_buy')))}",
        f"- 今日新增买入总额度：{money(account.get('allowed_new_total_value'))} 元，约 {pct(account.get('allowed_new_total_pct'))}",
        f"- 是否需要降仓：{yes_no(bool(account.get('need_reduce')))}",
        f"- 账户级建议：{account.get('account_advice', '-')}",
        f"- 不能盯盘处理：{account.get('no_watch_action', '-')}",
    ]
    return lines


def write_account_report(as_of: str, account: dict[str, Any]) -> dict[str, str]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / f"account_position_advice_{as_of}.md"
    json_path = REPORTS_DIR / f"account_position_advice_{as_of}.json"
    json_path.write_text(json.dumps(account, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 账户级仓位管理建议", ""]
    lines.extend(["## 账户摘要", *account_section_lines(account), ""])
    lines.extend(["## 单票仓位表", "| 股票 | 板块 | 角色 | 执行标签 | 持仓标签 | 市值 | 仓位 | 单票上限 | 是否过高 |", "| -- | -- | -- | -- | -- | --: | --: | --: | -- |"])
    for item in account.get("stock_positions", []):
        lines.append(
            f"| {item.get('name')} {item.get('ts_code')} | {item.get('sector_name')} | {item.get('stock_role')} | {item.get('final_execution_label')} | {item.get('holding_label')} | {money(item.get('market_value'))} | {pct(item.get('position_pct'))} | {pct(item.get('role_limit_pct'))} | {yes_no(bool(item.get('is_too_high')))} |"
        )
    lines.extend(["", "## 板块仓位表", "| 板块 | 周期 | 置信度 | 市值 | 仓位 | 板块上限 | 是否拥挤 |", "| -- | -- | -- | --: | --: | --: | -- |"])
    for item in account.get("sector_positions", []):
        lines.append(
            f"| {item.get('sector_name')} | {item.get('sector_cycle')} | {item.get('sector_confidence')} | {money(item.get('market_value'))} | {pct(item.get('position_pct'))} | {pct(item.get('sector_limit_pct'))} | {yes_no(bool(item.get('is_crowded')))} |"
        )
    lines.extend(["", "## 新候选额度", "| 股票 | 板块 | 角色 | 执行标签 | 允许买 | 单票新增上限 | 额度 |", "| -- | -- | -- | -- | -- | --: | --: |"])
    for item in account.get("candidate_limits", [])[:10]:
        lines.append(
            f"| {item.get('name')} {item.get('ts_code')} | {item.get('sector_name')} | {item.get('stock_role')} | {item.get('final_execution_label')} | {yes_no(bool(item.get('allow_buy')))} | {pct(item.get('single_new_limit_pct'))} | {money(item.get('single_new_limit_value'))} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"markdown": str(md_path), "json": str(json_path)}


def build_advice(cash: float, holdings: list[dict[str, Any]], can_watch: bool = True, total_asset: float | None = None) -> dict[str, Any]:
    as_of = latest_date()
    decisions = read_decisions(as_of)
    quotes = read_quotes(as_of)
    stocks = read_stocks(as_of)
    sector_source = read_sector_source(as_of)
    if not stocks.empty:
        merged = stocks.merge(decisions, on="ts_code", how="left", suffixes=("", "_decision"))
    else:
        merged = decisions.copy()
    merged = merged.merge(quotes, on="ts_code", how="left")
    if not merged.empty:
        exec_rows: list[dict[str, Any]] = []
        for _, row in merged.iterrows():
            exec_decision = execution_for_row(row, sector_source, stocks, "empty")
            holding_exec = execution_for_row(row, sector_source, stocks, "holding")
            exec_rows.append({
                "ts_code": row.get("ts_code"),
                "final_execution_label": exec_decision["final_label"],
                "allow_buy": exec_decision["allow_buy"],
                "max_position_pct": exec_decision["max_position_pct"],
                "execution_reason": "；".join(exec_decision["downgrade_reasons"][:2]) or "-",
                "holding_final_execution_label": holding_exec["final_label"],
                "holding_advice": holding_exec["holding_advice"],
                "holding_reason": "；".join(holding_exec["downgrade_reasons"][:2]) or "-",
                "stop_advice": holding_exec["stop_advice"],
                "sector_cycle_text": exec_decision["sector_cycle_text"],
                "sector_cycle": exec_decision["sector_cycle"],
                "sector_aux_labels": exec_decision["sector_aux_labels"],
                "sector_confidence": exec_decision["sector_confidence"],
                "holding_sector_cycle": holding_exec["sector_cycle"],
                "holding_sector_aux_labels": holding_exec["sector_aux_labels"],
                "holding_sector_confidence": holding_exec["sector_confidence"],
                "stock_role": exec_decision["stock_role"]["role"],
                "stock_role_name": exec_decision["stock_role"]["role_name"],
                "stock_role_confidence": exec_decision["stock_role"]["confidence"],
                "stock_role_detail": exec_decision["stock_role"],
            })
        exec_df = pd.DataFrame(exec_rows)
        merged = merged.merge(exec_df, on="ts_code", how="left")
    ranked = merged.sort_values(["stock_score", "leader_score"], ascending=False)
    account_holdings = [holding_from_dict(x) for x in account_holdings_from_rows(holdings, merged)]
    inferred_total_asset = float(cash) + sum(item.market_value for item in account_holdings)
    account_total_asset = float(total_asset) if total_asset is not None and total_asset > 0 else inferred_total_asset
    account_candidates = [candidate_from_dict(x) for x in account_candidates_from_rows(ranked)]
    account_decision = decide_account_position(
        total_asset=account_total_asset,
        cash=cash,
        holdings=account_holdings,
        candidates=account_candidates,
        market_weather=market_weather_from_data(merged),
        can_watch=can_watch,
    )
    account_payload = decision_to_dict(account_decision)
    account_paths = write_account_report(as_of, account_payload)

    sections = {
        "summary": [
            f"- 日期：{as_of}",
            "- 这是一份模型辅助建议，不替代你的最终交易决定。",
            "- 现阶段优先参考：天气 -> 街区 -> 班长 -> 店铺。",
        ],
        "account_position": account_section_lines(account_payload),
        "empty_position": advise_empty_position(cash, ranked),
        "holdings": advise_holdings(holdings, merged, can_watch=can_watch),
    }
    return {
        "as_of_date": as_of,
        "cash": cash,
        "total_asset": account_total_asset,
        "holdings": holdings,
        "can_watch": can_watch,
        "account_position": account_payload,
        "account_report": account_paths,
        "sections": sections,
    }


def write_outputs(result: dict[str, Any]) -> dict[str, str]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    as_of = result["as_of_date"]
    json_path = REPORTS_DIR / f"position_advice_{as_of}.json"
    md_path = REPORTS_DIR / f"position_advice_{as_of}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 空仓 / 持仓建议", ""]
    for title, items in result["sections"].items():
        lines.append(f"## {title}")
        lines.extend(items or ["- 无"])
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Advise on empty position or holdings")
    parser.add_argument("--cash", dest="cash", type=float, default=0.0)
    parser.add_argument("--asset", dest="total_asset", type=float, default=0.0, help="Optional total account asset for simulated account advice")
    parser.add_argument("--holding", dest="holdings", action="append", default=[], help="Format: TS_CODE:SHARES:COST")
    parser.add_argument("--no-watch", dest="can_watch", action="store_false", help="Use stricter rules for users who cannot watch the market")
    args = parser.parse_args(argv)
    holdings = [parse_holding(v) for v in args.holdings]
    result = build_advice(args.cash, holdings, can_watch=args.can_watch, total_asset=args.total_asset or None)
    paths = write_outputs(result)
    print(json.dumps({"as_of_date": result["as_of_date"], **paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
