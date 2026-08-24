#!/usr/bin/env python3
"""Validate an industry-etf-snapshot/v1 artifact and its research boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


OUTPUT_SCHEMA = "industry-etf-snapshot/v1"
FUNDAMENTAL_STATES = {"improving", "stable", "weakening", "unclear"}
MARKET_STATES = {"confirming", "mixed", "not_confirming", "unclear"}
FORBIDDEN_KEYS = {
    "recommendation",
    "rating",
    "target_price",
    "position",
    "position_size",
    "trade_action",
    "buy_signal",
    "sell_signal",
    "composite_score",
    "probability",
    "win_rate",
}


def _walk(value: Any, path: str = "root") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_snapshot(payload: Any) -> Dict[str, List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(payload, Mapping):
        return {"errors": ["root must be an object"], "warnings": []}
    if payload.get("schema_version") != OUTPUT_SCHEMA:
        errors.append(f"schema_version must be {OUTPUT_SCHEMA}")
    for required in ("as_of", "industry", "index_exposure", "etf_market_confirmation", "synthesis", "counterevidence", "limitations", "evidence", "calculation_basis", "snapshot_sha256"):
        if required not in payload:
            errors.append(f"missing required field {required}")

    evidence = payload.get("evidence")
    evidence_ids: set[str] = set()
    if not isinstance(evidence, list) or not evidence:
        errors.append("evidence must be a non-empty array")
    else:
        for position, item in enumerate(evidence):
            if not isinstance(item, Mapping):
                errors.append(f"evidence[{position}] must be an object")
                continue
            evidence_id = item.get("id")
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                errors.append(f"evidence[{position}].id is required")
            elif evidence_id in evidence_ids:
                errors.append(f"duplicate evidence id {evidence_id}")
            else:
                evidence_ids.add(evidence_id)
            if not item.get("source"):
                errors.append(f"evidence[{position}].source is required")
            if not (item.get("available_at") or item.get("observed_at")):
                errors.append(f"evidence[{position}] requires available_at or observed_at")

    indices = payload.get("index_exposure")
    index_codes: set[str] = set()
    if not isinstance(indices, list) or not indices:
        errors.append("index_exposure must be a non-empty array")
    else:
        for position, row in enumerate(indices):
            if not isinstance(row, Mapping):
                errors.append(f"index_exposure[{position}] must be an object")
                continue
            code = row.get("index_code")
            if not isinstance(code, str) or not code:
                errors.append(f"index_exposure[{position}].index_code is required")
            elif code in index_codes:
                errors.append(f"duplicate index_code {code}")
            else:
                index_codes.add(code)
            total = row.get("weight_total_pct")
            if not _finite(total) or float(total) <= 0:
                errors.append(f"index_exposure[{position}].weight_total_pct must be positive")
            elif not 99.0 <= float(total) <= 101.0:
                warnings.append(f"{code}: constituent weights do not sum to approximately 100%")
            hhi = row.get("hhi_normalized")
            if not _finite(hhi) or not 0 < float(hhi) <= 1:
                errors.append(f"index_exposure[{position}].hhi_normalized must be in (0, 1]")
            _check_refs(row.get("evidence_ids"), evidence_ids, f"index_exposure[{position}]", errors)
            if not row.get("constituents_as_of") or not row.get("constituents_pit_grade"):
                errors.append(f"index_exposure[{position}] lacks constituent snapshot provenance")

    etfs = payload.get("etf_market_confirmation")
    if not isinstance(etfs, list) or not etfs:
        errors.append("etf_market_confirmation must be a non-empty array")
    else:
        seen_etfs: set[str] = set()
        for position, row in enumerate(etfs):
            if not isinstance(row, Mapping):
                errors.append(f"etf_market_confirmation[{position}] must be an object")
                continue
            code = row.get("ts_code")
            if not isinstance(code, str) or not code:
                errors.append(f"etf_market_confirmation[{position}].ts_code is required")
            elif code in seen_etfs:
                errors.append(f"duplicate ETF code {code}")
            else:
                seen_etfs.add(code)
            if row.get("index_code") not in index_codes:
                errors.append(f"{code}: index_code is not present in index_exposure")
            _check_refs(row.get("evidence_ids"), evidence_ids, f"etf_market_confirmation[{position}]", errors)
            for share_row in row.get("share_changes") or []:
                if isinstance(share_row, Mapping) and share_row.get("estimated_net_creation_cny") is not None and share_row.get("estimate_basis") != "share_change_times_same_date_unit_nav":
                    errors.append(f"{code}: estimated net creation lacks the required estimate basis")

    synthesis = payload.get("synthesis")
    if not isinstance(synthesis, Mapping):
        errors.append("synthesis must be an object")
    else:
        fundamental = synthesis.get("fundamental_state")
        market = synthesis.get("market_state")
        if fundamental not in FUNDAMENTAL_STATES:
            errors.append("synthesis.fundamental_state is invalid")
        if market not in MARKET_STATES:
            errors.append("synthesis.market_state is invalid")
        if synthesis.get("is_trade_signal") is not False:
            errors.append("synthesis.is_trade_signal must be false")
        _check_refs(synthesis.get("fundamental_evidence_ids"), evidence_ids, "synthesis.fundamental_evidence_ids", errors, required=fundamental != "unclear")
        _check_refs(synthesis.get("market_evidence_ids"), evidence_ids, "synthesis.market_evidence_ids", errors, required=market != "unclear")

    for field in ("counterevidence", "limitations"):
        value = payload.get(field)
        if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
            errors.append(f"{field} must be a non-empty string array")

    basis = payload.get("calculation_basis")
    if isinstance(basis, Mapping):
        if basis.get("no_composite_score") is not True:
            errors.append("calculation_basis.no_composite_score must be true")
        if basis.get("estimated_flow_label") != "estimated_net_creation_cny":
            errors.append("calculation_basis.estimated_flow_label is invalid")

    recorded_digest = payload.get("snapshot_sha256")
    if isinstance(recorded_digest, str):
        digest_payload = dict(payload)
        digest_payload.pop("snapshot_sha256", None)
        if recorded_digest != _stable_digest(digest_payload):
            errors.append("snapshot_sha256 does not match snapshot content")

    for path, value in _walk(payload):
        if isinstance(value, Mapping):
            bad = sorted(set(value) & FORBIDDEN_KEYS)
            if bad:
                errors.append(f"{path} contains forbidden decision fields: {bad}")

    return {"errors": sorted(set(errors)), "warnings": sorted(set(warnings))}


def _check_refs(value: Any, known: set[str], label: str, errors: List[str], *, required: bool = True) -> None:
    if not isinstance(value, list):
        errors.append(f"{label} evidence refs must be an array")
        return
    if required and not value:
        errors.append(f"{label} evidence refs must not be empty")
    if any(not isinstance(item, str) or not item for item in value):
        errors.append(f"{label} evidence refs must contain non-empty strings")
    missing = sorted({item for item in value if isinstance(item, str)} - known)
    if missing:
        errors.append(f"{label} references missing evidence ids: {missing}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="snapshot JSON path")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "errors": [str(error)], "warnings": []}, ensure_ascii=False, indent=2))
        return 2
    result = validate_snapshot(payload)
    print(json.dumps({"ok": not result["errors"], **result}, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
