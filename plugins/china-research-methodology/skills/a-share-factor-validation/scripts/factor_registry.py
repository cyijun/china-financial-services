#!/usr/bin/env python3
"""Append a schema-checked factor experiment to a locked hash-chain registry."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, IO, Mapping, Optional


REQUIRED = {
    "experiment_id",
    "factor_name",
    "hypothesis",
    "data_snapshot_sha256",
    "code_git_sha",
    "sample_start",
    "sample_end",
    "status",
}
STATUSES = {"preregistered", "running", "invalidated", "inconclusive", "research_candidate", "out_of_sample_supported", "production_unverified"}


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def validate_experiment(value: Mapping[str, Any]) -> Dict[str, Any]:
    missing = REQUIRED - set(value)
    if missing:
        raise ValueError(f"missing experiment fields: {sorted(missing)}")
    if value.get("status") not in STATUSES:
        raise ValueError(f"invalid status: {value.get('status')}")
    for field in ("data_snapshot_sha256", "code_git_sha"):
        text = str(value.get(field, ""))
        minimum = 64 if field == "data_snapshot_sha256" else 7
        if len(text) < minimum or any(character not in "0123456789abcdefABCDEF" for character in text):
            raise ValueError(f"{field} must be a hexadecimal digest")
    return dict(value)


def _verify_stream(stream: IO[str]) -> Optional[str]:
    stream.seek(0)
    expected: Optional[str] = None
    for number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        value = json.loads(line)
        stored = str(value.pop("record_hash", ""))
        calculated = hashlib.sha256(canonical(value)).hexdigest()
        if value.get("previous_hash") != expected or stored != calculated:
            raise ValueError(f"registry hash-chain verification failed at line {number}")
        expected = stored
    return expected


def append_experiment(path: Path, experiment: Mapping[str, Any]) -> Dict[str, Any]:
    checked = validate_experiment(experiment)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        previous = _verify_stream(stream)
        payload: Dict[str, Any] = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "previous_hash": previous,
            "experiment": checked,
        }
        payload["record_hash"] = hashlib.sha256(canonical(payload)).hexdigest()
        stream.seek(0, os.SEEK_END)
        stream.write(canonical(payload).decode("utf-8") + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    return payload


def verify_registry(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
        result = _verify_stream(stream)
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("--experiment", required=True, help="JSON object")
    args = parser.parse_args()
    value = json.loads(args.experiment)
    if not isinstance(value, dict):
        raise SystemExit("--experiment must be a JSON object")
    print(json.dumps(append_experiment(args.registry, value), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
