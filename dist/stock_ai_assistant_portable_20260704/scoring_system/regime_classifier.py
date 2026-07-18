from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCORES_DIR = ROOT / "data" / "processed" / "scores"
REPORTS_DIR = ROOT / "reports" / "regime"

状态顺序 = ["退潮", "转弱中", "短期回调", "延续", "中性观察"]


def 列出日期(limit: int = 5) -> list[str]:
    dates: list[str] = []
    for path in SCORES_DIR.glob("sector_scores_*_calibrated.csv"):
        dates.extend([p for p in path.stem.split("_") if p.isdigit() and len(p) == 8])
    return sorted(set(dates))[-limit:]


def 读取板块评分(as_of: str) -> pd.DataFrame:
    path = SCORES_DIR / f"sector_scores_{as_of}_calibrated.csv"
    return pd.read_csv(path, dtype={"index_code": "string"}) if path.exists() else pd.DataFrame()


def 读取市场评分(as_of: str) -> dict[str, Any]:
    path = SCORES_DIR / f"market_sector_score_{as_of}_calibrated.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def 识别板块状态(当前: pd.Series, 前一日: pd.Series | None, 市场天气分: float) -> tuple[str, str]:
    当前分数 = float(当前.get("score", 0))
    当前等级 = str(当前.get("grade", ""))
    前一日分数 = float(前一日.get("score", 当前分数)) if 前一日 is not None else 当前分数
    分数变化 = 当前分数 - 前一日分数
    前一日等级 = str(前一日.get("grade", "")) if 前一日 is not None else ""

    if 前一日等级.startswith(("A", "B")) and 当前等级.startswith(("D", "E")):
        return "退潮", "原本强势的板块快速掉入转弱或退潮区"
    if 当前等级.startswith("E") and 分数变化 <= -10:
        return "退潮", "板块已经处于弱势或退潮，而且分数还在继续恶化"
    if 当前等级.startswith("E"):
        return "转弱中", "板块已经进入弱势区，后续更适合先防守再观察"
    if 当前等级.startswith("D") and 分数变化 <= -10:
        return "转弱中", "板块分数明显下滑，正在从普通状态继续走弱"
    if 当前等级.startswith(("B", "C")) and 分数变化 < 0 and 市场天气分 < 40:
        return "短期回调", "板块层级还在，但市场天气偏弱，更像受大盘压制的回调"
    if 当前等级.startswith(("A", "B")) and 分数变化 >= -5:
        return "延续", "板块仍然保持较高层级，暂时没有明显退潮信号"
    return "中性观察", "当前还没有足够信号明确归类为回调或退潮"


def 构建状态报告(日期列表: list[str]) -> dict[str, Any]:
    当前日期 = 日期列表[-1]
    对比日期 = 日期列表[-2] if len(日期列表) >= 2 else 日期列表[-1]
    当前表 = 读取板块评分(当前日期)
    前一日表 = 读取板块评分(对比日期)
    市场 = 读取市场评分(当前日期)
    市场天气分 = float(市场.get("market_score", {}).get("score", 0))

    前一日映射 = 前一日表.set_index("index_code").to_dict("index") if not 前一日表.empty else {}
    rows: list[dict[str, Any]] = []
    for _, row in 当前表.iterrows():
        code = str(row.get("index_code"))
        prior = 前一日映射.get(code)
        状态, 原因 = 识别板块状态(row, pd.Series(prior) if prior else None, 市场天气分)
        rows.append(
            {
                "trade_date": 当前日期,
                "index_code": code,
                "industry_name": str(row.get("industry_name", "")),
                "score": float(row.get("score", 0)),
                "grade": str(row.get("grade", "")),
                "prev_date": 对比日期,
                "prev_score": float(prior.get("score", 0)) if prior else None,
                "prev_grade": str(prior.get("grade", "")) if prior else "",
                "score_change": float(row.get("score", 0)) - float(prior.get("score", 0)) if prior else 0.0,
                "state": 状态,
                "reason": 原因,
            }
        )
    df = pd.DataFrame(rows)
    df["状态顺序"] = df["state"].map({k: i for i, k in enumerate(状态顺序)})
    df = df.sort_values(["状态顺序", "score"], ascending=[True, False]).drop(columns=["状态顺序"])
    return {
        "as_of_date": 当前日期,
        "prev_date": 对比日期,
        "market_score": 市场天气分,
        "states": df.to_dict(orient="records"),
    }


def 写出结果(报告: dict[str, Any]) -> dict[str, str]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    as_of = 报告["as_of_date"]
    json_path = REPORTS_DIR / f"sector_regime_{as_of}.json"
    md_path = REPORTS_DIR / f"sector_regime_{as_of}.md"
    json_path.write_text(json.dumps(报告, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 板块状态识别 {as_of}",
        "",
        f"- 对比日期：{报告['prev_date']} -> {报告['as_of_date']}",
        f"- 市场天气分：{报告['market_score']}",
        "",
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in 报告["states"]:
        grouped.setdefault(item["state"], []).append(item)
    for 状态 in 状态顺序:
        items = grouped.get(状态, [])
        if not items:
            continue
        lines.append(f"## {状态}")
        for item in items[:15]:
            lines.append(
                f"- {item['industry_name']} {item['index_code']}：{item['prev_score']} / {item['prev_grade']} -> {item['score']} / {item['grade']}，原因：{item['reason']}"
            )
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="识别板块是短期回调、转弱还是退潮")
    parser.add_argument("--days", dest="days", type=int, default=2)
    args = parser.parse_args(argv)
    dates = 列出日期(limit=max(args.days, 2))
    报告 = 构建状态报告(dates)
    路径 = 写出结果(报告)
    print(json.dumps({"as_of_date": 报告["as_of_date"], **路径}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
