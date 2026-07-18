from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeliveryResult:
    platform: str
    session: str
    sent: bool
    detail: str


def _latest_session_store(data_dir: Path, project: str) -> Path:
    candidates = sorted(
        data_dir.joinpath("sessions").glob(f"{project}_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"CC Connect session store missing for {project}")
    return candidates[0]


def discover_active_sessions(data_dir: Path, project: str, platforms: list[str]) -> dict[str, str]:
    payload = json.loads(_latest_session_store(data_dir, project).read_text(encoding="utf-8"))
    active = payload.get("active_session") or {}
    sessions = payload.get("sessions") or {}
    result: dict[str, str] = {}
    for platform in platforms:
        candidates: list[tuple[str, str]] = []
        for route, session_id in active.items():
            if not str(route).startswith(f"{platform}:"):
                continue
            updated_at = str((sessions.get(session_id) or {}).get("updated_at") or "")
            candidates.append((updated_at, str(route)))
        if candidates:
            result[platform] = sorted(candidates, reverse=True)[0][1]
    return result


def send_via_cc_connect(
    message: str,
    project: str = "codex-weixin",
    platforms: list[str] | None = None,
    session_overrides: dict[str, str] | None = None,
    data_dir: Path | None = None,
    dry_run: bool = False,
) -> list[DeliveryResult]:
    targets = platforms or ["weixin", "feishu"]
    root = data_dir or Path(os.environ.get("CC_CONNECT_DATA_DIR", Path.home() / ".cc-connect"))
    active = discover_active_sessions(root, project, targets)
    for platform, session_id in (session_overrides or {}).items():
        if platform in targets and session_id:
            active[platform] = str(session_id)
    executable = shutil.which("cc-connect")
    results: list[DeliveryResult] = []
    for platform in targets:
        session_id = active.get(platform, "")
        if not session_id:
            results.append(DeliveryResult(platform, "", False, "active_session_missing"))
            continue
        if dry_run:
            results.append(DeliveryResult(platform, session_id, True, "dry_run"))
            continue
        if not executable:
            results.append(DeliveryResult(platform, session_id, False, "cc-connect executable missing"))
            continue
        try:
            proc = subprocess.run(
                [executable, "send", "-p", project, "-s", session_id, "--data-dir", str(root), "--stdin"],
                input=message,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            detail = (proc.stdout or proc.stderr or "").strip()[:500]
            results.append(DeliveryResult(platform, session_id, proc.returncode == 0, detail))
        except (subprocess.SubprocessError, OSError) as exc:
            results.append(DeliveryResult(platform, session_id, False, f"{type(exc).__name__}: {str(exc)[:400]}"))
    return results
