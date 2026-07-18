from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("build_industry_map", SCRIPTS_DIR / "build_industry_map.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["build_industry_map"] = mod
spec.loader.exec_module(mod)


class IndustryMapTest(unittest.TestCase):
    def test_active_member_map_does_not_guess_unmatched(self) -> None:
        members = pd.DataFrame({"con_code": ["000001.SZ"], "industry_code": ["801010.SI"], "industry_name": ["银行"], "out_date": [pd.NA]})
        mapping = mod.active_member_map(members, "20260630")
        self.assertEqual(len(mapping), 1)
        self.assertEqual(mapping.loc[0, "ts_code"], "000001.SZ")

    def test_build_stats_counts_up_down(self) -> None:
        df = pd.DataFrame({
            "industry_name": ["A", "A", "B"],
            "name": ["a1", "a2", "b1"],
            "ts_code": ["1", "2", "3"],
            "return_1d_pct": [1.0, -2.0, 6.0],
            "return_3d_pct": [2.0, 1.0, -1.0],
            "return_5d_pct": [3.0, 2.0, -2.0],
            "amount_today": [100, 200, 300],
        })
        stats = mod.build_stats(df)
        row_a = stats[stats["industry_name"] == "A"].iloc[0]
        self.assertEqual(row_a["stock_count"], 2)
        self.assertEqual(row_a["up_count"], 1)
        self.assertEqual(row_a["down_count"], 1)

    def test_classify_industries(self) -> None:
        stats = pd.DataFrame({
            "industry_name": ["连续", "单日", "转弱"],
            "return_1d_pct": [1.0, 3.0, -1.0],
            "return_3d_pct": [1.0, -1.0, -2.0],
            "return_5d_pct": [1.0, -2.0, 1.0],
        })
        continuous, one_day, weakening = mod.classify_industries(stats)
        self.assertEqual(continuous.iloc[0]["industry_name"], "连续")
        self.assertEqual(one_day.iloc[0]["industry_name"], "单日")
        self.assertEqual(weakening.iloc[0]["industry_name"], "转弱")

    def test_stock_returns_calculates_3d_5d(self) -> None:
        dates = ["20260630", "20260629", "20260626", "20260625", "20260624"]
        rows = []
        for i, d in enumerate(dates):
            rows.append({"ts_code": "000001.SZ", "trade_date": d, "close": 110 - i, "pre_close": 100 + i, "pct_chg": 1.0, "amount": 100000})
        out = mod.stock_returns(pd.DataFrame(rows), dates)
        self.assertIn("return_3d_pct", out.columns)
        self.assertIn("return_5d_pct", out.columns)


if __name__ == "__main__":
    unittest.main()
