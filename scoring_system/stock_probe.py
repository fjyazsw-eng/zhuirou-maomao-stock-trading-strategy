from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scoring_system.kline_analysis import classify_kline, fmt, pct, read_bars


ROOT = Path(__file__).resolve().parents[1]
SQLITE_PATH = ROOT / "data" / "sqlite" / "market_120d.sqlite"
SCORES_DIR = ROOT / "data" / "processed" / "scores"
REPORT_DIR = ROOT / "reports" / "stock_probe"


def latest_score_date() -> str:
    dates: list[str] = []
    for path in SCORES_DIR.glob("sector_scores_*_calibrated.csv"):
        dates.extend([p for p in path.stem.split("_") if p.isdigit() and len(p) == 8])
    for path in SCORES_DIR.glob("stock_scores_*.csv"):
        dates.extend([p for p in path.stem.split("_") if p.isdigit() and len(p) == 8])
    if not dates:
        raise FileNotFoundError("没有找到评分文件")
    return sorted(set(dates))[-1]


def normalize_code(code: str) -> str:
    value = code.strip().upper()
    if "." in value:
        return value
    if value.startswith("6"):
        return f"{value}.SH"
    return f"{value}.SZ"


def secid(ts_code: str) -> str:
    symbol, exchange = ts_code.split(".")
    return ("1" if exchange == "SH" else "0") + "." + symbol


def read_sql(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with sqlite3.connect(SQLITE_PATH) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def stock_basic(ts_code: str) -> dict[str, Any]:
    df = read_sql("SELECT * FROM stock_basic WHERE ts_code = ?", (ts_code,))
    if df.empty:
        return {"ts_code": ts_code, "name": ts_code}
    return df.iloc[0].to_dict()


def latest_local_quote(ts_code: str, as_of: str) -> dict[str, Any]:
    df = read_sql(
        """
        SELECT d.ts_code, d.trade_date, d.open, d.high, d.low, d.close, d.pre_close,
               d.pct_chg, d.vol, d.amount_yuan,
               b.turnover_rate, b.volume_ratio, b.total_mv_yuan, b.circ_mv_yuan
        FROM daily d
        LEFT JOIN daily_basic b
          ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
        WHERE d.ts_code = ? AND d.trade_date <= ?
        ORDER BY d.trade_date DESC
        LIMIT 1
        """,
        (ts_code, as_of),
    )
    return {} if df.empty else df.iloc[0].to_dict()


def current_quote(ts_code: str, timeout: int = 8) -> dict[str, Any]:
    url = (
        "https://push2.eastmoney.com/api/qt/stock/get?"
        f"secid={secid(ts_code)}&fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f86,f116,f117,f168,f170"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    data = payload.get("data") or {}
    if not data:
        return {"ok": False, "error": "实时行情为空"}

    def scaled(field: str) -> float | None:
        value = data.get(field)
        if value in (None, "-", ""):
            return None
        return float(value) / 100

    ts = data.get("f86")
    snapshot_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts, (int, float)) else ""
    return {
        "ok": True,
        "source": "东方财富实时行情接口",
        "snapshot_time": snapshot_time,
        "price": scaled("f43"),
        "high": scaled("f44"),
        "low": scaled("f45"),
        "open": scaled("f46"),
        "pre_close": scaled("f60"),
        "pct_chg": scaled("f170"),
        "amount_yuan": data.get("f48"),
        "volume_ratio": scaled("f50"),
        "turnover_rate": scaled("f168"),
        "total_mv_yuan": data.get("f116"),
        "circ_mv_yuan": data.get("f117"),
    }


def sector_membership(ts_code: str) -> list[dict[str, Any]]:
    df = read_sql(
        """
        SELECT m.index_code, m.index_name, m.con_code, m.con_name, m.in_date, m.out_date, m.is_new,
               c.industry_name, c.level
        FROM index_member m
        LEFT JOIN index_classify c ON m.index_code = c.index_code
        WHERE m.con_code = ?
        ORDER BY CASE WHEN m.is_new = 'Y' THEN 0 ELSE 1 END, m.index_code
        """,
        (ts_code,),
    )
    return df.to_dict("records")


def read_scores(ts_code: str, as_of: str, memberships: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"stock": None, "leader": None, "sector": None}
    stock_path = SCORES_DIR / f"stock_scores_{as_of}.csv"
    leader_path = SCORES_DIR / f"leader_scores_{as_of}.csv"
    sector_path = SCORES_DIR / f"sector_scores_{as_of}_calibrated.csv"
    if stock_path.exists():
        stock = pd.read_csv(stock_path, dtype={"ts_code": "string"})
        hit = stock[stock["ts_code"].astype(str) == ts_code]
        if not hit.empty:
            result["stock"] = hit.iloc[0].to_dict()
    if leader_path.exists():
        leader = pd.read_csv(leader_path, dtype={"ts_code": "string"})
        hit = leader[leader["ts_code"].astype(str) == ts_code]
        if not hit.empty:
            result["leader"] = hit.iloc[0].to_dict()
    if sector_path.exists():
        sector = pd.read_csv(sector_path, dtype={"index_code": "string"})
        preferred = [m["index_code"] for m in memberships if m.get("is_new") == "Y"] or [m["index_code"] for m in memberships]
        hit = sector[sector["index_code"].astype(str).isin(preferred)]
        if not hit.empty:
            result["sector"] = hit.sort_values("score", ascending=False).iloc[0].to_dict()
    return result


def money_yi(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) / 1e8:.2f} 亿"


