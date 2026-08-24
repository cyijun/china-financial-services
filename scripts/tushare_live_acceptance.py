#!/usr/bin/env python3
"""Run a sanitized, read-only acceptance suite against Tushare Pro.

The token is read only from ``TUSHARE_TOKEN``. Reports contain endpoint names,
public request parameters, row counts, columns, and redacted errors; they never
contain returned records or credentials.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
FINANCIAL_PERIOD = "20241231"
ST_HISTORY_DATE = "20250813"
YIELD_CURVE_DATE = "20200203"
DEFAULT_TS_CODE = "600519.SH"


@dataclass(frozen=True)
class CheckSpec:
    check_id: str
    api_name: str
    params: Mapping[str, Any]
    required_columns: Tuple[str, ...]
    required: bool = True
    min_rows: int = 1
    distinct_column: Optional[str] = None
    min_distinct: int = 1
    expected_values: Mapping[str, str] = field(default_factory=dict)
    require_any_nonempty: Tuple[str, ...] = ()
    documented_row_limit: Optional[int] = None
    contract_note: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_text(value: Any, token: Optional[str]) -> str:
    text = str(value)
    if token:
        text = text.replace(token, "[REDACTED]")
    return text.replace("\n", " ").replace("\r", " ")[:1000]


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            result[str(key)] = "[REDACTED]" if any(marker in lowered for marker in ("token", "secret", "password", "credential")) else _redact(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _classify_error(message: str) -> str:
    lowered = message.lower()
    if (
        any(marker in message for marker in ("没有权限", "无权访问", "权限不足", "需要单独开通"))
        or ("没有" in message and "访问权限" in message)
        or "permission" in lowered
    ):
        return "permission_denied"
    if any(marker in message for marker in ("频率", "限流")) or "rate limit" in lowered or "too many" in lowered:
        return "rate_limited"
    if "token" in lowered and any(marker in lowered for marker in ("invalid", "error", "missing")):
        return "credential_rejected"
    return "api_error"


def _frame_payload(frame: Any) -> Tuple[List[str], List[Dict[str, Any]]]:
    if frame is None or not hasattr(frame, "columns") or not hasattr(frame, "to_dict"):
        raise TypeError(f"unsupported response type: {type(frame).__name__}")
    columns = [str(column) for column in frame.columns]
    records = [dict(row) for row in frame.to_dict(orient="records")]
    return columns, records


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    return text not in {"", "nan", "none", "nat"}


def _evaluate(spec: CheckSpec, columns: Sequence[str], records: Sequence[Mapping[str, Any]]) -> Tuple[List[str], Dict[str, Any]]:
    issues: List[str] = []
    missing = sorted(set(spec.required_columns) - set(columns))
    if missing:
        issues.append(f"missing_columns={missing}")
    if len(records) < spec.min_rows:
        issues.append(f"row_count={len(records)} below min_rows={spec.min_rows}")

    metrics: Dict[str, Any] = {}
    if spec.distinct_column:
        distinct = {str(row.get(spec.distinct_column)) for row in records if _nonempty(row.get(spec.distinct_column))}
        metrics[f"distinct_{spec.distinct_column}"] = len(distinct)
        if len(distinct) < spec.min_distinct:
            issues.append(f"distinct_{spec.distinct_column}={len(distinct)} below min_distinct={spec.min_distinct}")

    for column, expected in spec.expected_values.items():
        observed = {str(row.get(column)) for row in records if _nonempty(row.get(column))}
        metrics[f"observed_{column}"] = sorted(observed)[:20]
        if observed != {expected}:
            issues.append(f"{column} expected only {expected}, observed={sorted(observed)[:20]}")

    for column in spec.require_any_nonempty:
        count = sum(1 for row in records if _nonempty(row.get(column)))
        metrics[f"nonempty_{column}"] = count
        if count == 0:
            issues.append(f"no non-empty values for {column}")

    if spec.documented_row_limit is not None:
        metrics["documented_row_limit"] = spec.documented_row_limit
        metrics["possible_truncation"] = len(records) == spec.documented_row_limit
        metrics["documentation_limit_drift"] = len(records) > spec.documented_row_limit
    return issues, metrics


def _run_check(client: Any, spec: CheckSpec, token: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    started = _utc_now()
    base = {
        "check_id": spec.check_id,
        "api_name": spec.api_name,
        "required": spec.required,
        "params": _redact(dict(spec.params)),
        "contract_note": spec.contract_note,
        "started_at": started,
    }
    try:
        method = getattr(client, spec.api_name)
        columns, records = _frame_payload(method(**dict(spec.params)))
        issues, metrics = _evaluate(spec, columns, records)
        base.update(
            {
                "status": "pass" if not issues else "contract_failed",
                "row_count": len(records),
                "columns": columns,
                "issues": issues,
                "metrics": metrics,
            }
        )
        return base, records
    except Exception as error:  # Tushare SDK raises generic Exception subclasses.
        message = _sanitize_text(error, token)
        category = _classify_error(message)
        status = "expected_permission_gap" if not spec.required and category == "permission_denied" else category
        base.update({"status": status, "row_count": 0, "columns": [], "issues": [message], "metrics": {}})
        return base, []
    finally:
        base["finished_at"] = _utc_now()


def _base_specs(latest_open_date: str) -> List[CheckSpec]:
    financial_fields = "ts_code,ann_date,f_ann_date,end_date,report_type,update_flag"
    return [
        CheckSpec(
            "daily_single_security",
            "daily",
            {"ts_code": DEFAULT_TS_CODE, "trade_date": latest_open_date, "fields": "ts_code,trade_date,open,high,low,close,vol,amount"},
            ("ts_code", "trade_date", "open", "close", "vol", "amount"),
            expected_values={"ts_code": DEFAULT_TS_CODE, "trade_date": latest_open_date},
            contract_note="Unadjusted A-share daily bar; vol is lots and amount is thousand CNY.",
        ),
        CheckSpec("income_single_security", "income", {"ts_code": DEFAULT_TS_CODE, "period": FINANCIAL_PERIOD, "fields": financial_fields + ",revenue,n_income_attr_p"}, ("ts_code", "ann_date", "f_ann_date", "end_date", "revenue", "n_income_attr_p"), expected_values={"ts_code": DEFAULT_TS_CODE, "end_date": FINANCIAL_PERIOD}),
        CheckSpec("balance_sheet_single_security", "balancesheet", {"ts_code": DEFAULT_TS_CODE, "period": FINANCIAL_PERIOD, "fields": financial_fields + ",total_assets,total_liab"}, ("ts_code", "ann_date", "f_ann_date", "end_date", "total_assets", "total_liab"), expected_values={"ts_code": DEFAULT_TS_CODE, "end_date": FINANCIAL_PERIOD}),
        CheckSpec("cash_flow_single_security", "cashflow", {"ts_code": DEFAULT_TS_CODE, "period": FINANCIAL_PERIOD, "fields": financial_fields + ",n_cashflow_act"}, ("ts_code", "ann_date", "f_ann_date", "end_date", "n_cashflow_act"), expected_values={"ts_code": DEFAULT_TS_CODE, "end_date": FINANCIAL_PERIOD}),
        CheckSpec("financial_indicator_single_security", "fina_indicator", {"ts_code": DEFAULT_TS_CODE, "period": FINANCIAL_PERIOD, "fields": "ts_code,ann_date,end_date,roe,roe_waa,grossprofit_margin,debt_to_assets,update_flag"}, ("ts_code", "ann_date", "end_date", "roe", "debt_to_assets"), expected_values={"ts_code": DEFAULT_TS_CODE, "end_date": FINANCIAL_PERIOD}),
        CheckSpec("income_vip_cross_section", "income_vip", {"period": FINANCIAL_PERIOD, "fields": financial_fields + ",revenue,n_income_attr_p"}, ("ts_code", "ann_date", "f_ann_date", "end_date", "revenue", "n_income_attr_p"), min_rows=100, distinct_column="ts_code", min_distinct=100, expected_values={"end_date": FINANCIAL_PERIOD}),
        CheckSpec("balance_sheet_vip_cross_section", "balancesheet_vip", {"period": FINANCIAL_PERIOD, "fields": financial_fields + ",total_assets,total_liab"}, ("ts_code", "ann_date", "f_ann_date", "end_date", "total_assets", "total_liab"), min_rows=100, distinct_column="ts_code", min_distinct=100, expected_values={"end_date": FINANCIAL_PERIOD}),
        CheckSpec("cash_flow_vip_cross_section", "cashflow_vip", {"period": FINANCIAL_PERIOD, "fields": financial_fields + ",n_cashflow_act"}, ("ts_code", "ann_date", "f_ann_date", "end_date", "n_cashflow_act"), min_rows=100, distinct_column="ts_code", min_distinct=100, expected_values={"end_date": FINANCIAL_PERIOD}),
        CheckSpec("financial_indicator_vip_cross_section", "fina_indicator_vip", {"period": FINANCIAL_PERIOD, "fields": "ts_code,ann_date,end_date,roe,roe_waa,grossprofit_margin,debt_to_assets,update_flag"}, ("ts_code", "ann_date", "end_date", "roe", "debt_to_assets"), min_rows=100, distinct_column="ts_code", min_distinct=100, expected_values={"end_date": FINANCIAL_PERIOD}),
        CheckSpec("historical_industry_membership", "index_member_all", {"is_new": "N", "fields": "l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,in_date,out_date,is_new"}, ("l1_code", "l2_code", "l3_code", "ts_code", "in_date", "out_date", "is_new"), min_rows=1, expected_values={"is_new": "N"}, require_any_nonempty=("in_date", "out_date"), documented_row_limit=2000, contract_note="Historical rows are interval evidence; a result at the row limit is not a complete all-market extract."),
        CheckSpec("historical_st_status", "stock_st", {"trade_date": ST_HISTORY_DATE, "fields": "ts_code,name,trade_date,type,type_name"}, ("ts_code", "name", "trade_date", "type", "type_name"), expected_values={"trade_date": ST_HISTORY_DATE}, documented_row_limit=1000),
        CheckSpec("ths_index_catalog", "ths_index", {"exchange": "A", "type": "I", "fields": "ts_code,name,count,exchange,list_date,type"}, ("ts_code", "name", "exchange", "type"), min_rows=1, distinct_column="ts_code", min_distinct=1, expected_values={"exchange": "A", "type": "I"}, documented_row_limit=5000, contract_note="Current catalog only; not point-in-time history."),
        CheckSpec("china_yield_curve", "yc_cb", {"ts_code": "1001.CB", "curve_type": "0", "trade_date": YIELD_CURVE_DATE, "fields": "trade_date,ts_code,curve_name,curve_type,curve_term,yield"}, ("trade_date", "ts_code", "curve_type", "curve_term", "yield"), required=False, expected_values={"trade_date": YIELD_CURVE_DATE, "curve_type": "0"}, documented_row_limit=2000, contract_note="Official docs classify yc_cb as a separately granted permission, independent of points."),
    ]


def _calendar_spec(today: datetime) -> CheckSpec:
    end = (today.date() - timedelta(days=1)).strftime("%Y%m%d")
    start = (today.date() - timedelta(days=21)).strftime("%Y%m%d")
    return CheckSpec(
        "trade_calendar",
        "trade_cal",
        {"exchange": "SSE", "start_date": start, "end_date": end, "fields": "exchange,cal_date,is_open,pretrade_date"},
        ("exchange", "cal_date", "is_open", "pretrade_date"),
        min_rows=7,
        expected_values={"exchange": "SSE"},
    )


def _latest_open_date(records: Iterable[Mapping[str, Any]]) -> Optional[str]:
    values = [str(row.get("cal_date")) for row in records if str(row.get("is_open")) == "1" and _nonempty(row.get("cal_date"))]
    return max(values) if values else None


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_router_module() -> Any:
    path = Path(__file__).resolve().parents[1] / "plugins" / "vertical-plugins" / "china-research-methodology" / "skills" / "china-market-data" / "scripts" / "china_market_data.py"
    spec = importlib.util.spec_from_file_location("china_market_data_live_acceptance", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load router module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_router_checks(token: str, latest_open: str, ths_code: str) -> List[Dict[str, Any]]:
    cases = [
        ("router_daily_pit", "daily_bar", {"ts_code": DEFAULT_TS_CODE, "trade_date": latest_open}, f"{latest_open[:4]}-{latest_open[4:6]}-{latest_open[6:]}T16:30:00+08:00", True, "daily", 1),
        ("router_income_vip_pit", "income", {"period": FINANCIAL_PERIOD, "universe_mode": "cross_section", "fields": "ts_code,ann_date,f_ann_date,end_date,revenue,n_income_attr_p,update_flag"}, "2026-08-24T23:59:59+08:00", True, "income_vip", 100),
        ("router_historical_membership_pit", "industry_membership", {"ts_code": DEFAULT_TS_CODE}, "2020-01-02T23:59:59+08:00", True, "index_member_all", 1),
        ("router_ths_membership_snapshot", "ths_membership", {"ts_code": ths_code}, None, False, "ths_member", 1),
    ]
    try:
        module = _load_router_module()
        provider = module.TushareProvider(points_profile=6000)
    except Exception as error:
        return [{"check_id": "router_initialization", "required": True, "status": "router_error", "issues": [_sanitize_text(error, token)]}]

    output: List[Dict[str, Any]] = []
    for check_id, dataset, params, as_of, require_pit, expected_interface, min_rows in cases:
        started = _utc_now()
        entry: Dict[str, Any] = {
            "check_id": check_id,
            "dataset": dataset,
            "required": True,
            "params": _redact(params),
            "as_of": as_of,
            "require_pit": require_pit,
            "started_at": started,
        }
        try:
            result = provider.fetch(dataset, params=params, as_of=as_of, require_pit=require_pit)
            metadata = result.metadata
            issues: List[str] = []
            if metadata.get("interface") != expected_interface:
                issues.append(f"interface={metadata.get('interface')} expected={expected_interface}")
            if not metadata.get("permission_verified_live"):
                issues.append("permission_verified_live is not true")
            if len(result.records) < min_rows:
                issues.append(f"row_count={len(result.records)} below min_rows={min_rows}")
            if metadata.get("status") not in {"full", "partial"}:
                issues.append(f"contract_status={metadata.get('status')}")
            entry.update(
                {
                    "status": "pass" if not issues else "contract_failed",
                    "issues": issues,
                    "row_count": len(result.records),
                    "metadata": {
                        "interface": metadata.get("interface"),
                        "permission_verified_live": metadata.get("permission_verified_live"),
                        "pit_grade": metadata.get("pit_grade"),
                        "contract_status": metadata.get("status"),
                        "row_count_before_pit_filter": metadata.get("row_count_before_pit_filter"),
                        "row_count": metadata.get("row_count"),
                        "duplicate_key_rows": metadata.get("duplicate_key_rows"),
                        "truncation_suspected": metadata.get("truncation_suspected"),
                        "documentation_limit_drift": metadata.get("documentation_limit_drift"),
                    },
                }
            )
        except Exception as error:
            entry.update({"status": "router_error", "issues": [_sanitize_text(error, token)], "row_count": 0, "metadata": {}})
        entry["finished_at"] = _utc_now()
        output.append(entry)
    return output


def run(output: Path, strict_optional: bool = False) -> int:
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        report = {"generated_at": _utc_now(), "overall": "needs_revision", "fatal_error": "TUSHARE_TOKEN is not configured"}
        _write_report(output, report)
        print("Tushare live acceptance: TUSHARE_TOKEN is not configured", file=sys.stderr)
        return 2
    try:
        import tushare as ts  # type: ignore
    except ImportError:
        report = {"generated_at": _utc_now(), "overall": "needs_revision", "fatal_error": "Python package 'tushare' is not installed"}
        _write_report(output, report)
        print("Tushare live acceptance: package 'tushare' is not installed", file=sys.stderr)
        return 2

    client = ts.pro_api(token)
    now = datetime.now(SHANGHAI)
    results: List[Dict[str, Any]] = []
    calendar_result, calendar_records = _run_check(client, _calendar_spec(now), token)
    results.append(calendar_result)
    latest_open = _latest_open_date(calendar_records) or ST_HISTORY_DATE

    ths_index_records: List[Dict[str, Any]] = []
    for spec in _base_specs(latest_open):
        result, records = _run_check(client, spec, token)
        results.append(result)
        if spec.check_id == "ths_index_catalog":
            ths_index_records = records

    ths_code = next((str(row.get("ts_code")) for row in ths_index_records if _nonempty(row.get("ts_code"))), "885800.TI")
    ths_member_spec = CheckSpec(
        "ths_current_membership",
        "ths_member",
        {"ts_code": ths_code, "fields": "ts_code,con_code,con_name,weight,in_date,out_date,is_new"},
        ("ts_code", "con_code", "con_name"),
        min_rows=1,
        distinct_column="con_code",
        min_distinct=1,
        expected_values={"ts_code": ths_code},
        documented_row_limit=5000,
        contract_note="Current membership snapshot; official fields in_date/out_date are not populated reliably.",
    )
    ths_member_result, _ = _run_check(client, ths_member_spec, token)
    results.append(ths_member_result)

    router_checks = _run_router_checks(token, latest_open, ths_code)

    required_failures = [item["check_id"] for item in results if item["required"] and item["status"] != "pass"]
    required_failures.extend(f"router:{item['check_id']}" for item in router_checks if item["required"] and item["status"] != "pass")
    optional_gaps = [item["check_id"] for item in results if not item["required"] and item["status"] != "pass"]
    overall = "ready" if not required_failures and not optional_gaps else "ready_with_optional_caveats" if not required_failures else "needs_revision"
    if strict_optional and optional_gaps:
        overall = "needs_revision"

    report = {
        "generated_at": _utc_now(),
        "as_of_timezone": "Asia/Shanghai",
        "as_of_local": now.isoformat(),
        "sdk": {"python": platform.python_version(), "tushare": getattr(ts, "__version__", "unknown")},
        "security": {"credential_source": "TUSHARE_TOKEN environment variable", "token_in_report": False, "returned_records_in_report": False},
        "scope": {
            "points_profile": 6000,
            "daily_trade_date": latest_open,
            "financial_period": FINANCIAL_PERIOD,
            "historical_st_date": ST_HISTORY_DATE,
            "yield_curve_date": YIELD_CURVE_DATE,
        },
        "overall": overall,
        "required_failures": required_failures,
        "optional_gaps": optional_gaps,
        "checks": results,
        "router_checks": router_checks,
    }
    _write_report(output, report)
    all_checks = results + router_checks
    passed = sum(1 for item in all_checks if item["status"] == "pass")
    print(f"Tushare live acceptance: overall={overall} passed={passed}/{len(all_checks)} required_failures={len(required_failures)} optional_gaps={len(optional_gaps)}")
    return 1 if overall == "needs_revision" else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Sanitized JSON report path")
    parser.add_argument("--strict-optional", action="store_true", help="Fail when a separately granted optional endpoint is unavailable")
    args = parser.parse_args(argv)
    return run(args.output, strict_optional=args.strict_optional)


if __name__ == "__main__":
    raise SystemExit(main())
