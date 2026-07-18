from __future__ import annotations

import unittest

import pandas as pd

from scoring_system.industry_members import fetch_stock_industry_profile, fetch_sw_index_members


class FakePro:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def query(self, api_name: str, fields: str = "", **kwargs: str) -> pd.DataFrame:
        self.calls.append((api_name, kwargs))
        data = {
            "l1_code": ["801150.SI"],
            "l1_name": ["医药生物"],
            "l2_code": ["801151.SI"],
            "l2_name": ["化学制药"],
            "l3_code": ["851512.SI"],
            "l3_name": ["化学制剂"],
            "ts_code": ["600276.SH"],
            "name": ["恒瑞医药"],
            "in_date": ["20080102"],
            "out_date": [None],
            "is_new": ["Y"],
        }
        return pd.DataFrame(data)


class IndustryMembersTests(unittest.TestCase):
    def test_sw_members_use_index_member_all_and_keep_legacy_columns(self) -> None:
        pro = FakePro()
        frame = fetch_sw_index_members(pro, "801151.SI", level="L2")
        self.assertEqual("index_member_all", pro.calls[0][0])
        self.assertEqual({"l2_code": "801151.SI", "is_new": "Y"}, pro.calls[0][1])
        self.assertEqual(["index_code", "index_name", "con_code", "con_name", "in_date", "out_date", "is_new"], list(frame.columns))
        self.assertEqual("801151.SI", frame.iloc[0]["index_code"])
        self.assertEqual("", frame.iloc[0]["out_date"])

    def test_stock_profile_uses_sw_and_ci_interfaces(self) -> None:
        pro = FakePro()
        profile = fetch_stock_industry_profile(pro, "600276.SH")
        self.assertEqual(["index_member_all", "ci_index_member"], [call[0] for call in pro.calls])
        self.assertEqual("OK", profile["sw_status"])
        self.assertEqual("OK", profile["ci_status"])
        self.assertEqual("化学制剂", profile["sw"]["l3_name"])


if __name__ == "__main__":
    unittest.main()
