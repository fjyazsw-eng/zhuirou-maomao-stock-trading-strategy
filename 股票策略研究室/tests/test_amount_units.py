from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from amount_units import tushare_amount_to_wanyi, tushare_amount_to_yi


class TushareAmountUnitTest(unittest.TestCase):
    def test_tushare_amount_100000_qianyuan_equals_1_yi(self) -> None:
        self.assertEqual(tushare_amount_to_yi(100000), 1)

    def test_tushare_amount_100000_qianyuan_equals_0_0001_wanyi(self) -> None:
        self.assertEqual(tushare_amount_to_wanyi(100000), 0.0001)


if __name__ == "__main__":
    unittest.main()
