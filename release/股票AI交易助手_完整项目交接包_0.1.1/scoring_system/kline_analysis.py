from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from scoring_system.project_paths import database_path


ROOT = Path(__file__).resolve().parents[1]
SQLITE_PATH = database_path(ROOT)
SCORES_DIR = ROOT / "data" / "processed" / "scores"
REPORT_DIR = ROOT / "reports" / "kline"


def latest_date() -> str:
    dates: list[str] = []
    for path in SCORES_DIR.glob("stock_scores_*.csv"):
        dates.extend([p for p in path.stem.split("_") if p.isdigit() and len(p) == 8])
    if not dates:
        raise FileNotFoundError("no stock score files")
    return sorted(set(dates))[-1]


def load_candidates(as_of: str, limit: int) -> pd.DataFrame:
    path = SCORES_DIR / f"stock_scores_{as_of}.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"ts_code": "string", "sector_code": "string"})
    sort_cols = [c for c in ["stock_score", "leader_score"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=False)
    return df.head(limit).copy()


def read_bars(ts_code: str, as_of: str, days: int = 60) -> pd.DataFrame:
    with sqlite3.connect(SQLITE_PATH) as conn:
        df = pd.read_sql_query(
            """
            SELECT d.ts_code, d.trade_date, d.open, d.high, d.low, d.close, d.pre_close,
                   d.pct_chg, d.vol, d.amount_yuan,
                   b.turnover_rate, b.volume_ratio
            FROM daily d
            LEFT JOIN daily_basic b
              ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            WHERE d.ts_code = ? AND d.trade_date <= ?
            ORDER BY d.trade_date DESC
            LIMIT ?
            """,
            conn,
            params=(ts_code, as_of, days),
        )
    if df.empty:
        return df
    df = df.sort_values("trade_date").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount_yuan", "turnover_rate", "volume_ratio"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["amount_ma5"] = df["amount_yuan"].rolling(5).mean()
    return df


def fmt(v: Any, digits: int = 2) -> str:
    if v is None or pd.isna(v):
        return "-"
    if isinstance(v, (int, float)):
        return f"{float(v):.{digits}f}"
    return str(v)


def pct(v: Any) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{float(v):.2f}%"


def fnum(value: Any, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    return float(value)


def classify_kline(bars: pd.DataFrame) -> dict[str, Any]:
    if bars.empty:
        return {"state": "数据缺失", "reason": "没有K线数据"}
    last = bars.iloc[-1]
    prev = bars.iloc[-2] if len(bars) >= 2 else last
    prior = bars.iloc[-6:-1] if len(bars) >= 6 else bars.iloc[:-1]
    open_price = fnum(last["open"])
    high = fnum(last["high"])
    low = fnum(last["low"])
    close = fnum(last["close"])
    prev_close = fnum(prev["close"])
    body = abs(close - open_price)
    full = max(high - low, 1e-9)
    upper_shadow = high - max(open_price, close)
    lower_shadow = min(open_price, close) - low
    body_ratio = body / full
    upper_ratio = upper_shadow / full
    lower_ratio = lower_shadow / full
    amount_ratio = float(last["amount_yuan"] / last["amount_ma5"]) if pd.notna(last.get("amount_ma5")) and last["amount_ma5"] else None
    ma5 = float(last["ma5"]) if pd.notna(last.get("ma5")) else None
    ma10 = float(last["ma10"]) if pd.notna(last.get("ma10")) else None
    ma20 = float(last["ma20"]) if pd.notna(last.get("ma20")) else None
    pct_chg = float(last["pct_chg"]) if pd.notna(last.get("pct_chg")) else 0.0
    prior_low = float(prior["low"].min()) if not prior.empty else None
    prior_high = float(prior["high"].max()) if not prior.empty else None
    two_day_return = None
    three_day_return = None
    if len(bars) >= 3:
        two_day_base = fnum(bars.iloc[-3]["close"])
        if two_day_base:
            two_day_return = close / two_day_base - 1
    if len(bars) >= 4:
        three_day_base = fnum(bars.iloc[-4]["close"])
        if three_day_base:
            three_day_return = close / three_day_base - 1

    tags: list[str] = []
    risks: list[str] = []
    watch: list[str] = []
    support_score = 0
    low_absorb_score = 0

    if ma5 and ma10 and ma20 and close > ma5 > ma10 > ma20:
        tags.append("多头排列")
    if ma20 and close < ma20:
        risks.append("跌破20日均线")
    if upper_ratio >= 0.45:
        risks.append("长上影，冲高回落压力")
    if lower_ratio >= 0.45:
        tags.append("长下影，有承接迹象")
        support_score += 2
    if pct_chg <= -3 and amount_ratio and amount_ratio >= 1.5:
        risks.append("放量下跌")
    if pct_chg > 0 and amount_ratio is not None and amount_ratio < 0.8:
        tags.append("缩量反弹")
    if body_ratio <= 0.2:
        tags.append("小实体，方向未决")
    if pct_chg >= 5:
        tags.append("强势长阳或加速")
    if pct_chg <= -5:
        risks.append("大阴线或快速杀跌")
    if close >= open_price and lower_ratio >= 0.3:
        tags.append("收回开盘价，盘中承接较明显")
        support_score += 3
    elif close < open_price and lower_ratio >= 0.3:
        tags.append("有下影但未收回开盘价")
        support_score += 1
    if close >= prev_close:
        tags.append("收回前一日收盘价")
        support_score += 3
    elif pct_chg < 0:
        risks.append("未收回前一日收盘价")
    if prior_low is not None and low < prior_low and close > prior_low:
        tags.append("跌破近5日低点后收回")
        support_score += 2
    elif prior_low is not None and close < prior_low:
        risks.append("收盘仍低于近5日低点")
    if amount_ratio is not None:
        if 0.8 <= amount_ratio <= 1.3 and lower_ratio >= 0.3:
            tags.append("成交温和，承接不属于明显放量硬拉")
            support_score += 1
        elif amount_ratio < 0.8 and pct_chg < 0:
            risks.append("缩量下跌，仍需次日确认是否止跌")
        elif amount_ratio >= 1.5 and pct_chg < 0:
            risks.append("放量杀跌，承接质量偏低")
    if two_day_return is not None and two_day_return <= -0.08:
        risks.append(f"两日跌幅约 {two_day_return * 100:.2f}%，短线惯性风险高")
    if three_day_return is not None and three_day_return <= -0.12:
        risks.append(f"三日跌幅约 {three_day_return * 100:.2f}%，不宜把第一次反抽当反转")

    if support_score >= 7 and not any("放量杀跌" in r or "跌破20日" in r for r in risks):
        support_state = "分歧承接较强"
        low_absorb_score = 75
        low_absorb_view = "可以进入重点观察；若板块同步修复且次日不破低点，低吸条件开始接近。"
    elif support_score >= 4:
        support_state = "有承接但未确认"
        low_absorb_score = 55
        low_absorb_view = "只能算试探性承接，需要次日收回关键价位或板块同步止跌。"
    elif support_score >= 2:
        support_state = "弱承接"
        low_absorb_score = 40
        low_absorb_view = "有一点下影或修复痕迹，但不足以支持空仓直接低吸。"
    else:
        support_state = "未见有效承接"
        low_absorb_score = 25
        low_absorb_view = "还在释放风险，空仓应等待更清晰的止跌确认。"
    if any("两日跌幅" in r or "三日跌幅" in r or "收盘仍低于近5日低点" in r for r in risks):
        low_absorb_score = min(low_absorb_score, 45)
    if ma20 and close < ma20:
        low_absorb_score = min(low_absorb_score, 35)

    if risks and any("放量下跌" in r or "跌破" in r for r in risks):
        state = "转弱观察"
        view = "短线先看修复力度；若次日不能收回关键均线，容易从分歧转向退潮。"
    elif support_state == "分歧承接较强":
        state = "分歧承接"
        view = low_absorb_view
    elif "多头排列" in tags and not risks:
        state = "趋势延续"
        view = "结构仍偏强，但若涨幅过快，需要等回踩均线后的承接。"
    elif "长下影，有承接迹象" in tags:
        state = "分歧修复"
        view = "盘中有承接，后续重点看成交是否温和、收盘是否继续站回短均线。"
    elif "缩量反弹" in tags:
        state = "弱修复"
        view = "反弹力度需要确认，若没有放量承接，容易只是技术性修复。"
    else:
        state = "中性观察"
        view = "单根K线信号不够强，需要结合板块状态和次日确认。"

    if ma5:
        watch.append(f"观察是否站稳5日均线 {fmt(ma5)}")
    if ma10:
        watch.append(f"观察10日均线 {fmt(ma10)} 是否形成支撑")
    if ma20:
        watch.append(f"20日均线 {fmt(ma20)} 是中短期风险线")

    return {
        "trade_date": str(last["trade_date"]),
        "close": close,
        "pct_chg": pct_chg,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "amount_ratio": amount_ratio,
        "body_ratio": body_ratio,
        "upper_shadow_ratio": upper_ratio,
        "lower_shadow_ratio": lower_ratio,
        "support_score": support_score,
        "support_state": support_state,
        "low_absorb_score": low_absorb_score,
        "low_absorb_view": low_absorb_view,
        "two_day_return": two_day_return,
        "three_day_return": three_day_return,
        "prior_5d_low": prior_low,
        "prior_5d_high": prior_high,
        "state": state,
        "tags": tags,
        "risks": risks,
        "view": view,
        "watch": watch,
        "prev_close": prev_close,
    }


def candle_svg(bars: pd.DataFrame, width: int = 900, height: int = 360) -> str:
    if bars.empty:
        return "<svg></svg>"
    data = bars.tail(40).copy()
    hi = float(data["high"].max())
    lo = float(data["low"].min())
    pad = 28
    plot_h = height - pad * 2
    step = (width - pad * 2) / max(len(data), 1)

    def y(price: float) -> float:
        return pad + (hi - price) / max(hi - lo, 1e-9) * plot_h

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" xmlns="http://www.w3.org/2000/svg">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{pad}" y="20" fill="#5f6b7a" font-size="13">近40个交易日K线，红涨绿跌，含5/10/20日均线</text>',
        f'<line x1="{pad}" y1="{y(hi)}" x2="{width-pad}" y2="{y(hi)}" stroke="#e5eaf2"/>',
        f'<line x1="{pad}" y1="{y(lo)}" x2="{width-pad}" y2="{y(lo)}" stroke="#e5eaf2"/>',
        f'<text x="{width-pad-80}" y="{y(hi)+12}" fill="#6b7280" font-size="12">{fmt(hi)}</text>',
        f'<text x="{width-pad-80}" y="{y(lo)-4}" fill="#6b7280" font-size="12">{fmt(lo)}</text>',
    ]
    ma_paths: dict[str, list[str]] = {"ma5": [], "ma10": [], "ma20": []}
    for i, row in data.reset_index(drop=True).iterrows():
        x = pad + i * step + step / 2
        open_y, close_y = y(float(row["open"])), y(float(row["close"]))
        high_y, low_y = y(float(row["high"])), y(float(row["low"]))
        up = float(row["close"]) >= float(row["open"])
        color = "#d93f3f" if up else "#178b55"
        body_top = min(open_y, close_y)
        body_h = max(abs(open_y - close_y), 2)
        body_w = max(step * 0.58, 3)
        parts.append(f'<line x1="{x:.2f}" y1="{high_y:.2f}" x2="{x:.2f}" y2="{low_y:.2f}" stroke="{color}" stroke-width="1.2"/>')
        parts.append(f'<rect x="{x-body_w/2:.2f}" y="{body_top:.2f}" width="{body_w:.2f}" height="{body_h:.2f}" fill="{color}" opacity="0.9"/>')
        for ma in ma_paths:
            if pd.notna(row.get(ma)):
                ma_paths[ma].append(f"{x:.2f},{y(float(row[ma])):.2f}")
    colors = {"ma5": "#f59e0b", "ma10": "#2563eb", "ma20": "#7c3aed"}
    for ma, pts in ma_paths.items():
        if len(pts) >= 2:
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{colors[ma]}" stroke-width="1.6"/>')
    parts.append("</svg>")
    return "".join(parts)


def html_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ margin:0; font-family:"Segoe UI","Microsoft YaHei",sans-serif; background:#f5f7fb; color:#18212f; }}
    .page {{ max-width:1180px; margin:0 auto; padding:24px; }}
    .panel {{ background:#fff; border:1px solid #d8dfeb; border-radius:8px; padding:18px; margin-bottom:16px; }}
    h1,h2 {{ margin:0 0 12px; }}
    p,li {{ color:#5f6b7a; line-height:1.7; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th,td {{ text-align:left; border-bottom:1px solid #d8dfeb; padding:10px 8px; vertical-align:top; }}
    th {{ background:#f8fafc; color:#5f6b7a; }}
    a {{ color:#2363eb; text-decoration:none; }}
  </style>
</head>
<body><div class="page">{body}</div></body></html>"""


def build_pages(as_of: str, limit: int) -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    candidates = load_candidates(as_of, limit)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[dict[str, Any]] = []
    table_rows: list[str] = []
    for _, stock in candidates.iterrows():
        ts_code = str(stock["ts_code"])
        name = str(stock.get("name", ts_code))
        bars = read_bars(ts_code, as_of)
        analysis = classify_kline(bars)
        detail_name = f"kline_{ts_code}.html"
        detail_path = REPORT_DIR / detail_name
        body = [
            '<section class="panel">',
            f"<h1>{name} K线观察</h1>",
            f"<p>代码：{ts_code}；数据交易日：{analysis.get('trade_date', as_of)}；生成时间：{generated_at}</p>",
            f"<p>当前状态：{analysis['state']}；最新价：{fmt(analysis.get('close'))}；涨跌幅：{pct(analysis.get('pct_chg'))}</p>",
            "</section>",
            '<section class="panel">',
            candle_svg(bars),
            "</section>",
            '<section class="panel"><h2>分析说明</h2>',
            f"<p>{analysis['view']}</p>",
            "<ul>",
            "".join(f"<li>{x}</li>" for x in analysis.get("tags", []) or ["未出现强形态标签"]),
            "".join(f"<li>风险：{x}</li>" for x in analysis.get("risks", []) or []),
            "".join(f"<li>{x}</li>" for x in analysis.get("watch", []) or []),
            "</ul></section>",
            '<section class="panel"><h2>承接与低吸判断</h2>',
            f"<p>承接状态：{analysis.get('support_state', '-')}；低吸评分：{fmt(analysis.get('low_absorb_score'), 0)} / 100。</p>",
            f"<p>{analysis.get('low_absorb_view', '')}</p>",
            "</section>",
            '<section class="panel"><h2>核验字段</h2>',
            f"<p>MA5：{fmt(analysis.get('ma5'))}；MA10：{fmt(analysis.get('ma10'))}；MA20：{fmt(analysis.get('ma20'))}；成交额相对5日均值：{fmt(analysis.get('amount_ratio'))}</p>",
            "</section>",
        ]
        detail_path.write_text(html_page(f"{name} K线观察", "".join(body)), encoding="utf-8")
        row = {"ts_code": ts_code, "name": name, **analysis, "detail": str(detail_path)}
        rows.append(row)
        table_rows.append(
            "<tr>"
            f'<td><a href="{detail_name}">{name}</a></td>'
            f"<td>{ts_code}</td>"
            f"<td>{analysis.get('trade_date', as_of)}</td>"
            f"<td>{fmt(analysis.get('close'))}</td>"
            f"<td>{pct(analysis.get('pct_chg'))}</td>"
            f"<td>{analysis['state']}</td>"
            f"<td>{analysis.get('support_state', '-')}；{analysis['view']}</td>"
            "</tr>"
        )
    overview_body = [
        '<section class="panel">',
        "<h1>K线观察总览</h1>",
        f"<p>数据交易日：{as_of}；生成时间：{generated_at}；样本：当前候选前 {limit} 只。</p>",
        "<p>方法：日K实体、上下影线、5/10/20日均线、成交额相对5日均值、涨跌幅与位置共同判断，并区分分歧承接、弱修复和继续转弱。</p>",
        "</section>",
        '<section class="panel"><table><thead><tr><th>名称</th><th>代码</th><th>数据日</th><th>最新价</th><th>涨跌幅</th><th>状态</th><th>说明</th></tr></thead><tbody>',
        "".join(table_rows),
        "</tbody></table></section>",
    ]
    overview = REPORT_DIR / f"kline_overview_{as_of}.html"
    overview.write_text(html_page("K线观察总览", "".join(overview_body)), encoding="utf-8")
    payload = {
        "as_of_date": as_of,
        "generated_at": generated_at,
        "overview": str(overview),
        "items": rows,
    }
    json_path = REPORT_DIR / f"kline_analysis_{as_of}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build K-line analysis pages")
    parser.add_argument("--as-of", default="")
    parser.add_argument("--limit", type=int, default=16)
    args = parser.parse_args(argv)
    as_of = args.as_of or latest_date()
    payload = build_pages(as_of, args.limit)
    print(json.dumps({"as_of_date": as_of, "overview": payload["overview"], "count": len(payload["items"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
