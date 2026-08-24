import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "plugins/vertical-plugins/china-research-methodology/skills/china-market-data/scripts/china_market_data.py"
SPEC = importlib.util.spec_from_file_location("china_market_data", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient="records"):
        assert orient == "records"
        return self.rows


class FakeTushare:
    def __init__(self):
        self.calls = []

    def income_vip(self, **params):
        self.calls.append(("income_vip", params))
        return FakeFrame([
            {"ts_code": "600000.SH", "end_date": "20241231", "ann_date": "20250320", "f_ann_date": "20250321", "update_flag": "0"},
            {"ts_code": "000001.SZ", "end_date": "20241231", "ann_date": "20250329", "f_ann_date": "20250402", "update_flag": "1"},
            {"ts_code": "600519.SH", "end_date": "20241231", "ann_date": None, "f_ann_date": None},
        ])

    def daily(self, **params):
        self.calls.append(("daily", params))
        return FakeFrame([
            {"ts_code": "600000.SH", "trade_date": "20250102", "close": 10.0},
            {"ts_code": "600000.SH", "trade_date": "20250103", "close": 10.2},
        ])

    def stock_basic(self, **params):
        self.calls.append(("stock_basic", params))
        rows = {
            "L": [{"ts_code": "600000.SH", "list_date": "19991110", "delist_date": None}],
            "D": [{"ts_code": "600001.SH", "list_date": "19900101", "delist_date": "20200101"}],
            "P": [{"ts_code": "600002.SH", "list_date": "20260101", "delist_date": None}],
            "G": [{"ts_code": "920001.BJ", "list_date": "20270101", "delist_date": None}],
        }
        return FakeFrame(rows[params["list_status"]])

    def index_member_all(self, **params):
        self.calls.append(("index_member_all", params))
        if params.get("is_new") == "Y":
            return FakeFrame([{"l3_code": "801010.SI", "ts_code": "600000.SH", "in_date": "20200101", "out_date": None}])
        return FakeFrame([
            {"l3_code": "801010.SI", "ts_code": "600001.SH", "in_date": "20200101", "out_date": "20240101"},
            {"l3_code": "801010.SI", "ts_code": "600002.SH", "in_date": "20260101", "out_date": None},
        ])

    def ths_member(self, **params):
        self.calls.append(("ths_member", params))
        return FakeFrame([{"ts_code": params["ts_code"], "con_code": "600000.SH", "con_name": "浦发银行"}])

    def yc_cb(self, **params):
        self.calls.append(("yc_cb", params))
        return FakeFrame([{"trade_date": "20200203", "ts_code": "1001.CB", "curve_type": "0", "curve_term": 1.0, "yield": 2.0}])

    def suspend_d(self, **params):
        self.calls.append(("suspend_d", params))
        return FakeFrame([{"ts_code": "600000.SH", "trade_date": "20250102", "suspend_type": "S"}])

    def stk_limit(self, **params):
        self.calls.append(("stk_limit", params))
        return FakeFrame([{"ts_code": "600000.SH", "trade_date": "20250102", "pre_close": 10.0, "up_limit": 11.0, "down_limit": 9.0}])


class PermissionDeniedTushare:
    def daily(self, **params):
        raise RuntimeError("积分不足，无权限")

    def income(self, **params):
        raise RuntimeError("积分不足，无权限")


class ProgrammingErrorTushare:
    def daily(self, **params):
        raise RuntimeError("unexpected parser bug")


class FakeAkshare:
    def __init__(self, amount=False):
        self.amount = amount

    def stock_zh_a_hist(self, **params):
        first = {"日期": "2025-01-02", "开盘": 9.8, "收盘": 10.0, "成交量": 100}
        if self.amount:
            first["成交额"] = 123000
        return FakeFrame([first, {"日期": "2025-01-03", "开盘": 10.0, "收盘": 10.2, "成交量": 120}])

    def stock_info_a_code_name(self):
        return FakeFrame([{"code": "920001", "name": "北交样例"}])


