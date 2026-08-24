import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tushare_live_acceptance.py"
SPEC = importlib.util.spec_from_file_location("tushare_live_acceptance", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TushareLiveAcceptanceTests(unittest.TestCase):
    def test_sanitize_removes_token(self):
        self.assertNotIn("live-secret", MODULE._sanitize_text("bad live-secret token", "live-secret"))

    def test_permission_error_classification(self):
        self.assertEqual(MODULE._classify_error("抱歉，您没有权限访问该接口"), "permission_denied")
        self.assertEqual(MODULE._classify_error("抱歉，您没有接口(yc_cb)访问权限"), "permission_denied")

    def test_contract_evaluation_reports_schema_and_distinctness(self):
        spec = MODULE.CheckSpec(
            "vip",
            "income_vip",
            {},
            ("ts_code", "end_date"),
            min_rows=2,
            distinct_column="ts_code",
            min_distinct=2,
            expected_values={"end_date": "20241231"},
        )
        issues, metrics = MODULE._evaluate(
            spec,
            ("ts_code", "end_date"),
            [{"ts_code": "600000.SH", "end_date": "20241231"}, {"ts_code": "000001.SZ", "end_date": "20241231"}],
        )
        self.assertEqual(issues, [])
        self.assertEqual(metrics["distinct_ts_code"], 2)

    def test_documented_limit_drift_is_not_truncation(self):
        spec = MODULE.CheckSpec("history", "index_member_all", {}, ("ts_code",), documented_row_limit=2)
        issues, metrics = MODULE._evaluate(spec, ("ts_code",), [{"ts_code": "A"}, {"ts_code": "B"}, {"ts_code": "C"}])
        self.assertEqual(issues, [])
        self.assertFalse(metrics["possible_truncation"])
        self.assertTrue(metrics["documentation_limit_drift"])

    def test_optional_permission_gap_does_not_expose_records(self):
        class Client:
            def yc_cb(self, **_):
                raise RuntimeError("抱歉，您没有权限访问该接口")

        spec = MODULE.CheckSpec("yield", "yc_cb", {}, ("trade_date",), required=False)
        result, records = MODULE._run_check(Client(), spec, "secret")
        self.assertEqual(result["status"], "expected_permission_gap")
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