def low_absorb_conclusion(kline: dict[str, Any], sector: dict[str, Any] | None, stock_score: dict[str, Any] | None, live: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    score = float(kline.get("low_absorb_score") or 0)
    sector_score = float(sector.get("score")) if sector and not pd.isna(sector.get("score")) else None
    sector_grade = str(sector.get("grade", "")) if sector else "未进入板块评分"
    if sector_score is not None and sector_score < 40:
        score -= 25
        reasons.append(f"所属板块为 {sector_grade}，板块环境拖累低吸胜率")
    elif sector_score is not None and sector_score >= 70:
        score += 10
        reasons.append(f"所属板块为 {sector_grade}，板块环境支持观察")
    if stock_score is None:
        score -= 10
        reasons.append("未进入当前个股候选池，模型不把它列为优先机会")
    live_pct = live.get("pct_chg") if live.get("ok") else None
    if live_pct is not None and live_pct < -3:
        score -= 10
        reasons.append(f"实时跌幅 {live_pct:.2f}%，当下仍偏弱")
    if kline.get("support_state") in {"分歧承接较强", "有承接但未确认"}:
        reasons.append(f"K线层判断：{kline.get('support_state')}")
    else:
        reasons.append(f"K线层判断：{kline.get('support_state', '未见有效承接')}")
    if score >= 70:
        return "可以观察低吸条件，但仍需次日确认", reasons
    if score >= 50:
        return "只适合小心观察，不适合直接重仓低吸", reasons
    return "不适合空仓直接低吸", reasons


def build_probe(ts_code: str, as_of: str | None = None, with_live: bool = True) -> dict[str, Any]:
    as_of = as_of or latest_score_date()
    basic = stock_basic(ts_code)
    local_quote = latest_local_quote(ts_code, as_of)
    live = current_quote(ts_code) if with_live else {"ok": False, "error": "未请求实时行情"}
    memberships = sector_membership(ts_code)
    scores = read_scores(ts_code, as_of, memberships)
    bars = read_bars(ts_code, as_of, 60)
    kline = classify_kline(bars)
    conclusion, reasons = low_absorb_conclusion(kline, scores.get("sector"), scores.get("stock"), live)
    return {
        "ts_code": ts_code,
        "name": basic.get("name", ts_code),
        "as_of_date": as_of,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "basic": basic,
        "local_quote": local_quote,
        "live_quote": live,
        "memberships": memberships,
        "scores": scores,
        "kline": kline,
        "conclusion": conclusion,
        "reasons": reasons,
    }


def write_report(result: dict[str, Any]) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts_code = result["ts_code"]
    as_of = result["as_of_date"]
    json_path = REPORT_DIR / f"stock_probe_{ts_code}_{as_of}.json"
    md_path = REPORT_DIR / f"stock_probe_{ts_code}_{as_of}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    local = result.get("local_quote") or {}
    live = result.get("live_quote") or {}
    sector = (result.get("scores") or {}).get("sector") or {}
    stock = (result.get("scores") or {}).get("stock") or {}
    kline = result.get("kline") or {}
    lines = [
        f"# 单票体检：{result['name']} {ts_code}",
        "",
        f"- 本地数据日：{as_of}",
        f"- 报告生成时间：{result['generated_at']}",
        f"- 实时行情源：{live.get('source', '未获取')}",
        f"- 实时快照时间：{live.get('snapshot_time', '未获取')}",
        "",
        "## 当前结论",
        f"- {result['conclusion']}",
        *[f"- {x}" for x in result["reasons"]],
        "",
        "## 可核验行情",
        f"- 本地收盘：{fmt(local.get('close'))}，本地涨跌幅：{pct(local.get('pct_chg'))}，本地成交额：{money_yi(local.get('amount_yuan'))}",
        f"- 实时价格：{fmt(live.get('price'))}，实时涨跌幅：{pct(live.get('pct_chg'))}，实时成交额：{money_yi(live.get('amount_yuan'))}",
        f"- 实时最高/最低：{fmt(live.get('high'))} / {fmt(live.get('low'))}，实时换手率：{pct(live.get('turnover_rate'))}，量比：{fmt(live.get('volume_ratio'))}",
        "",
        "## 板块与模型位置",
        f"- 所属板块：{sector.get('industry_name', '未进入板块评分')} {sector.get('index_code', '')}",
        f"- 板块分：{fmt(sector.get('score'))}，板块级别：{sector.get('grade', '-')}",
        f"- 个股候选分：{fmt(stock.get('stock_score'))}，执行状态：{stock.get('execution_status', '未进入当前候选池')}",
        "",
        "## K线承接",
        f"- K线状态：{kline.get('state', '-')}",
        f"- 承接状态：{kline.get('support_state', '-')}",
        f"- 低吸评分：{fmt(kline.get('low_absorb_score'), 0)} / 100",
        f"- 说明：{kline.get('low_absorb_view', '-')}",
        f"- MA5 / MA10 / MA20：{fmt(kline.get('ma5'))} / {fmt(kline.get('ma10'))} / {fmt(kline.get('ma20'))}",
        f"- 成交额相对5日均值：{fmt(kline.get('amount_ratio'))}",
        "",
        "## 风险与观察条件",
        *[f"- 风险：{x}" for x in kline.get("risks", [])],
        *[f"- 观察：{x}" for x in kline.get("watch", [])],
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成单票体检报告")
    parser.add_argument("code", help="股票代码，如 300054 或 300054.SZ")
    parser.add_argument("--as-of", default="")
    parser.add_argument("--no-live", action="store_true")
    args = parser.parse_args(argv)
    result = build_probe(normalize_code(args.code), args.as_of or None, with_live=not args.no_live)
    paths = write_report(result)
    print(json.dumps({"ts_code": result["ts_code"], "name": result["name"], "conclusion": result["conclusion"], **paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
