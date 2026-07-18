from __future__ import annotations

import unittest

from scripts.run_simulated_live_v1_stock_selection_research_focus_sectors import (
    apply_manual_policy_overrides,
    build_dynamic_watch_pool,
)


class DynamicWatchPoolTests(unittest.TestCase):
    def test_dynamic_watch_pool_keeps_actionable_research_candidates(self) -> None:
        pool = build_dynamic_watch_pool(
            latest_trade_date="20260714",
            recommended_candidates=[
                {
                    "ts_code": "688012.SH",
                    "name": "中微公司",
                    "sector": "半导体设备",
                    "candidate_action": "BUY_CANDIDATE",
                    "leader_type": "TREND_LEADER",
                    "buy_point_quality": "GOOD",
                    "entry_condition": "回踩10日线企稳后重新放量。",
                    "stop_loss_condition": "跌破10日线且无法收回。",
                    "take_profit_condition": "冲高放量滞涨分批止盈。",
                },
                {
                    "ts_code": "002185.SZ",
                    "name": "华天科技",
                    "sector": "先进封装",
                    "candidate_action": "WATCH",
                    "leader_type": "ABSOLUTE_LEADER",
                    "buy_point_quality": "POOR",
                    "entry_condition": "不追高，等回踩。",
                    "stop_loss_condition": "跌破10日线且无法收回。",
                    "take_profit_condition": "放量滞涨分批止盈。",
                },
            ],
            candidate_continuity_review=[],
            manual_sample_stocks=[],
            max_items=5,
        )

        self.assertEqual("20260714", pool["latest_completed_trade_date"])
        self.assertEqual(["688012.SH", "002185.SZ"], [item["code"] for item in pool["watch_pool"]])
        self.assertEqual("轻仓试错", pool["watch_pool"][0]["plain_action"])
        self.assertEqual("回踩再买", pool["watch_pool"][1]["plain_action"])

    def test_manual_overrides_do_not_force_hengrui_to_buy_candidate(self) -> None:
        candidates, _, _ = apply_manual_policy_overrides(
            recommended_candidates=[
                {
                    "ts_code": "600276.SH",
                    "name": "恒瑞医药",
                    "sector": "化学制药",
                    "sector_group": "医药修复组",
                    "leader_type": "CAPACITY_CORE",
                    "candidate_action": "WATCH",
                    "buy_point_quality": "FAIR",
                    "suitable_for_candidate_pool": True,
                    "entry_condition": "回踩再看。",
                }
            ],
            removed_list=[],
            medical_manual_section={
                "sample_stocks": [],
            },
            market_weather={"market_risk_level": "NEUTRAL", "attack_level": "MODERATE"},
        )

        self.assertEqual("WATCH", candidates[0]["candidate_action"])


if __name__ == "__main__":
    unittest.main()
