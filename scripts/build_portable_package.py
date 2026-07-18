from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATE = datetime.now().strftime("%Y%m%d")
PACKAGE_NAME = f"stock_ai_assistant_portable_{DATE}"
DIST_DIR = ROOT / "dist"
BUILD_ROOT = DIST_DIR / PACKAGE_NAME
ZIP_PATH = DIST_DIR / f"{PACKAGE_NAME}.zip"
REPORT_PATH = DIST_DIR / f"{PACKAGE_NAME}_build_report.md"

EXCLUDE_DIRS = {".venv", "__pycache__", ".pytest_cache", ".git", "cache"}
EXCLUDE_FILES = {"auth.json", ".env", "config.toml", "push_channels.json", "telegram_bot.json"}
EXCLUDE_SUFFIXES = {".token", ".key", ".secret"}


def should_skip(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    if path.name in EXCLUDE_FILES:
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    return False


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if should_skip(rel):
            continue
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def copy_file(src: Path, dst: Path) -> None:
    if src.exists() and not should_skip(src):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def prepare_build_root() -> None:
    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    BUILD_ROOT.mkdir(parents=True)
    for rel in [
        "README_PORTABLE.md",
        "SETUP.md",
        "MIGRATION_CHECKLIST.md",
        "PROJECT_STATUS.md",
        "TEST_PLAN_2025.md",
        "DAILY_WORKFLOW.md",
        "REPORT_READING_GUIDE.md",
        ".env.example",
        "requirements.txt",
        "README.md",
    ]:
        copy_file(ROOT / rel, BUILD_ROOT / rel)
    for rel in ["skills", "scoring_system", "scripts"]:
        copy_tree(ROOT / rel, BUILD_ROOT / rel)


def prepare_config_templates() -> None:
    dst = BUILD_ROOT / "config_templates"
    dst.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / "config").glob("*"):
        if path.name in {"push_channels.json", "telegram_bot.json"}:
            continue
        if path.is_file() and not should_skip(path):
            shutil.copy2(path, dst / path.name)
    (dst / "README.md").write_text(
        "# config_templates\n\n这里只放非敏感配置模板。真实 token、webhook、cookie 不应放入迁移包。\n",
        encoding="utf-8",
    )


def prepare_reports_sample() -> None:
    dst = BUILD_ROOT / "reports_sample"
    dst.mkdir(parents=True, exist_ok=True)
    samples = [
        "latest_market_decision_dashboard.html",
        "latest_market_decision_report.md",
        "latest_market_decision_report.json",
        "advice/position_advice_20260702.md",
        "advice/account_position_advice_20260702.md",
        "workflow/daily_workflow_latest.md",
        "daily_workflow_sample.md",
        "holding/holding_mvp_validation_20260704.md",
        "stock_role/stock_role_mvp_validation_20260704.md",
        "execution/execution_mvp_validation_20260704.md",
        "exam_v2/exam8b_sector_cycle_observation_report_20260704.md",
    ]
    for rel in samples:
        copy_file(ROOT / "reports" / rel, dst / rel)
    (dst / "README.md").write_text(
        "# reports_sample\n\n这里只保存最近样例报告，完整历史报告不默认打包。\n",
        encoding="utf-8",
    )


def prepare_data_placeholder() -> None:
    dst = BUILD_ROOT / "data_placeholder"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "README.md").write_text(
        "# data_placeholder\n\n数据库默认不打包。请在新电脑放置 `data/sqlite/market_120d.sqlite`，或按项目脚本重新拉取/重建数据。\n",
        encoding="utf-8",
    )


def run_sanitize() -> tuple[bool, str]:
    report = BUILD_ROOT / "portable_sanitize_report.md"
    json_report = BUILD_ROOT / "portable_sanitize_report.json"
    cmd = [
        sys.executable,
        str(BUILD_ROOT / "scripts" / "sanitize_for_portable.py"),
        "--root",
        str(BUILD_ROOT),
        "--output",
        str(report),
        "--json",
        str(json_report),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    return proc.returncode == 0, proc.stdout + proc.stderr


def make_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in BUILD_ROOT.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(DIST_DIR))


def write_report(sanitize_ok: bool, sanitize_output: str) -> None:
    size_mb = ZIP_PATH.stat().st_size / 1024 / 1024 if ZIP_PATH.exists() else 0
    lines = [
        "# Portable Build Report",
        "",
        f"- Package: {PACKAGE_NAME}",
        f"- Zip: {ZIP_PATH}",
        f"- Size MB: {size_mb:.2f}",
        f"- Sanitize OK: {sanitize_ok}",
        "",
        "## Included top-level directories",
        "",
        "- skills",
        "- scoring_system",
        "- scripts",
        "- config_templates",
        "- reports_sample",
        "- data_placeholder",
        "",
        "## Excluded",
        "",
        "- .venv",
        "- __pycache__",
        "- .pytest_cache",
        "- .git",
        "- .env",
        "- auth.json",
        "- config.toml",
        "- real webhook/token config files",
        "- full data directory",
        "",
        "## Sanitize output",
        "",
        "```text",
        sanitize_output.strip(),
        "```",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    DIST_DIR.mkdir(exist_ok=True)
    prepare_build_root()
    prepare_config_templates()
    prepare_reports_sample()
    prepare_data_placeholder()
    sanitize_ok, sanitize_output = run_sanitize()
    if not sanitize_ok:
        write_report(False, sanitize_output)
        print(json.dumps({"status": "FAILED_SANITIZE", "report": str(REPORT_PATH)}, ensure_ascii=False, indent=2))
        return 2
    make_zip()
    write_report(True, sanitize_output)
    print(json.dumps({"status": "OK", "zip": str(ZIP_PATH), "report": str(REPORT_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
