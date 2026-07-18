from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _config(root: Path = ROOT) -> dict[str, Any]:
    path = root / "config" / "paths.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def data_dir(root: Path = ROOT) -> Path:
    value = os.environ.get("STOCK_AI_DATA_DIR") or _config(root).get("data_dir")
    return Path(value).expanduser() if value else root / "data"


def database_path(root: Path = ROOT) -> Path:
    value = os.environ.get("STOCK_AI_DATABASE_PATH") or _config(root).get("database_path")
    return Path(value).expanduser() if value else data_dir(root) / "sqlite" / "market_120d.sqlite"
