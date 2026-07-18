from __future__ import annotations

import pandas as pd
import pytest

from scoring_system.tushare_freshness_agent import evaluate_freshness


def frame(rows: int, **cols: object) -> pd.DataFrame:
    payload = {key: [value] * rows for key, value in cols.items()}
    if not payload:
        payload = {"x": list(range(rows))}
    return pd.DataFrame(payload)


class FakeTusharePro:
    def __init__(self, rows_by_api_date: dict[tuple[str, str], int], raise_on: tuple[str, str] | None = None) -> None:
        self.rows_by_api_date = rows_by_api_date
        self.raise_on = raise_on
        self.calls: list[tuple[str, str]] = []

    def trade_cal(self, **kwargs) -> pd.DataFrame:
        self.calls.append(("trade_cal", ""))
        return pd.DataFrame(
            [
                {"cal_date": "20260716", "is_open": 1},
                {"cal_date": "20260717", "is_open": 1},
            ]
        )

    def daily(self, trade_date: str, **kwargs) -> pd.DataFrame:
        return self._dated("daily", trade_date)

    def daily_basic(self, trade_date: str, **kwargs) -> pd.DataFrame:
        return self._dated("daily_basic", trade_date)

    def index_daily(self, trade_date: str, **kwargs) -> pd.DataFrame:
        return self._dated("index_daily", trade_date)

    def query(self, api_name: str, trade_date: str, **kwargs) -> pd.DataFrame:
        assert api_name == "sw_daily"
        return self._dated("sw_daily", trade_date)

    def _dated(self, api_name: str, trade_date: str) -> pd.DataFrame:
        self.calls.append((api_name, trade_date))
        if self.raise_on == (api_name, trade_date):
            raise RuntimeError("http_429: 并发请求过多")
        return frame(self.rows_by_api_date.get((api_name, trade_date), 0), trade_date=trade_date)


def test_passes_when_latest_trade_date_has_all_required_rows() -> None:
    pro = FakeTusharePro(
        {
            ("daily", "20260717"): 5522,
            ("daily_basic", "20260717"): 5522,
            ("index_daily", "20260717"): 1291,
            ("sw_daily", "20260717"): 439,
        }
    )

    result = evaluate_freshness(pro=pro, today="20260717", min_daily_rows=5000, min_index_rows=3, min_sw_rows=100)

    assert result["status"] == "PASS"
    assert result["latest_trade_date"] == "20260717"
    assert result["latest_complete_trade_date"] == "20260717"
    assert result["formal_recommendation_allowed"] is True
    assert result["data_is_latest_complete"] is True
    assert result["required_api_rows"] == {
        "daily": 5522,
        "daily_basic": 5522,
        "index_daily": 1291,
        "sw_daily": 439,
    }


def test_blocks_formal_recommendation_when_latest_trade_date_is_missing_rows() -> None:
    pro = FakeTusharePro(
        {
            ("daily", "20260717"): 0,
            ("daily_basic", "20260717"): 0,
            ("index_daily", "20260717"): 0,
            ("sw_daily", "20260717"): 439,
            ("daily", "20260716"): 5524,
            ("daily_basic", "20260716"): 5524,
            ("index_daily", "20260716"): 1280,
            ("sw_daily", "20260716"): 439,
        }
    )

    result = evaluate_freshness(pro=pro, today="20260717", min_daily_rows=5000, min_index_rows=3, min_sw_rows=100)

    assert result["status"] == "WARN"
    assert result["latest_trade_date"] == "20260717"
    assert result["latest_complete_trade_date"] == "20260716"
    assert result["formal_recommendation_allowed"] is False
    assert result["data_is_latest_complete"] is False
    assert result["required_api_rows"]["daily"] == 0
    assert "latest trade date missing complete Tushare rows" in result["message"]


def test_stops_after_rate_limit_and_blocks_formal_recommendation() -> None:
    pro = FakeTusharePro({}, raise_on=("daily", "20260717"))

    result = evaluate_freshness(pro=pro, today="20260717", min_daily_rows=5000, min_index_rows=3, min_sw_rows=100)

    assert result["status"] == "BLOCKED"
    assert result["error_category"] == "RATE_LIMITED"
    assert result["formal_recommendation_allowed"] is False
    assert result["latest_complete_trade_date"] == ""
    assert ("daily_basic", "20260717") not in pro.calls
    assert "http_429" in result["message"]
