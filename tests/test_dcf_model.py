import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "plugins/vertical-plugins/financial-analysis/skills/china-dcf-model/scripts/dcf_model.py"
SPEC = importlib.util.spec_from_file_location("dcf_model", PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class DcfModelTests(unittest.TestCase):
    def config(self):
        return {
            "valuation_date": "2026-08-24",
            "sources": [{"field": "revenue_base", "source": "annual report", "locator": "p.100"}],
            "revenue_base": 1000,
            "forecast_years": [
                {
                    "revenue_growth": 0.1,
                    "ebit_margin": 0.2,
                    "tax_rate": 0.25,
                    "da_pct_revenue": 0.03,
                    "capex_pct_revenue": 0.05,
                    "nwc_pct_revenue": 0.1,
                    "opening_nwc_pct_revenue": 0.1,
                },
                {
                    "revenue_growth": 0.08,
                    "ebit_margin": 0.21,
                    "tax_rate": 0.25,
                    "da_pct_revenue": 0.03,
                    "capex_pct_revenue": 0.05,
                    "nwc_pct_revenue": 0.1,
                },
            ],
            "capital": {
                "risk_free_rate": 0.025,
                "equity_risk_premium": 0.06,
                "beta": 1.0,
                "pre_tax_cost_of_debt": 0.04,
                "tax_rate": 0.25,
                "market_equity": 800,
                "gross_debt": 200,
            },
            "terminal_growth": 0.03,
            "bridge": {
                "cash": 50,
                "gross_debt": 200,
                "lease_liabilities": 10,
                "minority_interest": 5,
                "non_operating_assets": 15,
                "diluted_shares": 100,
            },
            "sensitivity": {"wacc_values": [0.07, 0.08, 0.09], "growth_values": [0.02, 0.03, 0.04]},
        }

    def test_fcff_value_bridge_and_center_check(self):
        report = module.run(self.config())
        self.assertGreater(report["forecast"][0]["fcff"], 0)
        self.assertGreater(report["valuation"]["enterprise_value"], report["valuation"]["equity_value"])
        self.assertTrue(report["checks"]["wacc_exceeds_terminal_growth"])
        self.assertTrue(report["checks"]["sensitivity_center_matches_base"])

    def test_terminal_growth_must_be_below_wacc(self):
        config = self.config()
        config["terminal_growth"] = 0.5
        with self.assertRaises(ValueError):
            module.run(config)


if __name__ == "__main__":
    unittest.main()
