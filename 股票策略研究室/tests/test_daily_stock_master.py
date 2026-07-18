from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("build_daily_stock_master", SCRIPTS_DIR / "build_daily_stock_master.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["build_daily_stock_master"] = mod
spec.loader.exec_module(mod)


class DailyStockMasterTest(unittest.TestCase):
    def test_symbol_from_ts_code_keeps_leading_zero(self) -> None:
        self.assertEqual(mod.symbol_from_ts_code("000001.SZ"), "000001")

    def test_repair_symbol_from_ts_code_when_lost_leading_zero(self) -> None:
        df = pd.DataFrame({"ts_code": ["000001.SZ"], "symbol": ["1"]})
        repaired = mod.repair_symbol(df)
        self.assertEqual(str(repaired.loc[0, "symbol"]), "000001")

    def test_build_master_left_join_keeps_daily_rows(self) -> None:
        daily = pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000002.SZ"],
                "trade_date": ["20260630", "20260630"],
                "open": [1, 2],
                "high": [1, 2],
                "low": [1, 2],
                "close": [1, 2],
                "pre_close": [1, 2],
                "change": [0, 0],
                "pct_chg": [0, 0],
                "vol": [10, 20],
                "amount": [100000, 200000],
            }
        )
        stock_basic = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "symbol": ["000001"],
                "name": ["平安银行"],
                "area": ["深圳"],
                "industry": ["银行"],
                "list_date": ["19910403"],
            }
        )
        daily_basic = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": ["20260630"],
                "turnover_rate": [1.0],
                "volume_ratio": [1.2],
                "pe": [5.0],
                "pb": [0.5],
                "total_mv": [1000.0],
                "circ_mv": [900.0],
            }
        )
        with patch.object(mod, "load_inputs", return_value=(daily, stock_basic, daily_basic, pd.DataFrame())):
            master, quality, _index = mod.build_master("20260630")
        self.assertEqual(len(master), 2)
        self.assertEqual(quality["name_match_count"], 1)
        self.assertEqual(quality["daily_basic_match_count"], 1)

    def test_missing_pe_pb_does_not_drop_row(self) -> None:
        daily = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": ["20260630"],
                "open": [1],
                "high": [1],
                "low": [1],
                "close": [1],
                "pre_close": [1],
                "change": [0],
                "pct_chg": [0],
                "vol": [10],
                "amount": [100000],
            }
        )
        stock_basic = pd.DataFrame({"ts_code": ["000001.SZ"], "symbol": ["000001"], "name": ["平安银行"]})
        daily_basic = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": ["20260630"],
                "turnover_rate": [1.0],
                "volume_ratio": [1.2],
                "pe": [pd.NA],
                "pb": [pd.NA],
                "total_mv": [1000.0],
                "circ_mv": [900.0],
            }
        )
        with patch.object(mod, "load_inputs", return_value=(daily, stock_basic, daily_basic, pd.DataFrame())):
            master, _quality, _index = mod.build_master("20260630")
        self.assertEqual(len(master), 1)
        self.assertTrue(pd.isna(master.loc[0, "pe"]))

    def test_index_not_in_sse_cache_reports_not_covered(self) -> None:
        index_basic = pd.DataFrame({"ts_code": ["000001.SH"], "name": ["上证指数"]})
        coverage = mod.find_index_coverage(index_basic)
        by_name = {row["name"]: row for row in coverage}
        self.assertEqual(by_name["上证指数"]["ts_code"], "000001.SH")
        self.assertEqual(by_name["深证成指"]["status"], "当前指数名册未覆盖")


if __name__ == "__main__":
    unittest.main()
