#!/usr/bin/env python3
"""Strategy Lab data gateway: hithink-finance primary, mootdx minutes only."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scoring_system.market_data import main
if __name__ == '__main__':
    raise SystemExit(main())
