import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/china-research-methodology/skills/industry-etf-research/scripts"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = load_module("industry_etf_builder", SKILL / "build_industry_etf_snapshot.py")
validator = load_module("industry_etf_validator", SKILL / "validate_industry_etf_report.py")


def sample_payload():
    evidence = [
        {"id": "ev-scope", "title": "industry definition", "source": "https://example.com/scope", "observed_at": "2025-01-04T10:00:00+08:00"},
        {"id": "ev-index-a", "title": "index A methodology", "source": "https://example.com/index-a", "observed_at": "2025-01-04T10:00:00+08:00"},
        {"id": "ev-index-b", "title": "index B methodology", "source": "https://example.com/index-b", "observed_at": "2025-01-04T10:00:00+08:00"},
        {"id": "ev-etf", "title": "ETF disclosure", "source": "https://example.com/etf", "observed_at": "2025-01-04T10:00:00+08:00"},
        {"id": "ev-fundamental", "title": "fundamental evidence", "source": "https://example.com/fundamental", "available_at": "2025-01-04T00:00:00+08:00"},
        {"id": "ev-market", "title": "market evidence", "source": "https://example.com/market", "available_at": "2025-01-03T16:00:00+08:00"},
    ]
    return {
        "schema_version": "industry-etf-input/v1",
        "as_of": "2025-01-04",
        "horizons": [1, 2],
        "industry": {"name": "测试行业", "taxonomy": "申万2021", "scope": "只覆盖A股测试样本", "evidence_ids": ["ev-scope"]},
        "indices": [
            {
                "index_code": "931000.CSI",
                "name": "测试指数A",
                "methodology_url": "https://example.com/index-a",
                "evidence_ids": ["ev-index-a"],
                "constituents_as_of": "20250103",
                "constituents_pit_grade": "trade_date",
                "levels": [
                    {"trade_date": "20250101", "close": 100},
                    {"trade_date": "20250102", "close": 101},
                    {"trade_date": "20250103", "close": 102},
                ],
                "constituents": [
                    {"ts_code": "600001.SH", "weight_pct": 60, "industry_match": True, "industry_revenue_share_pct": 80, "return_pct": 2, "above_ma": True},
                    {"ts_code": "600002.SH", "weight_pct": 40, "industry_match": False, "industry_revenue_share_pct": 20, "return_pct": -1, "above_ma": False},
                ],
            },
            {
                "index_code": "931001.CSI",
                "name": "测试指数B",
                "methodology_url": "https://example.com/index-b",
                "evidence_ids": ["ev-index-b"],
                "constituents_as_of": "20250103",
                "constituents_pit_grade": "trade_date",
                "levels": [],
                "constituents": [
                    {"ts_code": "600001.SH", "weight_pct": 50, "industry_match": True},
                    {"ts_code": "600003.SH", "weight_pct": 50, "industry_match": True},
                ],
            },
        ],
        "etfs": [
            {
                "ts_code": "510000.SH",
                "name": "测试ETF",
                "index_code": "931000.CSI",
                "evidence_ids": ["ev-etf"],
                "price_basis": "raw",
                "amount_unit": "thousand_CNY",
                "price_bars": [
                    {"trade_date": "20250101", "close": 4.0, "amount": 1000},
                    {"trade_date": "20250102", "close": 4.1, "amount": 2000},
                    {"trade_date": "20250103", "close": 4.2, "amount": 3000},
                ],
                "adjusted_nav": [
                    {"nav_date": "20250101", "adj_nav": 1.0, "unit_nav": 4.0},
                    {"nav_date": "20250102", "adj_nav": 1.01, "unit_nav": 4.05},
                    {"nav_date": "20250103", "adj_nav": 1.03, "unit_nav": 4.1},
                ],
                "share_unit": "ten_thousand_shares",
                "shares": [
                    {"trade_date": "20250101", "shares": 100},
                    {"trade_date": "20250102", "shares": 110},
                    {"trade_date": "20250103", "shares": 120},
                ],
                "realtime_snapshot": {"observed_at": "2025-01-03T14:30:00+08:00", "price": 4.15, "iopv": 4.1},
            }
        ],
        "state_assessment": {
            "fundamental_state": "improving",
            "market_state": "confirming",
            "fundamental_evidence_ids": ["ev-fundamental"],
            "market_evidence_ids": ["ev-market"],
        },
        "counterevidence": ["样本期太短，可能只是噪声"],
        "limitations": ["测试数据不代表真实市场"],
        "evidence": evidence,
    }


