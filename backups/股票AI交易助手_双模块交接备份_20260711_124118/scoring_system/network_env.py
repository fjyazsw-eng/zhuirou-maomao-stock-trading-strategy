from __future__ import annotations

import os
from typing import Any

PROXY_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]

NO_PROXY_VALUE = "api.waditu.com,127.0.0.1,localhost"


def proxy_snapshot() -> dict[str, str]:
    return {key: os.environ.get(key, "") for key in PROXY_KEYS + ["NO_PROXY", "no_proxy"]}


def clear_bad_tushare_proxy() -> dict[str, Any]:
    before = proxy_snapshot()
    removed: dict[str, str] = {}
    for key in PROXY_KEYS:
        value = os.environ.get(key, "")
        if "127.0.0.1:9" in value:
            removed[key] = value
            os.environ.pop(key, None)
    existing_no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    parts = [part.strip() for part in existing_no_proxy.split(",") if part.strip()]
    for part in NO_PROXY_VALUE.split(","):
        if part not in parts:
            parts.append(part)
    merged = ",".join(parts)
    os.environ["NO_PROXY"] = merged
    os.environ["no_proxy"] = merged
    return {"before": before, "removed": removed, "after": proxy_snapshot()}
