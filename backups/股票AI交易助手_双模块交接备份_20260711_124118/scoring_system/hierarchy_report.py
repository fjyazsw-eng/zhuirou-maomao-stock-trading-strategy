from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.sector_cycle_classifier import classify_sector_cycle, labels_to_text
from scoring_system.execution_decision_engine import decide_execution_from_dict
from scoring_system.stock_role_classifier import classify_stock_role_from_dict

SCORES = ROOT / "data" / "processed" / "scores"
DECISIONS = ROOT / "data" / "processed" / "decisions"
SQLITE_PATH = ROOT / "data" / "sqlite" / "market_120d.sqlite"
REPORT_PATH = ROOT / "reports" / "latest_market_decision_report.md"
JSON_PATH = ROOT / "reports" / "latest_market_decision_report.json"
HTML_PATH = ROOT / "reports" / "latest_market_decision_dashboard.html"
DETAIL_DIR = ROOT / "reports" / "details"
REPORTS_DIR = ROOT / "reports"


def pick_latest_date(as_of: str | None = None) -> str:
    if as_of:
        return as_of
    candidates: list[str] = []
    for folder, pattern in [
        (SCORES, "market_sector_score_*_calibrated.json"),
        (SCORES, "leader_scores_*.csv"),
        (SCORES, "stock_scores_*.csv"),
        (DECISIONS, "decision_results_*.csv"),
    ]:
        for path in folder.glob(pattern):
            candidates.extend([p for p in path.stem.split("_") if p.isdigit() and len(p) == 8])
    if not candidates:
        raise FileNotFoundError("No score artifacts found")
    return max(candidates)


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"ts_code": "string", "sector_code": "string", "index_code": "string"})


def load_payload(as_of: str) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    market_path = SCORES / f"market_sector_score_{as_of}_calibrated.json"
    sector_path = SCORES / f"sector_scores_{as_of}_calibrated.csv"
    leader_path = SCORES / f"leader_scores_{as_of}.csv"
    stock_path = SCORES / f"stock_scores_{as_of}.csv"
    decision_path = DECISIONS / f"decision_results_{as_of}.csv"
    market = json.loads(market_path.read_text(encoding="utf-8")) if market_path.exists() else {}
    sectors = read_csv(sector_path) if sector_path.exists() else pd.DataFrame()
    leaders = read_csv(leader_path) if leader_path.exists() else pd.DataFrame()
    stocks = read_csv(stock_path) if stock_path.exists() else pd.DataFrame()
    decisions = read_csv(decision_path) if decision_path.exists() else pd.DataFrame()
    return market, sectors, leaders, stocks, decisions


def read_sqlite_quotes(as_of: str) -> pd.DataFrame:
    if not SQLITE_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(SQLITE_PATH) as conn:
        daily = pd.read_sql_query(
            """
            SELECT d.ts_code, d.trade_date, d.open, d.high, d.low, d.close, d.pre_close, d.pct_chg,
                   d.vol, d.amount, d.amount_yuan, d.return,
                   b.turnover_rate, b.volume_ratio, b.circ_mv_yuan
            FROM daily d
            LEFT JOIN daily_basic b
              ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            WHERE d.trade_date = ?
            """,
            conn,
            params=(as_of,),
        )
    if daily.empty:
        return daily
    for col in [
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "pct_chg",
        "vol",
        "amount",
        "amount_yuan",
        "return",
        "turnover_rate",
        "volume_ratio",
        "circ_mv_yuan",
    ]:
        daily[col] = pd.to_numeric(daily[col], errors="coerce")
    return daily


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def top_rows(df: pd.DataFrame, n: int, sort_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    cols = [c for c in sort_cols if c in df.columns]
    if cols:
        df = df.sort_values(cols, ascending=False)
    return df.head(n).copy()


def fmt(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}"
    return clean_text(value)


def pct_fmt(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}%"


def money_fmt_yi(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) / 1e8:.{digits}f} 亿"


def html_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    probes = ("鏈", "鍗", "琛", "鏉", "鏃", "鐜", "搴", "鐝", "璇", "闃", "鍧", "浠")
    if any(token in text for token in probes):
        for enc in ("gb18030", "gbk", "cp936"):
            try:
                repaired = text.encode(enc, errors="ignore").decode("utf-8", errors="ignore").strip()
            except Exception:
                continue
            if repaired:
                text = repaired
                break
    return text.replace("Ⅱ", "II").replace("Ⅲ", "III").replace("Ⅳ", "IV").replace("Ⅴ", "V").replace("?", "")



def sector_cycle_for_row(row: pd.Series, sector_stocks: pd.DataFrame | None = None) -> dict[str, Any]:
    """Minimal daily-report bridge into the sector-cycle module."""
    raw_ret = row.get("equal_return")
    if raw_ret is None or pd.isna(raw_ret):
        raw_ret = row.get("return_used")
    ret_pct = float(raw_ret) * 100 if raw_ret is not None and not pd.isna(raw_ret) else None
    score = row.get("score", row.get("sector_score"))
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
    if sector_stocks is not None and not sector_stocks.empty:
        for _, item in top_rows(sector_stocks, 8, ["stock_score", "leader_score"]).iterrows():
            stock_score = item.get("stock_score")
            leader_score = item.get("leader_score")
            role = "角色不确定"
            if leader_score is not None and not pd.isna(leader_score) and float(leader_score) >= 75:
                role = "疑似龙头"
            elif stock_score is not None and not pd.isna(stock_score) and float(stock_score) >= 70:
                role = "趋势核心"
            elif stock_score is not None and not pd.isna(stock_score) and float(stock_score) < 55:
                role = "后排或弱结构"
            pool.append({"角色": role, "20日位置": None})
    result = classify_sector_cycle(metrics, breadth, pool)
    return {
        "main_label": result.main_label,
        "aux_labels": result.auxiliary_labels,
        "confidence": result.confidence,
        "empty_advice": result.empty_advice,
        "holding_advice": result.holding_advice,
        "no_watch_advice": result.no_watch_advice,
        "max_position": result.max_position,
        "support_evidence": result.support_evidence,
        "oppose_evidence": result.oppose_evidence,
    }


def sector_cycle_html(cycle: dict[str, Any]) -> str:
    return (
        "<ul>"
        f"<li>主周期标签：{html_escape(cycle.get('main_label', '-'))}</li>"
        f"<li>辅助交易标签：{html_escape(labels_to_text(cycle.get('aux_labels', [])))}</li>"
        f"<li>置信度：{html_escape(cycle.get('confidence', '-'))}</li>"
        f"<li>空仓建议：{html_escape(cycle.get('empty_advice', '-'))}</li>"
        f"<li>持仓建议：{html_escape(cycle.get('holding_advice', '-'))}</li>"
        f"<li>不能盯盘建议：{html_escape(cycle.get('no_watch_advice', '-'))}</li>"
        f"<li>最大仓位建议：{html_escape(cycle.get('max_position', '-'))}</li>"
        f"<li>支持证据：{html_escape('；'.join(cycle.get('support_evidence', [])[:2]) or '-')}</li>"
        f"<li>反对证据：{html_escape('；'.join(cycle.get('oppose_evidence', [])[:2]) or '-')}</li>"
        "</ul>"
    )


