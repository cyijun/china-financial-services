#!/usr/bin/env python3
"""
Re-sync hooks across all plugins from the source of truth.

The source of truth is hard-coded below. All other plugins receive a
byte-identical copy. Run this after editing hooks to propagate.

Usage: python3 scripts/sync-hooks.py
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"

# Source of truth — edit here, then run this script.
SRC_HOOKS = PLUGINS / "vertical-plugins" / "financial-analysis" / "hooks"


def tree_equal(left: Path, right: Path) -> bool:
    """Compare complete directory trees, not only top-level files."""
    import filecmp

    comparison = filecmp.dircmp(left, right)
    if comparison.diff_files or comparison.funny_files or comparison.left_only or comparison.right_only:
        return False
    return all(tree_equal(left / name, right / name) for name in comparison.common_dirs)

if not SRC_HOOKS.is_dir():
    print(f"ERROR: source of truth not found: {SRC_HOOKS.relative_to(ROOT)}", file=sys.stderr)
    sys.exit(1)

print(f"source of truth: {SRC_HOOKS.relative_to(ROOT)}")

# Sync to every other plugin
synced = 0
skipped = 0
for plugin_dir in sorted(PLUGINS.glob("*-plugins/*")):
    if not plugin_dir.is_dir():
        continue
    if plugin_dir == SRC_HOOKS.parent:
        continue

    target_hooks = plugin_dir / "hooks"

    # Skip if already identical
    if target_hooks.is_dir():
        if tree_equal(SRC_HOOKS, target_hooks):
            skipped += 1
            continue
        shutil.rmtree(target_hooks)

    shutil.copytree(SRC_HOOKS, target_hooks)
    synced += 1
    print(f"  synced -> {plugin_dir.relative_to(ROOT)}/hooks/")

print(f"\nsynced {synced} plugin(s), skipped {skipped} already up-to-date")
