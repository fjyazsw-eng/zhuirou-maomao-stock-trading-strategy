from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCORES_DIR = ROOT / "data" / "processed" / "scores"
REPORTS_DIR = ROOT / "reports" / "alerts"

TRACK_CODES = {
    "801081.SI": "半导体",
    "801086.SI": "电子化学品Ⅱ",
    "801084.SI": "光学光电子",
    "801083.SI": "元件",
    "801101.SI": "计算机设备",
    "801770.SI": "通信",
    "801750.SI": "计算机",
}

GRADE_ORDER = {
    "A级，强主线候选": 5,
    "B级，强势板块": 4,
    "C级，轮动或修复板块": 3,
    "D级，普通或转弱板块": 2,
    "E级，弱势或退潮板块": 1,
}


def latest_dates(limit: int = 5) -> list[str]:
    dates = []
    for path in SCORES_DIR.glob("sector_scores_*_calibrated.csv"):
        digits = [p for p in path.stem.split("_") if p.isdigit() and len(p) == 8]
        dates.extend(digits)
    return sorted(set(dates))[-limit:]


def read_sector_scores(as_of: str) -> pd.DataFrame:
    path = SCORES_DIR / f"sector_scores_{as_of}_calibrated.csv"
    return pd.read_csv(path, dtype={"index_code": "string"}) if path.exists() else pd.DataFrame()


def grade_rank(grade: str) -> int:
    return GRADE_ORDER.get(str(grade), 0)


def build_alerts(dates: list[str]) -> list[dict[str, Any]]:
    if len(dates) < 2:
        return []
    frames = []
    for d in dates:
        df = read_sector_scores(d)
        if df.empty:
            continue
        sub = df[df["index_code"].astype(str).isin(TRACK_CODES.keys())][["index_code", "industry_name", "score", "grade"]].copy()
        sub["trade_date"] = d
        frames.append(sub)
    if not frames:
        return []
    all_df = pd.concat(frames, ignore_index=True)
    alerts: list[dict[str, Any]] = []
    for code in TRACK_CODES:
        g = all_df[all_df["index_code"].astype(str) == code].sort_values("trade_date")
        if len(g) < 2:
            continue
        for i in range(1, len(g)):
            prev = g.iloc[i - 1]
            curr = g.iloc[i]
            prev_score = float(prev["score"])
            curr_score = float(curr["score"])
            prev_grade = str(prev["grade"])
            curr_grade = str(curr["grade"])
            score_drop = curr_score - prev_score
            grade_drop = grade_rank(curr_grade) - grade_rank(prev_grade)
            triggered = (
                score_drop <= -15
                or grade_drop <= -2
                or (prev_grade.startswith(("A", "B")) and curr_grade.startswith(("D", "E")))
                or curr_grade.startswith("E")
            )
            if triggered:
                alerts.append(
                    {
                        "index_code": code,
                        "industry_name": str(curr.get("industry_name") or TRACK_CODES[code]),
                        "prev_date": str(prev["trade_date"]),
                        "curr_date": str(curr["trade_date"]),
                        "prev_score": prev_score,
                        "curr_score": curr_score,
                        "score_change": score_drop,
                        "prev_grade": prev_grade,
                        "curr_grade": curr_grade,
                        "alert_level": "HIGH" if curr_grade.startswith("E") or score_drop <= -25 else "MEDIUM",
                        "reason": build_reason(prev_score, curr_score, prev_grade, curr_grade),
                    }
                )
    return sorted(alerts, key=lambda x: (x["alert_level"], x["score_change"]))


def build_reason(prev_score: float, curr_score: float, prev_grade: str, curr_grade: str) -> str:
    parts = [f"街区分从 {prev_score:.1f} 降到 {curr_score:.1f}", f"级别从 {prev_grade} 变成 {curr_grade}"]
    if prev_grade.startswith(("A", "B")) and curr_grade.startswith(("D", "E")):
        parts.append("强势区快速掉入转弱/退潮区")
    if curr_grade.startswith("E"):
        parts.append("当前已进入弱势或退潮")
    return "；".join(parts)


def write_outputs(dates: list[str], alerts: list[dict[str, Any]]) -> dict[str, str]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    end_date = dates[-1]
    json_path = REPORTS_DIR / f"sector_alerts_{end_date}.json"
    md_path = REPORTS_DIR / f"sector_alerts_{end_date}.md"
    payload = {"dates": dates, "alerts": alerts}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 街区退潮预警 {end_date}",
        "",
        f"- 观察窗口：{', '.join(dates)}",
        f"- 预警数量：{len(alerts)}",
        "",
    ]
    if not alerts:
        lines.append("- 本次未触发街区退潮预警。")
    else:
        for item in alerts:
            lines.extend(
                [
                    f"## {item['industry_name']} {item['index_code']}",
                    f"- 等级：{item['alert_level']}",
                    f"- 变化：{item['prev_date']} {item['prev_score']:.1f}/{item['prev_grade']} -> {item['curr_date']} {item['curr_score']:.1f}/{item['curr_grade']}",
                    f"- 原因：{item['reason']}",
                    "",
                ]
            )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build sector weakening alerts")
    parser.add_argument("--days", dest="days", type=int, default=3, help="Number of recent dates to compare")
    args = parser.parse_args(argv)
    dates = latest_dates(limit=max(args.days, 2))
    alerts = build_alerts(dates)
    paths = write_outputs(dates, alerts)
    print(json.dumps({"dates": dates, "alert_count": len(alerts), **paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
