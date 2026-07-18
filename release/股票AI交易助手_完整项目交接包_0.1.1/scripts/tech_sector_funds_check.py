from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import tushare as ts

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.industry_members import fetch_sw_index_members

OUT = ROOT / "reports" / "tech_sector_funds_check_20260701.json"
ASOF = "20260701"
TARGETS = {
    "光学光电子": "801084.SI",
    "半导体材料": "850813.SI",
    "电子化学品": "850861.SI",
}
DATES = ["20260625", "20260626", "20260629", "20260630", "20260701"]


def main() -> None:
    pro = ts.pro_api(os.getenv("TUSHARE_TOKEN"))
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
        try:
            df = pro.moneyflow(trade_date=d, fields="ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,net_mf_amount")
            frames.append(df)
        except Exception as exc:
            print("moneyflow failed", d, exc)
    mf = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    for col in mf.columns:
        if col not in {"ts_code", "trade_date"}:
            mf[col] = pd.to_numeric(mf[col], errors="coerce")

    result = {}
    for name, stocks in members.items():
        x = mf[mf["ts_code"].isin(stocks)].copy()
        x["large_net"] = (x["buy_lg_amount"] - x["sell_lg_amount"]) + (x["buy_elg_amount"] - x["sell_elg_amount"])
        by_day = x.groupby("trade_date").agg(net_mf_amount=("net_mf_amount", "sum"), large_net=("large_net", "sum")).reset_index()
        result[name] = {
            "days": by_day.to_dict("records"),
            "sum_5d_net_mf_amount_wan": round(float(x["net_mf_amount"].sum()), 2),
            "sum_5d_large_net_wan": round(float(x["large_net"].sum()), 2),
        }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
