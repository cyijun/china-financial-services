#!/usr/bin/env python3
"""Auditable China-market data router for Tushare Pro and AKShare.

SDKs are imported lazily, credentials stay process-local, and production never
falls back to mock data. The router is deliberately conservative: a date-only
financial announcement becomes usable on the following Shanghai calendar day,
and a daily bar becomes usable at 16:00 Asia/Shanghai.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo


SNAPSHOT_DATE = "2026-08-24"
DEFAULT_POINTS_PROFILE = 6000
SHANGHAI = ZoneInfo("Asia/Shanghai")
SENSITIVE_MARKERS = ("token", "secret", "password", "api_key", "apikey", "credential")
AUTO_FALLBACK_CODES = {
    "missing_credential",
    "missing_dependency",
    "permission_denied",
    "credential_rejected",
    "rate_limited",
    "network_error",
    "service_unavailable",
    "sdk_interface_missing",
}


class DataProviderError(RuntimeError):
    """Structured provider failure safe to return after credential redaction."""

    def __init__(self, code: str, message: str, provider: str, interface: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.interface = interface

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": str(self), "provider": self.provider, "interface": self.interface}


@dataclass(frozen=True)
class EndpointSpec:
    api_name: str
    min_points: Optional[int]
    pit_grade: str
    docs: str
    availability_fields: Tuple[str, ...] = ()
    vip_api_name: Optional[str] = None
    vip_min_points: Optional[int] = None
    max_rows: Optional[int] = None
    required_fields: Tuple[str, ...] = ()
    primary_key: Tuple[str, ...] = ()
    units: Tuple[Tuple[str, str], ...] = ()
    interval_end_inclusive: bool = False
    permission_note: Optional[str] = None


@dataclass(frozen=True)
class AsOf:
    moment: datetime
    precision: str

    @property
    def date_key(self) -> str:
        return self.moment.astimezone(SHANGHAI).strftime("%Y%m%d")


@dataclass
class DataResult:
    dataset: str
    records: List[Dict[str, Any]]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"dataset": self.dataset, "records": self.records, "metadata": self.metadata}


DOC = "https://tushare.pro/document/2?doc_id="
TUSHARE_ENDPOINTS: Dict[str, EndpointSpec] = {
    "security_master": EndpointSpec("stock_basic", 2000, "listing_interval", DOC + "25", ("list_date", "delist_date"), max_rows=6000, required_fields=("ts_code",), primary_key=("ts_code",)),
    "trade_calendar": EndpointSpec("trade_cal", 2000, "calendar_date", DOC + "26", ("cal_date",), max_rows=6000, required_fields=("cal_date",), primary_key=("exchange", "cal_date")),
    "daily_bar": EndpointSpec("daily", None, "trade_date", DOC + "27", ("trade_date",), max_rows=6000, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date"), units=(("vol", "lots"), ("amount", "thousand_CNY"))),
    "adjustment_factor": EndpointSpec("adj_factor", 2000, "trade_date", DOC + "28", ("trade_date",), max_rows=6000, required_fields=("ts_code", "trade_date", "adj_factor"), primary_key=("ts_code", "trade_date")),
    "daily_basic": EndpointSpec("daily_basic", 2000, "trade_date", DOC + "32", ("trade_date",), max_rows=6000, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date"), units=(("total_mv", "ten_thousand_CNY"), ("circ_mv", "ten_thousand_CNY"))),
    "income": EndpointSpec("income", 2000, "reported_with_availability", DOC + "33", ("ann_date", "f_ann_date"), "income_vip", 5000, required_fields=("ts_code", "end_date")),
    "balance_sheet": EndpointSpec("balancesheet", 2000, "reported_with_availability", DOC + "36", ("ann_date", "f_ann_date"), "balancesheet_vip", 5000, required_fields=("ts_code", "end_date")),
    "cash_flow": EndpointSpec("cashflow", 2000, "reported_with_availability", DOC + "44", ("ann_date", "f_ann_date"), "cashflow_vip", 5000, required_fields=("ts_code", "end_date")),
    "forecast": EndpointSpec("forecast", 2000, "reported_with_availability", DOC + "45", ("ann_date",), "forecast_vip", 5000, 3500, ("ts_code", "end_date")),
    "express": EndpointSpec("express", 2000, "reported_with_availability", DOC + "46", ("ann_date",), "express_vip", 5000, required_fields=("ts_code", "end_date")),
    "financial_indicator": EndpointSpec("fina_indicator", 2000, "reported_with_availability", DOC + "79", ("ann_date",), "fina_indicator_vip", 5000, 100, ("ts_code", "end_date")),
    "disclosure_schedule": EndpointSpec("disclosure_date", 2000, "schedule_not_actual_release", DOC + "162", max_rows=3000),
    "money_flow": EndpointSpec("moneyflow", 2000, "trade_date", DOC + "170", ("trade_date",), max_rows=6000, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date")),
    "suspend_status": EndpointSpec("suspend_d", None, "trade_date", DOC + "214", ("trade_date",), required_fields=("ts_code", "trade_date", "suspend_type"), primary_key=("ts_code", "trade_date", "suspend_type")),
    "price_limit": EndpointSpec("stk_limit", 2000, "market_rule_date", DOC + "183", ("trade_date",), max_rows=5800, required_fields=("ts_code", "trade_date", "up_limit", "down_limit"), primary_key=("ts_code", "trade_date"), units=(("pre_close", "CNY_per_share"), ("up_limit", "CNY_per_share"), ("down_limit", "CNY_per_share"))),
    "industry_classification": EndpointSpec("index_classify", 2000, "classification_version", DOC + "181", max_rows=10000),
    "industry_membership": EndpointSpec("index_member_all", 2000, "membership_interval", DOC + "335", ("in_date", "out_date"), max_rows=2000, required_fields=("ts_code", "in_date"), primary_key=("l1_code", "l2_code", "l3_code", "ts_code", "in_date")),
    "st_status": EndpointSpec("stock_st", 3000, "trade_date", DOC + "397", ("trade_date",), max_rows=1000, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date", "type")),
    "ths_index": EndpointSpec("ths_index", 6000, "current_snapshot", DOC + "259", max_rows=5000, required_fields=("ts_code", "name", "exchange", "type"), primary_key=("ts_code",)),
    "ths_membership": EndpointSpec("ths_member", 6000, "current_snapshot", DOC + "261", max_rows=5000, required_fields=("ts_code", "con_code", "con_name"), primary_key=("ts_code", "con_code")),
    "shibor": EndpointSpec("shibor", None, "calendar_date", DOC + "149", ("date",), max_rows=2000),
    "lpr": EndpointSpec("shibor_lpr", None, "calendar_date", DOC + "151", ("date",), max_rows=2000),
    "china_yield_curve": EndpointSpec("yc_cb", None, "calendar_date", DOC + "201", ("trade_date", "date"), max_rows=2000, required_fields=("trade_date", "ts_code", "curve_type", "curve_term", "yield"), primary_key=("trade_date", "ts_code", "curve_type", "curve_term"), permission_note="separate_grant_required"),
}

AKSHARE_ENDPOINTS: Dict[str, EndpointSpec] = {
    "security_master": EndpointSpec("stock_info_a_code_name", None, "current_snapshot", "https://akshare.akfamily.xyz/data/stock/stock.html", max_rows=10000, required_fields=("ts_code",), primary_key=("ts_code",)),
    "daily_bar": EndpointSpec("stock_zh_a_hist", None, "trade_date", "https://akshare.akfamily.xyz/data/stock/stock.html", ("trade_date",), max_rows=None, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date"), units=(("vol", "lots"), ("amount", "thousand_CNY"))),
    "spot_snapshot": EndpointSpec("stock_zh_a_spot_em", None, "current_snapshot", "https://akshare.akfamily.xyz/data/stock/stock.html", max_rows=10000),
    "industry_list": EndpointSpec("stock_board_industry_name_em", None, "current_snapshot", "https://akshare.akfamily.xyz/data/stock/stock.html", max_rows=1000),
    "industry_membership": EndpointSpec("stock_board_industry_cons_em", None, "current_snapshot", "https://akshare.akfamily.xyz/data/stock/stock.html", max_rows=1000),
}

DATASET_ALIASES = {
    "stock_basic": "security_master",
    "trade_cal": "trade_calendar",
    "daily": "daily_bar",
    "adj_factor": "adjustment_factor",
    "balancesheet": "balance_sheet",
    "cashflow": "cash_flow",
    "fina_indicator": "financial_indicator",
    "disclosure_date": "disclosure_schedule",
    "moneyflow": "money_flow",
    "suspend_d": "suspend_status",
    "stk_limit": "price_limit",
    "index_classify": "industry_classification",
    "index_member_all": "industry_membership",
    "stock_st": "st_status",
    "ths_member": "ths_membership",
    "shibor_lpr": "lpr",
    "yc_cb": "china_yield_curve",
}
PIT_SAFE_GRADES = {"calendar_date", "trade_date", "market_rule_date", "reported_with_availability", "membership_interval", "listing_interval"}
SAFE_MASTER_FIELDS = {"ts_code", "symbol", "market", "exchange", "curr_type", "list_date", "delist_date"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_dataset(dataset: str) -> str:
    return DATASET_ALIASES.get(dataset, dataset)


def _records(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [dict(row) for row in value]
    if hasattr(value, "to_dict"):
        try:
            return [dict(row) for row in value.to_dict(orient="records")]
        except TypeError:
            return [dict(row) for row in value.to_dict("records")]
    raise DataProviderError("unsupported_result", f"Unsupported result type: {type(value).__name__}", "router")


def _valid_date(value: Any) -> Optional[date]:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    match = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _date_key(value: Any) -> Optional[str]:
    parsed = _valid_date(value)
    return parsed.strftime("%Y%m%d") if parsed else None


def _parse_as_of(value: Optional[str]) -> Optional[AsOf]:
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{8}|\d{4}-\d{2}-\d{2}", text):
        parsed = _valid_date(text)
        if not parsed:
            raise DataProviderError("invalid_request", "as_of is not a real calendar date", "router")
        return AsOf(datetime.combine(parsed, time.max, SHANGHAI), "date")
    try:
        normalized = text.replace("Z", "+00:00")
        moment = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise DataProviderError("invalid_request", "as_of must be YYYYMMDD, YYYY-MM-DD, or ISO-8601", "router") from error
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    return AsOf(moment.astimezone(SHANGHAI), "timestamp")


def _row_available_at(value: Any, grade: str) -> Optional[datetime]:
    parsed = _valid_date(value)
    if not parsed:
        return None
    text_value = str(value)
    if "T" in text_value or re.search(r"\d{2}:\d{2}", text_value):
        try:
            moment = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=SHANGHAI)
            return moment.astimezone(SHANGHAI)
        except ValueError:
            pass
    if grade == "reported_with_availability":
        return datetime.combine(parsed + timedelta(days=1), time.min, SHANGHAI)
    if grade == "trade_date":
        return datetime.combine(parsed, time(16, 0), SHANGHAI)
    if grade == "market_rule_date":
        return datetime.combine(parsed, time(9, 0), SHANGHAI)
    return datetime.combine(parsed, time.max, SHANGHAI)


def _filter_as_of(rows: Sequence[Dict[str, Any]], as_of: Optional[str], fields: Sequence[str], require_pit: bool, grade: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    cutoff = _parse_as_of(as_of)
    if cutoff is None:
        if require_pit:
            raise DataProviderError("invalid_request", "require_pit=true requires as_of", "router")
        return list(rows), {"future_rows_dropped": 0, "missing_availability_dropped": 0}
    kept: List[Dict[str, Any]] = []
    future = missing = 0
    for row in rows:
        moments = [moment for field in fields if (moment := _row_available_at(row.get(field), grade))]
        if not moments:
            if require_pit:
                missing += 1
            else:
                kept.append(dict(row))
        elif max(moments) <= cutoff.moment:
            kept.append(dict(row))
        else:
            future += 1
    return kept, {"future_rows_dropped": future, "missing_availability_dropped": missing}


def _filter_interval_as_of(rows: Sequence[Dict[str, Any]], as_of: Optional[str], start_field: str, end_field: str, require_pit: bool, end_inclusive: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    cutoff = _parse_as_of(as_of)
    if cutoff is None:
        if require_pit:
            raise DataProviderError("invalid_request", "require_pit=true requires as_of", "router")
        return list(rows), {"outside_interval_rows_dropped": 0, "missing_availability_dropped": 0}
    key = cutoff.date_key
    kept: List[Dict[str, Any]] = []
    outside = missing = 0
    for row in rows:
        start, end = _date_key(row.get(start_field)), _date_key(row.get(end_field))
        if not start:
            if require_pit:
                missing += 1
            else:
                kept.append(dict(row))
        elif start <= key and (not end or (key <= end if end_inclusive else key < end)):
            kept.append(dict(row))
        else:
            outside += 1
    return kept, {"outside_interval_rows_dropped": outside, "missing_availability_dropped": missing}


def _safe_message(error: BaseException, token: Optional[str] = None) -> str:
    message = str(error)
    if token:
        message = message.replace(token, "[REDACTED_TOKEN]")
    return message[:1000]


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): "[REDACTED]" if any(mark in str(key).lower() for mark in SENSITIVE_MARKERS) else _redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def _provider_error(error: BaseException, provider: str, interface: str, token: Optional[str] = None) -> DataProviderError:
    message = _safe_message(error, token)
    lowered = message.lower()
    if any(word in message for word in ("积分", "权限", "无权限")) or "permission" in lowered or "forbidden" in lowered:
        code = "permission_denied"
    elif any(word in message for word in ("频率", "限流")) or "429" in lowered or "rate limit" in lowered:
        code = "rate_limited"
    elif "token" in lowered or "认证" in message or "unauthorized" in lowered:
        code = "credential_rejected"
    elif isinstance(error, (ConnectionError, TimeoutError)) or any(word in lowered for word in ("timeout", "connection", "dns", "network")):
        code = "network_error"
    elif any(word in lowered for word in ("502", "503", "service unavailable")):
        code = "service_unavailable"
    else:
        code = "provider_error"
    return DataProviderError(code, message, provider, interface)


def _canonical_ts_code(code: Any) -> str:
    text = str(code).strip().upper()
    if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", text):
        return text
    digits = re.sub(r"\D", "", text)
    if len(digits) != 6:
        return text
    if digits.startswith("92") or digits[0] in {"4", "8"}:
        suffix = "BJ"
    elif digits[0] in {"5", "6"} or digits.startswith("900"):
        suffix = "SH"
    else:
        suffix = "SZ"
    return f"{digits}.{suffix}"


def _validate_request(
    request: Mapping[str, Any],
    ts_code_pattern: str = r"\d{6}(?:\.(?:SH|SZ|BJ))?",
    ts_code_description: str = "a six-digit China security code",
) -> None:
    for key in ("start_date", "end_date", "trade_date", "period", "ann_date"):
        if key in request and request[key] not in (None, "") and not _valid_date(request[key]):
            raise DataProviderError("invalid_request", f"{key} is not a real calendar date", "router")
    for key in ("ts_code", "stock"):
        if key in request and request[key] not in (None, ""):
            codes = [part.strip() for part in str(request[key]).upper().split(",")]
            if not codes or any(not re.fullmatch(ts_code_pattern, code) for code in codes):
                raise DataProviderError("invalid_request", f"{key} must be {ts_code_description}", "router")


def _ak_symbol(code: Any) -> str:
    canonical = _canonical_ts_code(code)
    if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", canonical):
        raise DataProviderError("invalid_request", "invalid China security code", "akshare")
    return canonical[:6]


def _normalize_akshare(dataset: str, rows: Iterable[Dict[str, Any]], ts_code: Optional[str] = None) -> List[Dict[str, Any]]:
    mappings = {
        "daily_bar": {"日期": "trade_date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "vol", "成交额": "amount", "振幅": "amplitude", "涨跌幅": "pct_chg", "涨跌额": "change", "换手率": "turnover_rate"},
        "security_master": {"code": "symbol", "name": "name", "代码": "symbol", "名称": "name"},
    }
    rename = mappings.get(dataset, {})
    output: List[Dict[str, Any]] = []
    for raw in rows:
        row = {rename.get(key, key): value for key, value in raw.items()}
        if dataset == "security_master" and row.get("symbol"):
            row["ts_code"] = _canonical_ts_code(row["symbol"])
        if dataset == "daily_bar":
            row["ts_code"] = _canonical_ts_code(ts_code)
            row["trade_date"] = _date_key(row.get("trade_date"))
            if isinstance(row.get("amount"), (int, float)):
                row["amount"] = row["amount"] / 1000.0
        output.append(row)
    return output


def _dedupe(rows: Sequence[Dict[str, Any]], keys: Sequence[str]) -> List[Dict[str, Any]]:
    if not keys:
        return [dict(row) for row in rows]
    output, seen = [], set()
    for row in rows:
        marker = tuple(row.get(key) for key in keys)
        if marker not in seen:
            seen.add(marker)
            output.append(dict(row))
    return output


def _contract_metadata(spec: EndpointSpec, rows: Sequence[Dict[str, Any]], require_complete: bool, observed_limit_count: Optional[int] = None) -> Dict[str, Any]:
    missing_required = sorted({field for row in rows for field in spec.required_fields if field not in row})
    duplicate_count = len(rows) - len(_dedupe(rows, spec.primary_key)) if spec.primary_key else 0
    limit_count = len(rows) if observed_limit_count is None else observed_limit_count
    truncation_suspected = bool(spec.max_rows and limit_count == spec.max_rows)
    documentation_limit_drift = bool(spec.max_rows and limit_count > spec.max_rows)
    if missing_required:
        raise DataProviderError("schema_mismatch", f"missing canonical fields: {missing_required}", "router", spec.api_name)
    if require_complete and truncation_suspected:
        raise DataProviderError("truncation_suspected", f"row count reached interface limit {spec.max_rows}; segment the request", "router", spec.api_name)
    return {
        "required_fields": list(spec.required_fields),
        "primary_key": list(spec.primary_key),
        "units": dict(spec.units),
        "duplicate_key_rows": duplicate_count,
        "documented_row_limit": spec.max_rows,
        "truncation_suspected": truncation_suspected,
        "documentation_limit_drift": documentation_limit_drift,
        "status": "partial" if truncation_suspected else ("empty" if not rows else "full"),
        "empty_reason": "source_returned_no_rows" if not rows else None,
    }


def _as_of_metadata(as_of: Optional[str]) -> Dict[str, Any]:
    parsed = _parse_as_of(as_of)
    return {"as_of": parsed.moment.isoformat() if parsed else None, "as_of_precision": parsed.precision if parsed else None}


class TushareProvider:
    name = "tushare"

    def __init__(self, client: Any = None, token: Optional[str] = None, points_profile: int = DEFAULT_POINTS_PROFILE):
        self._token = token or os.environ.get("TUSHARE_TOKEN")
        self.points_profile = points_profile
        self._injected_client = client is not None
        if client is not None:
            self.client = client
            return
        if not self._token:
            raise DataProviderError("missing_credential", "TUSHARE_TOKEN is not configured", self.name)
        try:
            import tushare as ts  # type: ignore
        except ImportError as error:
            raise DataProviderError("missing_dependency", "Python package 'tushare' is not installed", self.name) from error
        self.client = ts.pro_api(self._token)

    def fetch(self, dataset: str, params: Optional[Mapping[str, Any]] = None, as_of: Optional[str] = None, require_pit: bool = False) -> DataResult:
        requested_dataset, dataset = dataset, _canonical_dataset(dataset)
        if dataset not in TUSHARE_ENDPOINTS:
            raise DataProviderError("unsupported_dataset", f"Tushare does not map dataset '{requested_dataset}'", self.name)
        spec = TUSHARE_ENDPOINTS[dataset]
        request = {key: value for key, value in dict(params or {}).items() if not any(mark in key.lower() for mark in SENSITIVE_MARKERS)}
        if dataset in {"ths_index", "ths_membership"}:
            _validate_request(request, r"\d{6}\.TI", "a six-digit Tonghuashun index code ending in .TI")
        elif dataset == "china_yield_curve":
            _validate_request(request, r"\d{3,6}\.CB", "a ChinaBond curve code ending in .CB")
        else:
            _validate_request(request)
        universe_mode = request.pop("universe_mode", "single_security")
        require_complete = bool(request.pop("require_complete", False))
        require_revision_history = bool(request.pop("require_revision_history", False))
        request.pop("require_pit", None)
        if require_pit and spec.pit_grade not in PIT_SAFE_GRADES:
            raise DataProviderError("pit_not_supported", f"Dataset '{dataset}' has PIT grade '{spec.pit_grade}'", self.name, spec.api_name)
        if require_revision_history and spec.pit_grade == "reported_with_availability":
            raise DataProviderError("bitemporal_history_unavailable", "Provider rows do not prove a complete historical revision ledger; use archived snapshots", self.name, spec.api_name)
        api_name, min_points = spec.api_name, spec.min_points
        if universe_mode == "cross_section" and spec.vip_api_name:
            api_name, min_points = spec.vip_api_name, spec.vip_min_points
        # Base and VIP interfaces can have different row limits. Do not reuse a
        # documented base-interface limit for VIP unless separately verified.
        contract_spec = replace(spec, api_name=api_name, max_rows=spec.max_rows if api_name == spec.api_name else None)
        if min_points is not None and self.points_profile < min_points:
            raise DataProviderError("profile_points_insufficient", f"Configured profile {self.points_profile} is below documented minimum {min_points}", self.name, api_name)
        try:
            method = getattr(self.client, api_name)
        except AttributeError as error:
            raise DataProviderError("sdk_interface_missing", f"Tushare client has no interface '{api_name}'", self.name, api_name) from error
        try:
            segment_row_counts: List[int] = []
            if dataset == "security_master" and (require_pit or request.get("list_status") == "ALL"):
                base = dict(request)
                base.pop("list_status", None)
                if require_pit:
                    requested_fields = {part.strip() for part in str(base.get("fields", "")).split(",") if part.strip()}
                    unsafe = requested_fields - SAFE_MASTER_FIELDS
                    if unsafe:
                        raise DataProviderError("field_not_pit_safe", f"security_master fields are not historically stable: {sorted(unsafe)}", self.name, api_name)
                    base["fields"] = ",".join(sorted(requested_fields or SAFE_MASTER_FIELDS))
                rows: List[Dict[str, Any]] = []
                for status in ("L", "D", "P", "G"):
                    segment = _records(method(list_status=status, **base))
                    segment_row_counts.append(len(segment))
                    rows.extend(segment)
            elif dataset == "industry_membership" and require_pit:
                base = dict(request)
                base.pop("is_new", None)
                rows = []
                for is_new in ("Y", "N"):
                    segment = _records(method(is_new=is_new, **base))
                    segment_row_counts.append(len(segment))
                    rows.extend(segment)
                rows = _dedupe(rows, spec.primary_key)
            else:
                rows = _records(method(**request))
                segment_row_counts.append(len(rows))
        except DataProviderError:
            raise
        except Exception as error:
            raise _provider_error(error, self.name, api_name, self._token) from error
        if spec.pit_grade == "membership_interval":
            filtered, stats = _filter_interval_as_of(rows, as_of, "in_date", "out_date", require_pit, spec.interval_end_inclusive)
        elif spec.pit_grade == "listing_interval":
            filtered, stats = _filter_interval_as_of(rows, as_of, "list_date", "delist_date", require_pit, True)
        else:
            filtered, stats = _filter_as_of(rows, as_of, spec.availability_fields, require_pit, spec.pit_grade)
        contract = _contract_metadata(contract_spec, filtered, require_complete, max(segment_row_counts, default=0))
        metadata = {
            "provider": self.name,
            "interface": api_name,
            "requested_dataset": requested_dataset,
            "docs": spec.docs,
            "points_profile": self.points_profile,
            "documented_min_points": min_points,
            "permission_verified_live": not self._injected_client,
            "interface_call_succeeded": True,
            "pit_grade": spec.pit_grade,
            "availability_fields": list(spec.availability_fields),
            "requested_at": _utc_now(),
            "request_params": _redact_value(request),
            "row_count_before_pit_filter": len(rows),
            "row_count": len(filtered),
            "request_segment_row_counts": segment_row_counts,
            "revision_history_complete": False if spec.pit_grade == "reported_with_availability" else None,
            "historical_claim_limit": "availability-filtered source rows; not a complete bitemporal revision ledger" if spec.pit_grade == "reported_with_availability" else None,
            "interval_end_semantics": "inclusive" if spec.interval_end_inclusive or spec.pit_grade == "listing_interval" else "exclusive",
            **_as_of_metadata(as_of),
            **stats,
            **contract,
        }
        return DataResult(dataset, filtered, metadata)


class AkshareProvider:
    name = "akshare"

    def __init__(self, client: Any = None):
        self._injected_client = client is not None
        if client is not None:
            self.client = client
            return
        try:
            import akshare as ak  # type: ignore
        except ImportError as error:
            raise DataProviderError("missing_dependency", "Python package 'akshare' is not installed", self.name) from error
        self.client = ak

    def fetch(self, dataset: str, params: Optional[Mapping[str, Any]] = None, as_of: Optional[str] = None, require_pit: bool = False) -> DataResult:
        requested_dataset, dataset = dataset, _canonical_dataset(dataset)
        if dataset not in AKSHARE_ENDPOINTS:
            raise DataProviderError("unsupported_dataset", f"AKShare does not map canonical dataset '{requested_dataset}'", self.name)
        spec = AKSHARE_ENDPOINTS[dataset]
        if require_pit and spec.pit_grade not in PIT_SAFE_GRADES:
            raise DataProviderError("pit_not_supported", f"AKShare '{dataset}' has PIT grade '{spec.pit_grade}'", self.name, spec.api_name)
        request = {key: value for key, value in dict(params or {}).items() if not any(mark in key.lower() for mark in SENSITIVE_MARKERS)}
        _validate_request(request)
        require_complete = bool(request.pop("require_complete", False))
        request.pop("universe_mode", None)
        request.pop("require_pit", None)
        normalized_code: Optional[str] = None
        if dataset in {"security_master", "spot_snapshot", "industry_list"}:
            call_params: Dict[str, Any] = {}
        elif dataset == "daily_bar":
            code = request.pop("ts_code", request.pop("symbol", ""))
            if not code:
                raise DataProviderError("invalid_request", "daily_bar requires ts_code or symbol", self.name, spec.api_name)
            normalized_code = _canonical_ts_code(code)
            call_params = {"symbol": _ak_symbol(code), "period": request.pop("period", "daily"), "start_date": request.pop("start_date", "19700101"), "end_date": request.pop("end_date", "20500101"), "adjust": request.pop("adjust", ""), "timeout": request.pop("timeout", 20), **request}
        elif dataset == "industry_membership":
            symbol = request.pop("symbol", request.pop("industry", ""))
            if not symbol:
                raise DataProviderError("invalid_request", "industry_membership requires symbol or industry", self.name, spec.api_name)
            call_params = {"symbol": symbol, **request}
        else:
            call_params = request
        try:
            method = getattr(self.client, spec.api_name)
            rows = _normalize_akshare(dataset, _records(method(**call_params)), normalized_code)
        except DataProviderError:
            raise
        except AttributeError as error:
            raise DataProviderError("sdk_interface_missing", f"AKShare client has no interface '{spec.api_name}'", self.name, spec.api_name) from error
        except Exception as error:
            raise _provider_error(error, self.name, spec.api_name) from error
        filtered, stats = _filter_as_of(rows, as_of, spec.availability_fields, require_pit, spec.pit_grade)
        contract = _contract_metadata(spec, filtered, require_complete)
        metadata = {
            "provider": self.name,
            "interface": spec.api_name,
            "requested_dataset": requested_dataset,
            "docs": spec.docs,
            "pit_grade": spec.pit_grade,
            "availability_fields": list(spec.availability_fields),
            "requested_at": _utc_now(),
            "interface_call_succeeded": True,
            "permission_verified_live": not self._injected_client,
            "request_params": _redact_value(call_params),
            "row_count_before_pit_filter": len(rows),
            "row_count": len(filtered),
            "fallback_warning": "AKShare wraps public websites; schema and availability can change without notice.",
            **_as_of_metadata(as_of),
            **stats,
            **contract,
        }
        return DataResult(dataset, filtered, metadata)


class MockProvider:
    """Explicit offline provider. AutoProvider never constructs or selects it."""

    name = "mock"

    def __init__(self, fixtures: Mapping[str, Sequence[Mapping[str, Any]]]):
        self.fixtures = {_canonical_dataset(key): [dict(row) for row in rows] for key, rows in fixtures.items()}

    def fetch(self, dataset: str, params: Optional[Mapping[str, Any]] = None, as_of: Optional[str] = None, require_pit: bool = False) -> DataResult:
        dataset = _canonical_dataset(dataset)
        if dataset not in self.fixtures:
            raise DataProviderError("fixture_missing", f"No mock fixture for '{dataset}'", self.name)
        spec = TUSHARE_ENDPOINTS.get(dataset)
        if not spec:
            raise DataProviderError("unsupported_dataset", f"No canonical contract for '{dataset}'", self.name)
        if require_pit and spec.pit_grade not in PIT_SAFE_GRADES:
            raise DataProviderError("pit_not_supported", f"Mock dataset grade '{spec.pit_grade}' is not PIT-safe", self.name)
        rows = list(self.fixtures[dataset])
        if spec.pit_grade == "membership_interval":
            filtered, stats = _filter_interval_as_of(rows, as_of, "in_date", "out_date", require_pit, spec.interval_end_inclusive)
        elif spec.pit_grade == "listing_interval":
            filtered, stats = _filter_interval_as_of(rows, as_of, "list_date", "delist_date", require_pit, True)
        else:
            filtered, stats = _filter_as_of(rows, as_of, spec.availability_fields, require_pit, spec.pit_grade)
        metadata = {
            "provider": self.name,
            "mock": True,
            "production_eligible": False,
            "pit_filter_executed": bool(require_pit),
            "request_params": _redact_value(dict(params or {})),
            "row_count_before_pit_filter": len(rows),
            "row_count": len(filtered),
            "requested_at": _utc_now(),
            **_as_of_metadata(as_of),
            **stats,
            **_contract_metadata(spec, filtered, False),
        }
        return DataResult(dataset, filtered, metadata)


class UnavailableProvider:
    def __init__(self, error: DataProviderError):
        self.error = error

    def fetch(self, dataset: str, **_: Any) -> DataResult:
        raise self.error


class AutoProvider:
    """Tushare-first router with a narrow, provenance-preserving fallback."""

    name = "auto"

    def __init__(self, tushare_provider: Any, akshare_provider: Any, allow_akshare_fallback: bool = True):
        self.tushare, self.akshare = tushare_provider, akshare_provider
        self.allow_akshare_fallback = allow_akshare_fallback

    def fetch(self, dataset: str, params: Optional[Mapping[str, Any]] = None, as_of: Optional[str] = None, require_pit: bool = False) -> DataResult:
        canonical = _canonical_dataset(dataset)
        try:
            return self.tushare.fetch(canonical, params=params, as_of=as_of, require_pit=require_pit)
        except DataProviderError as primary:
            if not self.allow_akshare_fallback or primary.code not in AUTO_FALLBACK_CODES:
                raise
            if canonical not in AKSHARE_ENDPOINTS:
                raise DataProviderError("fallback_unavailable", f"Tushare failed ({primary.code}); AKShare has no schema-compatible fallback for '{canonical}'", self.name) from primary
            spec = AKSHARE_ENDPOINTS[canonical]
            if require_pit and spec.pit_grade not in PIT_SAFE_GRADES:
                raise DataProviderError("fallback_rejected_for_pit", f"Tushare failed ({primary.code}); AKShare grade '{spec.pit_grade}' is unsafe for strict PIT", self.name, spec.api_name) from primary
            try:
                fallback = self.akshare.fetch(canonical, params=params, as_of=as_of, require_pit=require_pit)
            except DataProviderError as secondary:
                raise DataProviderError("all_providers_failed", json.dumps({"tushare": primary.to_dict(), "akshare": secondary.to_dict()}, ensure_ascii=False), self.name) from secondary
            fallback.metadata["fallback_from"] = primary.to_dict()
            fallback.metadata["route"] = ["tushare", "akshare"]
            return fallback


def capability_manifest(points_profile: int = DEFAULT_POINTS_PROFILE) -> Dict[str, Any]:
    def encode(specs: Mapping[str, EndpointSpec], provider: str) -> List[Dict[str, Any]]:
        return [{"provider": provider, "dataset": dataset, "interface": spec.api_name, "min_points": spec.min_points, "vip_interface": spec.vip_api_name, "vip_min_points": spec.vip_min_points, "profile_eligible": spec.min_points is None or points_profile >= spec.min_points, "permission_verified_live": False, "permission_note": spec.permission_note, "pit_grade": spec.pit_grade, "required_fields": list(spec.required_fields), "units": dict(spec.units), "documented_row_limit": spec.max_rows, "docs": spec.docs} for dataset, spec in specs.items()]

    return {"snapshot_date": SNAPSHOT_DATE, "points_profile": points_profile, "warning": "Documented thresholds are planning metadata, not a live permission guarantee.", "aliases": DATASET_ALIASES, "capabilities": encode(TUSHARE_ENDPOINTS, "tushare") + encode(AKSHARE_ENDPOINTS, "akshare")}


def _load_json_object(value: str) -> Dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("value must decode to a JSON object")
    return parsed


def _write_result(payload: Dict[str, Any], output: Optional[str]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    caps = commands.add_parser("capabilities")
    caps.add_argument("--points-profile", type=int, default=DEFAULT_POINTS_PROFILE)
    caps.add_argument("--output")
    fetch = commands.add_parser("fetch")
    fetch.add_argument("--dataset", required=True)
    fetch.add_argument("--provider", choices=("auto", "tushare", "akshare", "mock"), default="auto")
    fetch.add_argument("--params", type=_load_json_object, default={})
    fetch.add_argument("--as-of")
    fetch.add_argument("--require-pit", action="store_true")
    fetch.add_argument("--points-profile", type=int, default=DEFAULT_POINTS_PROFILE)
    fetch.add_argument("--mock-file")
    fetch.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.command == "capabilities":
            _write_result(capability_manifest(args.points_profile), args.output)
            return 0
        if args.provider == "tushare":
            provider: Any = TushareProvider(points_profile=args.points_profile)
        elif args.provider == "akshare":
            provider = AkshareProvider()
        elif args.provider == "mock":
            if not args.mock_file:
                raise DataProviderError("invalid_request", "--mock-file is required for provider=mock", "mock")
            provider = MockProvider(json.loads(Path(args.mock_file).read_text(encoding="utf-8")))
        else:
            try:
                tushare_provider: Any = TushareProvider(points_profile=args.points_profile)
            except DataProviderError as error:
                tushare_provider = UnavailableProvider(error)
            try:
                akshare_provider: Any = AkshareProvider()
            except DataProviderError as error:
                akshare_provider = UnavailableProvider(error)
            provider = AutoProvider(tushare_provider, akshare_provider)
        result = provider.fetch(args.dataset, params=args.params, as_of=args.as_of, require_pit=args.require_pit)
        _write_result(result.to_dict(), args.output)
        return 0
    except DataProviderError as error:
        _write_result({"ok": False, "error": error.to_dict()}, getattr(args, "output", None))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
