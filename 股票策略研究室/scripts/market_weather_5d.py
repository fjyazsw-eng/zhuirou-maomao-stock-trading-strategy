"""Build a 5-trading-day market weather report from Tushare daily data.

Rules:
- Tushare daily.amount is thousand CNY; use amount_units helpers only.
- Prefer local CSV files under data/raw.
- Only call Tushare daily when a local complete file is unavailable.
- Do not call trade_cal, stock_basic, daily_basic, or brokerage APIs.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from amount_units import tushare_amount_to_wanyi, tushare_amount_to_yi

REQUIRED_FIELDS = [
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
]
FIELDS = ",".join(REQUIRED_FIELDS)
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"


@dataclass
class QualityReport:
    date: str
    raw_rows: int
    valid_rows: int
    missing_values: int
    duplicate_codes: int
    duplicate_rows: int
    missing_fields: list[str]
    status: str


class DataQualityError(ValueError):
    pass


def raw_path(date: str) -> Path:
    return RAW_DIR / f"daily_{date}.csv"


def check_required_fields(df: pd.DataFrame) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in df.columns]
    if missing:
        raise DataQualityError("缺少必要字段: " + ",".join(missing))


def inspect_quality(df: pd.DataFrame, date: str) -> QualityReport:
    missing_fields = [field for field in REQUIRED_FIELDS if field not in df.columns]
    if missing_fields:
        return QualityReport(date, len(df), 0, 0, 0, 0, missing_fields, "字段缺失")
    raw_rows = len(df)
    valid = df.dropna(subset=REQUIRED_FIELDS).copy()
    return QualityReport(
        date=date,
        raw_rows=raw_rows,
        valid_rows=len(valid),
        missing_values=int(df[REQUIRED_FIELDS].isna().sum().sum()),
        duplicate_codes=int(df["ts_code"].duplicated().sum()),
        duplicate_rows=int(df.duplicated().sum()),
        missing_fields=[],
        status="正常" if len(valid) > 0 else "无有效行情",
    )


def is_complete_local_file(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        df = pd.read_csv(path)
    except Exception:
        return False
    try:
        check_required_fields(df)
    except DataQualityError:
        return False
    return len(df) > 0


def read_local_daily(date: str) -> pd.DataFrame | None:
    path = raw_path(date)
    if not is_complete_local_file(path):
        return None
    return pd.read_csv(path)


def fetch_daily_from_tushare(date: str, pro_api_factory: Callable[[], object] | None = None) -> pd.DataFrame:
    if pro_api_factory is None:
        import tushare as ts
        token = os.getenv("TUSHARE_TOKEN")
        if not token:
            raise RuntimeError("TUSHARE_TOKEN 不存在")
        pro = ts.pro_api(token)
    else:
        pro = pro_api_factory()
    return pro.daily(trade_date=date, fields=FIELDS)


def load_or_fetch_daily(
    date: str,
    fetcher: Callable[[str], pd.DataFrame] | None = None,
    sleep_seconds: float = 1.5,
) -> tuple[pd.DataFrame | None, str, QualityReport]:
    local = read_local_daily(date)
    if local is not None:
        return local, "本地CSV", inspect_quality(local, date)

    if fetcher is None:
        def fetcher(d: str) -> pd.DataFrame:
            return fetch_daily_from_tushare(d)

    time.sleep(sleep_seconds)
    df = fetcher(date)
    if len(df) > 0:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(raw_path(date), index=False, encoding="utf-8-sig")
    return df, "Tushare daily API", inspect_quality(df, date)


def recent_valid_daily_frames(
    analysis_date: str,
    needed: int = 5,
    max_natural_days: int = 12,
    fetcher: Callable[[str], pd.DataFrame] | None = None,
    sleep_seconds: float = 1.5,
) -> tuple[list[tuple[str, pd.DataFrame, str, QualityReport]], list[QualityReport]]:
    current = datetime.strptime(analysis_date, "%Y%m%d")
    valid: list[tuple[str, pd.DataFrame, str, QualityReport]] = []
    qualities: list[QualityReport] = []
    for offset in range(max_natural_days):
        date = (current - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df, source, quality = load_or_fetch_daily(date, fetcher=fetcher, sleep_seconds=sleep_seconds)
        except Exception as exc:
            quality = QualityReport(date, 0, 0, 0, 0, 0, [], f"程序异常: {exc}")
            qualities.append(quality)
            continue
        qualities.append(quality)
        if df is None or len(df) == 0:
            continue
        if quality.missing_fields or quality.valid_rows == 0:
            continue
        valid.append((date, df.dropna(subset=REQUIRED_FIELDS).copy(), source, quality))
        if len(valid) >= needed:
            break
    return valid, qualities


def daily_market_stats(date: str, df: pd.DataFrame) -> dict[str, float | int | str]:
    check_required_fields(df)
    total = len(df)
    up = int((df["pct_chg"] > 0).sum())
    down = int((df["pct_chg"] < 0).sum())
    flat = int((df["pct_chg"] == 0).sum())
    top_amount = df.sort_values("amount", ascending=False).head(20)
    amount_sum = float(df["amount"].sum())
    return {
        "trade_date": date,
        "stock_count": total,
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "up_ratio": up / total if total else 0.0,
        "pct_chg_mean": float(df["pct_chg"].mean()) if total else 0.0,
        "pct_chg_median": float(df["pct_chg"].median()) if total else 0.0,
        "up_ge_5_count": int((df["pct_chg"] >= 5).sum()),
        "down_le_neg5_count": int((df["pct_chg"] <= -5).sum()),
        "up_ge_9_8_count": int((df["pct_chg"] >= 9.8).sum()),
        "down_le_neg9_8_count": int((df["pct_chg"] <= -9.8).sum()),
        "amount_yi": tushare_amount_to_yi(amount_sum),
        "amount_wanyi": tushare_amount_to_wanyi(amount_sum),
        "top20_amount_pct_chg_mean": float(top_amount["pct_chg"].mean()) if len(top_amount) else 0.0,
        "top20_up_count": int((top_amount["pct_chg"] > 0).sum()),
        "top20_down_count": int((top_amount["pct_chg"] < 0).sum()),
        "top20_flat_count": int((top_amount["pct_chg"] == 0).sum()),
    }


def score_weather(today: dict[str, float | int | str]) -> tuple[int, dict[str, dict[str, float | str]]]:
    up_ratio = float(today["up_ratio"])
    median = float(today["pct_chg_median"])
    strong = int(today["up_ge_5_count"])
    weak = int(today["down_le_neg5_count"])
    top_mean = float(today["top20_amount_pct_chg_mean"])

    width = max(0.0, min(40.0, up_ratio * 40.0))
    median_score = max(0.0, min(20.0, 10.0 + median * 5.0))
    extreme_raw = 10.0 + (strong - weak) / max(strong + weak, 1) * 10.0
    extreme = max(0.0, min(20.0, extreme_raw))
    core = max(0.0, min(20.0, 10.0 + top_mean * 4.0))
    total = int(round(max(0.0, min(100.0, width + median_score + extreme + core))))
    details = {
        "market_width": {"score": width, "process": f"上涨占比{up_ratio:.2%} * 40 = {width:.2f}"},
        "median_change": {"score": median_score, "process": f"10 + 中位数涨跌幅{median:.2f} * 5 = {median_score:.2f}"},
        "extreme_structure": {"score": extreme, "process": f"10 + (>=5%数量{strong} - <=-5%数量{weak}) / max(二者合计,1) * 10 = {extreme:.2f}"},
        "amount_core": {"score": core, "process": f"10 + 成交额前20平均涨跌幅{top_mean:.2f} * 4 = {core:.2f}"},
    }
    return total, details


def determine_stage(stats: list[dict[str, float | int | str]]) -> tuple[str, list[str]]:
    today = stats[0]
    prev = stats[1] if len(stats) > 1 else stats[0]
    avg_amount = sum(float(s["amount_yi"]) for s in stats) / max(len(stats), 1)
    amount_dev = (float(today["amount_yi"]) - avg_amount) / avg_amount if avg_amount else 0.0
    up_ratio_change = float(today["up_ratio"]) - float(prev["up_ratio"])
    median_change = float(today["pct_chg_median"]) - float(prev["pct_chg_median"])
    top_mean = float(today["top20_amount_pct_chg_mean"])
    strong = int(today["up_ge_5_count"])
    weak = int(today["down_le_neg5_count"])

    reasons = [
        f"今日成交额相对5日均值偏离{amount_dev:.2%}",
        f"上涨占比较前一交易日变化{up_ratio_change:.2%}",
        f"涨跌中位数较前一交易日变化{median_change:.2f}个百分点",
        f">=5%股票{strong}只，<=-5%股票{weak}只",
        f"成交额前20平均涨跌幅{top_mean:.2f}%",
    ]
    if float(today["up_ratio"]) >= 0.65 and float(today["pct_chg_median"]) > 0.5 and top_mean > 0:
        return "持续强势", reasons
    if amount_dev > 0.15 and strong > weak * 2 and top_mean > 1:
        return "加速", reasons
    if float(today["up_ratio"]) > 0.55 and median_change > 0:
        return "转强", reasons
    if amount_dev > 0.1 and strong > 150 and weak > 80:
        return "高位分歧", reasons
    if float(today["up_ratio"]) > 0.5 and float(today["pct_chg_median"]) <= 0.2:
        return "弱势修复", reasons
    if float(today["up_ratio"]) < 0.35 and weak > strong:
        return "退潮", reasons
    if float(today["up_ratio"]) < 0.45 and float(today["pct_chg_median"]) < 0:
        return "持续弱势", reasons
    return "弱势修复", reasons


def trend_summary(stats: list[dict[str, float | int | str]]) -> dict[str, float | int | str]:
    today = stats[0]
    prev = stats[1] if len(stats) > 1 else stats[0]
    avg_amount = sum(float(s["amount_yi"]) for s in stats) / max(len(stats), 1)
    prev_amount = float(prev["amount_yi"])
    today_amount = float(today["amount_yi"])
    return {
        "amount_change_yi": today_amount - prev_amount,
        "amount_change_ratio": (today_amount - prev_amount) / prev_amount if prev_amount else 0.0,
        "amount_vs_5d_avg_ratio": (today_amount - avg_amount) / avg_amount if avg_amount else 0.0,
        "up_ratio_change_5d": float(today["up_ratio"]) - float(stats[-1]["up_ratio"]),
        "median_change_5d": float(today["pct_chg_median"]) - float(stats[-1]["pct_chg_median"]),
        "up_ge_5_change_5d": int(today["up_ge_5_count"]) - int(stats[-1]["up_ge_5_count"]),
        "down_le_neg5_change_5d": int(today["down_le_neg5_count"]) - int(stats[-1]["down_le_neg5_count"]),
        "top20_mean_change_5d": float(today["top20_amount_pct_chg_mean"]) - float(stats[-1]["top20_amount_pct_chg_mean"]),
    }


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    """Render a small DataFrame as a Markdown table without optional deps."""
    columns = [str(col) for col in df.columns]
    rows = []
    rows.append("| " + " | ".join(columns) + " |")
    rows.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in df.itertuples(index=False, name=None):
        values = []
        for value in row:
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            else:
                values.append(str(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)

def write_outputs(analysis_date: str, stats: list[dict[str, float | int | str]], qualities: Iterable[QualityReport]) -> tuple[Path, Path, int, str]:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    processed_path = PROCESSED_DIR / f"market_weather_5d_{analysis_date}.csv"
    report_path = REPORTS_DIR / f"market_weather_5d_{analysis_date}.md"
    df = pd.DataFrame(stats)
    df.to_csv(processed_path, index=False, encoding="utf-8-sig")

    score, score_details = score_weather(stats[0])
    stage, reasons = determine_stage(stats)
    trends = trend_summary(stats)
    conclusion = f"截至{analysis_date}，市场天气评分{score}/100，阶段更接近“{stage}”。"

    lines = [
        "# 最近5个交易日市场天气分析",
        "",
        "## 1. 一句话天气结论",
        conclusion,
        "",
        "## 2. 今日天气评分及分项",
        f"总分：{score}/100",
    ]
    for name, detail in score_details.items():
        lines.append(f"- {name}: {detail['score']:.2f}；{detail['process']}")
    lines += [
        "",
        "## 3. 最近5个交易日核心数据表",
        dataframe_to_markdown(df),
        "",
        "## 4. 市场宽度趋势",
        f"上涨占比5日变化：{trends['up_ratio_change_5d']:.2%}。",
        "",
        "## 5. 成交额趋势",
        f"今日成交额较前一交易日变化：{trends['amount_change_yi']:.2f}亿元，变化率{trends['amount_change_ratio']:.2%}；相对5日均值偏离{trends['amount_vs_5d_avg_ratio']:.2%}。",
        "",
        "## 6. 强势股和大跌股变化",
        f">=5%股票数量5日变化：{trends['up_ge_5_change_5d']}；<=-5%股票数量5日变化：{trends['down_le_neg5_change_5d']}。",
        "",
        "## 7. 高成交额核心表现",
        f"成交额前20平均涨跌幅5日变化：{trends['top20_mean_change_5d']:.2f}个百分点。",
        "",
        "## 8. 当前市场阶段判断",
        f"阶段：{stage}",
    ]
    lines.extend([f"- {reason}" for reason in reasons])
    lines += [
        "",
        "## 9. 风险点",
        "- 仅使用Tushare daily日线数据，未包含盘中分时、涨停封单、炸板等高频结构。",
        "- 涨跌停数量使用pct_chg阈值近似统计，不等同于交易所逐笔涨跌停状态。",
        "",
        "## 10. 下一交易日观察条件",
        "- 观察成交额是否继续高于5日均值。",
        "- 观察上涨占比和涨跌中位数是否同步改善。",
        "- 观察成交额前20股票是否继续贡献正收益。",
        "",
        "## 11. 数据局限",
    ]
    for quality in qualities:
        lines.append(f"- {quality.date}: {quality.status}，原始行数{quality.raw_rows}，有效行数{quality.valid_rows}，空值{quality.missing_values}，重复代码{quality.duplicate_codes}，整行重复{quality.duplicate_rows}。")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return processed_path, report_path, score, conclusion


def run_analysis(analysis_date: str, fetcher: Callable[[str], pd.DataFrame] | None = None, sleep_seconds: float = 1.5) -> dict[str, object]:
    frames, qualities = recent_valid_daily_frames(analysis_date, fetcher=fetcher, sleep_seconds=sleep_seconds)
    if len(frames) < 5:
        raise RuntimeError(f"最近12个自然日内只找到{len(frames)}个有效交易日")
    stats = [daily_market_stats(date, df) for date, df, _source, _quality in frames]
    processed_path, report_path, score, conclusion = write_outputs(analysis_date, stats, qualities)
    return {
        "dates": [date for date, _df, _source, _quality in frames],
        "processed_path": processed_path,
        "report_path": report_path,
        "score": score,
        "conclusion": conclusion,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="20260630")
    args = parser.parse_args()
    result = run_analysis(args.date)
    print("最近5个有效交易日: " + ",".join(result["dates"]))
    print(f"输出CSV: {result['processed_path']}")
    print(f"输出报告: {result['report_path']}")
    print(f"一句话结论: {result['conclusion']}")
    print(f"天气评分: {result['score']}/100")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


