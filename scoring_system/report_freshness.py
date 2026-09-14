from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SCORES = ROOT / "data" / "processed" / "scores"
DECISIONS = ROOT / "data" / "processed" / "decisions"
STATUS_PATH = REPORTS / "tushare" / "latest_tushare_status.json"
REPORT_PATH = REPORTS / "latest_market_decision_report.md"
REFRESH_STATE_PATH = REPORTS / "workflow" / "latest_refresh_state.json"
REFRESH_SCRIPT = ROOT / "scripts" / "refresh_latest_market_pipeline.py"


def read_tushare_status():
    path=ROOT / 'reports/fast_context/latest_verified_market_snapshot.json'
    try:
        payload=json.loads(path.read_text(encoding='utf-8'))
        from scoring_system.market_data import require_current_source
        require_current_source(payload)
        return dict(payload.get('freshness') or {})
    except (OSError, ValueError, RuntimeError, TypeError):
        return {'status':'BLOCKED','message':'No verified hithink-finance cache; retired cache rejected'}



def extract_report_date() -> str:
    if not REPORT_PATH.exists():
        return ""
    text = REPORT_PATH.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"最新市场决策报告\s+(\d{8})", text)
    return match.group(1) if match else ""


def report_has_placeholder_content() -> bool:
    if not REPORT_PATH.exists():
        return True
    text = REPORT_PATH.read_text(encoding="utf-8", errors="replace")
    placeholder_markers = [
        "大盘天气评分：- / -",
        "上涨家数：-",
        "下跌家数：-",
        "今日成交：-",
    ]
    return any(marker in text for marker in placeholder_markers)


def latest_date_from_pattern(folder: Path, pattern: str) -> str:
    dates: list[str] = []
    for path in folder.glob(pattern):
        match = re.search(r"(\d{8})", path.name)
        if match:
            dates.append(match.group(1))
    return max(dates) if dates else ""


def freshness_snapshot() -> dict[str, str]:
    return {
        "report_date": extract_report_date(),
        "market_score_date": latest_date_from_pattern(SCORES, "market_sector_score_*_calibrated.json"),
        "sector_score_date": latest_date_from_pattern(SCORES, "sector_scores_*_calibrated.csv"),
        "leader_score_date": latest_date_from_pattern(SCORES, "leader_scores_*.csv"),
        "stock_score_date": latest_date_from_pattern(SCORES, "stock_scores_*.csv"),
        "decision_date": latest_date_from_pattern(DECISIONS, "decision_results_*.csv"),
    }


def refresh_needed() -> tuple[bool, str, dict[str, str], dict[str, Any]]:
    status = read_tushare_status()
    latest_trade_date = str(status.get("latest_trade_date", ""))
    snapshot = freshness_snapshot()
    if not latest_trade_date:
        return False, "missing_latest_trade_date", snapshot, status
    if str(status.get("status")) != "PASS":
        return False, "tushare_not_ready", snapshot, status
    if report_has_placeholder_content():
        return True, "report_placeholder_content", snapshot, status
    for key, value in snapshot.items():
        if value < latest_trade_date:
            return True, f"{key}_stale", snapshot, status
    return False, "fresh", snapshot, status


def _read_refresh_state() -> dict[str, Any]:
    if not REFRESH_STATE_PATH.exists():
        return {}
    try:
        return json.loads(REFRESH_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_refresh_state(payload: dict[str, Any]) -> None:
    REFRESH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFRESH_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_fresh_reports(min_interval_seconds: int = 600, timeout_seconds: int = 240) -> dict[str, Any]:
    needed, reason, snapshot, status = refresh_needed()
    result: dict[str, Any] = {
        "refresh_needed": needed,
        "reason": reason,
        "snapshot": snapshot,
        "tushare_status": status,
        "refreshed": False,
    }
    if not needed:
        return result

    latest_trade_date = str(status.get("latest_trade_date", ""))
    state = _read_refresh_state()
    now_ts = int(time.time())
    last_attempt = int(state.get("last_attempt_ts", 0))
    last_target = str(state.get("latest_trade_date", ""))
    if last_target == latest_trade_date and now_ts - last_attempt < min_interval_seconds:
        result["skipped"] = "recent_attempt_exists"
        return result

    cmd = [sys.executable, str(REFRESH_SCRIPT), "--target-date", latest_trade_date]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )
    _write_refresh_state(
        {
            "last_attempt_ts": now_ts,
            "latest_trade_date": latest_trade_date,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    )
    result["refresh_returncode"] = proc.returncode
    result["stdout_tail"] = proc.stdout[-800:]
    result["stderr_tail"] = proc.stderr[-800:]
    result["refreshed"] = proc.returncode == 0
    return result
