from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scoring_system.verified_market_snapshot import build_verified_market_snapshot, write_verified_market_snapshot


class FakeSnapshotPro:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def daily(self, trade_date: str, **kwargs) -> pd.DataFrame:
        self.calls.append(f"daily:{trade_date}")
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": trade_date, "close": 10.0, "pct_chg": 2.0, "amount": 1000.0},
                {"ts_code": "000002.SZ", "trade_date": trade_date, "close": 8.0, "pct_chg": 1.0, "amount": 800.0},
                {"ts_code": "600001.SH", "trade_date": trade_date, "close": 6.0, "pct_chg": 0.0, "amount": 600.0},
            ]
        )

    def daily_basic(self, trade_date: str, **kwargs) -> pd.DataFrame:
        self.calls.append(f"daily_basic:{trade_date}")
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": trade_date, "turnover_rate": 2.0},
                {"ts_code": "000002.SZ", "trade_date": trade_date, "turnover_rate": 1.0},
                {"ts_code": "600001.SH", "trade_date": trade_date, "turnover_rate": 0.8},
            ]
        )

    def index_daily(self, trade_date: str, **kwargs) -> pd.DataFrame:
        self.calls.append(f"index_daily:{trade_date}")
        return pd.DataFrame(
            [
                {"ts_code": "000001.SH", "trade_date": trade_date, "close": 3700.0, "pct_chg": 1.2, "amount": 100.0},
                {"ts_code": "399001.SZ", "trade_date": trade_date, "close": 12000.0, "pct_chg": 0.8, "amount": 100.0},
                {"ts_code": "399006.SZ", "trade_date": trade_date, "close": 2600.0, "pct_chg": 1.0, "amount": 100.0},
                {"ts_code": "000688.SH", "trade_date": trade_date, "close": 1000.0, "pct_chg": 1.0, "amount": 100.0},
            ]
        )

    def query(self, api_name: str, trade_date: str, **kwargs) -> pd.DataFrame:
        self.calls.append(f"{api_name}:{trade_date}")
        assert api_name == "sw_daily"
        return pd.DataFrame(
            [
                {"ts_code": "801010.SI", "name": "农林牧渔", "trade_date": trade_date, "pct_change": 2.3, "amount": 500.0},
                {"ts_code": "801020.SI", "name": "基础化工", "trade_date": trade_date, "pct_change": -1.1, "amount": 400.0},
                {"ts_code": "801030.SI", "name": "钢铁", "trade_date": trade_date, "pct_change": 0.2, "amount": 100.0},
            ]
        )


def pass_freshness() -> dict[str, object]:
    return {
        "status": "PASS",
        "latest_trade_date": "20260717",
        "latest_complete_trade_date": "20260717",
        "formal_recommendation_allowed": True,
        "data_is_latest_complete": True,
        "required_api_rows": {"daily": 3, "daily_basic": 3, "index_daily": 4, "sw_daily": 3},
    }


def test_snapshot_is_blocked_when_freshness_disallows_formal_recommendation() -> None:
    pro = FakeSnapshotPro()
    snapshot = build_verified_market_snapshot(
        pro=pro,
        freshness={
            "status": "WARN",
            "latest_trade_date": "20260717",
            "latest_complete_trade_date": "20260716",
            "formal_recommendation_allowed": False,
            "data_is_latest_complete": False,
            "required_api_rows": {"daily": 0, "daily_basic": 0, "index_daily": 0, "sw_daily": 439},
        },
    )

    assert snapshot["snapshot_status"] == "BLOCKED"
    assert snapshot["formal_recommendation_allowed"] is False
    assert snapshot["market"] == {}
    assert pro.calls == []


def test_snapshot_contains_market_breadth_indexes_and_top_sectors_when_freshness_passes() -> None:
    snapshot = build_verified_market_snapshot(pro=FakeSnapshotPro(), freshness=pass_freshness())

    assert snapshot["snapshot_status"] == "PASS"
    assert snapshot["trade_date"] == "20260717"
    assert snapshot["formal_recommendation_allowed"] is True
    assert snapshot["required_api_rows"] == {"daily": 3, "daily_basic": 3, "index_daily": 4, "sw_daily": 3}
    assert snapshot["market"]["state"] == "强"
    assert snapshot["market"]["breadth"] == {"up": 2, "down": 0, "flat": 1, "count": 3, "up_ratio": 2 / 3}
    assert snapshot["market"]["core_index_avg_pct_chg"] == 1.0
    assert snapshot["top_sw_sectors"][0]["name"] == "农林牧渔"
    assert snapshot["top_sw_sectors"][0]["pct_chg"] == 2.3


def test_write_snapshot_creates_dated_and_latest_files(tmp_path: Path) -> None:
    snapshot = build_verified_market_snapshot(pro=FakeSnapshotPro(), freshness=pass_freshness())

    paths = write_verified_market_snapshot(snapshot, output_dir=tmp_path)

    assert paths["dated"].name == "verified_market_snapshot_20260717.json"
    assert paths["latest"].name == "latest_verified_market_snapshot.json"
    assert json.loads(paths["latest"].read_text(encoding="utf-8"))["trade_date"] == "20260717"
