#!/usr/bin/env python3
"""Append one canonical JSON record to a tamper-evident JSONL hash chain."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, IO, Mapping, Optional


REQUIRED_RECORD_FIELDS = {"version", "as_of", "core_thesis", "pillars", "counterevidence", "status"}
ALLOWED_STATUSES = {"supported", "mixed", "weakened", "broken", "unknown"}


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def validate_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    missing = REQUIRED_RECORD_FIELDS - set(record)
    if missing:
        raise ValueError(f"missing thesis fields: {sorted(missing)}")
    if not isinstance(record.get("version"), int) or int(record["version"]) < 1:
        raise ValueError("version must be a positive integer")
    if record.get("status") not in ALLOWED_STATUSES:
        raise ValueError(f"invalid thesis status: {record.get('status')}")
    if not isinstance(record.get("pillars"), list) or not isinstance(record.get("counterevidence"), list):
        raise ValueError("pillars and counterevidence must be lists")
    return dict(record)


def _verify_stream(stream: IO[str]) -> Optional[str]:
    expected_previous: Optional[str] = None
    stream.seek(0)
    for number, line in enumerate(stream, 1):
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict) or "record_hash" not in value:
                raise ValueError(f"invalid chain entry at line {number}")
            stored_hash = str(value["record_hash"])
            hashed_value = dict(value)
            hashed_value.pop("record_hash")
            calculated_hash = hashlib.sha256(canonical(hashed_value)).hexdigest()
            if value.get("previous_hash") != expected_previous or stored_hash != calculated_hash:
                raise ValueError(f"hash-chain verification failed at line {number}")
            expected_previous = stored_hash
    return expected_previous


def verify_chain(path: Path) -> Optional[str]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("r", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
        result = _verify_stream(stream)
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return result


def append_record(path: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    checked = validate_record(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        previous = _verify_stream(stream)
        payload: Dict[str, Any] = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "previous_hash": previous,
            "record": checked,
        }
        payload["record_hash"] = hashlib.sha256(canonical(payload)).hexdigest()
        stream.seek(0, os.SEEK_END)
        stream.write(canonical(payload).decode("utf-8") + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger")
    parser.add_argument("--record", required=True, help="JSON object")
    args = parser.parse_args()
    record = json.loads(args.record)
    if not isinstance(record, dict):
        raise SystemExit("--record must decode to a JSON object")
    print(json.dumps(append_record(Path(args.ledger), record), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
