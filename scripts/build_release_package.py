from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.1"
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
RELEASE = ROOT / "release"
BASE = RELEASE / "stock-strategy-lab-skill-0.1.0"
STAGE = RELEASE / f"股票AI交易助手_完整项目交接包_{VERSION}"
ZIP_PATH = RELEASE / f"股票AI交易助手_完整项目交接包_{VERSION}_{STAMP}.zip"


def copy(rel: str) -> None:
    source = ROOT / rel
    target = STAGE / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.sqlite", ".pytest_cache"))
    else:
        shutil.copy2(source, target)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_generated() -> None:
    for path in sorted(STAGE.rglob("__pycache__"), reverse=True):
        shutil.rmtree(path, ignore_errors=True)
    for rel in (".pytest_cache", "reports", "data", "logs", "runtime", ".venv"):
        shutil.rmtree(STAGE / rel, ignore_errors=True)
    for name in (".env",):
        path = STAGE / name
        if path.exists():
            path.unlink()


def write_manifest() -> None:
    files = sorted(p for p in STAGE.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {
        "package_name": STAGE.name,
        "version": VERSION,
        "build_time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_commit": None,
        "python": ">=3.11,<3.14",
        "secrets_included": False,
        "market_database_included": False,
        "demo_data_included": True,
        "file_count": len(files),
        "files": {p.relative_to(STAGE).as_posix(): digest(p) for p in files},
    }
    (STAGE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    shutil.copytree(BASE, STAGE, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "manifest.json"))
    for rel in [
        "README.md", "SETUP.md", ".env.example", ".gitignore", "requirements.txt", "requirements-dev.txt", "pyproject.toml",
        "PROJECT_CONTEXT.md", "股票分析工程文件.md", "DAILY_WORKFLOW.md", "REALTIME_WATCH_MONITOR.md",
        "docs/项目总设计.md", "docs/功能路线图.md", "docs/交易决策框架.md", "open_latest_dashboard.bat",
        "examples", "scripts/bootstrap_project.py", "scripts/run_demo.py", "scripts/release_check.py",
        "scripts/health_check.py", "scripts/check_daily_outputs.py", "scripts/run_daily_workflow.py",
    ]:
        copy(rel)
    obsolete_health = STAGE / "scripts" / "check_codex_runtime_health.ps1"
    if obsolete_health.exists():
        obsolete_health.unlink()
    shutil.copytree(STAGE / "skills" / "stock-strategy-lab", STAGE / "skills" / "stock_strategy_lab", dirs_exist_ok=True)
    write_manifest()
    proc = __import__("subprocess").run([sys.executable, "scripts/release_check.py"], cwd=STAGE)
    if proc.returncode:
        return proc.returncode
    clean_generated()
    write_manifest()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, f"{STAGE.name}/{path.relative_to(STAGE).as_posix()}")
    print(ZIP_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
