#!/usr/bin/env python3
"""Run sanitized, read-only acceptance checks against AKShare-backed routes.

The report contains only public request parameters, schemas, row counts,
contract metadata and response digests. Returned market records are never
written to the report.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo


DEFAULT_TS_CODE = "600519.SH"
DEFAULT_ETF_TS_CODE = "510300.SH"
HISTORY_START = "20250801"
HISTORY_END = "20250815"
CURVE_END_DATE = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
CURVE_START_DATE = CURVE_END_DATE - timedelta(days=7)
CURVE_START = CURVE_START_DATE.strftime("%Y%m%d")
CURVE_END = CURVE_END_DATE.strftime("%Y%m%d")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git_sha() -> Optional[str]:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _sanitize_text(value: Any) -> str:
    return str(value).replace("\n", " ").replace("\r", " ")[:1000]


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_router_module() -> Any:
    path = Path(__file__).resolve().parents[1] / "plugins" / "china-research-methodology" / "skills" / "china-market-data" / "scripts" / "china_market_data.py"
    spec = importlib.util.spec_from_file_location("china_market_data_akshare_acceptance", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load router module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _result_entry(
    check_id: str,
    dataset: str,
    params: Mapping[str, Any],
    result: Any,
    *,
    min_rows: int,
    expected_interface: str,
) -> Dict[str, Any]:
    metadata = result.metadata
    issues = []
    if metadata.get("interface") != expected_interface:
        issues.append(f"interface={metadata.get('interface')} expected={expected_interface}")
    if not metadata.get("permission_verified_live"):
        issues.append("permission_verified_live is not true")
    if len(result.records) < min_rows:
        issues.append(f"row_count={len(result.records)} below min_rows={min_rows}")
    if metadata.get("status") not in {"full", "partial"}:
        issues.append(f"contract_status={metadata.get('status')}")
    columns = sorted({str(key) for row in result.records for key in row})
    return {
        "check_id": check_id,
        "dataset": dataset,
        "required": True,
        "params": dict(params),
        "status": "pass" if not issues else "contract_failed",
        "issues": issues,
        "row_count": len(result.records),
        "columns": columns,
        "response_sha256": _stable_sha256(result.records),
        "metadata": {
            "interface": metadata.get("interface"),
            "permission_verified_live": metadata.get("permission_verified_live"),
            "pit_grade": metadata.get("pit_grade"),
            "contract_status": metadata.get("status"),
            "units": metadata.get("units"),
            "duplicate_key_rows": metadata.get("duplicate_key_rows"),
            "truncation_suspected": metadata.get("truncation_suspected"),
            "documentation_limit_drift": metadata.get("documentation_limit_drift"),
        },
    }


def _run_fetch(
    provider: Any,
    check_id: str,
    dataset: str,
    params: Mapping[str, Any],
    *,
    min_rows: int,
    expected_interface: str,
    as_of: Optional[str] = None,
    require_pit: bool = False,
) -> tuple[Dict[str, Any], Any]:
    try:
        result = provider.fetch(dataset, params=params, as_of=as_of, require_pit=require_pit)
        return _result_entry(check_id, dataset, params, result, min_rows=min_rows, expected_interface=expected_interface), result
    except Exception as error:
        return {
            "check_id": check_id,
            "dataset": dataset,
            "required": True,
            "params": dict(params),
            "status": "api_error",
            "issues": [_sanitize_text(error)],
            "row_count": 0,
            "columns": [],
        }, None


def _industry_symbol(result: Any) -> Optional[str]:
    if result is None:
        return None
    for row in result.records:
        for key in ("板块名称", "行业名称", "name", "symbol"):
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def run(output: Path) -> int:
    try:
        import akshare as ak  # type: ignore
        module = _load_router_module()
        provider = module.AkshareProvider()
    except Exception as error:
        report = {
            "generated_at": _utc_now(),
            "repository_git_sha": _git_sha(),
            "overall": "needs_revision",
            "fatal_error": _sanitize_text(error),
            "security": {"credentials_required": False, "returned_records_in_report": False},
        }
        _write_report(output, report)
        print("AKShare live acceptance: initialization failed", file=sys.stderr)
        return 2

    specs = [
        ("security_master", "security_master", {}, 1000, "stock_info_a_code_name", None, False),
        (
            "raw_daily_bar_pit",
            "daily_bar",
            {"ts_code": DEFAULT_TS_CODE, "start_date": HISTORY_START, "end_date": HISTORY_END, "adjust": "", "require_quality": True},
            5,
            "stock_zh_a_hist",
            HISTORY_END,
            True,
        ),
        (
            "raw_fund_daily_bar_pit",
            "fund_daily_bar",
            {"ts_code": DEFAULT_ETF_TS_CODE, "start_date": HISTORY_START, "end_date": HISTORY_END, "adjust": "", "require_quality": True},
            5,
            "fund_etf_hist_em",
            HISTORY_END,
            True,
        ),
        ("spot_snapshot", "spot_snapshot", {}, 1000, "stock_zh_a_spot_em", None, False),
        ("industry_list", "industry_list", {}, 10, "stock_board_industry_name_em", None, False),
        (
            "china_yield_curve_maturity",
            "china_yield_curve",
            {"ts_code": "1001.CB", "curve_type": "0", "curve_term": 10, "start_date": CURVE_START, "end_date": CURVE_END, "require_quality": True},
            1,
            "bond_china_yield",
            CURVE_END,
            True,
        ),
        (
            "china_yield_curve_spot",
            "china_yield_curve",
            {"ts_code": "1001.CB", "curve_type": "1", "curve_term": 10, "start_date": CURVE_START, "end_date": CURVE_END, "require_quality": True},
            1,
            "bond_china_close_return",
            CURVE_END,
            True,
        ),
    ]
    checks: list[Dict[str, Any]] = []
    industry_result = None
    for check_id, dataset, params, min_rows, interface, as_of, require_pit in specs:
        started = _utc_now()
        entry, result = _run_fetch(
            provider,
            check_id,
            dataset,
            params,
            min_rows=min_rows,
            expected_interface=interface,
            as_of=as_of,
            require_pit=require_pit,
        )
        entry["started_at"] = started
        entry["finished_at"] = _utc_now()
        checks.append(entry)
        if dataset == "industry_list":
            industry_result = result

    industry = _industry_symbol(industry_result)
    if industry:
        started = _utc_now()
        entry, _ = _run_fetch(
            provider,
            "industry_membership",
            "industry_membership",
            {"symbol": industry, "require_quality": True},
            min_rows=1,
            expected_interface="stock_board_industry_cons_em",
        )
        entry["params"] = {"symbol": industry}
        entry["started_at"] = started
        entry["finished_at"] = _utc_now()
        checks.append(entry)
    else:
        checks.append(
            {
                "check_id": "industry_membership",
                "dataset": "industry_membership",
                "required": True,
                "params": {},
                "status": "blocked_by_dependency",
                "issues": ["industry_list returned no usable industry name"],
                "row_count": 0,
                "columns": [],
                "started_at": _utc_now(),
                "finished_at": _utc_now(),
            }
        )

    # Policy checks: dynamically rebased adjusted prices must fail closed in
    # strict point-in-time mode before a network request is made.
    for dataset, ts_code in (("daily_bar", DEFAULT_TS_CODE), ("fund_daily_bar", DEFAULT_ETF_TS_CODE)):
        started = _utc_now()
        try:
            provider.fetch(
                dataset,
                params={"ts_code": ts_code, "start_date": HISTORY_START, "end_date": HISTORY_END, "adjust": "qfq"},
                as_of=HISTORY_END,
                require_pit=True,
            )
            rejection = {"status": "contract_failed", "issues": ["strict PIT unexpectedly accepted AKShare qfq"]}
        except module.DataProviderError as error:
            rejection = {
                "status": "pass" if error.code == "adjustment_not_pit_safe" else "contract_failed",
                "issues": [] if error.code == "adjustment_not_pit_safe" else [_sanitize_text(error)],
            }
        checks.append(
            {
                "check_id": f"strict_pit_rejects_{dataset}_dynamic_adjustment",
                "dataset": dataset,
                "required": True,
                "params": {"ts_code": ts_code, "adjust": "qfq", "require_pit": True},
                "row_count": 0,
                "columns": [],
                "started_at": started,
                "finished_at": _utc_now(),
                **rejection,
            }
        )

    network_datasets = {item[1] for item in specs} | {"industry_membership"}
    declared_coverage = [
        {
            "dataset": dataset,
            "interface": spec.api_name,
            "attempted_live": dataset in network_datasets,
            "check_statuses": [item["status"] for item in checks if item["dataset"] == dataset and not item["check_id"].startswith("strict_pit_rejects_")],
        }
        for dataset, spec in sorted(module.AKSHARE_ENDPOINTS.items())
    ]
    required_failures = [item["check_id"] for item in checks if item["required"] and item["status"] != "pass"]
    unattempted = [item["dataset"] for item in declared_coverage if not item["attempted_live"]]
    required_failures.extend(f"unattempted:{dataset}" for dataset in unattempted)
    overall = "ready" if not required_failures else "needs_revision"
    report = {
        "generated_at": _utc_now(),
        "repository_git_sha": _git_sha(),
        "sdk": {"python": platform.python_version(), "akshare": getattr(ak, "__version__", "unknown")},
        "security": {"credentials_required": False, "returned_records_in_report": False},
        "scope": {"raw_daily_ts_code": DEFAULT_TS_CODE, "raw_etf_ts_code": DEFAULT_ETF_TS_CODE, "history_start": HISTORY_START, "history_end": HISTORY_END, "curve_start": CURVE_START, "curve_end": CURVE_END},
        "overall": overall,
        "required_failures": required_failures,
        "acceptance_claim": "all declared AKShare router interfaces attempted live" if not unattempted else "partial declared-interface coverage",
        "declared_dataset_coverage": declared_coverage,
        "checks": checks,
    }
    report["evidence_sha256"] = _stable_sha256({"checks": checks, "declared_dataset_coverage": declared_coverage})
    _write_report(output, report)
    passed = sum(1 for item in checks if item["status"] == "pass")
    print(f"AKShare live acceptance: overall={overall} passed={passed}/{len(checks)} required_failures={len(required_failures)}")
    return 0 if overall == "ready" else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Sanitized JSON report path")
    args = parser.parse_args(argv)
    return run(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
