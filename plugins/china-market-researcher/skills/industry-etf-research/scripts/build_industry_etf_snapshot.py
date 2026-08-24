#!/usr/bin/env python3
"""Build a deterministic, non-trading industry-ETF research snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo


INPUT_SCHEMA = "industry-etf-input/v1"
OUTPUT_SCHEMA = "industry-etf-snapshot/v1"
FUNDAMENTAL_STATES = {"improving", "stable", "weakening", "unclear"}
MARKET_STATES = {"confirming", "mixed", "not_confirming", "unclear"}
PRICE_BASES = {"raw", "qfq", "hfq"}
AMOUNT_UNITS = {"CNY": 1.0, "thousand_CNY": 1000.0}
SHARE_UNITS = {"shares": 1.0, "ten_thousand_shares": 10000.0}
STRICT_INDEX_PIT_GRADES = {"trade_date", "historical_snapshot"}
SHANGHAI = ZoneInfo("Asia/Shanghai")


class ContractError(ValueError):
    """Input cannot support an auditable deterministic snapshot."""


def _number(value: Any, label: str, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    if value is None or isinstance(value, bool):
        raise ContractError(f"{label} must be a finite number")
    try:
        result = float(str(value).replace(",", ""))
    except (TypeError, ValueError) as error:
        raise ContractError(f"{label} must be a finite number") from error
    if not math.isfinite(result):
        raise ContractError(f"{label} must be a finite number")
    if minimum is not None and result < minimum:
        raise ContractError(f"{label} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise ContractError(f"{label} must be <= {maximum}")
    return result


def _date_key(value: Any, label: str) -> str:
    text = str(value or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            pass
    raise ContractError(f"{label} must be YYYYMMDD or YYYY-MM-DD")


def _valid_timestamp(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        try:
            date.fromisoformat(text)
            return True
        except ValueError:
            return False


def _timestamp_moment(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    try:
        if len(text) == 10 and text[4] == "-":
            return datetime.combine(date.fromisoformat(text), time.max, SHANGHAI)
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractError(f"{label} must be ISO-8601") from error
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    return moment.astimezone(SHANGHAI)


def _cutoff_moment(date_key: str) -> datetime:
    parsed = datetime.strptime(date_key, "%Y%m%d").date()
    return datetime.combine(parsed, time.max, SHANGHAI)


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _round(value: Optional[float], digits: int = 6) -> Optional[float]:
    return None if value is None else round(value, digits)


def _require_mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return dict(value)


def _require_list(value: Any, label: str, *, nonempty: bool = False) -> List[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be an array")
    if nonempty and not value:
        raise ContractError(f"{label} must not be empty")
    return value


def _require_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractError(f"{label} must not be empty")
    return text


def _evidence_ids(value: Any, label: str, known: set[str], *, nonempty: bool = True) -> List[str]:
    raw = _require_list(value, label, nonempty=nonempty)
    ids = [_require_text(item, f"{label}[]") for item in raw]
    if len(ids) != len(set(ids)):
        raise ContractError(f"{label} contains duplicate evidence ids")
    missing = sorted(set(ids) - known)
    if missing:
        raise ContractError(f"{label} references missing evidence ids: {missing}")
    return ids


def _series(
    rows: Any,
    *,
    label: str,
    date_field: str,
    value_field: str,
    cutoff: Optional[str] = None,
    allow_empty: bool = True,
) -> List[Tuple[str, float, Dict[str, Any]]]:
    values = _require_list(rows if rows is not None else [], label)
    if not values and not allow_empty:
        raise ContractError(f"{label} must not be empty")
    output: List[Tuple[str, float, Dict[str, Any]]] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        row = _require_mapping(raw, f"{label}[{index}]")
        key = _date_key(row.get(date_field), f"{label}[{index}].{date_field}")
        if key in seen:
            raise ContractError(f"{label} contains duplicate date {key}")
        if cutoff is not None and key > cutoff:
            raise ContractError(f"{label} contains future observation {key} after as_of {cutoff}")
        seen.add(key)
        value = _number(row.get(value_field), f"{label}[{index}].{value_field}", minimum=0.0)
        output.append((key, value, row))
    output.sort(key=lambda item: item[0])
    return output


def _window_return(series: Sequence[Tuple[str, float, Mapping[str, Any]]], horizon: int) -> Optional[float]:
    if len(series) < horizon + 1:
        return None
    first, last = series[-horizon - 1][1], series[-1][1]
    if first <= 0:
        return None
    return (last / first - 1.0) * 100.0


def _daily_returns(series: Sequence[Tuple[str, float, Mapping[str, Any]]]) -> Dict[str, float]:
    output: Dict[str, float] = {}
    for previous, current in zip(series, series[1:]):
        if previous[1] > 0:
            output[current[0]] = current[1] / previous[1] - 1.0
    return output


def _tracking_metrics(
    nav: Sequence[Tuple[str, float, Mapping[str, Any]]],
    index_levels: Sequence[Tuple[str, float, Mapping[str, Any]]],
    horizons: Sequence[int],
) -> Dict[str, Any]:
    nav_returns = _daily_returns(nav)
    index_returns = _daily_returns(index_levels)
    common_dates = sorted(set(nav_returns) & set(index_returns))
    differences = [nav_returns[key] - index_returns[key] for key in common_dates]
    tracking_error = statistics.stdev(differences) * math.sqrt(252.0) * 100.0 if len(differences) >= 2 else None
    horizon_rows = []
    nav_by_date = {key: value for key, value, _ in nav}
    index_by_date = {key: value for key, value, _ in index_levels}
    common_levels = sorted(set(nav_by_date) & set(index_by_date))
    paired_nav = [(key, nav_by_date[key], {}) for key in common_levels]
    paired_index = [(key, index_by_date[key], {}) for key in common_levels]
    for horizon in horizons:
        nav_return = _window_return(paired_nav, horizon)
        index_return = _window_return(paired_index, horizon)
        horizon_rows.append(
            {
                "observations": horizon,
                "matched_level_dates": len(common_levels),
                "adjusted_nav_return_pct": _round(nav_return),
                "index_return_pct": _round(index_return),
                "tracking_difference_pct": _round(nav_return - index_return) if nav_return is not None and index_return is not None else None,
            }
        )
    return {
        "matched_daily_return_dates": len(common_dates),
        "annualized_tracking_error_pct": _round(tracking_error),
        "horizons": horizon_rows,
    }


def _exposure_metrics(index: Mapping[str, Any], known_evidence: set[str], cutoff: str, require_pit: bool) -> Tuple[Dict[str, Any], Dict[str, float]]:
    code = _require_text(index.get("index_code"), "indices[].index_code")
    name = _require_text(index.get("name"), f"indices[{code}].name")
    method_url = _require_text(index.get("methodology_url"), f"indices[{code}].methodology_url")
    if not method_url.startswith(("https://", "http://")):
        raise ContractError(f"indices[{code}].methodology_url must be an HTTP(S) URL")
    evidence = _evidence_ids(index.get("evidence_ids"), f"indices[{code}].evidence_ids", known_evidence)
    constituents_as_of = _date_key(index.get("constituents_as_of"), f"indices[{code}].constituents_as_of")
    if constituents_as_of > cutoff:
        raise ContractError(f"indices[{code}].constituents_as_of is after as_of")
    constituents_pit_grade = _require_text(index.get("constituents_pit_grade"), f"indices[{code}].constituents_pit_grade")
    if require_pit and constituents_pit_grade not in STRICT_INDEX_PIT_GRADES:
        raise ContractError(f"indices[{code}] strict PIT requires constituents_pit_grade in {sorted(STRICT_INDEX_PIT_GRADES)}")
    constituents = _require_list(index.get("constituents"), f"indices[{code}].constituents", nonempty=True)
    weights: Dict[str, float] = {}
    rows: List[Tuple[Dict[str, Any], float]] = []
    for position, raw in enumerate(constituents):
        row = _require_mapping(raw, f"indices[{code}].constituents[{position}]")
        security = _require_text(row.get("ts_code"), f"indices[{code}].constituents[{position}].ts_code")
        if security in weights:
            raise ContractError(f"indices[{code}] contains duplicate constituent {security}")
        weight = _number(row.get("weight_pct"), f"indices[{code}].constituents[{position}].weight_pct", minimum=0.0)
        weights[security] = weight
        rows.append((row, weight))
    total = sum(weights.values())
    if total <= 0:
        raise ContractError(f"indices[{code}] weight total must be positive")
    sorted_weights = sorted(weights.values(), reverse=True)
    normalized = {security: weight / total for security, weight in weights.items()}
    hhi = sum(weight * weight for weight in normalized.values())

    match_known = [(row, weight) for row, weight in rows if isinstance(row.get("industry_match"), bool)]
    match_covered_weight = sum(weight for _, weight in match_known)
    match_weight = sum(weight for row, weight in match_known if row["industry_match"])

    purity_known = []
    for position, (row, weight) in enumerate(rows):
        if row.get("industry_revenue_share_pct") not in (None, ""):
            purity = _number(
                row.get("industry_revenue_share_pct"),
                f"indices[{code}].constituents[{position}].industry_revenue_share_pct",
                minimum=0.0,
                maximum=100.0,
            )
            purity_known.append((purity, weight))
    purity_weight = sum(weight for _, weight in purity_known)
    weighted_purity = sum(purity * weight for purity, weight in purity_known) / purity_weight if purity_weight > 0 else None

    return (
        {
            "index_code": code,
            "name": name,
            "methodology_url": method_url,
            "evidence_ids": evidence,
            "constituents_as_of": constituents_as_of,
            "constituents_pit_grade": constituents_pit_grade,
            "constituent_count": len(weights),
            "weight_total_pct": _round(total),
            "top1_weight_pct": _round(sum(sorted_weights[:1])),
            "top5_weight_pct": _round(sum(sorted_weights[:5])),
            "top10_weight_pct": _round(sum(sorted_weights[:10])),
            "hhi_normalized": _round(hhi),
            "effective_constituent_count": _round(1.0 / hhi if hhi else None),
            "industry_match_weight_pct_of_supplied": _round(match_weight / total * 100.0),
            "industry_match_coverage_weight_pct": _round(match_covered_weight / total * 100.0),
            "weighted_industry_revenue_share_pct": _round(weighted_purity),
            "revenue_purity_coverage_weight_pct": _round(purity_weight / total * 100.0),
            "breadth": _breadth_metrics(rows, total),
        },
        normalized,
    )


def _breadth_metrics(rows: Sequence[Tuple[Mapping[str, Any], float]], total_weight: float) -> Dict[str, Any]:
    return_known: List[Tuple[float, float]] = []
    above_known: List[Tuple[bool, float]] = []
    for row, weight in rows:
        if row.get("return_pct") not in (None, ""):
            return_known.append((_number(row.get("return_pct"), "constituent.return_pct"), weight))
        if isinstance(row.get("above_ma"), bool):
            above_known.append((bool(row["above_ma"]), weight))
    return_weight = sum(weight for _, weight in return_known)
    above_weight = sum(weight for _, weight in above_known)
    return {
        "return_observation_count": len(return_known),
        "positive_count_share_pct": _round(sum(1 for value, _ in return_known if value > 0) / len(return_known) * 100.0) if return_known else None,
        "positive_weight_share_pct": _round(sum(weight for value, weight in return_known if value > 0) / return_weight * 100.0) if return_weight else None,
        "return_coverage_weight_pct": _round(return_weight / total_weight * 100.0),
        "above_ma_observation_count": len(above_known),
        "above_ma_count_share_pct": _round(sum(1 for value, _ in above_known if value) / len(above_known) * 100.0) if above_known else None,
        "above_ma_weight_share_pct": _round(sum(weight for value, weight in above_known if value) / above_weight * 100.0) if above_weight else None,
        "above_ma_coverage_weight_pct": _round(above_weight / total_weight * 100.0),
    }


def _overlap(index_weights: Mapping[str, Mapping[str, float]]) -> List[Dict[str, Any]]:
    codes = sorted(index_weights)
    output = []
    for left_position, left in enumerate(codes):
        for right in codes[left_position + 1 :]:
            left_weights, right_weights = index_weights[left], index_weights[right]
            union = set(left_weights) | set(right_weights)
            intersection = set(left_weights) & set(right_weights)
            output.append(
                {
                    "left_index_code": left,
                    "right_index_code": right,
                    "weighted_overlap_pct": _round(sum(min(left_weights.get(code, 0.0), right_weights.get(code, 0.0)) for code in union) * 100.0),
                    "constituent_jaccard_pct": _round(len(intersection) / len(union) * 100.0) if union else None,
                    "common_constituent_count": len(intersection),
                }
            )
    return output


def _liquidity(price_rows: Sequence[Tuple[str, float, Mapping[str, Any]]], amount_unit: Any, label: str) -> Dict[str, Any]:
    amounts = [row.get("amount") for _, _, row in price_rows if row.get("amount") not in (None, "")]
    if not amounts:
        return {"observation_count": 0, "mean_amount_cny": None, "median_amount_cny": None}
    unit = _require_text(amount_unit, f"{label}.amount_unit")
    if unit not in AMOUNT_UNITS:
        raise ContractError(f"{label}.amount_unit must be one of {sorted(AMOUNT_UNITS)}")
    converted = [_number(value, f"{label}.price_bars[].amount", minimum=0.0) * AMOUNT_UNITS[unit] for value in amounts]
    return {
        "observation_count": len(converted),
        "mean_amount_cny": _round(statistics.fmean(converted), 2),
        "median_amount_cny": _round(statistics.median(converted), 2),
    }


def _share_metrics(
    share_rows: Sequence[Tuple[str, float, Mapping[str, Any]]],
    share_unit: Any,
    nav_rows: Sequence[Tuple[str, float, Mapping[str, Any]]],
    horizons: Sequence[int],
    label: str,
) -> List[Dict[str, Any]]:
    if not share_rows:
        return []
    unit = _require_text(share_unit, f"{label}.share_unit")
    if unit not in SHARE_UNITS:
        raise ContractError(f"{label}.share_unit must be one of {sorted(SHARE_UNITS)}")
    multiplier = SHARE_UNITS[unit]
    absolute = [(key, value * multiplier, row) for key, value, row in share_rows]
    unit_nav_by_date: Dict[str, float] = {}
    for key, _, row in nav_rows:
        if row.get("unit_nav") not in (None, ""):
            unit_nav_by_date[key] = _number(row.get("unit_nav"), f"{label}.adjusted_nav[].unit_nav", minimum=0.0)
    output = []
    for horizon in horizons:
        if len(absolute) < horizon + 1:
            output.append({"observations": horizon, "share_change": None, "share_change_pct": None, "estimated_net_creation_cny": None, "estimate_basis": None})
            continue
        start, end = absolute[-horizon - 1], absolute[-1]
        change = end[1] - start[1]
        nav = unit_nav_by_date.get(end[0])
        output.append(
            {
                "observations": horizon,
                "start_date": start[0],
                "end_date": end[0],
                "share_change": _round(change, 2),
                "share_change_pct": _round(change / start[1] * 100.0) if start[1] else None,
                "estimated_net_creation_cny": _round(change * nav, 2) if nav is not None else None,
                "estimate_basis": "share_change_times_same_date_unit_nav" if nav is not None else None,
            }
        )
    return output


def _premium_metrics(
    price_rows: Sequence[Tuple[str, float, Mapping[str, Any]]],
    nav_rows: Sequence[Tuple[str, float, Mapping[str, Any]]],
    price_basis: str,
    realtime: Any,
    label: str,
) -> Dict[str, Any]:
    close_premium = None
    if price_basis == "raw":
        closes = {key: value for key, value, _ in price_rows}
        navs: Dict[str, float] = {}
        for key, _, row in nav_rows:
            if row.get("unit_nav") not in (None, ""):
                navs[key] = _number(row.get("unit_nav"), f"{label}.adjusted_nav[].unit_nav", minimum=0.0)
        common = sorted(set(closes) & set(navs))
        if common and navs[common[-1]] > 0:
            key = common[-1]
            close_premium = {"date": key, "premium_pct": _round((closes[key] / navs[key] - 1.0) * 100.0)}
    realtime_premium = None
    if realtime is not None:
        row = _require_mapping(realtime, f"{label}.realtime_snapshot")
        observed_at = _require_text(row.get("observed_at"), f"{label}.realtime_snapshot.observed_at")
        if not _valid_timestamp(observed_at):
            raise ContractError(f"{label}.realtime_snapshot.observed_at must be ISO-8601")
        price = _number(row.get("price"), f"{label}.realtime_snapshot.price", minimum=0.0)
        iopv = _number(row.get("iopv"), f"{label}.realtime_snapshot.iopv", minimum=0.0)
        if iopv <= 0:
            raise ContractError(f"{label}.realtime_snapshot.iopv must be positive")
        realtime_premium = {"observed_at": observed_at, "premium_pct": _round((price / iopv - 1.0) * 100.0)}
    return {"close_to_nav": close_premium, "realtime_to_iopv": realtime_premium}


def _etf_metrics(
    etf: Mapping[str, Any],
    known_evidence: set[str],
    index_levels: Mapping[str, Sequence[Tuple[str, float, Mapping[str, Any]]]],
    horizons: Sequence[int],
    cutoff: str,
    require_pit: bool,
) -> Tuple[Dict[str, Any], List[str]]:
    code = _require_text(etf.get("ts_code"), "etfs[].ts_code")
    label = f"etfs[{code}]"
    name = _require_text(etf.get("name"), f"{label}.name")
    index_code = _require_text(etf.get("index_code"), f"{label}.index_code")
    if index_code not in index_levels:
        raise ContractError(f"{label}.index_code {index_code} is not present in indices")
    evidence = _evidence_ids(etf.get("evidence_ids"), f"{label}.evidence_ids", known_evidence)
    price_basis = _require_text(etf.get("price_basis"), f"{label}.price_basis")
    if price_basis not in PRICE_BASES:
        raise ContractError(f"{label}.price_basis must be one of {sorted(PRICE_BASES)}")
    if require_pit and price_basis != "raw":
        raise ContractError(f"{label}: strict PIT accepts raw trading prices only; use adjusted NAV for total return")
    price = _series(etf.get("price_bars"), label=f"{label}.price_bars", date_field="trade_date", value_field="close", cutoff=cutoff)
    nav = _series(etf.get("adjusted_nav"), label=f"{label}.adjusted_nav", date_field="nav_date", value_field="adj_nav", cutoff=cutoff)
    shares = _series(etf.get("shares"), label=f"{label}.shares", date_field="trade_date", value_field="shares", cutoff=cutoff)
    if require_pit:
        for key, _, row in nav:
            ann_date = _date_key(row.get("ann_date"), f"{label}.adjusted_nav[{key}].ann_date")
            if ann_date >= cutoff:
                raise ContractError(f"{label}.adjusted_nav[{key}] is not conservatively available by as_of; date-only ann_date becomes usable the next day")
        cutoff_at = _cutoff_moment(cutoff)
        for key, _, row in shares:
            available_at = row.get("available_at")
            if not available_at:
                raise ContractError(f"{label}.shares[{key}] strict PIT requires an archived available_at timestamp")
            if _timestamp_moment(available_at, f"{label}.shares[{key}].available_at") > cutoff_at:
                raise ContractError(f"{label}.shares[{key}].available_at is after as_of")
    warnings: List[str] = []
    if price_basis == "raw" and price:
        warnings.append(f"{code}: trading-price returns are raw-price returns, not dividend-adjusted total returns")
    if price_basis in {"qfq", "hfq"}:
        warnings.append(f"{code}: adjusted trading prices require an explicit source/version and are not assumed PIT-safe")
    if not nav:
        warnings.append(f"{code}: adjusted NAV is missing; total return and tracking metrics are incomplete")
    if not shares:
        warnings.append(f"{code}: share series is missing; estimated creations/redemptions are unavailable")
    price_returns = [{"observations": horizon, "return_pct": _round(_window_return(price, horizon))} for horizon in horizons]
    nav_returns = [{"observations": horizon, "return_pct": _round(_window_return(nav, horizon))} for horizon in horizons]
    tracking = _tracking_metrics(nav, index_levels[index_code], horizons) if nav and index_levels[index_code] else {
        "matched_daily_return_dates": 0,
        "annualized_tracking_error_pct": None,
        "horizons": [],
    }
    share_metrics = _share_metrics(shares, etf.get("share_unit"), nav, horizons, label)
    if share_metrics and any(row["share_change"] is not None and row["estimated_net_creation_cny"] is None for row in share_metrics):
        warnings.append(f"{code}: same-date unit NAV is missing for at least one share window; net creation estimate is omitted")
    return (
        {
            "ts_code": code,
            "name": name,
            "index_code": index_code,
            "evidence_ids": evidence,
            "price_basis": price_basis,
            "price_returns": price_returns,
            "adjusted_nav_total_returns": nav_returns,
            "tracking": tracking,
            "liquidity": _liquidity(price, etf.get("amount_unit"), label),
            "premiums": _premium_metrics(price, nav, price_basis, etf.get("realtime_snapshot"), label),
            "share_changes": share_metrics,
        },
        warnings,
    )


def _matrix_label(fundamental: str, market: str) -> str:
    labels = {
        ("improving", "confirming"): "基本面改善且市场确认",
        ("improving", "not_confirming"): "基本面改善、市场尚未确认",
        ("weakening", "confirming"): "市场强于基本面，需检查预期先行或暴露错配",
        ("weakening", "not_confirming"): "基本面走弱且市场未确认",
        ("stable", "confirming"): "基本面稳定、市场确认增强",
        ("stable", "not_confirming"): "基本面稳定、市场确认偏弱",
    }
    return labels.get((fundamental, market), "证据混合或不足，保留分歧")


def _validate_evidence(raw: Any, cutoff: str) -> Tuple[List[Dict[str, Any]], set[str]]:
    evidence = _require_list(raw, "evidence", nonempty=True)
    output: List[Dict[str, Any]] = []
    ids: set[str] = set()
    for position, item in enumerate(evidence):
        row = _require_mapping(item, f"evidence[{position}]")
        evidence_id = _require_text(row.get("id"), f"evidence[{position}].id")
        if evidence_id in ids:
            raise ContractError(f"duplicate evidence id {evidence_id}")
        ids.add(evidence_id)
        _require_text(row.get("title"), f"evidence[{position}].title")
        _require_text(row.get("source"), f"evidence[{position}].source")
        timestamp = row.get("available_at") or row.get("observed_at")
        if not _valid_timestamp(timestamp):
            raise ContractError(f"evidence[{position}] requires ISO-8601 available_at or observed_at")
        if _timestamp_moment(timestamp, f"evidence[{position}].available_at/observed_at") > _cutoff_moment(cutoff):
            raise ContractError(f"evidence[{position}] is observed or available after as_of")
        if row.get("provider") or row.get("interface"):
            if not row.get("provider") or not row.get("interface") or not row.get("pit_grade"):
                raise ContractError(f"evidence[{position}] structured data requires provider, interface, and pit_grade")
            digest = str(row.get("response_sha256") or "")
            if len(digest) != 64 or any(character not in "0123456789abcdefABCDEF" for character in digest):
                raise ContractError(f"evidence[{position}] structured data requires a 64-character response_sha256")
        output.append(row)
    return output, ids


def build_snapshot(payload: Mapping[str, Any]) -> Dict[str, Any]:
    source = _require_mapping(payload, "root")
    if source.get("schema_version") != INPUT_SCHEMA:
        raise ContractError(f"schema_version must be {INPUT_SCHEMA}")
    as_of = _date_key(source.get("as_of"), "as_of")
    require_pit = source.get("require_pit", False)
    if not isinstance(require_pit, bool):
        raise ContractError("require_pit must be true or false")
    evidence, known_evidence = _validate_evidence(source.get("evidence"), as_of)
    horizons_raw = _require_list(source.get("horizons", [20, 60, 120]), "horizons", nonempty=True)
    horizons = sorted({_number(value, "horizons[]", minimum=1.0) for value in horizons_raw})
    if any(not value.is_integer() for value in horizons):
        raise ContractError("horizons must contain positive integers")
    horizon_values = [int(value) for value in horizons]

    industry = _require_mapping(source.get("industry"), "industry")
    industry_output = {
        "name": _require_text(industry.get("name"), "industry.name"),
        "taxonomy": _require_text(industry.get("taxonomy"), "industry.taxonomy"),
        "scope": _require_text(industry.get("scope"), "industry.scope"),
        "evidence_ids": _evidence_ids(industry.get("evidence_ids"), "industry.evidence_ids", known_evidence),
    }

    index_rows = _require_list(source.get("indices"), "indices", nonempty=True)
    indices: List[Dict[str, Any]] = []
    normalized_weights: Dict[str, Dict[str, float]] = {}
    index_levels: Dict[str, Sequence[Tuple[str, float, Mapping[str, Any]]]] = {}
    warnings: List[str] = []
    for raw in index_rows:
        index = _require_mapping(raw, "indices[]")
        result, weights = _exposure_metrics(index, known_evidence, as_of, require_pit)
        code = result["index_code"]
        if code in normalized_weights:
            raise ContractError(f"duplicate index_code {code}")
        normalized_weights[code] = weights
        levels = _series(index.get("levels"), label=f"indices[{code}].levels", date_field="trade_date", value_field="close", cutoff=as_of)
        index_levels[code] = levels
        if not 99.0 <= result["weight_total_pct"] <= 101.0:
            warnings.append(f"{code}: supplied constituent weights sum to {result['weight_total_pct']}%, not approximately 100%")
        if result["industry_match_coverage_weight_pct"] < 100.0:
            warnings.append(f"{code}: industry-match coverage is {result['industry_match_coverage_weight_pct']}% of supplied weight")
        if result["revenue_purity_coverage_weight_pct"] < 100.0:
            warnings.append(f"{code}: revenue-purity coverage is {result['revenue_purity_coverage_weight_pct']}% of supplied weight")
        if not levels:
            warnings.append(f"{code}: index levels are missing; ETF tracking metrics are incomplete")
        indices.append(result)

    etf_rows = _require_list(source.get("etfs"), "etfs", nonempty=True)
    etfs: List[Dict[str, Any]] = []
    etf_codes: set[str] = set()
    for raw in etf_rows:
        etf, etf_warnings = _etf_metrics(_require_mapping(raw, "etfs[]"), known_evidence, index_levels, horizon_values, as_of, require_pit)
        if etf["ts_code"] in etf_codes:
            raise ContractError(f"duplicate ETF code {etf['ts_code']}")
        etf_codes.add(etf["ts_code"])
        etfs.append(etf)
        warnings.extend(etf_warnings)

    state = _require_mapping(source.get("state_assessment", {}), "state_assessment")
    fundamental = str(state.get("fundamental_state", "unclear")).strip()
    market = str(state.get("market_state", "unclear")).strip()
    if fundamental not in FUNDAMENTAL_STATES:
        raise ContractError(f"fundamental_state must be one of {sorted(FUNDAMENTAL_STATES)}")
    if market not in MARKET_STATES:
        raise ContractError(f"market_state must be one of {sorted(MARKET_STATES)}")
    fundamental_evidence = _evidence_ids(
        state.get("fundamental_evidence_ids", []),
        "state_assessment.fundamental_evidence_ids",
        known_evidence,
        nonempty=fundamental != "unclear",
    )
    market_evidence = _evidence_ids(
        state.get("market_evidence_ids", []),
        "state_assessment.market_evidence_ids",
        known_evidence,
        nonempty=market != "unclear",
    )
    counterevidence = [_require_text(item, "counterevidence[]") for item in _require_list(source.get("counterevidence"), "counterevidence", nonempty=True)]
    limitations = [_require_text(item, "limitations[]") for item in _require_list(source.get("limitations"), "limitations", nonempty=True)]

    output = {
        "schema_version": OUTPUT_SCHEMA,
        "as_of": as_of,
        "industry": industry_output,
        "horizons": horizon_values,
        "index_exposure": indices,
        "index_overlap": _overlap(normalized_weights),
        "etf_market_confirmation": etfs,
        "synthesis": {
            "fundamental_state": fundamental,
            "market_state": market,
            "matrix_label": _matrix_label(fundamental, market),
            "fundamental_evidence_ids": fundamental_evidence,
            "market_evidence_ids": market_evidence,
            "is_trade_signal": False,
        },
        "counterevidence": counterevidence,
        "limitations": limitations,
        "warnings": sorted(set(warnings)),
        "evidence": evidence,
        "calculation_basis": {
            "script": "build_industry_etf_snapshot.py",
            "input_schema": INPUT_SCHEMA,
            "input_sha256": _stable_digest(source),
            "require_pit": require_pit,
            "no_composite_score": True,
            "estimated_flow_label": "estimated_net_creation_cny",
        },
    }
    output["snapshot_sha256"] = _stable_digest(output)
    return output


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="industry-etf-input/v1 JSON")
    parser.add_argument("--output", help="write snapshot JSON; stdout when omitted")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        snapshot = build_snapshot(payload)
        text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    except (OSError, json.JSONDecodeError, ContractError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
