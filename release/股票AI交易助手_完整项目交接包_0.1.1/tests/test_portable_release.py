from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.portable_analysis import analyze_request
from scoring_system.portable_health import run_health
from scoring_system.project_paths import database_path


class PortableReleaseTests(unittest.TestCase):
    def test_required_skill_files_exist(self) -> None:
        required = [
            "README.md", "SETUP.md", "LICENSE", "VERSION", "CHANGELOG.md", ".env.example",
            "skills/stock-strategy-lab/SKILL.md", "skills/stock-strategy-lab/agents/openai.yaml",
            "skills/stock-strategy-lab/references/analysis-protocol.md",
            "config/realtime_watchlist.example.json", "scripts/stock_ai.py", "sample_data/demo_snapshot.json",
        ]
        self.assertEqual([], [item for item in required if not (ROOT / item).exists()])

    def test_key_markdown_links_resolve(self) -> None:
        missing: list[str] = []
        pattern = re.compile(r"\[[^]]+\]\(([^)#]+)(?:#[^)]+)?\)")
        for path in [ROOT / "README.md", ROOT / "SETUP.md", ROOT / "skills/stock-strategy-lab/SKILL.md"]:
            for target in pattern.findall(path.read_text(encoding="utf-8")):
                if "://" in target:
                    continue
                if not (path.parent / target).resolve().exists():
                    missing.append(f"{path.name}:{target}")
        self.assertEqual([], missing)

    def test_example_config_loads_and_contains_no_formal_holdings(self) -> None:
        payload = json.loads((ROOT / "config/realtime_watchlist.example.json").read_text(encoding="utf-8"))
        self.assertEqual([], payload["holding_watchlist"])
        self.assertEqual([], payload["watchlist"])
        self.assertIn("演示", payload["_notice"])

    def test_missing_environment_and_database_degrade_safely(self) -> None:
        keys = ["TUSHARE_TOKEN", "TUSHARE_TOKEN_PRO", "TUSHARE_REPLAY_API_KEY", "STOCK_AI_DATABASE_PATH"]
        with patch.dict(os.environ, {key: "" for key in keys}, clear=False):
            report = run_health(ROOT)
        self.assertIn(report["status"], {"PASS_WITH_WARNINGS", "FAIL"})
        names = {item["name"]: item for item in report["checks"]}
        self.assertEqual("WARN", names["tushare_token"]["status"])
        self.assertIn(names["database"]["status"], {"PASS", "WARN"})

    def test_no_database_analysis_has_date_field_and_stale_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"STOCK_AI_DATABASE_PATH": str(Path(tmp) / "missing.sqlite")}, clear=False):
            result = analyze_request({"task": "candidate_analysis"})
        self.assertIn("data_date", result)
        self.assertTrue(result["stale"])
        self.assertEqual("观察 / 数据不足", result["conclusion"])
        self.assertNotIn("自动下单", json.dumps(result, ensure_ascii=False))

    def test_unified_entry_help_and_demo(self) -> None:
        help_result = subprocess.run([sys.executable, "scripts/stock_ai.py", "--help"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, help_result.returncode)
        demo_result = subprocess.run([sys.executable, "scripts/stock_ai.py", "demo"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, demo_result.returncode)
        self.assertIn("DEMO DATA / 演示数据", demo_result.stdout)
        self.assertIn("不得用于真实交易决策", demo_result.stdout)

    def test_release_does_not_contain_secret_values_or_personal_paths(self) -> None:
        secret = re.compile(r"(?i)(token|api_key|app_secret|webhook)\s*=\s*['\"][^'\"]{8,}")
        personal_path = re.compile(r"[A-Za-z]:[\\/](?![\\/]|Software[\\/])")
        bad: list[str] = []
        for folder in [ROOT / "scoring_system", ROOT / "scripts", ROOT / "config", ROOT / "skills"]:
            for path in folder.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in {".py", ".ps1", ".json", ".yaml", ".yml", ".md"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                if secret.search(text) or personal_path.search(text):
                    bad.append(str(path.relative_to(ROOT)))
        self.assertEqual([], bad)

    def test_demo_and_skill_forbid_automatic_trading(self) -> None:
        skill = (ROOT / "skills/stock-strategy-lab/SKILL.md").read_text(encoding="utf-8")
        safety = (ROOT / "skills/stock-strategy-lab/references/safety-boundaries.md").read_text(encoding="utf-8")
        self.assertIn("Never place an order", skill)
        self.assertIn("Never enable automatic trading", safety)


if __name__ == "__main__":
    unittest.main()
