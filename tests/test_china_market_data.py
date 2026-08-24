import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "plugins/china-research-methodology/skills/china-market-data/scripts/china_market_data.py"
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

    def fund_basic(self, **params):
        self.calls.append(("fund_basic", params))
        rows = {
            "L": [{"ts_code": "510300.SH", "market": "E", "list_date": "20120528", "delist_date": None, "status": "L"}],
            "D": [{"ts_code": "510301.SH", "market": "E", "list_date": "20100101", "delist_date": "20250102", "status": "D"}],
            "I": [{"ts_code": "510302.SH", "market": "E", "list_date": "20260101", "delist_date": None, "status": "I"}],
        }
        return FakeFrame(rows[params["status"]])

    def fund_daily(self, **params):
        self.calls.append(("fund_daily", params))
        return FakeFrame([{"ts_code": "510300.SH", "trade_date": "20250102", "open": 4.0, "high": 4.1, "low": 3.9, "close": 4.05, "vol": 10.0, "amount": 40.5}])

    def fund_nav(self, **params):
        self.calls.append(("fund_nav", params))
        return FakeFrame([{"ts_code": "510300.SH", "ann_date": "20250103", "nav_date": "20250102", "unit_nav": 4.05, "accum_nav": 4.05}])

    def fund_share(self, **params):
        self.calls.append(("fund_share", params))
        return FakeFrame([{"ts_code": "510300.SH", "trade_date": "20250102", "fd_share": 12345.6}])

    def etf_basic(self, **params):
        self.calls.append(("etf_basic", params))
        return FakeFrame([{"ts_code": "510300.SH", "index_code": "000300.SH", "list_date": "20120528", "mgt_fee": 0.15}])

    def etf_index(self, **params):
        self.calls.append(("etf_index", params))
        return FakeFrame([{"ts_code": params.get("ts_code", "000990.CSI"), "indx_name": "测试指数", "pub_date": "20110802", "bp": 1000}])

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

    def index_weight(self, **params):
        self.calls.append(("index_weight", params))
        return FakeFrame([{"index_code": "000300.SH", "con_code": "600000.SH", "trade_date": "20250102", "weight": 0.25}])


class PermissionDeniedTushare:
    def daily(self, **params):
        raise RuntimeError("积分不足，无权限")

    def income(self, **params):
        raise RuntimeError("积分不足，无权限")

    def yc_cb(self, **params):
        raise RuntimeError("抱歉，您没有接口(yc_cb)访问权限")


class ProgrammingErrorTushare:
    def daily(self, **params):
        raise RuntimeError("unexpected parser bug")


class FakeAkshare:
    def __init__(self, amount=False):
        self.amount = amount
        self.calls = []
        self.curve_calls = []

    def stock_zh_a_hist(self, **params):
        self.calls.append(params)
        first = {"日期": "2025-01-02", "开盘": 9.8, "收盘": 10.0, "成交量": 100}
        if self.amount:
            first["成交额"] = 123000
        return FakeFrame([first, {"日期": "2025-01-03", "开盘": 10.0, "收盘": 10.2, "成交量": 120}])

    def fund_etf_hist_em(self, **params):
        self.calls.append(params)
        return FakeFrame([
            {"日期": "2025-01-02", "开盘": 3.9, "收盘": 4.0, "最高": 4.1, "最低": 3.8, "成交量": 1000, "成交额": 4000000},
            {"日期": "2025-01-03", "开盘": 4.0, "收盘": 4.1, "最高": 4.2, "最低": 3.9, "成交量": 1200, "成交额": 4920000},
        ])

    def stock_info_a_code_name(self):
        return FakeFrame([{"code": "920001", "name": "北交样例"}])

    def bond_china_yield(self, **params):
        self.curve_calls.append(("bond_china_yield", params))
        return FakeFrame(
            [
                {"曲线名称": "中债国债收益率曲线", "日期": params["start_date"], "3月": 1.1, "6月": 1.2, "1年": 1.3, "3年": 1.4, "5年": 1.5, "7年": 1.6, "10年": 1.6832, "30年": 1.9},
                {"曲线名称": "中债中短期票据收益率曲线(AAA)", "日期": params["start_date"], "3月": 2.1, "10年": 2.8},
            ]
        )

    def bond_china_close_return(self, **params):
        self.curve_calls.append(("bond_china_close_return", params))
        return FakeFrame(
            [
                {"日期": params["start_date"], "期限": 2.5, "到期收益率": 1.5, "即期收益率": 1.55, "远期收益率": 1.6},
                {"日期": params["start_date"], "期限": 10.0, "到期收益率": 1.683, "即期收益率": 1.6996, "远期收益率": 1.8},
            ]
        )


