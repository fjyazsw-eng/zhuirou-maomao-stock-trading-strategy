from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
TMP_DIR = PROJECT_ROOT / "tests" / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from amount_units import tushare_amount_to_yi

spec = importlib.util.spec_from_file_location("market_weather_5d", SCRIPTS_DIR / "market_weather_5d.py")
mw = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["market_weather_5d"] = mw
spec.loader.exec_module(mw)


def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
            "trade_date": ["20260630"] * 4,
            "open": [10, 10, 10, 10],
            "high": [11, 10, 10, 10],
            "low": [9, 9, 10, 9],
            "close": [11, 9, 10, 9.5],
            "pre_close": [10, 10, 10, 10],
            "change": [1, -1, 0, -0.5],
            "pct_chg": [10.0, -10.0, 0.0, -5.0],
            "vol": [100, 100, 100, 100],
            "amount": [100000, 200000, 300000, 400000],
        }
    )


def reset_case_dir(name: str) -> Path:
    path = TMP_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    for existing in path.glob("*.csv"):
        existing.unlink()
    return path


class MarketWeather5dTest(unittest.TestCase):
    def test_amount_100000_qianyuan_equals_1_yi(self) -> None:
        self.assertEqual(tushare_amount_to_yi(100000), 1)

    def test_empty_dataframe_does_not_crash_quality(self) -> None:
        df = pd.DataFrame(columns=mw.REQUIRED_FIELDS)
        quality = mw.inspect_quality(df, "20260630")
        self.assertEqual(quality.valid_rows, 0)
        self.assertEqual(quality.status, "无有效行情")

    def test_duplicate_stock_code_detected(self) -> None:
        df = sample_df()
        df.loc[1, "ts_code"] = "000001.SZ"
        quality = mw.inspect_quality(df, "20260630")
        self.assertEqual(quality.duplicate_codes, 1)

    def test_up_down_flat_counts(self) -> None:
        stats = mw.daily_market_stats("20260630", sample_df())
        self.assertEqual(stats["up_count"], 1)
        self.assertEqual(stats["down_count"], 2)
        self.assertEqual(stats["flat_count"], 1)

    def test_up_ratio(self) -> None:
        stats = mw.daily_market_stats("20260630", sample_df())
        self.assertEqual(stats["up_ratio"], 0.25)

    def test_top20_with_less_than_20_stocks(self) -> None:
        stats = mw.daily_market_stats("20260630", sample_df())
        self.assertEqual(stats["top20_up_count"], 1)
        self.assertEqual(stats["top20_down_count"], 2)
        self.assertEqual(stats["top20_flat_count"], 1)

    def test_weather_score_between_0_and_100(self) -> None:
        stats = mw.daily_market_stats("20260630", sample_df())
        score, _details = mw.score_weather(stats)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_missing_required_fields_raises_clear_error(self) -> None:
        df = sample_df().drop(columns=["pct_chg"])
        with self.assertRaisesRegex(mw.DataQualityError, "缺少必要字段"):
            mw.daily_market_stats("20260630", df)

    def test_local_file_exists_no_tushare_call(self) -> None:
        tmp_path = reset_case_dir("local_cache_case")
        with patch.object(mw, "RAW_DIR", tmp_path):
            sample_df().to_csv(tmp_path / "daily_20260630.csv", index=False)
            called = {"value": False}

            def fetcher(_date: str) -> pd.DataFrame:
                called["value"] = True
                return sample_df()

            df, source, quality = mw.load_or_fetch_daily("20260630", fetcher=fetcher, sleep_seconds=0)
            self.assertFalse(called["value"])
            self.assertEqual(source, "本地CSV")
            self.assertEqual(len(df), 4)
            self.assertEqual(quality.status, "正常")

    def test_empty_non_trading_day_not_counted_as_valid(self) -> None:
        def fetcher(date: str) -> pd.DataFrame:
            if date in {"20260629", "20260628"}:
                return pd.DataFrame(columns=mw.REQUIRED_FIELDS)
            df = sample_df()
            df["trade_date"] = date
            return df

        tmp_path = reset_case_dir("non_trading_case")
        with patch.object(mw, "RAW_DIR", tmp_path):
            frames, qualities = mw.recent_valid_daily_frames(
                "20260630",
                needed=5,
                max_natural_days=8,
                fetcher=fetcher,
                sleep_seconds=0,
            )
        dates = [date for date, _df, _source, _quality in frames]
        self.assertNotIn("20260629", dates)
        self.assertNotIn("20260628", dates)
        self.assertEqual(len(frames), 5)
        self.assertTrue(any(q.date == "20260629" and q.status == "无有效行情" for q in qualities))


if __name__ == "__main__":
    unittest.main()
