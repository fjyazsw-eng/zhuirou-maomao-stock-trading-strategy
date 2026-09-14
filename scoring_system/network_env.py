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

NO_PROXY_VALUE = "fuyao.aicubes.cn,127.0.0.1,localhost"


def proxy_snapshot() -> dict[str, str]:
    return {key: os.environ.get(key, "") for key in PROXY_KEYS + ["NO_PROXY", "no_proxy"]}


def clear_bad_tushare_proxy():
    return {'before': {}, 'removed': {}, 'after': {}}
