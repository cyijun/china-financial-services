#!/usr/bin/env python3
"""Auditable China-market data router for Tushare Pro and AKShare.

SDKs are imported lazily, credentials stay process-local, and production never
falls back to mock data. The router is deliberately conservative: a date-only
financial announcement becomes usable on the following Shanghai calendar day,
and a daily bar becomes usable at 16:00 Asia/Shanghai.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo


SNAPSHOT_DATE = "2026-08-25"
DEFAULT_POINTS_PROFILE = 6000
SHANGHAI = ZoneInfo("Asia/Shanghai")
SENSITIVE_MARKERS = ("token", "secret", "password", "api_key", "apikey", "credential")
CHINA_GOVT_CURVE_CODE = "1001.CB"
CHINA_GOVT_CURVE_NAME = "中债国债收益率曲线"
AKSHARE_STANDARD_CURVE_TERMS = {
    "3月": 0.25,
    "6月": 0.5,
    "1年": 1.0,
    "3年": 3.0,
    "5年": 5.0,
    "7年": 7.0,
    "10年": 10.0,
    "30年": 30.0,
}
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
    version_key: Tuple[str, ...] = ()
    date_fields: Tuple[str, ...] = ()
    numeric_fields: Tuple[str, ...] = ()
    nonnegative_fields: Tuple[str, ...] = ()
    units: Tuple[Tuple[str, str], ...] = ()
    interval_end_inclusive: bool = False
    permission_note: Optional[str] = None
    vip_max_rows: Optional[int] = None


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
    "daily_bar": EndpointSpec("daily", None, "trade_date", DOC + "27", ("trade_date",), max_rows=6000, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date"), date_fields=("trade_date",), numeric_fields=("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"), nonnegative_fields=("open", "high", "low", "close", "pre_close", "vol", "amount"), units=(("vol", "lots"), ("amount", "thousand_CNY"))),
    "adjustment_factor": EndpointSpec("adj_factor", 2000, "trade_date", DOC + "28", ("trade_date",), max_rows=6000, required_fields=("ts_code", "trade_date", "adj_factor"), primary_key=("ts_code", "trade_date"), date_fields=("trade_date",), numeric_fields=("adj_factor",), nonnegative_fields=("adj_factor",)),
    "daily_basic": EndpointSpec("daily_basic", 2000, "trade_date", DOC + "32", ("trade_date",), max_rows=6000, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date"), date_fields=("trade_date",), numeric_fields=("close", "turnover_rate", "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm", "total_share", "float_share", "free_share", "total_mv", "circ_mv"), nonnegative_fields=("close", "turnover_rate", "turnover_rate_f", "volume_ratio", "total_share", "float_share", "free_share", "total_mv", "circ_mv"), units=(("total_mv", "ten_thousand_CNY"), ("circ_mv", "ten_thousand_CNY"))),
    "income": EndpointSpec("income", 2000, "reported_with_availability", DOC + "33", ("ann_date", "f_ann_date"), "income_vip", 5000, required_fields=("ts_code", "end_date"), primary_key=("ts_code", "end_date", "report_type", "comp_type", "ann_date", "f_ann_date", "update_flag"), version_key=("ts_code", "end_date", "report_type", "comp_type"), date_fields=("ann_date", "f_ann_date", "end_date")),
    "balance_sheet": EndpointSpec("balancesheet", 2000, "reported_with_availability", DOC + "36", ("ann_date", "f_ann_date"), "balancesheet_vip", 5000, required_fields=("ts_code", "end_date"), primary_key=("ts_code", "end_date", "report_type", "comp_type", "ann_date", "f_ann_date", "update_flag"), version_key=("ts_code", "end_date", "report_type", "comp_type"), date_fields=("ann_date", "f_ann_date", "end_date")),
    "cash_flow": EndpointSpec("cashflow", 2000, "reported_with_availability", DOC + "44", ("ann_date", "f_ann_date"), "cashflow_vip", 5000, required_fields=("ts_code", "end_date"), primary_key=("ts_code", "end_date", "report_type", "comp_type", "ann_date", "f_ann_date", "update_flag"), version_key=("ts_code", "end_date", "report_type", "comp_type"), date_fields=("ann_date", "f_ann_date", "end_date")),
    "forecast": EndpointSpec("forecast", 2000, "reported_with_availability", DOC + "45", ("ann_date",), "forecast_vip", 5000, 3500, ("ts_code", "end_date")),
    "express": EndpointSpec("express", 2000, "reported_with_availability", DOC + "46", ("ann_date",), "express_vip", 5000, required_fields=("ts_code", "end_date")),
    "financial_indicator": EndpointSpec("fina_indicator", 2000, "reported_with_availability", DOC + "79", ("ann_date",), "fina_indicator_vip", 5000, 100, ("ts_code", "end_date")),
    "disclosure_schedule": EndpointSpec("disclosure_date", 2000, "schedule_not_actual_release", DOC + "162", max_rows=3000),
    "money_flow": EndpointSpec("moneyflow", 2000, "trade_date", DOC + "170", ("trade_date",), max_rows=6000, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date")),
    "suspend_status": EndpointSpec("suspend_d", None, "trade_date", DOC + "214", ("trade_date",), required_fields=("ts_code", "trade_date", "suspend_type"), primary_key=("ts_code", "trade_date", "suspend_type")),
    "price_limit": EndpointSpec("stk_limit", 2000, "market_rule_date", DOC + "183", ("trade_date",), max_rows=5800, required_fields=("ts_code", "trade_date", "up_limit", "down_limit"), primary_key=("ts_code", "trade_date"), units=(("pre_close", "CNY_per_share"), ("up_limit", "CNY_per_share"), ("down_limit", "CNY_per_share"))),
    "fund_master": EndpointSpec("fund_basic", 2000, "listing_interval", DOC + "19", ("list_date", "delist_date"), max_rows=15000, required_fields=("ts_code",), primary_key=("ts_code",), date_fields=("found_date", "list_date", "delist_date", "due_date")),
    "fund_daily_bar": EndpointSpec("fund_daily", 5000, "trade_date", DOC + "127", ("trade_date",), max_rows=5000, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date"), date_fields=("trade_date",), numeric_fields=("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"), nonnegative_fields=("open", "high", "low", "close", "pre_close", "vol", "amount"), units=(("vol", "lots"), ("amount", "thousand_CNY"))),
    "fund_nav": EndpointSpec("fund_nav", 2000, "reported_with_availability", DOC + "119", ("ann_date",), required_fields=("ts_code", "nav_date"), primary_key=("ts_code", "nav_date", "ann_date"), version_key=("ts_code", "nav_date"), date_fields=("ann_date", "nav_date"), numeric_fields=("unit_nav", "accum_nav", "accum_div", "net_asset", "total_netasset", "adj_nav"), nonnegative_fields=("unit_nav", "accum_nav", "accum_div", "net_asset", "total_netasset", "adj_nav")),
    "fund_share": EndpointSpec("fund_share", 2000, "observation_date_without_release_time", DOC + "207", ("trade_date",), max_rows=2000, required_fields=("ts_code", "trade_date", "fd_share"), primary_key=("ts_code", "trade_date"), date_fields=("trade_date",), numeric_fields=("fd_share",), nonnegative_fields=("fd_share",), units=(("fd_share", "ten_thousand_shares"),), permission_note="trade_date is the change/observation date; the official interface does not document an intraday release timestamp"),
    "etf_master": EndpointSpec("etf_basic", 8000, "current_snapshot", DOC + "385", max_rows=5000, required_fields=("ts_code",), primary_key=("ts_code",), date_fields=("setup_date", "list_date"), numeric_fields=("mgt_fee",), nonnegative_fields=("mgt_fee",), permission_note="8000_points_required; unavailable under the default 6000-point profile"),
    "etf_index_master": EndpointSpec("etf_index", 8000, "current_snapshot", DOC + "386", max_rows=5000, required_fields=("ts_code",), primary_key=("ts_code",), date_fields=("pub_date", "base_date"), numeric_fields=("bp",), nonnegative_fields=("bp",), permission_note="8000_points_required; unavailable under the default 6000-point profile"),
    "index_weight": EndpointSpec("index_weight", 2000, "trade_date", DOC + "96", ("trade_date",), required_fields=("index_code", "con_code", "trade_date", "weight"), primary_key=("index_code", "con_code", "trade_date"), date_fields=("trade_date",), numeric_fields=("weight",), nonnegative_fields=("weight",), units=(("weight", "percent"),)),
    "industry_classification": EndpointSpec("index_classify", 2000, "classification_version", DOC + "181", max_rows=10000),
    "industry_membership": EndpointSpec("index_member_all", 2000, "membership_interval", DOC + "335", ("in_date", "out_date"), max_rows=2000, required_fields=("ts_code", "in_date"), primary_key=("l1_code", "l2_code", "l3_code", "ts_code", "in_date")),
    "st_status": EndpointSpec("stock_st", 3000, "trade_date", DOC + "397", ("trade_date",), max_rows=1000, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date", "type")),
    "ths_index": EndpointSpec("ths_index", 6000, "current_snapshot", DOC + "259", max_rows=5000, required_fields=("ts_code", "name", "exchange", "type"), primary_key=("ts_code",)),
    "ths_membership": EndpointSpec("ths_member", 6000, "current_snapshot", DOC + "261", max_rows=5000, required_fields=("ts_code", "con_code", "con_name"), primary_key=("ts_code", "con_code")),
    "shibor": EndpointSpec("shibor", None, "calendar_date", DOC + "149", ("date",), max_rows=2000),
    "lpr": EndpointSpec("shibor_lpr", None, "calendar_date", DOC + "151", ("date",), max_rows=2000),
    "china_yield_curve": EndpointSpec("yc_cb", None, "calendar_date", DOC + "201", ("trade_date", "date"), max_rows=2000, required_fields=("trade_date", "ts_code", "curve_type", "curve_term", "yield"), primary_key=("trade_date", "ts_code", "curve_type", "curve_term"), numeric_fields=("curve_term", "yield"), units=(("curve_term", "years"), ("yield", "percent")), permission_note="separate_grant_required"),
}

AKSHARE_ENDPOINTS: Dict[str, EndpointSpec] = {
    "security_master": EndpointSpec("stock_info_a_code_name", None, "current_snapshot", "https://akshare.akfamily.xyz/data/stock/stock.html", max_rows=10000, required_fields=("ts_code",), primary_key=("ts_code",)),
    "daily_bar": EndpointSpec("stock_zh_a_hist", None, "trade_date", "https://akshare.akfamily.xyz/data/stock/stock.html", ("trade_date",), max_rows=None, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date"), date_fields=("trade_date",), numeric_fields=("open", "high", "low", "close", "vol", "amount"), nonnegative_fields=("open", "high", "low", "close", "vol", "amount"), units=(("vol", "lots"), ("amount", "thousand_CNY"))),
    "fund_daily_bar": EndpointSpec("fund_etf_hist_em", None, "trade_date", "https://akshare.akfamily.xyz/data/fund/fund_public.html", ("trade_date",), max_rows=None, required_fields=("ts_code", "trade_date"), primary_key=("ts_code", "trade_date"), date_fields=("trade_date",), numeric_fields=("open", "high", "low", "close", "vol", "amount"), nonnegative_fields=("open", "high", "low", "close", "vol", "amount"), units=(("vol", "provider_reported_unspecified"), ("amount", "thousand_CNY")), permission_note="dynamic qfq/hfq responses are not strict-PIT safe; raw history remains scrape-derived; volume unit is not asserted by the cited AKShare interface documentation"),
    "spot_snapshot": EndpointSpec("stock_zh_a_spot_em", None, "current_snapshot", "https://akshare.akfamily.xyz/data/stock/stock.html", max_rows=10000),
    "industry_list": EndpointSpec("stock_board_industry_name_em", None, "current_snapshot", "https://akshare.akfamily.xyz/data/stock/stock.html", max_rows=1000),
    "industry_membership": EndpointSpec("stock_board_industry_cons_em", None, "current_snapshot", "https://akshare.akfamily.xyz/data/stock/stock.html", max_rows=1000),
    "china_yield_curve": EndpointSpec("bond_china_yield", None, "calendar_date", "https://akshare.akfamily.xyz/data/bond/bond.html", ("trade_date",), required_fields=("trade_date", "ts_code", "curve_type", "curve_term", "yield"), primary_key=("trade_date", "ts_code", "curve_type", "curve_term"), date_fields=("trade_date",), numeric_fields=("curve_term", "yield"), units=(("curve_term", "years"), ("yield", "percent")), permission_note="bond_china_yield covers standard maturity tenors; bond_china_close_return covers recent dense maturity/spot curves"),
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
    "fund_basic": "fund_master",
    "fund_daily": "fund_daily_bar",
    "fund_etf_hist_em": "fund_daily_bar",
    "etf_basic": "etf_master",
    "etf_index": "etf_index_master",
    "index_weight": "index_weight",
    "index_classify": "industry_classification",
    "index_member_all": "industry_membership",
    "stock_st": "st_status",
    "ths_member": "ths_membership",
    "shibor_lpr": "lpr",
    "yc_cb": "china_yield_curve",
}
PIT_SAFE_GRADES = {"calendar_date", "trade_date", "market_rule_date", "reported_with_availability", "membership_interval", "listing_interval"}
SAFE_MASTER_FIELDS = {"ts_code", "symbol", "market", "exchange", "curr_type", "list_date", "delist_date"}
SAFE_FUND_MASTER_FIELDS = {"ts_code", "market", "found_date", "due_date", "list_date", "delist_date", "issue_date", "status"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_dataset(dataset: str) -> str:
    return DATASET_ALIASES.get(dataset, dataset)


def _augment_contract_fields(request: Dict[str, Any], spec: EndpointSpec) -> None:
    """Keep row identity and availability fields when callers project columns.

    Tushare accepts a comma-separated ``fields`` projection. Omitting report
    type, company type, version or availability fields makes duplicate and PIT
    checks ambiguous, so the router adds only the contract fields needed to
    interpret the returned rows. The original request remains separately
    recorded in metadata.
    """

    raw = request.get("fields")
    if not isinstance(raw, str) or not raw.strip():
        return
    fields = [part.strip() for part in raw.split(",") if part.strip()]
    seen = set(fields)
    for field in (*spec.required_fields, *spec.primary_key, *spec.version_key, *spec.availability_fields):
        if field and field not in seen:
            fields.append(field)
            seen.add(field)
    request["fields"] = ",".join(fields)


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
    for key in ("start_date", "end_date", "trade_date", "nav_date", "period", "ann_date"):
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


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _normalize_akshare_yield_curve(rows: Iterable[Dict[str, Any]], curve_type: str) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    yield_column = "到期收益率" if curve_type == "0" else "即期收益率"
    for raw in rows:
        trade_date = _date_key(raw.get("日期"))
        if raw.get("曲线名称") is not None:
            if str(raw.get("曲线名称")).strip() != CHINA_GOVT_CURVE_NAME or curve_type != "0":
                continue
            for source_column, term in AKSHARE_STANDARD_CURVE_TERMS.items():
                value = _number(raw.get(source_column))
                if trade_date and value is not None:
                    output.append(
                        {
                            "trade_date": trade_date,
                            "ts_code": CHINA_GOVT_CURVE_CODE,
                            "curve_name": CHINA_GOVT_CURVE_NAME,
                            "curve_type": "0",
                            "yield_type": "maturity",
                            "curve_term": term,
                            "yield": value,
                        }
                    )
            continue
        term, value = _number(raw.get("期限")), _number(raw.get(yield_column))
        if trade_date and term is not None and value is not None:
            output.append(
                {
                    "trade_date": trade_date,
                    "ts_code": CHINA_GOVT_CURVE_CODE,
                    "curve_name": CHINA_GOVT_CURVE_NAME,
                    "curve_type": curve_type,
                    "yield_type": "maturity" if curve_type == "0" else "spot",
                    "curve_term": term,
                    "yield": value,
                }
            )
    return output


def _normalize_akshare(dataset: str, rows: Iterable[Dict[str, Any]], ts_code: Optional[str] = None, curve_type: Optional[str] = None) -> List[Dict[str, Any]]:
    if dataset == "china_yield_curve":
        if curve_type not in {"0", "1"}:
            raise DataProviderError("invalid_request", "china_yield_curve requires curve_type 0 (maturity) or 1 (spot)", "akshare")
        return _normalize_akshare_yield_curve(rows, curve_type)
    mappings = {
        "daily_bar": {"日期": "trade_date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "vol", "成交额": "amount", "振幅": "amplitude", "涨跌幅": "pct_chg", "涨跌额": "change", "换手率": "turnover_rate"},
        "fund_daily_bar": {"日期": "trade_date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "vol", "成交额": "amount", "振幅": "amplitude", "涨跌幅": "pct_chg", "涨跌额": "change", "换手率": "turnover_rate"},
        "security_master": {"code": "symbol", "name": "name", "代码": "symbol", "名称": "name"},
    }
    rename = mappings.get(dataset, {})
    output: List[Dict[str, Any]] = []
    for raw in rows:
        row = {rename.get(key, key): value for key, value in raw.items()}
        if dataset == "security_master" and row.get("symbol"):
            row["ts_code"] = _canonical_ts_code(row["symbol"])
        if dataset in {"daily_bar", "fund_daily_bar"}:
            row["ts_code"] = _canonical_ts_code(ts_code)
            row["trade_date"] = _date_key(row.get("trade_date"))
            amount = _number(row.get("amount"))
            if amount is not None:
                row["amount"] = amount / 1000.0
        output.append(row)
    return output


def _number(value: Any) -> Optional[float]:
    """Return a finite numeric value while rejecting booleans and sentinels."""

    if value is None or isinstance(value, bool) or str(value).strip().lower() in {"", "nan", "none", "nat", "null", "--"}:
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _contract_metadata(
    spec: EndpointSpec,
    rows: Sequence[Dict[str, Any]],
    require_complete: bool,
    observed_limit_count: Optional[int] = None,
    require_quality: bool = False,
    pagination_complete: bool = False,
) -> Dict[str, Any]:
    missing_required = sorted({field for row in rows for field in spec.required_fields if field not in row})
    null_required = {
        field: sum(1 for row in rows if field in row and (row.get(field) is None or str(row.get(field)).strip() == ""))
        for field in spec.required_fields
    }
    null_required = {field: count for field, count in null_required.items() if count}
    duplicate_count = len(rows) - len(_dedupe(rows, spec.primary_key)) if spec.primary_key else 0
    version_counts: Dict[Tuple[Any, ...], int] = {}
    if spec.version_key:
        for row in rows:
            marker = tuple(row.get(key) for key in spec.version_key)
            version_counts[marker] = version_counts.get(marker, 0) + 1
    multi_version_groups = sum(1 for count in version_counts.values() if count > 1)
    invalid_dates = {
        field: sum(1 for row in rows if row.get(field) not in (None, "") and _valid_date(row.get(field)) is None)
        for field in spec.date_fields
    }
    invalid_dates = {field: count for field, count in invalid_dates.items() if count}
    non_numeric = {
        field: sum(1 for row in rows if row.get(field) not in (None, "") and _number(row.get(field)) is None)
        for field in spec.numeric_fields
    }
    non_numeric = {field: count for field, count in non_numeric.items() if count}
    negative = {
        field: sum(1 for row in rows if (number := _number(row.get(field))) is not None and number < 0)
        for field in spec.nonnegative_fields
    }
    negative = {field: count for field, count in negative.items() if count}
    limit_count = len(rows) if observed_limit_count is None else observed_limit_count
    truncation_suspected = bool(spec.max_rows and limit_count == spec.max_rows and not pagination_complete)
    documentation_limit_drift = bool(spec.max_rows and limit_count > spec.max_rows)
    if missing_required:
        raise DataProviderError("schema_mismatch", f"missing canonical fields: {missing_required}", "router", spec.api_name)
    if require_complete and truncation_suspected:
        raise DataProviderError("truncation_suspected", f"row count reached interface limit {spec.max_rows}; segment the request", "router", spec.api_name)
    quality_issues = {
        "null_required_values": null_required,
        "invalid_date_values": invalid_dates,
        "non_numeric_values": non_numeric,
        "negative_value_counts": negative,
        "duplicate_key_rows": duplicate_count,
    }
    if require_quality and any(bool(value) for value in quality_issues.values()):
        raise DataProviderError("data_quality_failed", json.dumps(quality_issues, ensure_ascii=False, sort_keys=True), "router", spec.api_name)
    return {
        "required_fields": list(spec.required_fields),
        "primary_key": list(spec.primary_key),
        "units": dict(spec.units),
        "duplicate_key_rows": duplicate_count,
        "version_key": list(spec.version_key),
        "multi_version_groups": multi_version_groups,
        "null_required_values": null_required,
        "invalid_date_values": invalid_dates,
        "non_numeric_values": non_numeric,
        "negative_value_counts": negative,
        "documented_row_limit": spec.max_rows,
        "truncation_suspected": truncation_suspected,
        "documentation_limit_drift": documentation_limit_drift,
        "pagination_complete": pagination_complete,
        "status": "partial" if truncation_suspected else ("empty" if not rows else ("quality_warning" if any(bool(value) for value in quality_issues.values()) else "full")),
        "empty_reason": "source_returned_no_rows" if not rows else None,
        "response_sha256": _stable_digest(rows),
    }


def adjust_price_records(
    daily_rows: Sequence[Mapping[str, Any]],
    factor_rows: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    as_of: str,
) -> DataResult:
    """Build qfq/hfq prices only from raw bars and factors available by ``as_of``.

    qfq is rebased to the latest factor available at the cutoff; hfq is rebased
    to the earliest factor in the supplied, cutoff-filtered history. The function
    never consults a future factor and fails closed on missing joins.
    """

    if mode not in {"qfq", "hfq"}:
        raise DataProviderError("invalid_request", "mode must be qfq or hfq", "router", "adjust_price_records")
    cutoff = _parse_as_of(as_of)
    if cutoff is None:
        raise DataProviderError("invalid_request", "as_of is required", "router", "adjust_price_records")
    cutoff_key = cutoff.date_key
    usable_factors: Dict[Tuple[str, str], float] = {}
    factors_by_code: Dict[str, List[Tuple[str, float]]] = {}
    future_factor_rows = 0
    for raw in factor_rows:
        code, trade_date = _canonical_ts_code(raw.get("ts_code")), _date_key(raw.get("trade_date"))
        factor = _number(raw.get("adj_factor"))
        if not trade_date or factor is None or factor <= 0:
            raise DataProviderError("data_quality_failed", "adjustment factors require valid trade_date and positive adj_factor", "router", "adjust_price_records")
        if trade_date > cutoff_key:
            future_factor_rows += 1
            continue
        usable_factors[(code, trade_date)] = factor
        factors_by_code.setdefault(code, []).append((trade_date, factor))
    anchors: Dict[str, float] = {}
    for code, values in factors_by_code.items():
        values.sort()
        anchors[code] = values[-1][1] if mode == "qfq" else values[0][1]
    adjusted: List[Dict[str, Any]] = []
    price_fields = ("open", "high", "low", "close", "pre_close")
    for raw in daily_rows:
        code, trade_date = _canonical_ts_code(raw.get("ts_code")), _date_key(raw.get("trade_date"))
        if not trade_date:
            raise DataProviderError("data_quality_failed", "daily rows require a valid trade_date", "router", "adjust_price_records")
        if trade_date > cutoff_key:
            continue
        factor, anchor = usable_factors.get((code, trade_date)), anchors.get(code)
        if factor is None or anchor is None:
            raise DataProviderError("missing_adjustment_factor", f"no cutoff-safe factor for {code} {trade_date}", "router", "adjust_price_records")
        row = dict(raw)
        for field in price_fields:
            if field in row and row[field] not in (None, ""):
                value = _number(row[field])
                if value is None:
                    raise DataProviderError("data_quality_failed", f"{field} is not numeric", "router", "adjust_price_records")
                row[field] = value * factor / anchor
        row["adjustment_mode"] = mode
        row["adjustment_factor_used"] = factor
        row["adjustment_anchor"] = anchor
        adjusted.append(row)
    adjusted.sort(key=lambda row: (str(row.get("ts_code")), str(row.get("trade_date"))))
    metadata = {
        "provider": "derived",
        "interface": "raw_daily_plus_adj_factor",
        "pit_grade": "trade_date",
        "as_of": cutoff.moment.isoformat(),
        "as_of_precision": cutoff.precision,
        "adjustment_mode": mode,
        "future_factor_rows_dropped": future_factor_rows,
        "row_count": len(adjusted),
        "response_sha256": _stable_digest(adjusted),
        "warning": "PIT-safe only for the supplied raw bars and factor history; no corporate-action event reconstruction is implied.",
    }
    return DataResult("adjusted_daily_bar", adjusted, metadata)


def _as_of_metadata(as_of: Optional[str]) -> Dict[str, Any]:
    parsed = _parse_as_of(as_of)
    return {"as_of": parsed.moment.isoformat() if parsed else None, "as_of_precision": parsed.precision if parsed else None}


def _call_paginated(
    method: Any,
    request: Mapping[str, Any],
    spec: EndpointSpec,
    *,
    paginate: bool,
    page_size: Optional[int],
    max_pages: int,
) -> Tuple[List[Dict[str, Any]], List[int], bool]:
    if not paginate:
        rows = _records(method(**dict(request)))
        return rows, [len(rows)], False
    if max_pages < 1:
        raise DataProviderError("invalid_request", "max_pages must be >= 1", "router", spec.api_name)
    size = int(page_size or spec.max_rows or 5000)
    if size < 1:
        raise DataProviderError("invalid_request", "page_size must be >= 1", "router", spec.api_name)
    base = dict(request)
    base.pop("limit", None)
    base.pop("offset", None)
    rows: List[Dict[str, Any]] = []
    counts: List[int] = []
    seen_pages: set[str] = set()
    offset = 0
    for _ in range(max_pages):
        try:
            page = _records(method(**base, limit=size, offset=offset))
        except TypeError as error:
            raise DataProviderError("pagination_unsupported", "endpoint or SDK rejected limit/offset pagination", "router", spec.api_name) from error
        digest = _stable_digest(page)
        if page and digest in seen_pages:
            raise DataProviderError("pagination_stalled", "provider repeated a page; completeness cannot be established", "router", spec.api_name)
        seen_pages.add(digest)
        counts.append(len(page))
        rows.extend(page)
        if len(page) < size:
            return rows, counts, True
        offset += len(page)
    raise DataProviderError("pagination_incomplete", f"max_pages={max_pages} reached before a short page", "router", spec.api_name)


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
        original_request = dict(request)
        if dataset in {"ths_index", "ths_membership"}:
            _validate_request(request, r"\d{6}\.TI", "a six-digit Tonghuashun index code ending in .TI")
        elif dataset == "etf_index_master":
            _validate_request(request, r"\d{6}\.[A-Z]{2,4}", "a six-digit index code with an exchange or provider suffix")
        elif dataset == "china_yield_curve":
            _validate_request(request, r"\d{3,6}\.CB", "a ChinaBond curve code ending in .CB")
        else:
            _validate_request(request)
        universe_mode = request.pop("universe_mode", "single_security")
        require_complete = bool(request.pop("require_complete", False))
        require_quality = bool(request.pop("require_quality", False))
        require_revision_history = bool(request.pop("require_revision_history", False))
        paginate = bool(request.pop("paginate", False))
        page_size_value = request.pop("page_size", None)
        page_size = int(page_size_value) if page_size_value is not None else None
        max_pages = int(request.pop("max_pages", 100))
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
        contract_spec = replace(spec, api_name=api_name, max_rows=spec.max_rows if api_name == spec.api_name else spec.vip_max_rows)
        if min_points is not None and self.points_profile < min_points:
            raise DataProviderError("profile_points_insufficient", f"Configured profile {self.points_profile} is below documented minimum {min_points}", self.name, api_name)
        _augment_contract_fields(request, contract_spec)
        try:
            method = getattr(self.client, api_name)
        except AttributeError as error:
            raise DataProviderError("sdk_interface_missing", f"Tushare client has no interface '{api_name}'", self.name, api_name) from error
        try:
            segment_row_counts: List[int] = []
            pagination_complete = False
            if dataset == "security_master" and (require_pit or request.get("list_status") == "ALL"):
                if paginate:
                    raise DataProviderError("invalid_request", "security_master lifecycle segmentation cannot be combined with paginate", self.name, api_name)
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
            elif dataset == "fund_master" and (require_pit or request.get("status") == "ALL"):
                if paginate:
                    raise DataProviderError("invalid_request", "fund_master lifecycle segmentation cannot be combined with paginate", self.name, api_name)
                base = dict(request)
                base.pop("status", None)
                if require_pit:
                    requested_fields = {part.strip() for part in str(base.get("fields", "")).split(",") if part.strip()}
                    unsafe = requested_fields - SAFE_FUND_MASTER_FIELDS
                    if unsafe:
                        raise DataProviderError("field_not_pit_safe", f"fund_master fields are not historically stable: {sorted(unsafe)}", self.name, api_name)
                    base["fields"] = ",".join(sorted(requested_fields or SAFE_FUND_MASTER_FIELDS))
                rows = []
                for status in ("L", "D", "I"):
                    segment = _records(method(status=status, **base))
                    segment_row_counts.append(len(segment))
                    rows.extend(segment)
            elif dataset == "industry_membership" and require_pit:
                if paginate:
                    raise DataProviderError("invalid_request", "industry membership lifecycle segmentation cannot be combined with paginate", self.name, api_name)
                base = dict(request)
                base.pop("is_new", None)
                rows = []
                for is_new in ("Y", "N"):
                    segment = _records(method(is_new=is_new, **base))
                    segment_row_counts.append(len(segment))
                    rows.extend(segment)
                rows = _dedupe(rows, spec.primary_key)
            else:
                rows, segment_row_counts, pagination_complete = _call_paginated(
                    method,
                    request,
                    contract_spec,
                    paginate=paginate,
                    page_size=page_size,
                    max_pages=max_pages,
                )
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
        contract = _contract_metadata(
            contract_spec,
            filtered,
            require_complete,
            max(segment_row_counts, default=0),
            require_quality,
            pagination_complete,
        )
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
            "request_params": _redact_value(original_request),
            "provider_call_params": _redact_value(request),
            "control_flags": {
                "universe_mode": universe_mode,
                "require_complete": require_complete,
                "require_quality": require_quality,
                "require_revision_history": require_revision_history,
                "paginate": paginate,
                "page_size": page_size,
                "max_pages": max_pages,
            },
            "row_count_before_pit_filter": len(rows),
            "row_count": len(filtered),
            "request_segment_row_counts": segment_row_counts,
            "page_count": len(segment_row_counts) if paginate else 1,
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
        effective_spec = spec
        if require_pit and spec.pit_grade not in PIT_SAFE_GRADES:
            raise DataProviderError("pit_not_supported", f"AKShare '{dataset}' has PIT grade '{spec.pit_grade}'", self.name, spec.api_name)
        request = {key: value for key, value in dict(params or {}).items() if not any(mark in key.lower() for mark in SENSITIVE_MARKERS)}
        original_request = dict(request)
        if dataset == "china_yield_curve":
            _validate_request(request, r"1001\.CB", "the China government curve code 1001.CB")
        else:
            _validate_request(request)
        require_complete = bool(request.pop("require_complete", False))
        require_quality = bool(request.pop("require_quality", False))
        request.pop("universe_mode", None)
        request.pop("require_revision_history", None)
        request.pop("paginate", None)
        request.pop("page_size", None)
        request.pop("max_pages", None)
        request.pop("require_pit", None)
        normalized_code: Optional[str] = None
        curve_type: Optional[str] = None
        curve_term: Optional[float] = None
        call_segments: Optional[List[Dict[str, Any]]] = None
        provider_segment_row_counts: List[int] = []
        adjustment_mode: Optional[str] = None
        if dataset in {"security_master", "spot_snapshot", "industry_list"}:
            call_params: Dict[str, Any] = {}
        elif dataset in {"daily_bar", "fund_daily_bar"}:
            code = request.pop("ts_code", request.pop("symbol", ""))
            if not code:
                raise DataProviderError("invalid_request", f"{dataset} requires ts_code or symbol", self.name, spec.api_name)
            normalized_code = _canonical_ts_code(code)
            trade_date = request.pop("trade_date", None)
            start_date = request.pop("start_date", trade_date or "19700101")
            end_date = request.pop("end_date", trade_date or "20500101")
            request.pop("fields", None)
            request.pop("limit", None)
            request.pop("offset", None)
            adjust = str(request.pop("adjust", "") or "")
            adjustment_mode = adjust or "raw"
            if require_pit and adjust:
                raise DataProviderError(
                    "adjustment_not_pit_safe",
                    "AKShare qfq/hfq is dynamically rebased; strict PIT requires raw bars plus cutoff-safe adjustment_factor",
                    self.name,
                    spec.api_name,
                )
            period = request.pop("period", "daily")
            timeout = request.pop("timeout", 20) if dataset == "daily_bar" else None
            if request:
                raise DataProviderError("parameter_translation_unavailable", f"AKShare {dataset} fallback cannot translate parameters: {sorted(request)}", self.name, spec.api_name)
            call_params = {"symbol": _ak_symbol(code), "period": period, "start_date": start_date, "end_date": end_date, "adjust": adjust}
            if dataset == "daily_bar":
                call_params["timeout"] = timeout
        elif dataset == "industry_membership":
            symbol = request.pop("symbol", request.pop("industry", ""))
            if not symbol:
                raise DataProviderError("invalid_request", "industry_membership requires symbol or industry", self.name, spec.api_name)
            call_params = {"symbol": symbol, **request}
        elif dataset == "china_yield_curve":
            code = str(request.pop("ts_code", CHINA_GOVT_CURVE_CODE)).strip().upper()
            if code != CHINA_GOVT_CURVE_CODE:
                raise DataProviderError("semantic_coverage_unavailable", "AKShare fallback only maps the verified China government curve 1001.CB", self.name, spec.api_name)
            raw_curve_type = request.pop("curve_type", None)
            if raw_curve_type is None or str(raw_curve_type) not in {"0", "1"}:
                raise DataProviderError("semantic_ambiguity", "AKShare curve fallback requires curve_type=0 (maturity) or curve_type=1 (spot)", self.name, spec.api_name)
            curve_type = str(raw_curve_type)
            raw_curve_term = request.pop("curve_term", None)
            if raw_curve_term not in (None, ""):
                curve_term = _number(raw_curve_term)
                if curve_term is None or curve_term < 0:
                    raise DataProviderError("invalid_request", "curve_term must be a non-negative number of years", self.name, spec.api_name)
            trade_date = request.pop("trade_date", None)
            explicit_start = request.pop("start_date", None)
            explicit_end = request.pop("end_date", None)
            if trade_date and any(_date_key(value) != _date_key(trade_date) for value in (explicit_start, explicit_end) if value not in (None, "")):
                raise DataProviderError("invalid_request", "trade_date conflicts with start_date/end_date", self.name, spec.api_name)
            start_date = explicit_start or trade_date
            end_date = explicit_end or trade_date
            request.pop("fields", None)
            request.pop("limit", None)
            request.pop("offset", None)
            if not start_date or not end_date:
                raise DataProviderError("invalid_request", "china_yield_curve requires trade_date or start_date/end_date", self.name, spec.api_name)
            start, end = _valid_date(start_date), _valid_date(end_date)
            if start is None or end is None or start > end:
                raise DataProviderError("invalid_request", "yield-curve dates must be valid and start_date <= end_date", self.name, spec.api_name)
            if request:
                raise DataProviderError("parameter_translation_unavailable", f"AKShare yield-curve fallback cannot translate parameters: {sorted(request)}", self.name, spec.api_name)
            standard_terms = set(AKSHARE_STANDARD_CURVE_TERMS.values())
            needs_dense_curve = curve_type == "1" or (curve_term is not None and curve_term not in standard_terms)
            if needs_dense_curve:
                if (end - start).days > 31:
                    raise DataProviderError("historical_coverage_unavailable", "bond_china_close_return accepts no more than one month per request", self.name, "bond_china_close_return")
                oldest_supported = _subtract_months(datetime.now(SHANGHAI).date(), 3)
                if start < oldest_supported:
                    raise DataProviderError("historical_coverage_unavailable", "AKShare dense maturity/spot curve is only available for the most recent three months", self.name, "bond_china_close_return")
                effective_spec = replace(spec, api_name="bond_china_close_return", docs="https://akshare.akfamily.xyz/data/bond/bond.html#id44")
                call_segments = [
                    {"symbol": "国债", "period": period, "start_date": _date_key(start), "end_date": _date_key(end)}
                    for period in ("0.1", "0.5", "1")
                ]
                call_params = {"segments": call_segments}
            else:
                if (end - start).days >= 365:
                    raise DataProviderError("invalid_request", "bond_china_yield requires a date span shorter than one year", self.name, spec.api_name)
                call_params = {"start_date": _date_key(start), "end_date": _date_key(end)}
        else:
            call_params = request
        try:
            method = getattr(self.client, effective_spec.api_name)
            if call_segments is not None:
                source_rows: List[Dict[str, Any]] = []
                for segment in call_segments:
                    segment_rows = _records(method(**segment))
                    provider_segment_row_counts.append(len(segment_rows))
                    source_rows.extend(segment_rows)
                rows = _dedupe(_normalize_akshare(dataset, source_rows, normalized_code, curve_type), effective_spec.primary_key)
            else:
                rows = _normalize_akshare(dataset, _records(method(**call_params)), normalized_code, curve_type)
            if dataset == "china_yield_curve" and curve_term is not None:
                unfiltered_rows = rows
                rows = [row for row in rows if math.isclose(float(row["curve_term"]), curve_term, rel_tol=0.0, abs_tol=1e-9)]
                if unfiltered_rows and not rows:
                    raise DataProviderError("requested_term_unavailable", f"AKShare curve response does not contain curve_term={curve_term}", self.name, effective_spec.api_name)
        except DataProviderError:
            raise
        except AttributeError as error:
            raise DataProviderError("sdk_interface_missing", f"AKShare client has no interface '{effective_spec.api_name}'", self.name, effective_spec.api_name) from error
        except Exception as error:
            raise _provider_error(error, self.name, effective_spec.api_name) from error
        filtered, stats = _filter_as_of(rows, as_of, effective_spec.availability_fields, require_pit, effective_spec.pit_grade)
        contract = _contract_metadata(effective_spec, filtered, require_complete, require_quality=require_quality)
        metadata = {
            "provider": self.name,
            "interface": effective_spec.api_name,
            "requested_dataset": requested_dataset,
            "docs": effective_spec.docs,
            "pit_grade": effective_spec.pit_grade,
            "availability_fields": list(effective_spec.availability_fields),
            "requested_at": _utc_now(),
            "interface_call_succeeded": True,
            "permission_verified_live": not self._injected_client,
            "request_params": _redact_value(original_request),
            "provider_call_params": _redact_value(call_params),
            "provider_segment_row_counts": provider_segment_row_counts,
            "control_flags": {"require_complete": require_complete, "require_quality": require_quality},
            "row_count_before_pit_filter": len(rows),
            "row_count": len(filtered),
            "fallback_warning": "AKShare wraps public websites; schema and availability can change without notice.",
            "adjustment_mode": adjustment_mode,
            "semantic_scope": (
                "standard_maturity_tenors" if dataset == "china_yield_curve" and effective_spec.api_name == "bond_china_yield"
                else "recent_dense_maturity_or_spot" if dataset == "china_yield_curve"
                else None
            ),
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


def _load_json_rows(path: str) -> List[Dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(value, dict) and isinstance(value.get("records"), list):
        value = value["records"]
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise DataProviderError("invalid_request", f"{path} must contain a JSON row list or a DataResult object", "router")
    return [dict(row) for row in value]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    caps = commands.add_parser("capabilities")
    caps.add_argument("--points-profile", type=int, default=DEFAULT_POINTS_PROFILE)
    caps.add_argument("--output")
    adjust = commands.add_parser("adjust", help="Build cutoff-safe qfq/hfq prices from raw bars and adj_factor rows")
    adjust.add_argument("--daily-file", required=True)
    adjust.add_argument("--factor-file", required=True)
    adjust.add_argument("--mode", choices=("qfq", "hfq"), required=True)
    adjust.add_argument("--as-of", required=True)
    adjust.add_argument("--output")
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
        if args.command == "adjust":
            result = adjust_price_records(
                _load_json_rows(args.daily_file),
                _load_json_rows(args.factor_file),
                mode=args.mode,
                as_of=args.as_of,
            )
            _write_result(result.to_dict(), args.output)
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
