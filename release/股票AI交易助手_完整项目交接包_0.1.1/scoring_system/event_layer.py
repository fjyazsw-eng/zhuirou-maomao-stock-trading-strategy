from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCORES_DIR = ROOT / "data" / "processed" / "scores"
EVENT_DIR = ROOT / "data" / "events"
REPORT_DIR = ROOT / "reports" / "events"


NEGATIVE_WORDS = [
    "减持",
    "立案",
    "处罚",
    "问询",
    "亏损",
    "下修",
    "终止",
    "违约",
    "诉讼",
    "冻结",
    "监管",
    "退市",
    "解禁",
]
POSITIVE_WORDS = [
    "增持",
    "回购",
    "中标",
    "订单",
    "扭亏",
    "预增",
    "增长",
    "合作",
    "获批",
    "补贴",
]
POLICY_WORDS = ["政策", "国务院", "财政部", "工信部", "发改委", "商务部", "监管", "支持", "鼓励"]
PERFORMANCE_WORDS = ["业绩", "预告", "快报", "营收", "净利", "利润", "亏损", "扭亏"]


@dataclass
class EventItem:
    event_date: str
    source: str
    title: str
    ts_code: str = ""
    name: str = ""
    sector_code: str = ""
    sector_name: str = ""
    category: str = "未分类"
    polarity: str = "中性"
    severity: str = "观察"
    reason: str = ""


def latest_score_date() -> str:
    dates: list[str] = []
    for path in SCORES_DIR.glob("stock_scores_*.csv"):
        dates.extend([p for p in path.stem.split("_") if p.isdigit() and len(p) == 8])
    if not dates:
        raise FileNotFoundError("no stock score files")
    return sorted(set(dates))[-1]


def load_stock_map(as_of: str) -> dict[str, dict[str, Any]]:
    path = SCORES_DIR / f"stock_scores_{as_of}.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"ts_code": "string", "sector_code": "string"})
    return df.set_index("ts_code").to_dict("index")


def classify_event(title: str) -> tuple[str, str, str, str]:
    tags: list[str] = []
    if any(w in title for w in POLICY_WORDS):
        tags.append("政策")
    if any(w in title for w in PERFORMANCE_WORDS):
        tags.append("业绩")
    if "公告" in title or "减持" in title or "回购" in title or "问询" in title:
        tags.append("公告")
    if not tags:
        tags.append("新闻/其他")

    neg = [w for w in NEGATIVE_WORDS if w in title]
    pos = [w for w in POSITIVE_WORDS if w in title]
    if neg and not pos:
        polarity = "偏利空"
    elif pos and not neg:
        polarity = "偏利好"
    elif neg and pos:
        polarity = "多空混合"
    else:
        polarity = "中性"

    if any(w in title for w in ["立案", "处罚", "退市", "违约", "冻结"]):
        severity = "高"
    elif any(w in title for w in ["减持", "问询", "亏损", "下修", "解禁", "终止"]):
        severity = "中"
    else:
        severity = "观察"
    reason = "；".join(neg + pos) if (neg or pos) else "未命中明确正负关键词"
    return "、".join(tags), polarity, severity, reason


def ensure_template() -> Path:
    EVENT_DIR.mkdir(parents=True, exist_ok=True)
    path = EVENT_DIR / "manual_events_template.csv"
    if not path.exists():
        rows = [
            ["event_date", "source", "title", "ts_code", "name", "sector_code", "sector_name"],
            ["20260702", "手工示例", "某公司公告业绩预增", "", "", "", ""],
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
    return path


def load_manual_events() -> list[dict[str, str]]:
    EVENT_DIR.mkdir(parents=True, exist_ok=True)
    ensure_template()
    rows: list[dict[str, str]] = []
    for path in EVENT_DIR.glob("manual_events*.csv"):
        if path.name == "manual_events_template.csv":
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("title"):
                    rows.append({k: (v or "").strip() for k, v in row.items()})
    return rows


def build_event_report(as_of: str) -> dict[str, Any]:
    stock_map = load_stock_map(as_of)
    raw_events = load_manual_events()
    items: list[EventItem] = []
    for raw in raw_events:
        ts_code = raw.get("ts_code", "")
        stock = stock_map.get(ts_code, {})
        title = raw.get("title", "")
        category, polarity, severity, reason = classify_event(title)
        items.append(
            EventItem(
                event_date=raw.get("event_date", ""),
                source=raw.get("source", "手工录入"),
                title=title,
                ts_code=ts_code,
                name=raw.get("name") or str(stock.get("name", "")),
                sector_code=raw.get("sector_code") or str(stock.get("sector_code", "")),
                sector_name=raw.get("sector_name") or str(stock.get("sector_name", "")),
                category=category,
                polarity=polarity,
                severity=severity,
                reason=reason,
            )
        )
    return {
        "as_of_date": as_of,
        "event_count": len(items),
        "events": [asdict(x) for x in items],
        "data_status": "NO_STRUCTURED_SOURCE" if not items else "MANUAL_EVENTS_LOADED",
        "template": str(ensure_template()),
        "note": "当前事件层已具备结构化入口；未接入公告/新闻接口时，不生成无来源事件。",
    }


def write_outputs(payload: dict[str, Any]) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    as_of = payload["as_of_date"]
    json_path = REPORT_DIR / f"event_layer_{as_of}.json"
    md_path = REPORT_DIR / f"event_layer_{as_of}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 事件面结构化报告 {as_of}",
        "",
        f"- 事件数量：{payload['event_count']}",
        f"- 数据状态：{payload['data_status']}",
        f"- 手工事件模板：{payload['template']}",
        "",
        "## 事件列表",
    ]
    if not payload["events"]:
        lines.append("- 暂无结构化事件。当前不会凭空生成政策、公告、业绩或新闻结论。")
    else:
        for item in payload["events"]:
            lines.append(
                f"- {item['event_date']} {item['title']}：{item['category']}，{item['polarity']}，严重度 {item['severity']}，原因 {item['reason']}"
            )
    lines.extend(
        [
            "",
            "## 后续接入口",
            "- Tushare 公告/业绩接口",
            "- 交易所公告",
            "- 东方财富/巨潮资讯公开公告",
            "- 用户手工补充的突发新闻或截图摘要",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build structured event risk layer")
    parser.add_argument("--as-of", default="")
    args = parser.parse_args(argv)
    as_of = args.as_of or latest_score_date()
    payload = build_event_report(as_of)
    paths = write_outputs(payload)
    print(json.dumps({"as_of_date": as_of, **paths, "event_count": payload["event_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