class ChinaMarketDataTests(unittest.TestCase):
    def test_6000_profile_uses_vip_and_conservative_financial_time(self):
        fake = FakeTushare()
        provider = module.TushareProvider(client=fake, points_profile=6000)
        result = provider.fetch("income", {"period": "20241231", "universe_mode": "cross_section"}, as_of="2025-03-31", require_pit=True)
        self.assertEqual(fake.calls[0][0], "income_vip")
        self.assertEqual([row["ts_code"] for row in result.records], ["600000.SH"])
        self.assertEqual(result.metadata["future_rows_dropped"], 1)
        self.assertEqual(result.metadata["missing_availability_dropped"], 1)
        self.assertFalse(result.metadata["revision_history_complete"])
        self.assertIsNone(result.metadata["documented_row_limit"])

    def test_date_only_announcement_not_available_until_next_day(self):
        provider = module.TushareProvider(client=FakeTushare(), points_profile=6000)
        before = provider.fetch("income", {"period": "20241231", "universe_mode": "cross_section"}, as_of="2025-03-21T23:59:59+08:00", require_pit=True)
        after = provider.fetch("income", {"period": "20241231", "universe_mode": "cross_section"}, as_of="2025-03-22T00:00:00+08:00", require_pit=True)
        self.assertEqual(before.records, [])
        self.assertEqual([row["ts_code"] for row in after.records], ["600000.SH"])

    def test_daily_bar_available_after_1600_shanghai(self):
        provider = module.TushareProvider(client=FakeTushare(), points_profile=6000)
        before = provider.fetch("daily_bar", {"ts_code": "600000.SH"}, as_of="2025-01-02T15:59:59+08:00", require_pit=True)
        after = provider.fetch("daily_bar", {"ts_code": "600000.SH"}, as_of="2025-01-02T16:00:00+08:00", require_pit=True)
        self.assertEqual(before.records, [])
        self.assertEqual(len(after.records), 1)

    def test_listing_lifecycle_fetches_l_d_p_g_and_filters(self):
        fake = FakeTushare()
        result = module.TushareProvider(client=fake).fetch("security_master", {"list_status": "ALL", "fields": "ts_code,list_date,delist_date"}, as_of="20250102", require_pit=True)
        self.assertEqual([row["ts_code"] for row in result.records], ["600000.SH"])
        self.assertEqual([call[1]["list_status"] for call in fake.calls], ["L", "D", "P", "G"])

    def test_security_master_rejects_nonhistorical_fields(self):
        provider = module.TushareProvider(client=FakeTushare())
        with self.assertRaises(module.DataProviderError) as caught:
            provider.fetch("security_master", {"fields": "ts_code,name,industry"}, as_of="20250102", require_pit=True)
        self.assertEqual(caught.exception.code, "field_not_pit_safe")

    def test_historical_membership_fetches_current_and_retired(self):
        fake = FakeTushare()
        result = module.TushareProvider(client=fake).fetch("industry_membership", {"l3_code": "801010.SI"}, as_of="20250102", require_pit=True)
        self.assertEqual([row["ts_code"] for row in result.records], ["600000.SH"])
        self.assertEqual([call[1]["is_new"] for call in fake.calls], ["Y", "N"])
        self.assertEqual(result.metadata["outside_interval_rows_dropped"], 2)

    def test_segmented_history_limit_uses_largest_segment_not_merged_total(self):
        original = module.TUSHARE_ENDPOINTS["industry_membership"]
        module.TUSHARE_ENDPOINTS["industry_membership"] = replace(original, max_rows=3)
        try:
            result = module.TushareProvider(client=FakeTushare()).fetch("industry_membership", {"l3_code": "801010.SI"}, as_of="20270102", require_pit=True)
            self.assertEqual(result.metadata["request_segment_row_counts"], [1, 2])
            self.assertFalse(result.metadata["truncation_suspected"])
        finally:
            module.TUSHARE_ENDPOINTS["industry_membership"] = original

    def test_ths_current_membership_rejected_for_strict_pit(self):
        with self.assertRaises(module.DataProviderError) as caught:
            module.TushareProvider(client=FakeTushare()).fetch("ths_membership", {}, as_of="20250102", require_pit=True)
        self.assertEqual(caught.exception.code, "pit_not_supported")

    def test_execution_status_datasets_have_explicit_availability(self):
        provider = module.TushareProvider(client=FakeTushare())
        suspend = provider.fetch("suspend_status", {"trade_date": "20250102"}, as_of="20250102", require_pit=True)
        before = provider.fetch("price_limit", {"trade_date": "20250102"}, as_of="2025-01-02T08:59:59+08:00", require_pit=True)
        after = provider.fetch("price_limit", {"trade_date": "20250102"}, as_of="2025-01-02T09:00:00+08:00", require_pit=True)
        self.assertEqual(len(suspend.records), 1)
        self.assertEqual(before.records, [])
        self.assertEqual(after.records[0]["up_limit"], 11.0)

    def test_akshare_daily_schema_code_amount_and_units(self):
        result = module.AkshareProvider(client=FakeAkshare(amount=True)).fetch("daily_bar", {"ts_code": "600000.SH", "start_date": "20250101", "end_date": "20250103"}, as_of="20250102", require_pit=True)
        self.assertEqual(result.metadata["request_params"]["symbol"], "600000")
        self.assertEqual(result.records[0]["ts_code"], "600000.SH")
        self.assertEqual(result.records[0]["amount"], 123.0)
        self.assertEqual(result.metadata["units"]["amount"], "thousand_CNY")

    def test_beijing_920_code_is_canonicalized(self):
        self.assertEqual(module._canonical_ts_code("920001"), "920001.BJ")
        result = module.AkshareProvider(client=FakeAkshare()).fetch("security_master")
        self.assertEqual(result.records[0]["ts_code"], "920001.BJ")

    def test_auto_fallback_keeps_failure_provenance(self):
        auto = module.AutoProvider(module.TushareProvider(client=PermissionDeniedTushare()), module.AkshareProvider(client=FakeAkshare()))
        result = auto.fetch("daily_bar", {"ts_code": "600000.SH", "start_date": "20250101", "end_date": "20250103"}, as_of="20250102", require_pit=True)
        self.assertEqual(result.metadata["provider"], "akshare")
        self.assertEqual(result.metadata["fallback_from"]["code"], "permission_denied")

    def test_programming_error_does_not_trigger_fallback(self):
        auto = module.AutoProvider(module.TushareProvider(client=ProgrammingErrorTushare()), module.AkshareProvider(client=FakeAkshare()))
        with self.assertRaises(module.DataProviderError) as caught:
            auto.fetch("daily_bar", {"ts_code": "600000.SH"})
        self.assertEqual(caught.exception.code, "provider_error")

    def test_no_schema_compatible_financial_fallback(self):
        auto = module.AutoProvider(module.TushareProvider(client=PermissionDeniedTushare()), module.AkshareProvider(client=FakeAkshare()))
        with self.assertRaises(module.DataProviderError) as caught:
            auto.fetch("income", {"ts_code": "600000.SH"}, as_of="20250331", require_pit=True)
        self.assertEqual(caught.exception.code, "fallback_unavailable")

    def test_bitemporal_history_request_fails_closed(self):
        with self.assertRaises(module.DataProviderError) as caught:
            module.TushareProvider(client=FakeTushare()).fetch("income", {"require_revision_history": True}, as_of="20250331", require_pit=True)
        self.assertEqual(caught.exception.code, "bitemporal_history_unavailable")

    def test_mock_runs_same_pit_filter_and_deep_redaction(self):
        provider = module.MockProvider({"daily": [{"ts_code": "600000.SH", "trade_date": "20250102"}, {"ts_code": "600000.SH", "trade_date": "20250103"}]})
        result = provider.fetch("daily_bar", {"nested": {"api_key": "secret"}}, as_of="20250102", require_pit=True)
        self.assertEqual(len(result.records), 1)
        self.assertTrue(result.metadata["mock"])
        self.assertFalse(result.metadata["production_eligible"])
        self.assertEqual(result.metadata["request_params"]["nested"]["api_key"], "[REDACTED]")

    def test_invalid_dates_and_codes_are_rejected(self):
        provider = module.TushareProvider(client=FakeTushare())
        with self.assertRaises(module.DataProviderError):
            provider.fetch("daily_bar", {"ts_code": "600000.SH"}, as_of="2025-02-31", require_pit=True)
        with self.assertRaises(module.DataProviderError):
            provider.fetch("daily_bar", {"ts_code": "BAD"})

    def test_dataset_specific_non_equity_codes_are_accepted(self):
        fake = FakeTushare()
        provider = module.TushareProvider(client=fake)
        ths = provider.fetch("ths_membership", {"ts_code": "885800.TI"})
        curve = provider.fetch("china_yield_curve", {"ts_code": "1001.CB", "curve_type": "0", "trade_date": "20200203"})
        self.assertEqual(ths.records[0]["ts_code"], "885800.TI")
        self.assertEqual(curve.records[0]["ts_code"], "1001.CB")
        with self.assertRaises(module.DataProviderError):
            provider.fetch("daily_bar", {"ts_code": "885800.TI"})

    def test_documented_limit_drift_is_not_silent_truncation(self):
        spec = module.EndpointSpec("example", None, "current_snapshot", "docs", max_rows=2)
        metadata = module._contract_metadata(spec, [{"id": 1}, {"id": 2}, {"id": 3}], False)
        self.assertFalse(metadata["truncation_suspected"])
        self.assertTrue(metadata["documentation_limit_drift"])

    def test_aliases_are_supported(self):
        result = module.TushareProvider(client=FakeTushare()).fetch("daily", {"ts_code": "600000.SH"}, as_of="20250102", require_pit=True)
        self.assertEqual(result.dataset, "daily_bar")
        self.assertEqual(result.metadata["requested_dataset"], "daily")

    def test_tushare_accepts_comma_separated_security_codes(self):
        result = module.TushareProvider(client=FakeTushare()).fetch("daily_bar", {"ts_code": "600000.SH,000001.SZ"}, as_of="20250102", require_pit=True)
        self.assertEqual(len(result.records), 1)

    def test_truncation_can_fail_closed(self):
        original = module.TUSHARE_ENDPOINTS["daily_bar"]
        module.TUSHARE_ENDPOINTS["daily_bar"] = replace(original, max_rows=2)
        try:
            with self.assertRaises(module.DataProviderError) as caught:
                module.TushareProvider(client=FakeTushare()).fetch("daily_bar", {"ts_code": "600000.SH", "require_complete": True})
            self.assertEqual(caught.exception.code, "truncation_suspected")
        finally:
            module.TUSHARE_ENDPOINTS["daily_bar"] = original

    def test_capability_manifest_is_serializable(self):
        payload = module.capability_manifest(6000)
        self.assertTrue(any(row["dataset"] == "china_yield_curve" for row in payload["capabilities"]))
        curve = next(row for row in payload["capabilities"] if row["provider"] == "tushare" and row["dataset"] == "china_yield_curve")
        self.assertEqual(curve["permission_note"], "separate_grant_required")
        self.assertEqual(payload["aliases"]["daily"], "daily_bar")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capabilities.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertGreater(path.stat().st_size, 100)


if __name__ == "__main__":
    unittest.main()
