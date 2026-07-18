from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scoring_system.env_loader import load_project_env, local_proxy_available

load_project_env()
WARNINGS: list[str] = []
ERRORS: list[str] = []


def ok(message: str) -> None:
    print(f"[OK] {message}")


def warn(message: str) -> None:
    WARNINGS.append(message)
    print(f"[WARN] {message}")


def fail(message: str) -> None:
    ERRORS.append(message)
    print(f"[FAIL] {message}")


def check_python() -> None:
    version = sys.version_info
    if version.major == 3 and 11 <= version.minor < 14:
        ok(f"Python version {version.major}.{version.minor}.{version.micro}")
    else:
        fail(f"Unsupported Python: {version.major}.{version.minor}.{version.micro}; require >=3.11,<3.14")


def check_dirs() -> None:
    ok(f"Working directory {ROOT}")
    for item in ["scoring_system", "scripts", "skills/stock_strategy_lab", "config", "examples"]:
        path = ROOT / item
        if path.exists():
            ok(f"Directory found: {item}")
        else:
            fail(f"Directory missing: {item}")


def check_imports() -> None:
    modules = [
        "scoring_system.sector_cycle_classifier",
        "scoring_system.execution_decision_engine",
        "scoring_system.position_sizing",
        "scoring_system.position_advisor",
        "scoring_system.holding_management",
        "scoring_system.stock_role_classifier",
        "scoring_system.account_position_manager",
    ]
    for module in modules:
        try:
            importlib.import_module(module)
            ok(f"Import {module}")
        except Exception as exc:
            fail(f"Import failed {module}: {type(exc).__name__}")


def check_files() -> None:
    checks = {
        "skills/stock_strategy_lab/SKILL.md": "skill found",
        "requirements.txt": "requirements.txt found",
        ".env.example": ".env.example found",
        "SETUP.md": "SETUP.md found",
    }
    for rel, label in checks.items():
        if (ROOT / rel).exists():
            ok(label)
        else:
            fail(f"{rel} missing")


def check_database() -> None:
    configured = os.environ.get("STOCK_AI_MARKET_DB", "data/sqlite/market_120d.sqlite")
    db = Path(configured)
    if not db.is_absolute():
        db = ROOT / db
    if db.exists():
        ok("Local database found")
    else:
        warn("database not found: place data/sqlite/market_120d.sqlite or rebuild data")


def check_walk_forward_db() -> None:
    configured = os.environ.get("STOCK_AI_WALK_FORWARD_DB", "").strip()
    if not configured:
        warn("STOCK_AI_WALK_FORWARD_DB not configured; walk-forward features unavailable")
        return
    db = Path(configured)
    if not db.is_absolute():
        db = ROOT / db
    if not db.exists():
        warn(f"walk-forward database not found: {db}")
        return
    try:
        uri = f"file:{quote(str(db))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.execute("select 1").fetchone()
        conn.close()
        ok("2025 database opens read-only")
    except Exception as exc:
        fail(f"2025 database read-only open failed: {type(exc).__name__}")


def check_token() -> None:
    token = os.environ.get("TUSHARE_REPLAY_API_KEY") or os.environ.get("TUSHARE_TOKEN") or os.environ.get("TUSHARE_TOKEN_PRO")
    if token:
        ok("Tushare credential configured (value hidden)")
    else:
        warn("TUSHARE_TOKEN not configured")


def check_proxy() -> None:
    http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if http or https:
        ok("proxy env found")
        return
    project_env = ROOT / ".codex" / ".env"
    if project_env.exists():
        stale: list[str] = []
        for line in project_env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "PROXY" not in line.upper() or "=" not in line:
                continue
            _key, value = line.split("=", 1)
            if not local_proxy_available(value.strip()):
                stale.append(value.strip())
        if stale:
            ok("stale local proxy skipped")
            return
    warn("proxy env not found; network calls may rely on system proxy only")


def check_report_write() -> None:
    report_dir = ROOT / "reports"
    report_dir.mkdir(exist_ok=True)
    target = report_dir / "health_check_test.md"
    try:
        target.write_text("# health check\n\nOK\n", encoding="utf-8")
        ok("report directory writable")
    except Exception as exc:
        fail(f"report directory not writable: {type(exc).__name__}")


def check_demo() -> None:
    proc = subprocess.run([sys.executable, "scripts/run_demo.py"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode == 0 and (ROOT / "reports/demo/demo_analysis_report.md").exists():
        ok("offline demo runnable")
    else:
        fail(f"offline demo failed: {proc.stderr[-300:]}")


def check_test_runner() -> None:
    try:
        importlib.import_module("pytest")
        ok("pytest available; run python -m pytest -q for full tests")
    except Exception:
        warn("pytest not installed; install requirements-dev.txt before running tests")


def main() -> int:
    check_python()
    check_dirs()
    check_imports()
    check_files()
    check_database()
    check_walk_forward_db()
    check_token()
    check_proxy()
    check_report_write()
    check_demo()
    check_test_runner()
    if os.environ.get("TUSHARE_REPLAY_API_KEY") or os.environ.get("TUSHARE_TOKEN") or os.environ.get("TUSHARE_TOKEN_PRO"):
        probe = subprocess.run([sys.executable, "scripts/tushare_realtime_probe.py"], cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace")
        if probe.returncode == 0:
            ok("Tushare data source reachable")
        else:
            warn(f"Tushare data source probe returned {probe.returncode}")
    else:
        warn("Tushare connectivity not tested because no credential is configured")
    if ERRORS:
        status = "FAIL"
        code = 2
    elif WARNINGS:
        status = "PASS_WITH_WARNINGS"
        code = 0
    else:
        status = "PASS"
        code = 0
    print(f"\nFinal status: {status}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
