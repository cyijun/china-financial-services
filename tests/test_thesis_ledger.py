import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "plugins/vertical-plugins/china-research-methodology/skills/a-share-thesis-tracker/scripts/append_thesis_record.py"
SPEC = importlib.util.spec_from_file_location("append_thesis_record", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class ThesisLedgerTests(unittest.TestCase):
    def test_append_builds_and_verifies_hash_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "thesis.jsonl"
            first = module.append_record(ledger, {"version": 1, "state": "unknown"})
            second = module.append_record(ledger, {"version": 2, "state": "mixed"})
            self.assertIsNone(first["previous_hash"])
            self.assertEqual(second["previous_hash"], first["record_hash"])
            self.assertEqual(module.verify_chain(ledger), second["record_hash"])

    def test_mutation_is_detected_before_next_append(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "thesis.jsonl"
            module.append_record(ledger, {"version": 1})
            row = json.loads(ledger.read_text(encoding="utf-8"))
            row["record"]["version"] = 9
            ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                module.append_record(ledger, {"version": 2})


if __name__ == "__main__":
    unittest.main()
