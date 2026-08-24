import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preflight.py"
SPEC = importlib.util.spec_from_file_location("preflight", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PreflightTests(unittest.TestCase):
    def test_tushare_live_checks_only_its_runtime_and_token(self):
        imported = []

        def fake_import(name):
            imported.append(name)
            return object()

        with patch.object(MODULE.importlib, "import_module", side_effect=fake_import), patch.dict(os.environ, {"TUSHARE_TOKEN": "present"}):
            self.assertEqual(MODULE.run("tushare-live"), [])
        self.assertEqual(set(imported), {"pandas", "tushare"})

    def test_akshare_live_does_not_require_tushare_token(self):
        with patch.object(MODULE.importlib, "import_module", return_value=object()), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(MODULE.run("akshare-live"), [])

    def test_missing_tushare_token_fails_without_exposing_value(self):
        with patch.object(MODULE.importlib, "import_module", return_value=object()), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(MODULE.run("tushare-live"), ["TUSHARE_TOKEN environment variable is not configured"])


if __name__ == "__main__":
    unittest.main()
