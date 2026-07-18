from __future__ import annotations

import unittest

from scoring_system.tushare_probe import build_feature_summary, classify_probe_error, summarize_permissions


class TushareProbeTests(unittest.TestCase):
    def test_permission_summary_tracks_core_failures(self) -> None:
        checks = [
            {"api_name": "daily", "ok": True, "critical": True, "status": "PASS"},
            {"api_name": "index_member_all", "ok": False, "critical": True, "status": "FAIL"},
            {"api_name": "index_weight", "ok": True, "critical": False, "status": "PASS"},
        ]
        summary = summarize_permissions(checks)
        self.assertFalse(summary["core_passed"])
        self.assertEqual(["index_member_all"], summary["critical_failed_apis"])

    def test_feature_summary_separates_industry_and_index_functions(self) -> None:
        checks = [
            {"api_name": "index_daily", "ok": True, "status": "PASS"},
            {"api_name": "index_weight", "ok": True, "status": "PASS"},
            {"api_name": "index_classify", "ok": True, "status": "PASS"},
            {"api_name": "index_member_all", "ok": True, "status": "PASS"},
            {"api_name": "ci_index_member", "ok": True, "status": "PASS"},
        ]
        features = build_feature_summary(checks)
        self.assertEqual("PASS", features["指数"]["status"])
        self.assertEqual("PASS", features["行业成分"]["status"])
        self.assertEqual(["index_classify", "index_member_all", "ci_index_member"], features["行业成分"]["passed_apis"])

    def test_classifies_local_network_permission_block(self) -> None:
        exc = ConnectionError("[WinError 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试。")
        self.assertEqual("LOCAL_NETWORK_PERMISSION_BLOCKED", classify_probe_error(exc))


if __name__ == "__main__":
    unittest.main()
