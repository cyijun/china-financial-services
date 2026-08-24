#!/usr/bin/env python3
"""Assert that JSON emitted by a host CLI mentions every expected plugin id."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable


def strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", nargs="+")
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    observed = set(strings(payload))
    # Claude can report ``name@marketplace`` while Codex may expose the plain
    # name. Accept either host representation without fuzzy prefix matching.
    normalized = observed | {value.split("@", 1)[0] for value in observed}
    missing = [name for name in args.expected if name not in normalized]
    if missing:
        print(f"missing plugin ids: {missing}", file=sys.stderr)
        return 1
    print(f"plugin_inventory=ok expected={len(args.expected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