class FakePaginatedTushare:
    def daily(self, **params):
        offset = params["offset"]
        rows = [
            {"ts_code": "600000.SH", "trade_date": "20250101"},
            {"ts_code": "600000.SH", "trade_date": "20250102"},
            {"ts_code": "600000.SH", "trade_date": "20250103"},
        ]
        return FakeFrame(rows[offset:offset + params["limit"]])


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

    def test_financial_projection_keeps_identity_and_availability_fields(self):
        fake = FakeTushare()
        module.TushareProvider(client=fake, points_profile=6000).fetch(
            "income",
            {"period": "20241231", "universe_mode": "cross_section", "fields": "ts_code,end_date,revenue"},
            as_of="2025-03-31",
            require_pit=True,
        )
        fields = set(fake.calls[0][1]["fields"].split(","))
        self.assertTrue({"ann_date", "f_ann_date", "report_type", "comp_type", "update_flag"}.issubset(fields))

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

    def test_delist_date_is_inclusive_then_removed_next_day(self):
        provider = module.TushareProvider(client=FakeTushare())
        on_date = provider.fetch("security_master", {"list_status": "ALL", "fields": "ts_code,list_date,delist_date"}, as_of="20200101", require_pit=True)
        next_day = provider.fetch("security_master", {"list_status": "ALL", "fields": "ts_code,list_date,delist_date"}, as_of="20200102", require_pit=True)
        self.assertIn("600001.SH", [row["ts_code"] for row in on_date.records])
        self.assertNotIn("600001.SH", [row["ts_code"] for row in next_day.records])

    def test_fund_master_lifecycle_and_fund_data_contracts(self):
        provider = module.TushareProvider(client=FakeTushare(), points_profile=6000)
        on_delist = provider.fetch("fund_basic", {"status": "ALL", "market": "E", "fields": "ts_code,market,list_date,delist_date,status"}, as_of="20250102", require_pit=True)
        after_delist = provider.fetch("fund_master", {"status": "ALL", "market": "E"}, as_of="20250103", require_pit=True)
        daily = provider.fetch("fund_daily", {"ts_code": "510300.SH", "trade_date": "20250102"}, as_of="20250102T16:00:00+08:00", require_pit=True)
        nav_before = provider.fetch("fund_nav", {"ts_code": "510300.SH"}, as_of="20250103T23:59:59+08:00", require_pit=True)
        nav_after = provider.fetch("fund_nav", {"ts_code": "510300.SH"}, as_of="20250104T00:00:00+08:00", require_pit=True)
        self.assertIn("510301.SH", [row["ts_code"] for row in on_delist.records])
        self.assertNotIn("510301.SH", [row["ts_code"] for row in after_delist.records])
        self.assertEqual(daily.metadata["units"]["amount"], "thousand_CNY")
        self.assertEqual(nav_before.records, [])
        self.assertEqual(nav_after.records[0]["unit_nav"], 4.05)
        self.assertEqual([call[1]["status"] for call in provider.client.calls if call[0] == "fund_basic"], ["L", "D", "I", "L", "D", "I"])

    def test_fund_share_units_and_unknown_release_time_fail_strict_pit(self):
        provider = module.TushareProvider(client=FakeTushare(), points_profile=6000)
        result = provider.fetch("fund_share", {"ts_code": "510300.SH", "trade_date": "20250102"}, as_of="20250102")
        self.assertEqual(result.records[0]["fd_share"], 12345.6)
        self.assertEqual(result.metadata["units"]["fd_share"], "ten_thousand_shares")
        self.assertEqual(result.metadata["pit_grade"], "observation_date_without_release_time")
        with self.assertRaises(module.DataProviderError) as caught:
            provider.fetch("fund_share", {"ts_code": "510300.SH"}, as_of="20250102", require_pit=True)
        self.assertEqual(caught.exception.code, "pit_not_supported")

    def test_8000_point_etf_mapping_is_declared_but_not_available_to_6000_profile(self):
        capability = next(row for row in module.capability_manifest(6000)["capabilities"] if row["provider"] == "tushare" and row["dataset"] == "etf_master")
        self.assertFalse(capability["profile_eligible"])
        self.assertEqual(capability["interface"], "etf_basic")
        with self.assertRaises(module.DataProviderError) as caught:
            module.TushareProvider(client=FakeTushare(), points_profile=6000).fetch("etf_basic")
        self.assertEqual(caught.exception.code, "profile_points_insufficient")
        result = module.TushareProvider(client=FakeTushare(), points_profile=8000).fetch("etf_master")
        self.assertEqual(result.records[0]["index_code"], "000300.SH")
        self.assertEqual(result.metadata["pit_grade"], "current_snapshot")
        index_result = module.TushareProvider(client=FakeTushare(), points_profile=8000).fetch("etf_index", {"ts_code": "000990.CSI"})
        self.assertEqual(index_result.records[0]["ts_code"], "000990.CSI")

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
        fake = FakeAkshare(amount=True)
        result = module.AkshareProvider(client=fake).fetch("daily_bar", {"ts_code": "600000.SH", "start_date": "20250101", "end_date": "20250103"}, as_of="20250102", require_pit=True)
        self.assertEqual(result.metadata["request_params"]["ts_code"], "600000.SH")
        self.assertEqual(result.metadata["provider_call_params"]["symbol"], "600000")
        self.assertEqual(result.records[0]["ts_code"], "600000.SH")
        self.assertEqual(result.records[0]["amount"], 123.0)
        self.assertEqual(result.metadata["units"]["amount"], "thousand_CNY")

    def test_akshare_etf_daily_fallback_is_normalized_and_adjustment_is_explicit(self):
        fake = FakeAkshare()
        result = module.AkshareProvider(client=fake).fetch(
            "fund_daily_bar",
            {"ts_code": "510300.SH", "start_date": "20250101", "end_date": "20250103"},
            as_of="20250102",
            require_pit=True,
        )
        self.assertEqual(result.records[0]["ts_code"], "510300.SH")
        self.assertEqual(result.records[0]["amount"], 4000.0)
        self.assertEqual(result.metadata["units"]["amount"], "thousand_CNY")
        self.assertEqual(result.metadata["adjustment_mode"], "raw")
        self.assertNotIn("timeout", fake.calls[0])
        with self.assertRaises(module.DataProviderError) as caught:
            module.AkshareProvider(client=FakeAkshare()).fetch(
                "fund_daily_bar",
                {"ts_code": "510300.SH", "adjust": "qfq"},
                as_of="20250102",
                require_pit=True,
            )
        self.assertEqual(caught.exception.code, "adjustment_not_pit_safe")

    def test_akshare_fallback_translates_trade_date_and_drops_fields(self):
        fake = FakeAkshare()
        result = module.AkshareProvider(client=fake).fetch(
            "daily_bar",
            {"ts_code": "600000.SH", "trade_date": "20250102", "fields": "ts_code,trade_date,close"},
            as_of="20250102",
            require_pit=True,
        )
        self.assertEqual(fake.calls[0]["start_date"], "20250102")
        self.assertEqual(fake.calls[0]["end_date"], "20250102")
        self.assertNotIn("fields", fake.calls[0])
        self.assertEqual(len(result.records), 1)

    def test_akshare_adjustment_is_rejected_in_strict_pit(self):
        with self.assertRaises(module.DataProviderError) as caught:
            module.AkshareProvider(client=FakeAkshare()).fetch(
                "daily_bar",
                {"ts_code": "600000.SH", "adjust": "qfq"},
                as_of="20250102",
                require_pit=True,
            )
        self.assertEqual(caught.exception.code, "adjustment_not_pit_safe")

    def test_akshare_standard_yield_curve_is_filtered_and_normalized(self):
        fake = FakeAkshare()
        result = module.AkshareProvider(client=fake).fetch(
            "china_yield_curve",
            {"ts_code": "1001.CB", "curve_type": "0", "curve_term": 10, "trade_date": "20260820", "fields": "trade_date,curve_term,yield"},
            as_of="20260820",
            require_pit=True,
        )
        self.assertEqual(fake.curve_calls[0][0], "bond_china_yield")
        self.assertEqual(fake.curve_calls[0][1], {"start_date": "20260820", "end_date": "20260820"})
        self.assertEqual(result.records, [{"trade_date": "20260820", "ts_code": "1001.CB", "curve_name": "中债国债收益率曲线", "curve_type": "0", "yield_type": "maturity", "curve_term": 10.0, "yield": 1.6832}])
        self.assertEqual(result.metadata["units"], {"curve_term": "years", "yield": "percent"})
        self.assertEqual(result.metadata["semantic_scope"], "standard_maturity_tenors")

    def test_akshare_recent_spot_curve_uses_dense_interface(self):
        current = datetime.now(module.SHANGHAI).strftime("%Y%m%d")
        fake = FakeAkshare()
        result = module.AkshareProvider(client=fake).fetch(
            "china_yield_curve",
            {"ts_code": "1001.CB", "curve_type": "1", "curve_term": 10, "trade_date": current},
            as_of=current,
            require_pit=True,
        )
        self.assertEqual(fake.curve_calls[0][0], "bond_china_close_return")
        self.assertEqual([call[1]["period"] for call in fake.curve_calls], ["0.1", "0.5", "1"])
        self.assertEqual(result.records[0]["yield_type"], "spot")
        self.assertEqual(result.records[0]["yield"], 1.6996)
        self.assertEqual(result.metadata["interface"], "bond_china_close_return")
        self.assertEqual(result.metadata["provider_segment_row_counts"], [2, 2, 2])

    def test_akshare_historical_spot_curve_fails_closed(self):
        with self.assertRaises(module.DataProviderError) as caught:
            module.AkshareProvider(client=FakeAkshare()).fetch(
                "china_yield_curve",
                {"ts_code": "1001.CB", "curve_type": "1", "trade_date": "20200102"},
            )
        self.assertEqual(caught.exception.code, "historical_coverage_unavailable")

    def test_akshare_yield_curve_requires_explicit_curve_type(self):
        with self.assertRaises(module.DataProviderError) as caught:
            module.AkshareProvider(client=FakeAkshare()).fetch(
                "china_yield_curve",
                {"ts_code": "1001.CB", "trade_date": "20260820"},
            )
        self.assertEqual(caught.exception.code, "semantic_ambiguity")

    def test_akshare_yield_curve_rejects_conflicting_dates(self):
        with self.assertRaises(module.DataProviderError) as caught:
            module.AkshareProvider(client=FakeAkshare()).fetch(
                "china_yield_curve",
                {"ts_code": "1001.CB", "curve_type": "0", "trade_date": "20260820", "start_date": "20260819"},
            )
        self.assertEqual(caught.exception.code, "invalid_request")

    def test_akshare_missing_requested_term_is_not_silent_empty(self):
        current = datetime.now(module.SHANGHAI).strftime("%Y%m%d")
        with self.assertRaises(module.DataProviderError) as caught:
            module.AkshareProvider(client=FakeAkshare()).fetch(
                "china_yield_curve",
                {"ts_code": "1001.CB", "curve_type": "1", "curve_term": 9.75, "trade_date": current},
            )
        self.assertEqual(caught.exception.code, "requested_term_unavailable")

    def test_beijing_920_code_is_canonicalized(self):
        self.assertEqual(module._canonical_ts_code("920001"), "920001.BJ")
        result = module.AkshareProvider(client=FakeAkshare()).fetch("security_master")
        self.assertEqual(result.records[0]["ts_code"], "920001.BJ")

    def test_auto_fallback_keeps_failure_provenance(self):
        auto = module.AutoProvider(module.TushareProvider(client=PermissionDeniedTushare()), module.AkshareProvider(client=FakeAkshare()))
        result = auto.fetch("daily_bar", {"ts_code": "600000.SH", "start_date": "20250101", "end_date": "20250103"}, as_of="20250102", require_pit=True)
        self.assertEqual(result.metadata["provider"], "akshare")
        self.assertEqual(result.metadata["fallback_from"]["code"], "permission_denied")

    def test_auto_yield_curve_fallback_keeps_semantics_and_provenance(self):
        auto = module.AutoProvider(module.TushareProvider(client=PermissionDeniedTushare()), module.AkshareProvider(client=FakeAkshare()))
        result = auto.fetch(
            "china_yield_curve",
            {"ts_code": "1001.CB", "curve_type": "0", "curve_term": 10, "trade_date": "20260820"},
            as_of="20260820",
            require_pit=True,
        )
        self.assertEqual(result.records[0]["yield"], 1.6832)
        self.assertEqual(result.metadata["fallback_from"]["code"], "permission_denied")
        self.assertEqual(result.metadata["route"], ["tushare", "akshare"])

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

    def test_financial_contract_distinguishes_duplicates_and_versions(self):
        spec = module.TUSHARE_ENDPOINTS["income"]
        base = {"ts_code": "600000.SH", "end_date": "20241231", "report_type": "1", "comp_type": "1"}
        rows = [
            {**base, "ann_date": "20250320", "f_ann_date": "20250320", "update_flag": "0"},
            {**base, "ann_date": "20250320", "f_ann_date": "20250320", "update_flag": "0"},
            {**base, "ann_date": "20250420", "f_ann_date": "20250420", "update_flag": "1"},
        ]
        metadata = module._contract_metadata(spec, rows, False)
        self.assertEqual(metadata["duplicate_key_rows"], 1)
        self.assertEqual(metadata["multi_version_groups"], 1)

    def test_quality_contract_can_fail_closed(self):
        spec = module.TUSHARE_ENDPOINTS["daily_bar"]
        with self.assertRaises(module.DataProviderError) as caught:
            module._contract_metadata(
                spec,
                [{"ts_code": "600000.SH", "trade_date": "bad", "close": "not-a-number", "vol": -1}],
                False,
                require_quality=True,
            )
        self.assertEqual(caught.exception.code, "data_quality_failed")

    def test_explicit_offset_pagination_establishes_completeness(self):
        original = module.TUSHARE_ENDPOINTS["daily_bar"]
        module.TUSHARE_ENDPOINTS["daily_bar"] = replace(original, max_rows=2)
        try:
            result = module.TushareProvider(client=FakePaginatedTushare()).fetch(
                "daily_bar",
                {"paginate": True, "page_size": 2, "require_complete": True},
            )
            self.assertEqual(len(result.records), 3)
            self.assertTrue(result.metadata["pagination_complete"])
            self.assertEqual(result.metadata["request_segment_row_counts"], [2, 1])
        finally:
            module.TUSHARE_ENDPOINTS["daily_bar"] = original

    def test_index_weight_has_historical_pit_contract(self):
        result = module.TushareProvider(client=FakeTushare()).fetch(
            "index_weight",
            {"index_code": "000300.SH", "trade_date": "20250102"},
            as_of="20250102T16:00:00+08:00",
            require_pit=True,
        )
        self.assertEqual(result.records[0]["con_code"], "600000.SH")
        self.assertEqual(result.metadata["units"]["weight"], "percent")

    def test_cutoff_safe_adjustment_ignores_future_factor(self):
        daily = [
            {"ts_code": "600000.SH", "trade_date": "20250101", "close": 10.0},
            {"ts_code": "600000.SH", "trade_date": "20250102", "close": 11.0},
        ]
        factors = [
            {"ts_code": "600000.SH", "trade_date": "20250101", "adj_factor": 1.0},
            {"ts_code": "600000.SH", "trade_date": "20250102", "adj_factor": 1.1},
            {"ts_code": "600000.SH", "trade_date": "20250103", "adj_factor": 99.0},
        ]
        result = module.adjust_price_records(daily, factors, mode="qfq", as_of="20250102")
        self.assertAlmostEqual(result.records[0]["close"], 10.0 / 1.1)
        self.assertAlmostEqual(result.records[1]["close"], 11.0)
        self.assertEqual(result.metadata["future_factor_rows_dropped"], 1)

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
        ak_curve = next(row for row in payload["capabilities"] if row["provider"] == "akshare" and row["dataset"] == "china_yield_curve")
        self.assertEqual(ak_curve["interface"], "bond_china_yield")
        self.assertEqual(ak_curve["units"]["yield"], "percent")
        self.assertEqual(payload["aliases"]["daily"], "daily_bar")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capabilities.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertGreater(path.stat().st_size, 100)


if __name__ == "__main__":
    unittest.main()
