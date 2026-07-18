from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md", "SETUP.md", ".env.example", ".gitignore", "requirements.txt",
    "requirements-dev.txt", "pyproject.toml", "scripts/bootstrap_project.py",
    "scripts/health_check.py", "scripts/run_demo.py", "scripts/release_check.py",
    "examples/demo_market_data.json", "examples/demo_holdings.json",
]
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".yaml", ".yml", ".txt", ".bat", ".ps1"}
EXCLUDED_PARTS = {".venv", "__pycache__", ".pytest_cache", "logs", "runtime", "reports", "data"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_files() -> list[Path]:
    return sorted(
        p for p in ROOT.rglob("*")
        if p.is_file() and p.name not in {"manifest.json", ".env"} and not EXCLUDED_PARTS.intersection(p.relative_to(ROOT).parts)
    )


def main() -> int:
    errors: list[str] = []
    for rel in REQUIRED:
        if not (ROOT / rel).is_file():
            errors.append(f"missing required file: {rel}")
    personal = re.compile(r"(?i)([A-Z]" + r":[\\/]Users[\\/][^\\/]+|[A-Z]" + r":[\\/]股票AI交易助手数据|codex" + r"-runtimes)")
    secret = re.compile(r"(?i)(sk-[a-z0-9_-]{16,}|https://[^\s\"']+(?:webhook|hook)[^\s\"']*|\d{6,}:[a-z0-9_-]{20,})")
    for path in package_files():
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in {".sqlite", ".sqlite3", ".log", ".pyc"}:
            errors.append(f"forbidden packaged file: {rel}")
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if personal.search(text):
                errors.append(f"personal absolute path: {rel}")
            if secret.search(text):
                errors.append(f"possible secret value: {rel}")
    for path in [ROOT / "README.md", ROOT / "SETUP.md"]:
        if not path.exists():
            continue
        for target in re.findall(r"\[[^]]+\]\(([^)#]+)", path.read_text(encoding="utf-8")):
            if "://" not in target and not (path.parent / target).exists():
                errors.append(f"broken markdown link: {path.name} -> {target}")
    for command, label in [
        ([sys.executable, "-m", "compileall", "-q", "scoring_system", "scripts", "tests"], "compile"),
        ([sys.executable, "scripts/run_demo.py"], "demo"),
        ([sys.executable, "-m", "pytest", "-q"], "pytest"),
    ]:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            errors.append(f"{label} failed: {(proc.stdout + proc.stderr)[-500:]}")
    manifest_path = ROOT / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual = {p.relative_to(ROOT).as_posix(): digest(p) for p in package_files()}
        if manifest.get("file_count") != len(actual):
            errors.append("manifest file_count mismatch")
        if manifest.get("files") != actual:
            errors.append("manifest hashes mismatch")
    else:
        errors.append("manifest.json missing")
    status = "NOT_RELEASE_READY" if errors else "RELEASE_READY"
    print(status)
    for item in errors:
        print(f"- {item}")
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
