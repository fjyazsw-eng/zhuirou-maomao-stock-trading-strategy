from __future__ import annotations

import os
import socket
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILES = [ROOT / ".env", ROOT / ".codex" / ".env"]
PROXY_KEYS = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"}


def local_proxy_available(value: str) -> bool:
    if "127.0.0.1:" not in value and "localhost:" not in value:
        return True
    try:
        host_port = value.split("://", 1)[-1].split("/", 1)[0]
        host, port_text = host_port.rsplit(":", 1)
        host = "127.0.0.1" if host == "localhost" else host
        port = int(port_text)
    except Exception:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def load_project_env(override: bool = False) -> list[str]:
    """Load simple KEY=VALUE pairs from project env files.

    Values are not returned, only loaded key names, so callers can report
    whether config was discovered without leaking secrets.
    """
    loaded: list[str] = []
    for path in ENV_FILES:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if key in PROXY_KEYS and not local_proxy_available(value):
                continue
            if override or key not in os.environ:
                os.environ[key] = value
                loaded.append(key)
    return loaded
