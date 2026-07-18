from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVENT_DIR = ROOT / "data" / "events"
EVENT_FILE = EVENT_DIR / "manual_events.csv"
FIELDS = ["event_date", "source", "title", "ts_code", "name", "sector_code", "sector_name"]


def normalize_date(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return datetime.now().strftime("%Y%m%d")
    return text.replace("-", "").replace("/", "")


def ensure_file() -> None:
    EVENT_DIR.mkdir(parents=True, exist_ok=True)
    if EVENT_FILE.exists():
        return
    with EVENT_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()


def append_event(args: argparse.Namespace) -> Path:
    ensure_file()
    row = {
        "event_date": normalize_date(args.date),
        "source": args.source.strip() or "手工录入",
        "title": args.title.strip(),
        "ts_code": args.ts_code.strip(),
        "name": args.name.strip(),
        "sector_code": args.sector_code.strip(),
        "sector_name": args.sector_name.strip(),
    }
    if not row["title"]:
        raise ValueError("title 不能为空")
    with EVENT_FILE.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writerow(row)
    return EVENT_FILE


def main() -> int:
    parser = argparse.ArgumentParser(description="追加一条手工事件，供事件层结构化使用")
    parser.add_argument("--title", required=True, help="事件标题，例如：某公司公告业绩预增")
    parser.add_argument("--date", default="", help="事件日期，默认今天，格式 YYYYMMDD")
    parser.add_argument("--source", default="手工录入", help="来源，例如：公告、新闻、用户截图")
    parser.add_argument("--ts-code", default="", help="股票代码，例如 300054.SZ")
    parser.add_argument("--name", default="", help="股票名称")
    parser.add_argument("--sector-code", default="", help="板块代码")
    parser.add_argument("--sector-name", default="", help="板块名称")
    args = parser.parse_args()
    path = append_event(args)
    print(f"已追加事件：{path}")
    print("下一步运行：python scripts\\run_event_layer.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
