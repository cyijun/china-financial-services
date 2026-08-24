import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "plugins/china-research-methodology/skills/a-share-research-evidence/scripts/build_evidence_manifest.py"
SPEC = importlib.util.spec_from_file_location("build_evidence_manifest", PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class EvidenceManifestTests(unittest.TestCase):
    def record(self, local_path):
        return {
            "evidence_id": "annual-report-2024",
            "source_type": "cninfo_filing",
            "source_url": "https://example.com/report.pdf",
            "document_date": "2025-03-20",
            "disclosed_at": "2025-03-20T18:30:00+08:00",
            "as_of": "2025-03-21T09:00:00+08:00",
            "locator": "p.42, revenue recognition policy",
            "claim": "revenue recognition uses acceptance",
            "local_path": str(local_path),
        }

    def test_local_original_is_hashed_and_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.pdf"
            path.write_bytes(b"primary evidence")
            report = module.build([self.record(path)])
            self.assertEqual(report["status"], "ready")
            self.assertEqual(report["evidence"][0]["source_tier"], "primary")
            self.assertEqual(len(report["evidence"][0]["content_sha256"]), 64)

    def test_future_disclosure_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.pdf"
            path.write_bytes(b"future")
            record = self.record(path)
            record["as_of"] = "2025-03-20T10:00:00+08:00"
            report = module.build([record])
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["counts"]["forbidden_future"], 1)


if __name__ == "__main__":
    unittest.main()
