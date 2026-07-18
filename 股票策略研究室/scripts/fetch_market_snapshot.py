#!/usr/bin/env python3
"""Fetch a minimal public market snapshot for Strategy Lab.

This script only collects public market and announcement data. It does not
connect to brokerage accounts, place orders, or generate trading advice.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import yaml
except ImportError:  # Keep the script usable for --help and static checks.
    yaml = None

CN_TZ = timezone(timedelta(hours=8))
EASTMONEY_PUSH2 = "https://push2.eastmoney.com/api/qt"
EASTMONEY_PUSH2HIS = "https://push2his.eastmoney.com/api/qt"
EASTMONEY_NOTICE = "https://np-anotice-stock.eastmoney.com/api/security/ann"

DEFAULT_INDEX_SECIDS = [
    "1.000001",  # SH Composite
    "0.399001",  # SZ Component
    "0.399006",  # ChiNext
    "1.000688",  # STAR 50
]

DEFAULT_BOARD_SECIDS = {
    "semiconductor": "90.BK1036",
    "semiconductor_materials": "90.BK1325",
    "semiconductor_equipment": "90.BK1326",
    "lithography_photoresist": "90.BK0884",
    "advanced_packaging": "90.BK1101",
    "memory_chip": "90.BK1137",
    "panel": "90.BK1335",
    "display_technology": "90.BK1651",
    "securities": "90.BK0473",
}

USER_AGENT = "Mozilla/5.0 StrategyLab/0.1"


def http_json(url: str, params: dict[str, Any] | None = None, timeout: int = 15) -> dict[str, Any]:
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to read project YAML config. Install with: python -m pip install PyYAML")
    with path.open("r", encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


def to_eastmoney_stock_secid(symbol: str) -> str:
    code, exchange = symbol.split(".")
    market = "1" if exchange.upper() == "SH" else "0"
    return f"{market}.{code}"


def fetch_ulist(secids: list[str], fields: str) -> dict[str, Any]:
    return http_json(
        f"{EASTMONEY_PUSH2}/ulist.np/get",
        {
            "fltt": "2",
            "invt": "2",
            "fields": fields,
            "secids": ",".join(secids),
        },
    )


def fetch_market_breadth(max_pages: int = 60, page_size: int = 100) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        data = http_json(
            f"{EASTMONEY_PUSH2}/clist/get",
            {
                "pn": page,
                "pz": page_size,
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f3",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                "fields": "f12,f14,f2,f3",
            },
        )
        diff = (data.get("data") or {}).get("diff") or []
        if not diff:
            break
        rows.extend(diff)
    pct_values = [float(r["f3"]) for r in rows if isinstance(r.get("f3"), (int, float))]
    return {
        "sample_size": len(pct_values),
        "advancers": sum(v > 0 for v in pct_values),
        "decliners": sum(v < 0 for v in pct_values),
        "flat": sum(v == 0 for v in pct_values),
        "approx_limit_up": sum(v >= 9.8 for v in pct_values),
        "approx_limit_down": sum(v <= -9.8 for v in pct_values),
        "note": "Limit-up/down counts are approximations based on percent-change thresholds.",
    }


def fetch_announcements(codes: list[str], page_size: int = 5) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for code in codes:
        data = http_json(
            EASTMONEY_NOTICE,
            {
                "sr": "-1",
                "page_size": page_size,
                "page_index": "1",
                "ann_type": "A",
                "client_source": "web",
                "stock_list": code,
            },
        )
        rows = ((data.get("data") or {}).get("list") or [])[:page_size]
        out[code] = [
            {
                "title": row.get("title"),
                "notice_date": row.get("notice_date"),
                "art_code": row.get("art_code"),
            }
            for row in rows
        ]
        time.sleep(0.15)
    return out


def build_snapshot(project_root: Path) -> dict[str, Any]:
    account = load_yaml(project_root / "config" / "account_baseline.yaml")
    watchlist = load_yaml(project_root / "config" / "watchlist.yaml")
    holdings = account.get("holdings", [])
    watches = watchlist.get("watchlist", [])
    securities = holdings + watches
    stock_secids = [to_eastmoney_stock_secid(item["symbol"]) for item in securities]
    stock_codes = [item["code"] for item in securities]

    fields = "f2,f3,f4,f6,f8,f12,f14,f15,f16,f17,f18,f62"
    board_fields = "f2,f3,f4,f6,f12,f14,f62,f104,f105,f106,f128,f140,f141,f136,f152"

    return {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "data_nature": "public market snapshot; intraday or closing status depends on exchange session time",
        "sources": [
            "Eastmoney push2 quote API",
            "Eastmoney announcement API",
        ],
        "indices": fetch_ulist(DEFAULT_INDEX_SECIDS, "f2,f3,f4,f6,f12,f14"),
        "market_breadth": fetch_market_breadth(),
        "boards": fetch_ulist(list(DEFAULT_BOARD_SECIDS.values()), board_fields),
        "stocks": fetch_ulist(stock_secids, fields),
        "announcements": fetch_announcements(stock_codes),
        "missing_data_policy": "Fields unavailable from public API must be reported as 数据缺失.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch public market snapshot for Strategy Lab.")
    parser.add_argument("--project-root", default=".", help="Path to Strategy Lab project root.")
    parser.add_argument("--output", help="Optional JSON output path. Prints to stdout when omitted.")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    snapshot = build_snapshot(project_root)
    text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
