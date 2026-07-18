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
    if version.major == 3 and version.minor >= 10:
        ok(f"Python version {version.major}.{version.minor}.{version.micro}")
    else:
        fail(f"Python version too old: {version.major}.{version.minor}.{version.micro}")


def check_dirs() -> None:
    ok(f"Working directory {ROOT}")
    for item in ["scoring_system", "scripts", "skills/stock_strategy_lab", "reports", "config"]:
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
    db = ROOT / "data" / "sqlite" / "market_120d.sqlite"
    if db.exists():
        ok("Local database found")
    else:
        warn("database not found: place data/sqlite/market_120d.sqlite or rebuild data")


def check_walk_forward_db() -> None:
    db = Path(r"D:\股票AI交易助手数据\sqlite\market_2025.sqlite")
    if not db.exists():
        warn("2025 database not found at D:/股票AI交易助手数据/sqlite/market_2025.sqlite")
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
    token = os.environ.get("TUSHARE_TOKEN", "")
    env_file = ROOT / ".env"
    has_env_hint = False
    if env_file.exists():
        text = env_file.read_text(encoding="utf-8", errors="ignore")
        has_env_hint = "TUSHARE_TOKEN" in text
    if token or has_env_hint:
        ok("TUSHARE_TOKEN configured or .env contains token key")
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
    probe = subprocess.run(
        [sys.executable, "scripts/tushare_realtime_probe.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if probe.stdout.strip():
        print(probe.stdout.strip())
    if probe.returncode == 2:
        fail("tushare_realtime_probe blocked")
    elif probe.returncode != 0:
        warn(f"tushare_realtime_probe returned {probe.returncode}")
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
