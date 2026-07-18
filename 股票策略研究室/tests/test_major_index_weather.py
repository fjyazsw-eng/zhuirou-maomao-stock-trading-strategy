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

spec = importlib.util.spec_from_file_location("build_major_index_weather", SCRIPTS_DIR / "build_major_index_weather.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["build_major_index_weather"] = mod
spec.loader.exec_module(mod)


def sample_index_daily(rows: int = 20) -> pd.DataFrame:
    data = []
    for i in range(rows):
        close = 100 + i
        data.append(
            {
                "ts_code": "000001.SH",
                "trade_date": str(20260630 - i),
                "close": close,
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "pre_close": close - 1,
                "change": 1,
                "pct_chg": 1,
                "vol": 1000,
                "amount": 10000,
            }
        )
    return pd.DataFrame(data)


class MajorIndexWeatherTest(unittest.TestCase):
    def test_pct_return_uses_pre_close_base(self) -> None:
        df = pd.DataFrame({"close": [110, 108, 105], "pre_close": [109, 107, 100]})
        self.assertAlmostEqual(mod.pct_return(df, 3), 10.0)

    def test_uncovered_index_is_not_guessed(self) -> None:
        index_basic = pd.DataFrame({"ts_code": ["000001.SH"], "name": ["上证指数"]})
        with patch.object(mod, "load_or_fetch_index_basic", return_value=index_basic):
            results = mod.resolve_indices(pro=object(), sleep_seconds=0)
        by_name = {item.name: item for item in results}
        self.assertEqual(by_name["上证指数"].ts_code, "000001.SH")
        self.assertIsNone(by_name["深证成指"].ts_code)

    def test_complete_local_index_daily_no_api_call_needed(self) -> None:
        with patch.object(mod, "complete_csv", return_value=(True, sample_index_daily())):
            df = mod.load_or_fetch_index_daily("000001.SH", "20260630", pro=object(), sleep_seconds=0)
        self.assertEqual(len(df), 20)

    def test_style_judgment_prefers_best_5d_group(self) -> None:
        df = pd.DataFrame(
            [
                {"name": "沪深300", "return_5d_pct": 1.0},
                {"name": "中证1000", "return_5d_pct": 2.0},
                {"name": "中证2000", "return_5d_pct": 3.0},
                {"name": "创业板指", "return_5d_pct": 0.5},
                {"name": "科创50", "return_5d_pct": 0.5},
                {"name": "深证成指", "return_5d_pct": 0.5},
            ]
        )
        judgment, _reasons = mod.style_judgment(df)
        self.assertIn("小盘", judgment)


if __name__ == "__main__":
    unittest.main()
