from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import fetch_handoff_latest_readonly_quotes as quotes


class HandoffQuoteFetchTests(unittest.TestCase):
    def test_finds_latest_handoff_by_trade_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            review_dir = Path(tmp)
            old_path = review_dir / "stock_selection_to_trading_handoff_20260706.json"
            new_path = review_dir / "stock_selection_to_trading_handoff_20260714.json"
            old_path.write_text(json.dumps({"latest_completed_trade_date": "20260706"}), encoding="utf-8")
            new_path.write_text(json.dumps({"latest_completed_trade_date": "20260714"}), encoding="utf-8")

            self.assertEqual(new_path, quotes.resolve_handoff_path(review_dir=review_dir))

    def test_build_payload_uses_resolved_trade_date_as_requested_date(self) -> None:
        payload = quotes.build_payload(
            handoff_rows=[{"ts_code": "688012.SH"}],
            trade_date="20260714",
            latest_completed_trade_date="20260714",
            fallback_to_latest_completed_trade_date=False,
            loaded_rows=[],
            missing_symbols=["688012.SH"],
        )

        self.assertEqual("20260714", payload["requested_trade_date"])
        self.assertEqual("20260714", payload["trade_date"])

    def test_preferred_trade_date_defaults_to_handoff_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff_path = Path(tmp) / "stock_selection_to_trading_handoff_20260714.json"
            handoff_path.write_text(
                json.dumps({"latest_completed_trade_date": "20260714", "handoff_to_trading_model": []}),
                encoding="utf-8",
            )

            self.assertEqual("20260714", quotes.preferred_trade_date_from_handoff(handoff_path, ""))
            self.assertEqual("20260710", quotes.preferred_trade_date_from_handoff(handoff_path, "20260710"))

    def test_failure_review_marks_tushare_timeout_as_data_abnormal(self) -> None:
        review = quotes.build_failure_review(
            handoff_path=Path("stock_selection_to_trading_handoff_20260714.json"),
            requested_trade_date="20260714",
            error=TimeoutError("connect timeout"),
        )

        self.assertFalse(review["handoff_latest_readonly_quotes_fetch_completed"])
        self.assertFalse(review["data_quality"]["tushare_available"])
        self.assertIn("数据异常", review["message"])


if __name__ == "__main__":
    unittest.main()