def sector_cycle_md_lines(cycle: dict[str, Any]) -> list[str]:
    return [
        f"  - 板块周期：{cycle.get('main_label', '-')}",
        f"  - 辅助标签：{labels_to_text(cycle.get('aux_labels', []))}",
        f"  - 置信度：{cycle.get('confidence', '-')}",
        f"  - 空仓：{cycle.get('empty_advice', '-')}",
        f"  - 持仓：{cycle.get('holding_advice', '-')}",
        f"  - 不能盯盘：{cycle.get('no_watch_advice', '-')}",
        f"  - 最大仓位：{cycle.get('max_position', '-')}",
        f"  - 支持证据：{'；'.join(cycle.get('support_evidence', [])[:2]) or '-'}",
        f"  - 反对证据：{'；'.join(cycle.get('oppose_evidence', [])[:2]) or '-'}",
    ]


def execution_for_stock_row(
    row: pd.Series,
    decision: dict[str, Any] | None,
    cycle: dict[str, Any],
    quote: dict[str, Any] | None = None,
    user_state: str = "empty",
    can_watch: bool = True,
) -> dict[str, Any]:
    decision = decision or {}
    quote = quote or {}
    risks = "；".join(split_cn_text(row.get("basic_risk")) + split_cn_text(decision.get("risks")))
    stock_role = stock_role_for_report(row, decision, cycle, quote)
    payload = {
        "ts_code": row.get("ts_code", ""),
        "name": row.get("name", ""),
        "stock_score": row.get("stock_score"),
        "leader_score": row.get("leader_score", decision.get("leader_score")),
        "original_status": decision.get("final_decision", row.get("execution_status", "-")),
        "sector_name": row.get("sector_name", ""),
        "sector_cycle": cycle.get("main_label", "UNKNOWN"),
        "sector_aux_labels": cycle.get("aux_labels", []),
        "sector_confidence": cycle.get("confidence", "LOW"),
        "risk_text": risks,
        "leader_labels": row.get("leader_labels", decision.get("leader_labels", "")),
        "core_identity": decision.get("core_identity", ""),
        "stock_role": stock_role.get("role", "UNCERTAIN_ROLE"),
        "user_state": user_state,
        "can_watch": can_watch,
        "has_alert": True,
        "latest_price": quote.get("close"),
    }
    result = decide_execution_from_dict(payload)
    return {
        "original_status": result.original_status,
        "final_label": result.final_label,
        "allow_buy": result.allow_buy,
        "allow_add": result.allow_add,
        "max_position_pct": result.max_position_pct,
        "sector_cycle_text": result.sector_cycle_text,
        "sector_confidence": result.sector_confidence,
        "downgrade_reasons": result.downgrade_reasons,
        "empty_advice": result.empty_advice,
        "holding_advice": result.holding_advice,
        "no_watch_advice": result.no_watch_advice,
        "stop_advice": result.stop_advice,
        "profit_protection_advice": result.profit_protection_advice,
        "upgrade_conditions": result.upgrade_conditions,
        "invalid_conditions": result.invalid_conditions,
        "stock_role": stock_role,
    }


