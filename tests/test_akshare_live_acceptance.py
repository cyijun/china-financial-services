import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "akshare_live_acceptance.py"
SPEC = importlib.util.spec_from_file_location("akshare_live_acceptance", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Result:
    records = [{"ts_code": "600519.SH", "trade_date": "20250801"}]
    metadata = {
        "interface": "stock_zh_a_hist",
        "permission_verified_live": True,
        "status": "full",
        "pit_grade": "trade_date",
        "units": {"vol": "lots", "amount": "thousand_CNY"},
    }


class AkshareLiveAcceptanceTests(unittest.TestCase):
    def test_result_entry_contains_digest_not_records(self):
        entry = MODULE._result_entry(
            "daily",
            "daily_bar",
            {"ts_code": "600519.SH"},
            Result(),
            min_rows=1,
            expected_interface="stock_zh_a_hist",
        )
        self.assertEqual(entry["status"], "pass")
        self.assertIn("response_sha256", entry)
        self.assertNotIn("records", entry)

    def test_contract_mismatch_fails(self):
        entry = MODULE._result_entry(
            "daily",
            "daily_bar",
            {},
            Result(),
            min_rows=2,
            expected_interface="wrong_interface",
        )
        self.assertEqual(entry["status"], "contract_failed")
        self.assertEqual(len(entry["issues"]), 2)

    def test_industry_symbol_supports_chinese_schema(self):
        class IndustryResult:
            records = [{"板块名称": "半导体"}]

        self.assertEqual(MODULE._industry_symbol(IndustryResult()), "半导体")


if __name__ == "__main__":
    unittest.main()
