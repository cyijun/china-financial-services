#!/usr/bin/env python3
"""Fail-fast environment preflight without exposing credential values."""

from __future__ import annotations

import argparse
import importlib
import os
import sys


RUNTIME_MODULES = {
    "akshare": "akshare",
    "openpyxl": "openpyxl",
    "pandas": "pandas",
    "python-pptx": "pptx",
    "PyYAML": "yaml",
    "tushare": "tushare",
}
TUSHARE_LIVE_MODULES = {"pandas": "pandas", "tushare": "tushare"}
AKSHARE_LIVE_MODULES = {"akshare": "akshare", "pandas": "pandas"}


def run(mode: str) -> list[str]:
    issues: list[str] = []
    if sys.version_info < (3, 11):
        issues.append(f"python={sys.version.split()[0]} requires >=3.11")
    modules = {
        "runtime": RUNTIME_MODULES,
        "live": TUSHARE_LIVE_MODULES,
        "tushare-live": TUSHARE_LIVE_MODULES,
        "akshare-live": AKSHARE_LIVE_MODULES,
    }.get(mode, {})
    for package, module in modules.items():
        try:
            importlib.import_module(module)
        except ImportError:
            issues.append(f"python package missing: {package}")
    if mode in {"live", "tushare-live"} and not os.environ.get("TUSHARE_TOKEN"):
        issues.append("TUSHARE_TOKEN environment variable is not configured")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "runtime", "live", "tushare-live", "akshare-live"), default="offline")
    args = parser.parse_args()
    issues = run(args.mode)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    print(f"preflight={args.mode} ok; credentials_checked={'yes' if args.mode in {'live', 'tushare-live'} else 'not_required'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
