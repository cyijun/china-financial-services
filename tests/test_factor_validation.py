import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/china-research-methodology/skills/a-share-factor-validation/scripts"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SKILL / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


factor = load("factor_validation", "factor_validation.py")
registry = load("factor_registry", "factor_registry.py")


def sample_rows(days=24):
    rows = []
    for day in range(1, days + 1):
        date = f"202501{day:02d}"
        for index in range(10):
            rows.append(
                {
                    "date": date,
                    "ts_code": f"{600000 + index}.SH",
                    "factor": index,
                    "forward_return": (index - 4.5) / 1000,
                    "tradable": True,
                }
            )
    return rows


class FactorValidationTests(unittest.TestCase):
    def test_analysis_reports_ic_costs_and_real_trade_events(self):
        report = factor.analyze(sample_rows(), cost_bps=10, seed=3)
        self.assertEqual(report["status"], "inconclusive")
        self.assertTrue(report["decision_status_requires_preregistered_gates"])
        self.assertAlmostEqual(report["ic"]["mean"], 1.0)
        self.assertGreater(report["backtest"]["trade_events"], 0)
        self.assertLess(report["backtest"]["net_total_return"], report["backtest"]["gross_total_return"])
        self.assertIsNone(report["backtest"]["round_trip_trade_win_rate"])

    def test_future_perturbation_does_not_change_past(self):
        rows = sample_rows(days=6)
        changed = [dict(row) for row in rows]
        for row in changed:
            if row["date"] > "20250103":
                row["forward_return"] = 999
        self.assertTrue(factor.future_perturbation_invariant(rows, changed, cutoff="20250103"))

    def test_purged_walk_forward_has_gap(self):
        dates = [f"202501{day:02d}" for day in range(1, 21)]
        splits = factor.purged_walk_forward(dates, test_size=4, min_train_size=8, purge_days=2)
        self.assertTrue(splits)
        self.assertLess(splits[0]["train"][-1], splits[0]["test"][0])
        self.assertEqual(len(splits[0]["test"]), 4)

    def test_bh_and_cscv_return_explicit_diagnostics(self):
        adjusted = factor.benjamini_hochberg({"a": 0.001, "b": 0.04, "c": 0.8})
        self.assertTrue(adjusted["a"]["fdr_reject"])
        pbo = factor.cscv_probability_of_backtest_overfit(
            {"a": [0.01, 0.02, -0.01, 0.03, 0.02, -0.01], "b": [0.0, 0.01, 0.02, -0.02, 0.01, 0.02]}
        )
        self.assertGreaterEqual(pbo["pbo"], 0)
        self.assertLessEqual(pbo["pbo"], 1)

    def test_registry_is_schema_checked_and_hash_chained(self):
        experiment = {
            "experiment_id": "exp-1",
            "factor_name": "quality",
            "hypothesis": "cash conversion predicts forward returns",
            "data_snapshot_sha256": "a" * 64,
            "code_git_sha": "b" * 40,
            "sample_start": "20200101",
            "sample_end": "20241231",
            "status": "preregistered",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.jsonl"
            first = registry.append_experiment(path, experiment)
            second = registry.append_experiment(path, {**experiment, "experiment_id": "exp-2", "status": "inconclusive"})
            self.assertEqual(second["previous_hash"], first["record_hash"])
            self.assertEqual(registry.verify_registry(path), second["record_hash"])
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()
