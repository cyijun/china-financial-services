#!/usr/bin/env python3
"""分页导出Tushare公募基金/ETF原始数据与可复核元信息。

严格PIT基金池和净值研究应改用china-market-data路由，以保留摘牌基金和公告可得时点。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import tushare as ts


def _client() -> Any:
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required; global token caches are not used")
    return ts.pro_api(token)


def _records(frame: Any) -> List[Dict[str, Any]]:
    if frame is None or not hasattr(frame, "to_dict"):
        raise TypeError(f"unsupported Tushare response: {type(frame).__name__}")
    return [dict(row) for row in frame.to_dict(orient="records")]


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def fetch_all(client: Any, api_name: str, params: Mapping[str, Any], *, page_size: int, max_pages: int) -> Tuple[List[Dict[str, Any]], List[int]]:
    method = getattr(client, api_name)
    rows: List[Dict[str, Any]] = []
    counts: List[int] = []
    seen: set[str] = set()
    for page in range(max_pages):
        batch = _records(method(**dict(params), limit=page_size, offset=page * page_size))
        fingerprint = _digest(batch)
        if batch and fingerprint in seen:
            raise RuntimeError(f"{api_name} repeated a page; completeness is not established")
        seen.add(fingerprint)
        rows.extend(batch)
        counts.append(len(batch))
        if len(batch) < page_size:
            return rows, counts
    raise RuntimeError(f"{api_name} exceeded max_pages={max_pages}; narrow or segment the request")


def _write(output: Path, api_name: str, params: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], page_counts: Sequence[int]) -> None:
    payload = {
        "dataset": api_name,
        "records": list(rows),
        "metadata": {
            "provider": "tushare",
            "interface": api_name,
            "request_params": dict(params),
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "row_count": len(rows),
            "page_row_counts": list(page_counts),
            "pagination_complete": True,
            "response_sha256": _digest(rows),
            "pit_eligible": False,
            "warning": "Raw current-query example; use china-market-data for L/D/I lifecycle and ann_date availability filtering.",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=("fund-list", "fund-daily", "fund-nav"))
    parser.add_argument("--ts-code")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--status", choices=("L", "D", "I"), default="L")
    parser.add_argument("--market", choices=("E", "O"), default="E")
    parser.add_argument("--page-size", type=int, default=5000)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.page_size < 1 or args.max_pages < 1:
        parser.error("page-size and max-pages must be positive")

    if args.dataset == "fund-list":
        api_name = "fund_basic"
        params: Dict[str, Any] = {"market": args.market, "status": args.status, "fields": "ts_code,name,market,status,fund_type,found_date,list_date,delist_date"}
    elif args.dataset == "fund-daily":
        if not args.ts_code or not args.start_date or not args.end_date:
            parser.error("fund-daily requires --ts-code, --start-date and --end-date")
        api_name = "fund_daily"
        params = {"ts_code": args.ts_code, "start_date": args.start_date, "end_date": args.end_date, "fields": "ts_code,trade_date,open,high,low,close,pre_close,vol,amount"}
    else:
        if not args.ts_code or not args.start_date or not args.end_date:
            parser.error("fund-nav requires --ts-code, --start-date and --end-date")
        api_name = "fund_nav"
        params = {"ts_code": args.ts_code, "start_date": args.start_date, "end_date": args.end_date, "fields": "ts_code,ann_date,nav_date,unit_nav,accum_nav,adj_nav"}

    rows, counts = fetch_all(_client(), api_name, params, page_size=args.page_size, max_pages=args.max_pages)
    _write(args.output, api_name, params, rows, counts)
    print(json.dumps({"output": str(args.output), "interface": api_name, "row_count": len(rows), "response_sha256": _digest(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
