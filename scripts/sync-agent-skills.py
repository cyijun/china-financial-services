#!/usr/bin/env python3
"""
Re-sync each agent plugin's bundled skills from the vertical-plugin source.

Agent plugins under plugins/agent-plugins/<slug>/skills/<name>/ are vendored
copies of plugins/vertical-plugins/*/skills/<name>/. The vertical copy is the
source of truth; run this after editing a skill there to propagate the change
into every agent that bundles it.

Usage: python3 scripts/sync-agent-skills.py
       python3 scripts/sync-agent-skills.py --check
"""
import hashlib
import shutil
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "plugins" / "agent-plugins"
VERTICALS = ROOT / "plugins" / "vertical-plugins"
CHECK = "--check" in sys.argv[1:]
unknown = [arg for arg in sys.argv[1:] if arg != "--check"]
if unknown:
    print(f"ERROR: unknown arguments: {unknown}", file=sys.stderr)
    sys.exit(2)


def tree_signature(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for item in sorted(path.rglob("*")):
        if item.is_file() and item.name != ".DS_Store" and "__pycache__" not in item.parts and item.suffix != ".pyc":
            result[str(item.relative_to(path))] = hashlib.sha256(item.read_bytes()).hexdigest()
    return result

# index every skill name -> source dir in verticals
src_by_name: dict[str, Path] = {}
for sk in VERTICALS.glob("*/skills/*"):
    if sk.is_dir():
        if sk.name in src_by_name:
            print(f"ERROR: duplicate vertical skill name '{sk.name}': {src_by_name[sk.name]} and {sk}", file=sys.stderr)
            sys.exit(1)
        src_by_name[sk.name] = sk

synced = 0
wrappers_synced = 0
agent_specific: list[str] = []
drifted: list[str] = []
for agent_root in sorted(AGENTS.iterdir()):
    if not agent_root.is_dir():
        continue
    skills_dir = agent_root / "skills"
    existing = {path.name for path in skills_dir.iterdir() if path.is_dir()} if skills_dir.is_dir() else set()
    referenced: set[str] = set()
    for prompt in sorted((agent_root / "agents").glob("*.md")):
        referenced.update(re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", prompt.read_text()))
    wanted = existing | {name for name in referenced if name in src_by_name}
    for name in sorted(wanted):
        src = src_by_name.get(name)
        bundled = skills_dir / name
        if not src:
            agent_specific.append(str(bundled.relative_to(ROOT)))
            continue
        if tree_signature(src) == tree_signature(bundled):
            continue
        if CHECK:
            drifted.append(str(bundled.relative_to(ROOT)))
            continue
        if bundled.exists():
            shutil.rmtree(bundled)
        shutil.copytree(src, bundled)
        synced += 1

    # Kimi sessionStart wrapper mirrors the Claude agent body. Keep only
    # skill-compatible name/description frontmatter; the body is identical.
    prompts = sorted((agent_root / "agents").glob("*.md"))
    if len(prompts) == 1:
        prompt_text = prompts[0].read_text(encoding="utf-8")
        _, prompt_frontmatter, prompt_body = prompt_text.split("---", 2)
        name = re.search(r"^name:\s*(.+)$", prompt_frontmatter, re.MULTILINE)
        description = re.search(r"^description:\s*(.+)$", prompt_frontmatter, re.MULTILINE)
        if not name or not description:
            print(f"ERROR: missing name/description in {prompts[0]}", file=sys.stderr)
            sys.exit(1)
        wrapper = skills_dir / name.group(1).strip() / "SKILL.md"
        if wrapper.is_file():
            expected = f"---\nname: {name.group(1).strip()}\ndescription: {description.group(1).strip()}\n---{prompt_body}"
            if wrapper.read_text(encoding="utf-8") != expected:
                if CHECK:
                    drifted.append(str(wrapper.relative_to(ROOT)))
                else:
                    wrapper.write_text(expected, encoding="utf-8")
                    wrappers_synced += 1

if CHECK:
    if drifted:
        print("ERROR: bundled skill drift:", file=sys.stderr)
        for path in sorted(set(drifted)):
            print(f"  - {path}", file=sys.stderr)
        sys.exit(1)
    print("bundled skills and sessionStart wrappers are in sync")
else:
    print(f"synced {synced} bundled skill dir(s) from vertical-plugins/")
    print(f"synced {wrappers_synced} agent sessionStart wrapper(s)")
if agent_specific:
    print("WARN: no vertical source found for:", file=sys.stderr)
    for m in agent_specific:
        print(f"  - {m}", file=sys.stderr)
