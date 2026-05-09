#!/usr/bin/env python3
"""
Re-sync hooks across all plugins from the source of truth.

Only one plugin should define hooks/ (source of truth). All other plugins
receive a byte-identical copy. Run this after editing hooks to propagate.

Usage: python3 scripts/sync-hooks.py
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"

# 1. Find all plugins with hooks/
hooks_dirs: list[Path] = []
for plugin_dir in sorted(PLUGINS.glob("*-plugins/*")):
    if (plugin_dir / "hooks").is_dir():
        hooks_dirs.append(plugin_dir)

if len(hooks_dirs) == 0:
    print("ERROR: no hooks/ found in any plugin", file=sys.stderr)
    sys.exit(1)

if len(hooks_dirs) > 1:
    print(
        "ERROR: multiple plugins define hooks/ (only one source of truth allowed):",
        file=sys.stderr,
    )
    for d in hooks_dirs:
        print(f"  - {d.relative_to(ROOT)}/hooks/", file=sys.stderr)
    sys.exit(1)

src_plugin = hooks_dirs[0]
src_hooks = src_plugin / "hooks"
print(f"source of truth: {src_plugin.relative_to(ROOT)}/hooks/")

# 2. Sync to every other plugin
synced = 0
skipped = 0
for plugin_dir in sorted(PLUGINS.glob("*-plugins/*")):
    if plugin_dir == src_plugin:
        continue

    target_hooks = plugin_dir / "hooks"

    # Skip if already identical
    if target_hooks.is_dir():
        import filecmp

        cmp = filecmp.dircmp(src_hooks, target_hooks)
        if not (cmp.diff_files or cmp.left_only or cmp.right_only):
            skipped += 1
            continue
        shutil.rmtree(target_hooks)

    shutil.copytree(src_hooks, target_hooks)
    synced += 1
    print(f"  synced -> {plugin_dir.relative_to(ROOT)}/hooks/")

print(f"\nsynced {synced} plugin(s), skipped {skipped} already up-to-date")
