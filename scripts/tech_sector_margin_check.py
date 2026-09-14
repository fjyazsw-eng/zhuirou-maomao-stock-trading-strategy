from __future__ import annotations
from scoring_system.tushare_client import credential_marker

import json
import os
import sys
from pathlib import Path

import pandas as pd
from scoring_system import tushare_client as ts

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.industry_members import fetch_sw_index_members

OUT = ROOT / "reports" / "tech_sector_margin_check_20260630.json"
ASOF = "20260630"
TARGETS = {
    "光学光电子": "801084.SI",
    "半导体材料": "850813.SI",
    "电子化学品": "850861.SI",
}
DATES = ["20260624", "20260625", "20260626", "20260629", "20260630"]


def main() -> None:
    pro = ts.pro_api(credential_marker())
    try:
        pro._DataApi__timeout = 120
    except Exception:
        pass
    members = {}
    for name, code in TARGETS.items():
        level = "L2" if code.startswith("801") else "L3"
        m = fetch_sw_index_members(pro, code, level=level)
        m["out_date"] = m["out_date"].fillna("")
        m["in_date"] = m["in_date"].fillna("00000000").astype(str)
        active = m[(m["in_date"] <= ASOF) & ((m["out_date"].astype(str) == "") | (m["out_date"].astype(str) >= ASOF))]
        members[name] = set(active["con_code"].astype(str))
    frames = []
    for d in DATES:
        df = pro.margin_detail(trade_date=d, fields="trade_date,ts_code,rzye,rqye,rzmre,rzche")
        frames.append(df)
    mg = pd.concat(frames, ignore_index=True)
    for col in ["rzye", "rqye", "rzmre", "rzche"]:
        mg[col] = pd.to_numeric(mg[col], errors="coerce")
    mg["margin_balance"] = mg["rzye"] + mg["rqye"]
    result = {}
    for name, stocks in members.items():
        x = mg[mg["ts_code"].isin(stocks)]
        by_day = x.groupby("trade_date").agg(
            margin_balance=("margin_balance", "sum"),
            financing_balance=("rzye", "sum"),
            financing_buy=("rzmre", "sum"),
            financing_repay=("rzche", "sum"),
        ).reset_index()
        records = by_day.to_dict("records")
        change = None
        if len(by_day) >= 2:
            change = float(by_day.iloc[-1]["margin_balance"] - by_day.iloc[0]["margin_balance"])
        result[name] = {"days": records, "balance_change_yuan": change}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
