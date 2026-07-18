from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SENSITIVE_WORDS = [
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "auth",
    "cookie",
    "authorization",
    "TUSHARE_TOKEN",
    "FEISHU_WEBHOOK",
    "TELEGRAM_BOT_TOKEN",
]

EXCLUDED_NAMES = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".git",
    "auth.json",
    ".env",
    "config.toml",
    "push_channels.json",
    "telegram_bot.json",
}

TEXT_EXTS = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".example",
    ".bat",
}

ASSIGNMENT_RE = re.compile(
    r"(?i)(token|secret|password|passwd|api_key|apikey|authorization|cookie|webhook)\s*[:=]\s*['\"]?([^'\"\s]+)"
)
PLACEHOLDER_WORDS = ("example", "placeholder", "your_", "请在这里", "可选", "填写", "dummy", "xxx")
CODE_REFERENCE_WORDS = ("os.environ", "getenv", "config", "read", "load", "none", "true", "false", "optional", "placeholder")
SECRET_SHAPE_RE = re.compile(
    r"(?i)(^sk-[A-Za-z0-9_-]{16,}|^\d{8,}:[A-Za-z0-9_-]{20,}|open-apis/bot/v2/hook/[A-Za-z0-9-]{20,}|[A-Za-z0-9_/-]{32,})"
)


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_NAMES for part in path.parts)


def is_template(path: Path) -> bool:
    lowered = str(path).lower()
    return "example" in lowered or "template" in lowered or path.name in {".env.example"}


def scan_file(path: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if path.suffix.lower() not in TEXT_EXTS and path.name != ".env.example":
        return findings
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings
    for match in ASSIGNMENT_RE.finditer(text):
        value = match.group(2)
        lower_value = value.lower()
        if is_template(path) or any(x in lower_value for x in PLACEHOLDER_WORDS):
            severity = "template_allowed"
        elif path.suffix.lower() == ".py" and any(x in lower_value for x in CODE_REFERENCE_WORDS):
            severity = "code_reference"
        elif SECRET_SHAPE_RE.search(value) and not any(x in lower_value for x in CODE_REFERENCE_WORDS):
            severity = "high"
        else:
            severity = "code_reference"
        findings.append({"file": str(path), "risk": match.group(1), "severity": severity})
    return findings


def scan(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if is_excluded(rel):
            continue
        if path.is_file():
            findings.extend(scan_file(path))
    return findings


def write_report(root: Path, findings: list[dict[str, str]], output: Path) -> None:
    lines = [
        "# Portable Sanitize Report",
        "",
        f"- Scan root: {root}",
        f"- Findings: {len(findings)}",
        "",
    ]
    if findings:
        lines.append("| File | Risk Type | Severity |")
        lines.append("| -- | -- | -- |")
        for item in findings:
            lines.append(f"| {item['file']} | {item['risk']} | {item['severity']} |")
    else:
        lines.append("No suspicious sensitive assignments found.")
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan portable package files for sensitive assignments")
    parser.add_argument("--root", default=".", help="Root directory to scan")
    parser.add_argument("--output", default="portable_sanitize_report.md", help="Report path")
    parser.add_argument("--json", dest="json_path", default="", help="Optional JSON report path")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output).resolve()
    findings = scan(root)
    write_report(root, findings, output)
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")
    high = [x for x in findings if x["severity"] == "high"]
    print(json.dumps({"root": str(root), "findings": len(findings), "high": len(high), "report": str(output)}, ensure_ascii=False, indent=2))
    return 1 if high else 0


if __name__ == "__main__":
    raise SystemExit(main())