class IndustryEtfResearchTests(unittest.TestCase):
    def test_snapshot_keeps_exposure_return_premium_and_share_concepts_separate(self):
        result = builder.build_snapshot(sample_payload())
        exposure = result["index_exposure"][0]
        etf = result["etf_market_confirmation"][0]
        self.assertEqual(exposure["hhi_normalized"], 0.52)
        self.assertEqual(exposure["weighted_industry_revenue_share_pct"], 56.0)
        self.assertEqual(result["index_overlap"][0]["weighted_overlap_pct"], 50.0)
        self.assertAlmostEqual(etf["price_returns"][0]["return_pct"], 2.439024, places=6)
        self.assertAlmostEqual(etf["adjusted_nav_total_returns"][0]["return_pct"], 1.980198, places=6)
        self.assertAlmostEqual(etf["premiums"]["close_to_nav"]["premium_pct"], 2.439024, places=6)
        self.assertAlmostEqual(etf["premiums"]["realtime_to_iopv"]["premium_pct"], 1.219512, places=6)
        self.assertEqual(etf["share_changes"][0]["share_change"], 100000.0)
        self.assertEqual(etf["share_changes"][0]["estimated_net_creation_cny"], 410000.0)
        self.assertFalse(result["synthesis"]["is_trade_signal"])
        self.assertTrue(result["calculation_basis"]["no_composite_score"])

    def test_tracking_uses_adjusted_nav_not_raw_trading_price(self):
        result = builder.build_snapshot(sample_payload())
        tracking = result["etf_market_confirmation"][0]["tracking"]
        first = tracking["horizons"][0]
        self.assertEqual(first["observations"], 1)
        self.assertAlmostEqual(first["adjusted_nav_return_pct"], 1.980198, places=6)
        self.assertAlmostEqual(first["index_return_pct"], 0.990099, places=6)
        self.assertAlmostEqual(first["tracking_difference_pct"], 0.990099, places=6)

    def test_invalid_share_unit_fails_closed(self):
        payload = sample_payload()
        payload["etfs"][0]["share_unit"] = "lots"
        with self.assertRaises(builder.ContractError):
            builder.build_snapshot(payload)

    def test_non_unclear_state_requires_evidence(self):
        payload = sample_payload()
        payload["state_assessment"]["fundamental_evidence_ids"] = []
        with self.assertRaises(builder.ContractError):
            builder.build_snapshot(payload)

    def test_future_observation_is_rejected(self):
        payload = sample_payload()
        payload["etfs"][0]["price_bars"][-1]["trade_date"] = "20250105"
        with self.assertRaises(builder.ContractError):
            builder.build_snapshot(payload)

    def test_strict_pit_requires_raw_price_announced_nav_and_archived_share_time(self):
        payload = sample_payload()
        payload["require_pit"] = True
        for row in payload["etfs"][0]["adjusted_nav"]:
            row["ann_date"] = "20250103"
        for row in payload["etfs"][0]["shares"]:
            row["available_at"] = "2025-01-03T18:00:00+08:00"
        result = builder.build_snapshot(payload)
        self.assertTrue(result["calculation_basis"]["require_pit"])
        payload["etfs"][0]["price_basis"] = "qfq"
        with self.assertRaises(builder.ContractError):
            builder.build_snapshot(payload)

    def test_validator_rejects_trading_decision_fields(self):
        result = builder.build_snapshot(sample_payload())
        self.assertEqual(validator.validate_snapshot(result)["errors"], [])
        result["snapshot_sha256"] = "0" * 64
        self.assertIn("snapshot_sha256 does not match snapshot content", validator.validate_snapshot(result)["errors"])
        result = builder.build_snapshot(sample_payload())
        result["synthesis"]["recommendation"] = "buy"
        errors = validator.validate_snapshot(result)["errors"]
        self.assertTrue(any("forbidden decision fields" in error for error in errors))

    def test_cli_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            output = Path(directory) / "snapshot.json"
            source.write_text(json.dumps(sample_payload(), ensure_ascii=False), encoding="utf-8")
            build = subprocess.run(
                [sys.executable, str(SKILL / "build_industry_etf_snapshot.py"), "--input", str(source), "--output", str(output)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            check = subprocess.run(
                [sys.executable, str(SKILL / "validate_industry_etf_report.py"), str(output)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertTrue(json.loads(check.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
