import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "plugins/china-research-methodology/skills/a-share-thesis-tracker/scripts/append_thesis_record.py"
SPEC = importlib.util.spec_from_file_location("append_thesis_record", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class ThesisLedgerTests(unittest.TestCase):
    def record(self, version, state="unknown"):
        return {
            "version": version,
            "as_of": "2026-08-24T16:00:00+08:00",
            "core_thesis": "testable thesis",
            "pillars": [],
            "counterevidence": [],
            "status": state,
        }

    def test_append_builds_and_verifies_hash_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "thesis.jsonl"
            first = module.append_record(ledger, self.record(1))
            second = module.append_record(ledger, self.record(2, "mixed"))
            self.assertIsNone(first["previous_hash"])
            self.assertEqual(second["previous_hash"], first["record_hash"])
            self.assertEqual(module.verify_chain(ledger), second["record_hash"])

    def test_mutation_is_detected_before_next_append(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "thesis.jsonl"
            module.append_record(ledger, self.record(1))
            row = json.loads(ledger.read_text(encoding="utf-8"))
            row["record"]["version"] = 9
            ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                module.append_record(ledger, self.record(2))

    def test_schema_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                module.append_record(Path(directory) / "thesis.jsonl", {"version": 1})

    def test_concurrent_cli_appends_keep_one_valid_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "thesis.jsonl"
            processes = [
                subprocess.Popen(
                    [sys.executable, str(MODULE_PATH), str(ledger), "--record", json.dumps(self.record(index))],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for index in range(1, 9)
            ]
            for process in processes:
                _, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 8)
            self.assertIsNotNone(module.verify_chain(ledger))


if __name__ == "__main__":
    unittest.main()
