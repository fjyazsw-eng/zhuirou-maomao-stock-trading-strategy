from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    for rel in ("data/sqlite", "reports/demo", "reports/workflow", "logs", "runtime"):
        (ROOT / rel).mkdir(parents=True, exist_ok=True)
        print(f"[OK] directory: {rel}")
    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copyfile(ROOT / ".env.example", env_file)
        print("[OK] created .env from placeholders; no secrets were written")
    else:
        print("[OK] existing .env preserved")
    print("Database: set STOCK_AI_MARKET_DB or place data/sqlite/market_120d.sqlite.")
    print("Offline verification: python scripts/run_demo.py")
    print("Health check: python scripts/health_check.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
