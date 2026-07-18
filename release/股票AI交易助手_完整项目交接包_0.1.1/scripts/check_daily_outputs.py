from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
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


def newest(pattern: str) -> Path | None:
    files = sorted(REPORTS.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def check_file(rel: str, label: str) -> None:
    path = REPORTS / rel
    if path.exists() and path.stat().st_size > 0:
        ok(f"{label}: {path}")
    elif path.exists():
        warn(f"{label} exists but is empty: {path}")
    else:
        fail(f"{label} missing: {path}")


def check_glob(pattern: str, label: str) -> None:
    path = newest(pattern)
    if path and path.stat().st_size > 0:
        ok(f"{label}: {path}")
    elif path:
        warn(f"{label} exists but is empty: {path}")
    else:
        fail(f"{label} missing: reports/{pattern}")


def main() -> int:
    check_file("latest_market_decision_report.md", "latest_market_decision_report.md")
    check_file("latest_market_decision_dashboard.html", "latest_market_decision_dashboard.html")
    check_glob("advice/position_advice_*.md", "position advice found")
    check_glob("advice/account_position_advice_*.md", "account position advice found")

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
