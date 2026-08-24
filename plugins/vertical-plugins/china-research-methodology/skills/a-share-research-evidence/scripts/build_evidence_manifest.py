#!/usr/bin/env python3
"""Validate, optionally retrieve, and hash an A-share original-document ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence


REQUIRED = {"evidence_id", "source_type", "source_url", "document_date", "disclosed_at", "as_of", "locator", "claim"}
PRIMARY_TYPES = {"exchange_filing", "cninfo_filing", "company_filing", "regulator_document", "court_document"}


def parse_time(value: Any, field: str) -> datetime:
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{field} must be ISO-8601 with timezone") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def safe_filename(evidence_id: str, url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ".bin"
    slug = re.sub(r"[^a-zA-Z0-9._-]", "_", evidence_id)[:100]
    return f"{slug}{suffix}"


def retrieve(url: str, destination: Path, *, max_bytes: int = 25_000_000, timeout: int = 30) -> Dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("original-document retrieval requires an https URL")
    request = urllib.request.Request(url, headers={"User-Agent": "china-financial-services-evidence/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        payload = response.read(max_bytes + 1)
        final_url = response.geturl()
    if len(payload) > max_bytes:
        raise ValueError(f"document exceeds max_bytes={max_bytes}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {
        "local_path": str(destination),
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "content_bytes": len(payload),
        "content_type": content_type,
        "final_url": final_url,
    }


def validate_record(raw: Mapping[str, Any], download_dir: Optional[Path] = None) -> Dict[str, Any]:
    missing = REQUIRED - set(raw)
    if missing:
        raise ValueError(f"missing evidence fields: {sorted(missing)}")
    row = dict(raw)
    disclosed = parse_time(row["disclosed_at"], "disclosed_at")
    as_of = parse_time(row["as_of"], "as_of")
    row["evidence_status"] = "usable" if disclosed <= as_of else "forbidden_future"
    row["source_tier"] = "primary" if row["source_type"] in PRIMARY_TYPES else "secondary_or_convenience"
    row["disclosed_at_utc"] = disclosed.isoformat()
    row["as_of_utc"] = as_of.isoformat()
    local_path = row.get("local_path")
    if local_path:
        path = Path(str(local_path)).expanduser().resolve()
        payload = path.read_bytes()
        row.update({"local_path": str(path), "content_sha256": hashlib.sha256(payload).hexdigest(), "content_bytes": len(payload)})
    elif download_dir is not None:
        destination = download_dir / safe_filename(str(row["evidence_id"]), str(row["source_url"]))
        row.update(retrieve(str(row["source_url"]), destination))
    else:
        row["content_sha256"] = None
        row["retrieval_status"] = "not_retrieved"
    if not str(row["locator"]).strip():
        raise ValueError("locator must identify a page, section, table, paragraph, or timestamp")
    return row


def build(records: Sequence[Mapping[str, Any]], download_dir: Optional[Path] = None) -> Dict[str, Any]:
    ids: set[str] = set()
    rows = []
    for raw in records:
        checked = validate_record(raw, download_dir)
        evidence_id = str(checked["evidence_id"])
        if evidence_id in ids:
            raise ValueError(f"duplicate evidence_id: {evidence_id}")
        ids.add(evidence_id)
        rows.append(checked)
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    counts = {status: sum(row["evidence_status"] == status for row in rows) for status in ("usable", "forbidden_future")}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "counts": counts,
        "status": "blocked" if counts["forbidden_future"] else ("ready" if rows else "partial"),
        "evidence": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON list of evidence records")
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SystemExit("input must be a JSON list of objects")
    report = build(value, args.download_dir)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
