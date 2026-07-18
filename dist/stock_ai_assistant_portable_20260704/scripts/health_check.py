from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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
    check_token()
    check_report_write()
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
