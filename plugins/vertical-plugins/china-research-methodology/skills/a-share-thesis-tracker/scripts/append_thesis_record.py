#!/usr/bin/env python3
"""Append one canonical JSON record to a tamper-evident JSONL hash chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_chain(path: Path) -> Optional[str]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    expected_previous: Optional[str] = None
    with path.open("r", encoding="utf-8") as stream:
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


def append_record(path: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    previous = verify_chain(path)
    payload: Dict[str, Any] = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "previous_hash": previous,
        "record": record,
    }
    payload["record_hash"] = hashlib.sha256(canonical(payload)).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, canonical(payload) + b"\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
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