def stock_role_for_report(
    row: pd.Series,
    decision: dict[str, Any] | None,
    cycle: dict[str, Any],
    quote: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision = decision or {}
    quote = quote or {}
    risks = "；".join(split_cn_text(row.get("basic_risk")) + split_cn_text(decision.get("risks")))
    role = classify_stock_role_from_dict({
        "ts_code": row.get("ts_code", ""),
        "name": row.get("name", ""),
        "sector_name": row.get("sector_name", ""),
        "stock_score": row.get("stock_score"),
        "leader_score": row.get("leader_score", decision.get("leader_score")),
        "trend_structure_score": row.get("trend_structure_score"),
        "volume_price_quality_score": row.get("volume_price_quality_score"),
        "position_heat_score": row.get("position_heat_score"),
        "tradability_score": row.get("tradability_score"),
        "pct_chg": quote.get("pct_chg"),
        "turnover_rate": quote.get("turnover_rate"),
        "sector_cycle": cycle.get("main_label", "UNKNOWN"),
        "leader_labels": row.get("leader_labels", decision.get("leader_labels", "")),
        "risk_text": risks,
        "execution_status": decision.get("final_decision", row.get("execution_status", "")),
        "sub_scores_json": row.get("sub_scores_json"),
    })
    role["old_role"] = clean_text(row.get("leader_labels", decision.get("leader_labels", "-"))) or "-"
    return role


def stock_role_html(role: dict[str, Any]) -> str:
    return (
        "<ul>"
        f"<li>旧角色：{html_escape(role.get('old_role', '-'))}</li>"
        f"<li>新角色：{html_escape(role.get('role', '-'))}（{html_escape(role.get('role_name', '-'))}）</li>"
        f"<li>角色置信度：{html_escape(role.get('confidence', '-'))}</li>"
        f"<li>角色依据：{html_escape('；'.join(role.get('evidence', [])[:3]) or '-')}</li>"
        f"<li>角色风险：{html_escape('；'.join(role.get('risks', [])[:3]) or '-')}</li>"
        f"<li>是否核心：{html_escape('是' if role.get('is_core') else '否')}</li>"
        f"<li>是否后排：{html_escape('是' if role.get('is_backrow') else '否')}</li>"
        f"<li>角色对执行影响：{html_escape(role.get('execution_effect', '-'))}</li>"
        "</ul>"
    )


def stock_role_brief(role: dict[str, Any]) -> str:
    return (
        f"新角色：{role.get('role', '-')}（{role.get('role_name', '-')}），"
        f"置信度：{role.get('confidence', '-')}；"
        f"依据：{'；'.join(role.get('evidence', [])[:2]) or '-'}；"
        f"风险：{'；'.join(role.get('risks', [])[:2]) or '-'}；"
        f"对执行影响：{role.get('execution_effect', '-')}"
    )


def execution_html(exec_decision: dict[str, Any]) -> str:
    role = exec_decision.get("stock_role", {}) or {}
    return (
        "<ul>"
        f"<li>原始状态：{html_escape(exec_decision.get('original_status', '-'))}</li>"
        f"<li>最终执行标签：{html_escape(exec_decision.get('final_label', '-'))}</li>"
        f"<li>新角色：{html_escape(role.get('role', '-'))}（{html_escape(role.get('role_name', '-'))}），置信度 {html_escape(role.get('confidence', '-'))}</li>"
        f"<li>角色影响：{html_escape(role.get('execution_effect', '-'))}</li>"
        f"<li>是否允许买：{html_escape('是' if exec_decision.get('allow_buy') else '否')}</li>"
        f"<li>最大仓位：{html_escape(str(exec_decision.get('max_position_pct', 0)))}%</li>"
        f"<li>所属板块周期：{html_escape(exec_decision.get('sector_cycle_text', '-'))}，置信度 {html_escape(exec_decision.get('sector_confidence', '-'))}</li>"
        f"<li>降级原因：{html_escape('；'.join(exec_decision.get('downgrade_reasons', [])[:3]) or '-')}</li>"
        f"<li>空仓建议：{html_escape(exec_decision.get('empty_advice', '-'))}</li>"
        f"<li>持仓建议：{html_escape(exec_decision.get('holding_advice', '-'))}</li>"
        f"<li>不能盯盘建议：{html_escape(exec_decision.get('no_watch_advice', '-'))}</li>"
        f"<li>止损/保护：{html_escape(exec_decision.get('stop_advice', '-'))}</li>"
        "</ul>"
    )


def execution_brief(exec_decision: dict[str, Any]) -> str:
    role = exec_decision.get("stock_role", {}) or {}
    return (
        f"原始状态：{exec_decision.get('original_status', '-')}；"
        f"最终执行标签：{exec_decision.get('final_label', '-')}；"
        f"新角色：{role.get('role', '-')}（{role.get('role_name', '-')}），置信度{role.get('confidence', '-')}；"
        f"允许买：{'是' if exec_decision.get('allow_buy') else '否'}；"
        f"最大仓位：{exec_decision.get('max_position_pct', 0)}%；"
        f"板块周期：{exec_decision.get('sector_cycle_text', '-')}，置信度{exec_decision.get('sector_confidence', '-')}; "
        f"降级原因：{'；'.join(exec_decision.get('downgrade_reasons', [])[:2]) or '-'}；"
        f"空仓：{exec_decision.get('empty_advice', '-')}；"
        f"持仓：{exec_decision.get('holding_advice', '-')}；"
        f"不能盯盘：{exec_decision.get('no_watch_advice', '-')}；"
        f"止损/保护：{exec_decision.get('stop_advice', '-')}"
    )


def sector_cycle_for_code(code: str, sector_source: pd.DataFrame, stocks: pd.DataFrame) -> dict[str, Any]:
    if not code:
        return sector_cycle_for_row(pd.Series(dtype="object"), pd.DataFrame())
    sector_row = pd.Series(dtype="object")
    if not sector_source.empty:
        for key in ["index_code", "sector_code"]:
            if key in sector_source.columns:
                matched = sector_source[sector_source[key].astype(str) == str(code)]
                if not matched.empty:
                    sector_row = matched.iloc[0]
                    break
    sector_stocks = stocks[stocks["sector_code"].astype(str) == str(code)].copy() if "sector_code" in stocks.columns else pd.DataFrame()
    return sector_cycle_for_row(sector_row, sector_stocks)


def parse_json(value: Any) -> Any:
    if value is None or pd.isna(value):
        return {}
    try:
        return json.loads(str(value))
    except Exception:
        return {}


def split_cn_text(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    for prefix in ["基础行情风险：", "事件风险：", "优势：", "风险："]:
        text = text.replace(prefix, "")
    for token in ["；", "。", "，", ",", "|", "/", "、"]:
        text = text.replace(token, "|")
    return [item.strip() for item in text.split("|") if item.strip()]


def detail_href(kind: str, code: str) -> str:
    return f"details/{kind}_{code}.html"


def render_table(headers: list[str], rows_html: list[str]) -> str:
    head_html = "".join(f"<th>{html_escape(h)}</th>" for h in headers)
    body_html = "".join(rows_html) if rows_html else f"<tr><td colspan=\"{len(headers)}\">暂无数据</td></tr>"
    return f"<table><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>"


def style_block(title: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)}</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #18212f;
      --muted: #5f6b7a;
      --line: #d8dfeb;
      --accent: #2363eb;
      --accent-soft: #eef4ff;
      --good: #157f3b;
      --warn: #c77a00;
      --bad: #c23333;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    .page {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 24px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 16px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      flex-wrap: wrap;
    }}
    h1, h2, h3 {{ margin: 0 0 12px 0; }}
    p {{ margin: 0; color: var(--muted); line-height: 1.6; }}
    .sub {{ color: var(--muted); font-size: 14px; margin-top: 6px; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-weight: 600;
      font-size: 14px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .metric-card {{
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 92px;
    }}
    .metric-label {{ color: var(--muted); font-size: 13px; margin-bottom: 10px; }}
    .metric-value {{ font-size: 24px; font-weight: 700; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .grid-3 {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
    }}
    .progress-wrap {{
      display: grid;
      gap: 12px;
    }}
    .progress-bar {{
      width: 100%;
      height: 14px;
      background: #e8edf6;
      border-radius: 999px;
      overflow: hidden;
      border: 1px solid var(--line);
    }}
    .progress-bar > span {{
      display: block;
      height: 100%;
      background: linear-gradient(90deg, #2363eb 0%, #21a1ff 100%);
    }}
    .status-list {{
      display: grid;
      gap: 10px;
    }}
    .status-item {{
      padding: 12px;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .status-done {{ border-left: 4px solid var(--good); }}
    .status-going {{ border-left: 4px solid var(--warn); }}
    .status-pending {{ border-left: 4px solid var(--bad); }}
    .pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      background: #edf2ff;
      color: #2747a0;
      margin-bottom: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; background: #f8fafc; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 6px 0; }}
    code {{ background: #f3f5f8; padding: 2px 6px; border-radius: 4px; }}
    .file-list a {{ display: inline-block; margin: 4px 0; }}
    @media (max-width: 1100px) {{
      .metrics {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .grid, .grid-3 {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 720px) {{
      .page {{ padding: 12px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <div class="page">
"""


def close_html() -> str:
    return "</div></body></html>"


def recommendation_text(
    market_grade: str,
    sector_grade: str,
    final_decision: str,
    quote: dict[str, Any],
    advantages: list[str],
    risks: list[str],
) -> str:
    latest_price = f"最新价 {fmt(quote.get('close'))}" if quote else "最新价缺失"
    latest_chg = f"涨跌幅 {pct_fmt(quote.get('pct_chg'))}" if quote else "涨跌幅缺失"
    adv_text = "；".join(advantages[:2]) if advantages else "暂无优势说明"
    risk_text = "；".join(risks[:2]) if risks else "暂无显式风险"
    return (
        f"{latest_price}，{latest_chg}。市场层级为 {clean_text(market_grade)}，"
        f"街区层级为 {clean_text(sector_grade)}，当前执行状态为 {clean_text(final_decision)}。"
        f"优势：{adv_text}。风险：{risk_text}。"
    )


def render_market_cards(market: dict[str, Any]) -> str:
    payload = market.get("market_score", {})
    feat = payload.get("features", {})
    cards = [
        ("大盘天气评分", f"{fmt(payload.get('score'))} / {clean_text(payload.get('grade', '-'))}"),
        ("上涨家数", f"{feat.get('up_count', '-')} / {feat.get('stock_count', '-')}"),
        ("下跌家数", f"{feat.get('down_count', '-')} / {feat.get('stock_count', '-')}"),
        ("今日成交", money_fmt_yi(feat.get("market_amount_today_yuan"))),
        ("5日均值", money_fmt_yi(feat.get("amount_5d_avg_yuan"))),
        ("上涨占比", pct_fmt((feat.get("up_ratio") or 0) * 100 if feat.get("up_ratio") is not None else None)),
    ]
    return "".join(
        f'<div class="metric-card"><div class="metric-label">{html_escape(label)}</div><div class="metric-value">{html_escape(value)}</div></div>'
        for label, value in cards
    )


def project_progress_payload(as_of: str) -> dict[str, Any]:
    items = [
        ("大盘-板块-龙头-个股四层打分", "done"),
        ("最新价、涨跌幅、成交额、换手率等可验证展示", "done"),
        ("板块详情页、个股详情页、打分过程下钻", "done"),
        ("退潮预警与短期回调/转弱/退潮区分", "done"),
        ("空仓/持仓建议输出", "done"),
        ("Tushare 数据接入与本地缓存", "done"),
        ("日报主页总览与完整文件入口", "done"),
        ("定时报送到飞书/企业微信", "going"),
        ("远程互动问答入口", "going"),
        ("真实资金流、政策面、公告面增强", "pending"),
        ("DSA 深度并入生产链路", "pending"),
    ]
    total = len(items)
    completed = sum(1 for _, state in items if state == "done")
    going = sum(1 for _, state in items if state == "going")
    percent = round((completed + going * 0.5) / total * 100, 1)
    key_files = [
        ("总览主页", "latest_market_decision_dashboard.html"),
        ("总览报告", "latest_market_decision_report.md"),
        ("板块预警", f"alerts/sector_alerts_{as_of}.md"),
        ("板块状态判断", f"regime/sector_regime_{as_of}.md"),
        ("空仓与持仓建议", f"advice/position_advice_{as_of}.md"),
        ("分层生成器", "scoring_system/hierarchy_report.py"),
        ("预警模块", "scoring_system/sector_alerts.py"),
        ("状态识别模块", "scoring_system/regime_classifier.py"),
        ("持仓建议模块", "scoring_system/position_advisor.py"),
    ]
    return {"percent": percent, "items": items, "key_files": key_files}


def relative_report_href(path: Path) -> str:
    return path.relative_to(REPORTS_DIR).as_posix()


def build_sector_detail_pages(
    as_of: str,
    sector_source: pd.DataFrame,
    leaders: pd.DataFrame,
    stocks: pd.DataFrame,
    decisions: pd.DataFrame,
    quotes: pd.DataFrame,
) -> None:
    quote_map = quotes.set_index("ts_code").to_dict("index") if not quotes.empty else {}
    decision_map = decisions.set_index("ts_code").to_dict("index") if not decisions.empty else {}
    for _, sector in sector_source.iterrows():
        code = str(sector.get("index_code", sector.get("sector_code", "")))
        if not code:
            continue
        name = clean_text(sector.get("industry_name", sector.get("sector_name", code)))
        sector_leaders = leaders[leaders["sector_code"].astype(str) == code].copy() if "sector_code" in leaders.columns else pd.DataFrame()
        sector_stocks = stocks[stocks["sector_code"].astype(str) == code].copy() if "sector_code" in stocks.columns else pd.DataFrame()
        cycle = sector_cycle_for_row(sector, sector_stocks)
        leader_rows = []
        for _, row in top_rows(sector_leaders, 12, ["score"]).iterrows():
            q = quote_map.get(str(row.get("ts_code")))
            leader_rows.append(
                "<tr>"
                f"<td><a href=\"../{detail_href('stock', str(row.get('ts_code')))}\">{html_escape(clean_text(row.get('name', '-')))}</a></td>"
                f"<td>{html_escape(row.get('ts_code', '-'))}</td>"
                f"<td>{html_escape(fmt(row.get('score')))}</td>"
                f"<td>{html_escape(pct_fmt(q.get('pct_chg')) if q else '-')}</td>"
                f"<td>{html_escape(fmt(q.get('close')) if q else '-')}</td>"
                f"<td>{html_escape(money_fmt_yi(q.get('amount_yuan')) if q else '-')}</td>"
                "</tr>"
            )
        stock_rows = []
        for _, row in top_rows(sector_stocks, 20, ["stock_score", "leader_score"]).iterrows():
            ts_code = str(row.get("ts_code"))
            q = quote_map.get(ts_code)
            decision = decision_map.get(ts_code, {})
            exec_decision = execution_for_stock_row(row, decision, cycle, q)
            role = exec_decision.get("stock_role", {})
            adv = split_cn_text(row.get("advantages"))
            risks = split_cn_text(row.get("basic_risk"))
            note = recommendation_text(
                str(row.get("market_grade", "-")),
                str(row.get("sector_grade", "-")),
                str(decision.get("final_decision", row.get("execution_status", "-"))),
                q or {},
                adv,
                risks,
            )
            stock_rows.append(
                "<tr>"
                f"<td><a href=\"../{detail_href('stock', ts_code)}\">{html_escape(clean_text(row.get('name', '-')))}</a></td>"
                f"<td>{html_escape(ts_code)}</td>"
                f"<td>{html_escape(fmt(row.get('stock_score')))}</td>"
                f"<td>{html_escape(fmt(row.get('leader_score')))}</td>"
                f"<td>{html_escape(fmt(q.get('close')) if q else '-')}</td>"
                f"<td>{html_escape(pct_fmt(q.get('pct_chg')) if q else '-')}</td>"
                f"<td>{html_escape(clean_text(decision.get('final_decision', row.get('execution_status', '-'))))}</td>"
                f"<td>{html_escape(role.get('role', '-'))}<br><span class=\"sub\">{html_escape(role.get('confidence', '-'))}</span></td>"
                f"<td>{html_escape(exec_decision.get('final_label', '-'))}</td>"
                f"<td>{html_escape('是' if exec_decision.get('allow_buy') else '否')}</td>"
                f"<td>{html_escape(str(exec_decision.get('max_position_pct', 0)))}%</td>"
                f"<td>{html_escape(note)}<br><span class=\"sub\">{html_escape(stock_role_brief(role))}</span><br><span class=\"sub\">{html_escape(execution_brief(exec_decision))}</span></td>"
                "</tr>"
            )
        html = [
            style_block(f"{name} 详情"),
            '<section class="panel"><div class="hero">',
            f"<div><h1>{html_escape(name)}</h1><div class=\"sub\">代码 {html_escape(code)} | 日期 {html_escape(as_of)} | <a href=\"../latest_market_decision_dashboard.html\">返回总览</a></div></div>",
            f"<div class=\"badge\">街区分 {html_escape(fmt(sector.get('score', sector.get('sector_score'))))}</div>",
            "</div></section>",
            '<section class="panel"><h2>可验证数据</h2>',
            f"<ul><li>等权收益：{html_escape(pct_fmt((sector.get('equal_return') or sector.get('return_used')) * 100 if pd.notna(sector.get('equal_return') or sector.get('return_used')) else None))}</li>",
            f"<li>加权收益：{html_escape(pct_fmt((sector.get('weighted_return') or sector.get('return_used')) * 100 if pd.notna(sector.get('weighted_return') or sector.get('return_used')) else None))}</li>",
            f"<li>成交占比：{html_escape(pct_fmt((sector.get('amount_share') or 0) * 100 if sector.get('amount_share') is not None else None))}</li>",
            f"<li>覆盖率：{html_escape(pct_fmt((sector.get('quote_coverage') or 0) * 100 if sector.get('quote_coverage') is not None else None))}</li>",
            "</ul></section>",
            '<section class="panel"><h2>板块周期</h2>',
            sector_cycle_html(cycle),
            "</section>",
            '<section class="panel"><h2>龙头候选</h2>',
            render_table(["名称", "代码", "龙头分", "涨跌幅", "最新价", "成交额"], leader_rows),
            "</section>",
            '<section class="panel"><h2>个股候选</h2>',
            render_table(["名称", "代码", "个股分", "龙头分", "最新价", "涨跌幅", "原始状态", "新角色", "最终执行标签", "允许买", "最大仓位", "推荐说明"], stock_rows),
            "</section>",
            close_html(),
        ]
        (DETAIL_DIR / f"sector_{code}.html").write_text("".join(html), encoding="utf-8")


def build_stock_detail_pages(
    as_of: str,
    sector_source: pd.DataFrame,
    stocks: pd.DataFrame,
    leaders: pd.DataFrame,
    decisions: pd.DataFrame,
    quotes: pd.DataFrame,
) -> None:
    quote_map = quotes.set_index("ts_code").to_dict("index") if not quotes.empty else {}
    leader_map = leaders.set_index("ts_code").to_dict("index") if not leaders.empty else {}
    decision_map = decisions.set_index("ts_code").to_dict("index") if not decisions.empty else {}
    for _, row in stocks.iterrows():
        ts_code = str(row.get("ts_code"))
        name = clean_text(row.get("name", ts_code))
        q = quote_map.get(ts_code, {})
        leader = leader_map.get(ts_code, {})
        decision = decision_map.get(ts_code, {})
        cycle = sector_cycle_for_code(str(row.get("sector_code", "")), sector_source, stocks)
        exec_decision = execution_for_stock_row(row, decision, cycle, q)
        role = exec_decision.get("stock_role", {})
        sub_scores = parse_json(row.get("sub_scores_json"))
        advantages = split_cn_text(row.get("advantages"))
        risks = split_cn_text(row.get("basic_risk"))
        waits = split_cn_text(row.get("wait_or_stop_conditions"))
        recommendation = recommendation_text(
            str(row.get("market_grade", "-")),
            str(row.get("sector_grade", "-")),
            str(decision.get("final_decision", row.get("execution_status", "-"))),
            q,
            advantages,
            risks,
        )
        score_rows = []
        for bucket, payload in sub_scores.items():
            if not isinstance(payload, dict):
                continue
            for item_name, item_val in payload.items():
                if isinstance(item_val, dict) and "score" in item_val:
                    score_rows.append(
                        "<tr>"
                        f"<td>{html_escape(clean_text(bucket))}</td>"
                        f"<td>{html_escape(clean_text(item_name))}</td>"
                        f"<td>{html_escape(fmt(item_val.get('score')))}</td>"
                        f"<td>{html_escape(fmt(item_val.get('value')))}</td>"
                        f"<td>{html_escape(clean_text(item_val.get('label', '-')))}</td>"
                        "</tr>"
                    )
        leader_sub = parse_json(leader.get("sub_scores_json"))
        leader_rows = []
        for key, val in leader_sub.items():
            if isinstance(val, dict):
                leader_rows.append(
                    "<tr>"
                    f"<td>{html_escape(clean_text(key))}</td>"
                    f"<td>{html_escape(fmt(val.get('score')))}</td>"
                    f"<td>{html_escape(fmt(val.get('value')))}</td>"
                    f"<td>{html_escape(clean_text(val.get('label', '-')))}</td>"
                    "</tr>"
                )
        html = [
            style_block(f"{name} 详情"),
            '<section class="panel"><div class="hero">',
            f"<div><h1>{html_escape(name)}</h1><div class=\"sub\">{html_escape(ts_code)} | {html_escape(clean_text(row.get('sector_name', '-')))} | 日期 {html_escape(as_of)} | <a href=\"../latest_market_decision_dashboard.html\">返回总览</a></div></div>",
            f"<div class=\"badge\">{html_escape(clean_text(decision.get('final_decision', row.get('execution_status', '-'))))}</div>",
            "</div>",
            '<div class="metrics">',
            f'<div class="metric-card"><div class="metric-label">最新价</div><div class="metric-value">{html_escape(fmt(q.get("close")))}</div></div>',
            f'<div class="metric-card"><div class="metric-label">涨跌幅</div><div class="metric-value">{html_escape(pct_fmt(q.get("pct_chg")))}</div></div>',
            f'<div class="metric-card"><div class="metric-label">成交额</div><div class="metric-value">{html_escape(money_fmt_yi(q.get("amount_yuan")))}</div></div>',
            f'<div class="metric-card"><div class="metric-label">换手率</div><div class="metric-value">{html_escape(pct_fmt(q.get("turnover_rate")))}</div></div>',
            f'<div class="metric-card"><div class="metric-label">流通市值</div><div class="metric-value">{html_escape(money_fmt_yi(q.get("circ_mv_yuan")))}</div></div>',
            f'<div class="metric-card"><div class="metric-label">量比</div><div class="metric-value">{html_escape(fmt(q.get("volume_ratio")))}</div></div>',
            "</div></section>",
            '<section class="panel"><h2>推荐说明</h2>',
            f"<p>{html_escape(recommendation)}</p>",
            "<ul>"
            "<li>长期视角：看市场天气、板块持续性、赛道位置，政策面和公告面后续再补充接入。</li>"
            "<li>中期视角：重点看 3 到 5 日相对强弱、街区位置、龙头带动能力、换手和成交稳定性。</li>"
            "<li>短期视角：重点看最新价、当日涨跌幅、量比、换手率，以及最近 1/3/5 日结构。</li>"
            "</ul></section>",
            '<section class="panel"><h2>执行标签与仓位</h2>',
            execution_html(exec_decision),
            "</section>",
            '<section class="panel"><h2>个股角色识别</h2>',
            stock_role_html(role),
            "</section>",
            '<div class="grid">',
            '<section class="panel"><h2>个股打分过程</h2>' + render_table(["维度", "子项", "得分", "数值", "标签"], score_rows) + "</section>",
            '<section class="panel"><h2>龙头打分过程</h2>' + render_table(["维度", "得分", "数值", "标签"], leader_rows) + "</section>",
            "</div>",
            '<div class="grid">',
            '<section class="panel"><h2>优势</h2><ul>' + "".join(f"<li>{html_escape(x)}</li>" for x in (advantages or ["-"])) + "</ul></section>",
            '<section class="panel"><h2>风险与等待</h2><ul>'
            + "".join(f"<li>{html_escape(x)}</li>" for x in ((risks + waits) or ["-"]))
            + "</ul></section>",
            "</div>",
            '<section class="panel"><h2>可验证数据口径</h2><ul>'
            "<li>最新价、涨跌幅、成交额来自本地 SQLite 的 <code>daily</code> 表。</li>"
            "<li>换手率、量比、流通市值来自本地 SQLite 的 <code>daily_basic</code> 表。</li>"
            "<li>当前未展示无法本地核实的主力净流入数据。</li>"
            "<li>政策面、公司公告、事件催化后续将作为增强层补充。</li>"
            "</ul></section>",
            close_html(),
        ]
        (DETAIL_DIR / f"stock_{ts_code}.html").write_text("".join(html), encoding="utf-8")


def write_markdown_report(
    as_of: str,
    market: dict[str, Any],
    sector_source: pd.DataFrame,
    leaders: pd.DataFrame,
    stocks: pd.DataFrame,
    decisions: pd.DataFrame,
    quotes: pd.DataFrame,
) -> None:
    feat = market.get("market_score", {}).get("features", {})
    lines = [
        f"# 最新市场决策报告 {as_of}",
        "",
        "## 大盘天气",
        f"- 大盘天气评分：{fmt(market.get('market_score', {}).get('score'))} / {clean_text(market.get('market_score', {}).get('grade', '-'))}",
        f"- 上涨家数：{feat.get('up_count', '-')}",
        f"- 下跌家数：{feat.get('down_count', '-')}",
        f"- 今日成交：{money_fmt_yi(feat.get('market_amount_today_yuan'))}",
        "",
        "## 优势板块",
    ]
    for _, row in top_rows(sector_source, 5, ["sector_score", "score"]).iterrows():
        code = str(row.get("index_code", row.get("sector_code", "")))
        sector_stocks = stocks[stocks["sector_code"].astype(str) == code].copy() if code and "sector_code" in stocks.columns else pd.DataFrame()
        cycle = sector_cycle_for_row(row, sector_stocks)
        lines.append(
            f"- {clean_text(row.get('industry_name', row.get('sector_name', '-')))}：街区分 {fmt(row.get('score', row.get('sector_score')))}，等权收益 {pct_fmt((row.get('equal_return') or row.get('return_used')) * 100 if pd.notna(row.get('equal_return') or row.get('return_used')) else None)}"
        )
        lines.extend(sector_cycle_md_lines(cycle))
    lines.extend(["", "## 龙头候选"])
    for _, row in top_rows(leaders, 5, ["score"]).iterrows():
        lines.append(f"- {clean_text(row.get('name', '-'))} / {row.get('ts_code', '-')}：龙头分 {fmt(row.get('score'))}")
    lines.extend(["", "## 个股候选"])
    quote_map = quotes.set_index("ts_code").to_dict("index") if not quotes.empty else {}
    decision_map = decisions.set_index("ts_code").to_dict("index") if not decisions.empty else {}
    for _, row in top_rows(stocks, 10, ["stock_score", "leader_score"]).iterrows():
        ts_code = str(row.get("ts_code"))
        q = quote_map.get(ts_code, {})
        decision = decision_map.get(ts_code, {})
        cycle = sector_cycle_for_code(str(row.get("sector_code", "")), sector_source, stocks)
        exec_decision = execution_for_stock_row(row, decision, cycle, q)
        role = exec_decision.get("stock_role", {})
        lines.append(
            f"- {clean_text(row.get('name', '-'))} / {ts_code}：个股分 {fmt(row.get('stock_score'))}，最新价 {fmt(q.get('close'))}，涨跌幅 {pct_fmt(q.get('pct_chg'))}，状态 {clean_text(decision.get('final_decision', row.get('execution_status', '-')))}"
        )
        lines.append(f"  - 角色：旧角色 {role.get('old_role', '-')}；新角色 {role.get('role', '-')}（{role.get('role_name', '-')}），置信度 {role.get('confidence', '-')}")
        lines.append(f"  - 角色依据：{'；'.join(role.get('evidence', [])[:2]) or '-'}；角色风险：{'；'.join(role.get('risks', [])[:2]) or '-'}")
        lines.append(f"  - {execution_brief(exec_decision)}")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def render_progress_panel(progress: dict[str, Any]) -> str:
    items_html = []
    status_label = {"done": "已完成", "going": "推进中", "pending": "待接入"}
    status_class = {"done": "status-done", "going": "status-going", "pending": "status-pending"}
    for title, state in progress["items"]:
        items_html.append(
            f'<div class="status-item {status_class[state]}"><div class="pill">{status_label[state]}</div><div>{html_escape(title)}</div></div>'
        )
    file_html = "".join(
        f'<a href="{html_escape(path)}">{html_escape(name)}：{html_escape(path)}</a><br>'
        for name, path in progress["key_files"]
    )
    return (
        '<div class="grid">'
        '<section class="panel"><h2>开发进度</h2>'
        f'<div class="progress-wrap"><div><strong>{progress["percent"]:.1f}%</strong></div>'
        f'<div class="progress-bar"><span style="width:{progress["percent"]:.1f}%"></span></div>'
        '<p>当前已完成核心分析、详情下钻、预警识别、持仓建议与 Tushare 接入，正在推进定时报送和远程互动。</p>'
        '</div></section>'
        '<section class="panel"><h2>完整文件入口</h2><div class="file-list">'
        f"{file_html}</div></section></div>"
        '<section class="panel"><h2>成果清单</h2><div class="status-list">'
        f"{''.join(items_html)}</div></section>"
    )


def render_regime_panel(as_of: str) -> str:
    payload = read_json_if_exists(REPORTS_DIR / "regime" / f"sector_regime_{as_of}.json")
    states = payload.get("states", [])
    rows = []
    for item in states[:10]:
        rows.append(
            "<tr>"
            f"<td><a href=\"{detail_href('sector', str(item.get('index_code', '-')))}\">{html_escape(clean_text(item.get('industry_name', '-')))}</a></td>"
            f"<td>{html_escape(item.get('index_code', '-'))}</td>"
            f"<td>{html_escape(clean_text(item.get('state', '-')))}</td>"
            f"<td>{html_escape(fmt(item.get('prev_score')))} → {html_escape(fmt(item.get('score')))}</td>"
            f"<td>{html_escape(clean_text(item.get('reason', '-')))}</td>"
            "</tr>"
        )
    return (
        '<section class="panel"><h2>板块状态判断</h2><p>这里区分短期回调、转弱中、退潮、延续，方便判断是洗盘还是退潮。</p>'
        + render_table(["板块", "代码", "当前状态", "分数变化", "判断原因"], rows)
        + f'<p class="sub"><a href="{html_escape(relative_report_href(REPORTS_DIR / "regime" / f"sector_regime_{as_of}.md"))}">查看完整板块状态报告</a></p>'
        + "</section>"
    )


def render_alert_panel(as_of: str) -> str:
    payload = read_json_if_exists(REPORTS_DIR / "alerts" / f"sector_alerts_{as_of}.json")
    alerts = payload.get("alerts", [])
    rows = []
    for item in alerts[:10]:
        rows.append(
            "<tr>"
            f"<td><a href=\"{detail_href('sector', str(item.get('index_code', '-')))}\">{html_escape(clean_text(item.get('industry_name', '-')))}</a></td>"
            f"<td>{html_escape(item.get('prev_date', '-'))} → {html_escape(item.get('curr_date', '-'))}</td>"
            f"<td>{html_escape(fmt(item.get('prev_score')))} → {html_escape(fmt(item.get('curr_score')))}</td>"
            f"<td>{html_escape(clean_text(item.get('alert_level', '-')))}</td>"
            f"<td>{html_escape(clean_text(item.get('reason', '-')))}</td>"
            "</tr>"
        )
    return (
        '<section class="panel"><h2>退潮预警</h2><p>这里专门抓强势板块突然转弱、连续走坏、适合提前收缩仓位的信号。</p>'
        + render_table(["板块", "时间区间", "分数变化", "预警级别", "原因"], rows)
        + f'<p class="sub"><a href="{html_escape(relative_report_href(REPORTS_DIR / "alerts" / f"sector_alerts_{as_of}.md"))}">查看完整预警报告</a></p>'
        + "</section>"
    )


def render_advice_panel(as_of: str) -> str:
    payload = read_json_if_exists(REPORTS_DIR / "advice" / f"position_advice_{as_of}.json")
    sections = payload.get("sections", {})
    summary = [clean_text(x) for x in sections.get("summary", [])]
    account_position = [clean_text(x) for x in sections.get("account_position", [])]
    empty_position = [clean_text(x) for x in sections.get("empty_position", [])]
    holdings = [clean_text(x) for x in sections.get("holdings", [])]
    return (
        '<section class="panel"><h2>空仓与持仓建议</h2>'
        '<div class="grid">'
        '<div><h3>总说明</h3><ul>'
        + "".join(f"<li>{html_escape(x)}</li>" for x in (summary or ["暂无"] ))
        + '</ul></div><div><h3>账户级摘要</h3><ul>'
        + "".join(f"<li>{html_escape(x)}</li>" for x in (account_position[:8] or ["暂无"] ))
        + '</ul></div></div><div class="grid"><div><h3>空仓参考</h3><ul>'
        + "".join(f"<li>{html_escape(x)}</li>" for x in (empty_position[:6] or ["暂无"]))
        + '</ul></div><div><h3>持仓参考</h3><ul>'
        + "".join(f"<li>{html_escape(x)}</li>" for x in (holdings[:6] or ["暂无"]))
        + f'</ul></div></div><p class="sub"><a href="{html_escape(relative_report_href(REPORTS_DIR / "advice" / f"position_advice_{as_of}.md"))}">查看完整空仓/持仓建议</a> | <a href="{html_escape(relative_report_href(REPORTS_DIR / "advice" / f"account_position_advice_{as_of}.md"))}">查看账户级仓位建议</a></p></section>'
    )


def write_dashboard_html(
    as_of: str,
    market: dict[str, Any],
    sector_source: pd.DataFrame,
    leaders: pd.DataFrame,
    stocks: pd.DataFrame,
    decisions: pd.DataFrame,
    quotes: pd.DataFrame,
) -> None:
    quote_map = quotes.set_index("ts_code").to_dict("index") if not quotes.empty else {}
    decision_map = decisions.set_index("ts_code").to_dict("index") if not decisions.empty else {}
    sector_rows_html: list[str] = []
    for _, row in top_rows(sector_source, 8, ["sector_score", "score"]).iterrows():
        code = str(row.get("index_code", row.get("sector_code", "-")))
        sector_stocks = stocks[stocks["sector_code"].astype(str) == code].copy() if "sector_code" in stocks.columns else pd.DataFrame()
        cycle = sector_cycle_for_row(row, sector_stocks)
        support_text = "；".join(cycle.get("support_evidence", [])[:1]) or "-"
        oppose_text = "；".join(cycle.get("oppose_evidence", [])[:1]) or "-"
        sector_rows_html.append(
            "<tr>"
            f"<td><a href=\"{detail_href('sector', code)}\">{html_escape(clean_text(row.get('industry_name', row.get('sector_name', '-'))))}</a></td>"
            f"<td>{html_escape(code)}</td>"
            f"<td>{html_escape(fmt(row.get('score', row.get('sector_score'))))}</td>"
            f"<td>{html_escape(clean_text(row.get('grade', row.get('sector_grade', '-'))))}</td>"
            f"<td>{html_escape(cycle.get('main_label', '-'))}<br>"
            f"<span class='sub'>辅助：{html_escape(labels_to_text(cycle.get('aux_labels', [])))} / 置信度：{html_escape(cycle.get('confidence', '-'))}</span><br>"
            f"<span class='sub'>空仓：{html_escape(cycle.get('empty_advice', '-'))}</span><br>"
            f"<span class='sub'>持仓：{html_escape(cycle.get('holding_advice', '-'))}</span><br>"
            f"<span class='sub'>不能盯盘：{html_escape(cycle.get('no_watch_advice', '-'))} / 最大仓位：{html_escape(cycle.get('max_position', '-'))}</span><br>"
            f"<span class='sub'>支持：{html_escape(support_text)}</span><br>"
            f"<span class='sub'>反对：{html_escape(oppose_text)}</span></td>"
            f"<td>{html_escape(pct_fmt((row.get('equal_return') or row.get('return_used')) * 100 if pd.notna(row.get('equal_return') or row.get('return_used')) else None))}</td>"
            f"<td>{html_escape(pct_fmt((row.get('weighted_return') or row.get('return_used')) * 100 if pd.notna(row.get('weighted_return') or row.get('return_used')) else None))}</td>"
            "</tr>"
        )
    leader_rows_html: list[str] = []
    for _, row in top_rows(leaders, 8, ["score"]).iterrows():
        ts_code = str(row.get("ts_code", "-"))
        q = quote_map.get(ts_code, {})
        leader_rows_html.append(
            "<tr>"
            f"<td><a href=\"{detail_href('stock', ts_code)}\">{html_escape(clean_text(row.get('name', '-')))}</a></td>"
            f"<td>{html_escape(ts_code)}</td>"
            f"<td>{html_escape(clean_text(row.get('sector_name', '-')))}</td>"
            f"<td>{html_escape(fmt(row.get('score')))}</td>"
            f"<td>{html_escape(fmt(q.get('close')) if q else '-')}</td>"
            f"<td>{html_escape(pct_fmt(q.get('pct_chg')) if q else '-')}</td>"
            "</tr>"
        )
    merged = stocks.merge(
        decisions[["ts_code", "final_decision", "current_stage"]]
        if not decisions.empty and "ts_code" in decisions.columns
        else pd.DataFrame(columns=["ts_code", "final_decision", "current_stage"]),
        on="ts_code",
        how="left",
    )
    store_rows_html: list[str] = []
    for _, row in top_rows(merged, 12, ["stock_score", "leader_score"]).iterrows():
        ts_code = str(row.get("ts_code", "-"))
        q = quote_map.get(ts_code, {})
        decision = decision_map.get(ts_code, {})
        cycle = sector_cycle_for_code(str(row.get("sector_code", "")), sector_source, stocks)
        exec_decision = execution_for_stock_row(row, decision, cycle, q)
        role = exec_decision.get("stock_role", {})
        note = recommendation_text(
            str(row.get("market_grade", "-")),
            str(row.get("sector_grade", "-")),
            str(row.get("final_decision", row.get("execution_status", "-"))),
            q,
            split_cn_text(row.get("advantages")),
            split_cn_text(row.get("basic_risk")),
        )
        store_rows_html.append(
            "<tr>"
            f"<td><a href=\"{detail_href('stock', ts_code)}\">{html_escape(clean_text(row.get('name', '-')))}</a></td>"
            f"<td>{html_escape(ts_code)}</td>"
            f"<td>{html_escape(clean_text(row.get('sector_name', '-')))}</td>"
            f"<td>{html_escape(fmt(row.get('stock_score')))}</td>"
            f"<td>{html_escape(fmt(row.get('leader_score')))}</td>"
            f"<td>{html_escape(fmt(q.get('close')) if q else '-')}</td>"
            f"<td>{html_escape(pct_fmt(q.get('pct_chg')) if q else '-')}</td>"
            f"<td>{html_escape(clean_text(row.get('final_decision', row.get('execution_status', '-'))))}</td>"
            f"<td>{html_escape(role.get('role', '-'))}<br><span class='sub'>{html_escape(role.get('role_name', '-'))} / {html_escape(role.get('confidence', '-'))}</span></td>"
            f"<td>{html_escape(exec_decision.get('final_label', '-'))}</td>"
            f"<td>{html_escape('是' if exec_decision.get('allow_buy') else '否')}</td>"
            f"<td>{html_escape(str(exec_decision.get('max_position_pct', 0)))}%</td>"
            f"<td>{html_escape(exec_decision.get('sector_cycle_text', '-'))}<br><span class='sub'>置信度：{html_escape(exec_decision.get('sector_confidence', '-'))}</span></td>"
            f"<td>{html_escape('；'.join(exec_decision.get('downgrade_reasons', [])[:2]) or '-')}</td>"
            f"<td>{html_escape(note)}<br><span class='sub'>{html_escape(stock_role_brief(role))}</span><br><span class='sub'>{html_escape(execution_brief(exec_decision))}</span></td>"
            "</tr>"
        )
    market_grade = clean_text(market.get("market_score", {}).get("grade", "-"))
    progress = project_progress_payload(as_of)
    html = [
        style_block(f"最新市场决策看板 {as_of}"),
        '<section class="panel"><div class="hero">',
        f"<div><h1>最新市场决策看板</h1><div class=\"sub\">日期 {html_escape(as_of)} | 当前大盘天气 {html_escape(market_grade)} | 页面数据均可向下点击核验</div></div>",
        f"<div class=\"badge\">{html_escape(market_grade)}</div>",
        "</div>",
        f'<div class="metrics">{render_market_cards(market)}</div>',
        "</section>",
        render_progress_panel(progress),
        '<div class="grid">',
        '<section class="panel"><h2>优势街区</h2><p>点击板块可查看街区明细、龙头候选和个股候选。</p>'
        + render_table(["板块", "代码", "街区分", "级别", "板块周期", "等权收益", "加权收益"], sector_rows_html)
        + "</section>",
        '<section class="panel"><h2>龙头候选</h2><p>点击个股可查看最新价、涨跌幅、成交额、换手率和完整打分过程。</p>'
        + render_table(["名称", "代码", "街区", "龙头分", "最新价", "涨跌幅"], leader_rows_html)
        + "</section></div>",
        '<section class="panel"><h2>个股候选</h2><p>这里只放可验证字段和推荐说明，不写当前无法核实的数据。</p>'
        + render_table(["名称", "代码", "街区", "个股分", "龙头分", "最新价", "涨跌幅", "原始状态", "新角色", "最终执行标签", "允许买", "最大仓位", "板块周期", "降级原因", "推荐说明"], store_rows_html)
        + "</section>",
        '<div class="grid">'
        + render_regime_panel(as_of)
        + render_alert_panel(as_of)
        + "</div>",
        render_advice_panel(as_of),
        '<section class="panel"><h2>当前边界说明</h2><ul>'
        "<li>已接入可验证数据：最新价、涨跌幅、成交额、换手率、量比、流通市值、板块收益、市场宽度。</li>"
        "<li>当前 DSA 仍是参考层，不是主生产链路；现在主链路是本地评分系统加 Tushare 数据。</li>"
        "<li>当前未接入真实资金净流入主表，因此不展示无法本地核验的资金字段。</li>"
        "<li>政策面、公司公告、事件催化、飞书/企业微信定时推送、远程互动仍在继续建设。</li>"
        "</ul></section>",
        close_html(),
    ]
    HTML_PATH.write_text("".join(html), encoding="utf-8")


def write_outputs(
    as_of: str,
    market: dict[str, Any],
    sectors: pd.DataFrame,
    leaders: pd.DataFrame,
    stocks: pd.DataFrame,
    decisions: pd.DataFrame,
) -> dict[str, str]:
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    quotes = read_sqlite_quotes(as_of)
    sector_source = pd.DataFrame(market.get("sector_rankings", []))
    if sector_source.empty:
        sector_source = sectors.copy()
    build_sector_detail_pages(as_of, sector_source, leaders, stocks, decisions, quotes)
    build_stock_detail_pages(as_of, sector_source, stocks, leaders, decisions, quotes)
    write_markdown_report(as_of, market, sector_source, leaders, stocks, decisions, quotes)
    write_dashboard_html(as_of, market, sector_source, leaders, stocks, decisions, quotes)
    payload = {
        "as_of_date": as_of,
        "dashboard": str(HTML_PATH),
        "report": str(REPORT_PATH),
        "detail_dir": str(DETAIL_DIR),
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"markdown": str(REPORT_PATH), "json": str(JSON_PATH), "html": str(HTML_PATH), "details": str(DETAIL_DIR)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build latest market decision dashboard and detail pages")
    parser.add_argument("--as-of", dest="as_of", default="", help="Target date in YYYYMMDD")
    args = parser.parse_args(argv)
    as_of = pick_latest_date(args.as_of or None)
    market, sectors, leaders, stocks, decisions = load_payload(as_of)
    paths = write_outputs(as_of, market, sectors, leaders, stocks, decisions)
    print(json.dumps({"as_of_date": as_of, **paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
