from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_stock_selection_to_trading_handoff as handoff


class StockSelectionHandoffTests(unittest.TestCase):
    def test_finds_latest_model_test_pool_by_trade_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            review_dir = Path(tmp)
            old_path = review_dir / "stock_selection_model_test_pool_20260706.json"
            new_path = review_dir / "stock_selection_research_focus_sectors_20260714.json"
            old_path.write_text(json.dumps({"latest_completed_trade_date": "20260706"}), encoding="utf-8")
            new_path.write_text(json.dumps({"latest_completed_trade_date": "20260714"}), encoding="utf-8")

            self.assertEqual(new_path, handoff.resolve_source_json(review_dir=review_dir))

    def test_build_handoff_allows_non_hengrui_buy_candidate_for_human_review(self) -> None:
        source = {
            "latest_completed_trade_date": "20260714",
            "market_weather": {"market_risk_level": "NEUTRAL", "attack_level": "MODERATE"},
            "candidate_continuity_review": [
                {
                    "ts_code": "688012.SH",
                    "name": "中微公司",
                    "sector": "半导体设备",
                    "sector_nature": "POTENTIAL_MAINLINE",
                    "mainline_score_0_100": 76,
                    "current_action": "BUY_CANDIDATE",
                    "buy_point_quality": "GOOD",
                    "manual_mapping_candidate": False,
                    "confidence_level": "MEDIUM",
                    "action_change_reason": "趋势持续且买点质量改善。",
                    "entry_condition": "回踩10日线企稳后重新放量。",
                    "stop_loss_condition": "跌破10日线且无法收回。",
                    "take_profit_condition": "冲高放量滞涨分批止盈。",
                    "invalidation_condition": "板块重新转弱。",
                    "main_risks": "半导体仍有分歧。",
                }
            ],
            "model_test_candidate_pool": [
                {
                    "ts_code": "688012.SH",
                    "name": "中微公司",
                    "current_action": "BUY_CANDIDATE",
                    "test_role": "WATCH_TEST",
                    "action_change_reason": "趋势持续且买点质量改善。",
                    "short_term_logic": "轻仓试错。",
                    "mid_long_term_logic": "观察能否继续跑赢设备板块。",
                    "entry_condition": "回踩10日线企稳后重新放量。",
                    "stop_loss_condition": "跌破10日线且无法收回。",
                    "take_profit_condition": "冲高放量滞涨分批止盈。",
                    "invalidation_condition": "板块重新转弱。",
                    "main_risks": "半导体仍有分歧。",
                    "mainline_score_0_100": 76,
                    "sector": "半导体设备",
                    "sector_nature": "POTENTIAL_MAINLINE",
                }
            ],
        }

        report = handoff.build_handoff(source)

        self.assertEqual(["688012.SH"], report["human_review_summary"]["stocks_allowed_for_simulated_buy_judgement"])
        self.assertTrue(report["handoff_to_trading_model"][0]["can_trading_model_simulate_buy"])

    def test_build_handoff_can_use_focus_report_recommended_candidates(self) -> None:
        source = {
            "latest_completed_trade_date": "20260714",
            "market_weather": {"market_risk_level": "NEUTRAL", "attack_level": "MODERATE"},
            "candidate_continuity_review": [],
            "recommended_candidates": [
                {
                    "ts_code": "688012.SH",
                    "name": "中微公司",
                    "sector": "半导体设备",
                    "sector_nature": "POTENTIAL_MAINLINE",
                    "mainline_score_0_100": 76,
                    "candidate_action": "BUY_CANDIDATE",
                    "buy_point_quality": "GOOD",
                    "manual_mapping_candidate": False,
                    "entry_condition": "回踩10日线企稳后重新放量。",
                    "stop_loss_condition": "跌破10日线且无法收回。",
                    "take_profit_condition": "冲高放量滞涨分批止盈。",
                }
            ],
            "model_test_candidate_pool": [],
        }

        report = handoff.build_handoff(source)

        self.assertEqual("688012.SH", report["handoff_to_trading_model"][0]["ts_code"])
        self.assertTrue(report["handoff_to_trading_model"][0]["can_trading_model_simulate_buy"])


if __name__ == "__main__":
    unittest.main()
