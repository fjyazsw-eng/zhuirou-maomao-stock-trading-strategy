from __future__ import annotations

import json
from pathlib import Path

from scoring_system import conversation_entry as ce


def write_snapshot(root: Path, *, status: str = "PASS", allowed: bool = True, market_state: str = "极弱") -> None:
    path = root / "fast_context" / "latest_verified_market_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "snapshot_status": status,
                "trade_date": "20260717",
                "formal_recommendation_allowed": allowed,
                "data_is_latest_complete": allowed,
                "required_api_rows": {"daily": 5522, "daily_basic": 5522, "index_daily": 1291, "sw_daily": 439},
                "freshness": {
                    "status": status,
                    "endpoint": "https://ts.gyzcloud.top/api",
                    "latest_trade_date": "20260717",
                    "latest_complete_trade_date": "20260717" if allowed else "20260716",
                    "data_is_latest_complete": allowed,
                    "formal_recommendation_allowed": allowed,
                    "message": "latest trade date has complete Tushare rows" if allowed else "blocked by freshness gate",
                    "required_api_rows": {"daily": 5522 if allowed else 0, "daily_basic": 5522 if allowed else 0, "index_daily": 1291 if allowed else 0, "sw_daily": 439},
                },
                "market": {
                    "state": market_state,
                    "breadth": {"up": 482, "down": 5001, "flat": 39, "count": 5522, "up_ratio": 0.08728721477725462},
                    "core_index_avg_pct_chg": -5.676324999999999,
                },
                "top_sw_sectors": [
                    {"code": "801780.SI", "name": "银行", "pct_chg": 0.9, "amount": 4004113.0},
                    {"code": "851112.SI", "name": "空调", "pct_chg": 0.81, "amount": 676698.0},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def patch_paths(monkeypatch, tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    out_dir = reports / "conversation"
    monkeypatch.setattr(ce, "REPORTS", reports)
    monkeypatch.setattr(ce, "OUT_DIR", out_dir)
    monkeypatch.setattr(ce, "USER_CONTEXT_PATH", out_dir / "user_context.json")
    monkeypatch.setattr(ce, "ensure_fresh_reports", lambda: None)


def test_answer_uses_verified_snapshot_for_candidate_market_gate(monkeypatch, tmp_path: Path) -> None:
    patch_paths(monkeypatch, tmp_path)
    write_snapshot(tmp_path / "reports")

    text = ce.answer("推荐板块和个股")

    assert "Tushare状态| 正常" in text
    assert "最新交易日| 20260717" in text
    assert "行情落点| 20260717" in text
    assert "市场状态：极弱" in text
    assert "今天 / 下一交易日可以轻仓试错：没有" in text
    assert "银行 +0.90%" in text
    assert "空调 +0.81%" in text


def test_answer_blocks_when_verified_snapshot_is_not_fresh(monkeypatch, tmp_path: Path) -> None:
    patch_paths(monkeypatch, tmp_path)
    write_snapshot(tmp_path / "reports", status="WARN", allowed=False)

    text = ce.answer("推荐板块和个股")

    assert "Tushare状态| 异常 / 待确认" in text
    assert "先不做新的确定性买入判断" in text
    assert "blocked by freshness gate" in text
