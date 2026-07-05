#!/usr/bin/env python3
"""
Lint all plugin + managed-agent manifests and verify cross-file references.

Checks:
  1. Every *.yaml under managed-agents/ parses.
  2. Every plugin.json / marketplace.json / steering-examples.json parses.
  3. Every <vertical>/agents/*.md has valid YAML frontmatter with name + description.
  4. Every system.file, skills[].path, callable_agents[].manifest in agent.yaml
     and subagent yamls resolves to an existing file/dir.
  5. Every managed-agents/<slug>/ has agent.yaml, README.md, steering-examples.json.

Exit 0 if clean, 1 otherwise. Requires: pyyaml.
"""
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: requires pyyaml (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"
MANAGED = ROOT / "managed-agent-cookbooks"
errors: list[str] = []
checked = 0


def err(msg: str) -> None:
    errors.append(msg)


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


# --- 1. YAML parse ----------------------------------------------------------
for yml in sorted(MANAGED.rglob("*.yaml")):
    checked += 1
    try:
        with open(yml) as f:
            yaml.safe_load(f)
    except yaml.YAMLError as e:
        err(f"YAML parse: {rel(yml)}: {e}")

# --- 2. JSON parse ----------------------------------------------------------
json_globs = [
    "marketplace.json",
    ".claude-plugin/marketplace.json",
    "plugins/**/.claude-plugin/plugin.json",
    "managed-agent-cookbooks/*/steering-examples.json",
]
for pat in json_globs:
    for jf in sorted(ROOT.glob(pat)):
        checked += 1
        try:
            json.loads(jf.read_text())
        except json.JSONDecodeError as e:
            err(f"JSON parse: {rel(jf)}: {e}")

# --- 3. agent.md frontmatter -----------------------------------------------
for md in sorted(PLUGINS.glob("agent-plugins/*/agents/*.md")):
    checked += 1
    text = md.read_text()
    if not text.startswith("---"):
        err(f"frontmatter: {rel(md)}: missing leading ---")
        continue
    try:
        _, fm, _ = text.split("---", 2)
        meta = yaml.safe_load(fm)
        for k in ("name", "description"):
            if k not in meta:
                err(f"frontmatter: {rel(md)}: missing '{k}'")
    except (ValueError, yaml.YAMLError) as e:
        err(f"frontmatter: {rel(md)}: {e}")


# --- 4. reference resolution -----------------------------------------------
def check_refs(yml: Path) -> None:
    try:
        data = yaml.safe_load(yml.read_text()) or {}
    except yaml.YAMLError:
        return  # already reported above
    base = yml.parent

    sys_spec = data.get("system")
    if isinstance(sys_spec, dict) and "file" in sys_spec:
        p = (base / sys_spec["file"]).resolve()
        if not p.is_file():
            err(f"ref: {rel(yml)}: system.file -> {sys_spec['file']} (not found)")

    for s in data.get("skills") or []:
        if isinstance(s, dict) and "path" in s:
            p = (base / s["path"]).resolve()
            if not p.exists():
                err(f"ref: {rel(yml)}: skills.path -> {s['path']} (not found)")
        if isinstance(s, dict) and "from_plugin" in s:
            p = (base / s["from_plugin"]).resolve()
            if not (p / "skills").is_dir():
                err(f"ref: {rel(yml)}: skills.from_plugin -> {s['from_plugin']} (no skills/ dir)")

    for c in data.get("callable_agents") or []:
        if isinstance(c, dict) and "manifest" in c:
            p = (base / c["manifest"]).resolve()
            if not p.is_file():
                err(f"ref: {rel(yml)}: callable_agents.manifest -> {c['manifest']} (not found)")


for yml in sorted(MANAGED.rglob("*.yaml")):
    check_refs(yml)

# --- 4b. agent-plugin bundled skills match vertical source -----------------
import filecmp  # noqa: E402
import re  # noqa: E402

# --- 4c. kimi.plugin.json validation ----------------------------------------
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
VALID_CAPS = {"Read", "Write", "Edit", "Bash", "WebSearch", "WebFetch", "Agent", "AskUser", "Think"}

for km in sorted(ROOT.glob("plugins/**/.kimi-plugin/plugin.json")):
    checked += 1
    try:
        data = json.loads(km.read_text())
    except json.JSONDecodeError as e:
        err(f"JSON parse: {rel(km)}: {e}")
        continue

    plugin_root = km.parent.parent
    name = data.get("name")
    if not name:
        err(f"kimi-manifest: {rel(km)}: missing 'name'")
    elif not NAME_RE.match(name):
        err(f"kimi-manifest: {rel(km)}: name '{name}' does not match allowed pattern")

    skills = data.get("skills")
    if not skills:
        err(f"kimi-manifest: {rel(km)}: missing 'skills'")
    elif not isinstance(skills, str) or not skills.startswith("./"):
        err(f"kimi-manifest: {rel(km)}: skills path must start with './'")
    else:
        p = (plugin_root / skills).resolve()
        if plugin_root not in p.parents and p != plugin_root:
            err(f"kimi-manifest: {rel(km)}: skills -> {skills} (outside plugin root)")
        elif not p.is_dir():
            err(f"kimi-manifest: {rel(km)}: skills -> {skills} (not found)")

    session_skill = (data.get("sessionStart") or {}).get("skill")
    if session_skill:
        if isinstance(skills, str):
            p = (plugin_root / skills / session_skill / "SKILL.md").resolve()
            if plugin_root not in p.parents and p != plugin_root:
                err(f"kimi-manifest: {rel(km)}: sessionStart.skill '{session_skill}' (outside plugin root)")
            elif not p.is_file():
                err(f"kimi-manifest: {rel(km)}: sessionStart.skill '{session_skill}' not found")

    caps = (data.get("interface") or {}).get("capabilities")
    if caps:
        bad = [c for c in caps if c not in VALID_CAPS]
        if bad:
            err(f"kimi-manifest: {rel(km)}: unknown capabilities {bad}")

src_by_name = {p.name: p for p in PLUGINS.glob("vertical-plugins/*/skills/*") if p.is_dir()}
for bundled in sorted(PLUGINS.glob("agent-plugins/*/skills/*")):
    if not bundled.is_dir():
        continue
    src = src_by_name.get(bundled.name)
    if not src:
        # Agent-specific skills (no vertical-plugins source) are allowed
        print(f"  ⚠ bundled-skill: {rel(bundled)}: no vertical-plugins source named '{bundled.name}' (agent-specific, ok)", file=sys.stderr)
        continue
    cmp = filecmp.dircmp(src, bundled)
    if cmp.diff_files or cmp.left_only or cmp.right_only:
        err(
            f"bundled-skill: {rel(bundled)}: drifted from {rel(src)} "
            f"(run scripts/sync-agent-skills.py)"
        )

# --- 4b2. agent.md skill references exist in the agent's own bundle --------
for md in sorted(PLUGINS.glob("agent-plugins/*/agents/*.md")):
    slug = md.parents[1].name
    sk_dir = PLUGINS / "agent-plugins" / slug / "skills"
    bundle = {p.name for p in sk_dir.iterdir() if p.is_dir()} if sk_dir.is_dir() else set()
    for ref in set(re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", md.read_text())):
        if ref in src_by_name and ref not in bundle:
            err(
                f"agent-prose: {rel(md)}: references `{ref}` but "
                f"plugins/agent-plugins/{slug}/skills/{ref}/ is not bundled"
            )

# --- 4d. marketplace source paths resolve ----------------------------------
mp = ROOT / ".claude-plugin" / "marketplace.json"
for p in json.loads(mp.read_text()).get("plugins", []):
    src = (ROOT / p["source"]).resolve()
    if not (src / ".claude-plugin" / "plugin.json").is_file():
        err(f"marketplace: {p['name']} source -> {p['source']} (no plugin.json)")

# --- 4e. kimi marketplace source paths resolve -----------------------------
KIMI_MP = ROOT / "marketplace.json"
KIMI_RELEASE_BASE = "https://github.com/cyijun/china-financial-services/releases/latest/download/"
if KIMI_MP.is_file():
    checked += 1
    try:
        kimi_data = json.loads(KIMI_MP.read_text())
    except json.JSONDecodeError as e:
        err(f"JSON parse: {rel(KIMI_MP)}: {e}")
    else:
        for p in kimi_data.get("plugins") or []:
            source = p.get("source", "")
            if not source.startswith(KIMI_RELEASE_BASE) or not source.endswith(".zip"):
                err(
                    f"kimi-marketplace: {p.get('id')}: source must be a "
                    f"{KIMI_RELEASE_BASE}<plugin>.zip URL"
                )
                continue
            plugin_id = p.get("id", "")
            expected_zip = f"{plugin_id}.zip"
            if not source.endswith(expected_zip):
                err(f"kimi-marketplace: {plugin_id}: source filename must match {expected_zip}")
                continue
            local_plugin = None
            for plugin_dir in PLUGINS.glob("*/*"):
                if plugin_dir.is_dir() and plugin_dir.name == plugin_id:
                    if (plugin_dir / ".kimi-plugin" / "plugin.json").is_file():
                        local_plugin = plugin_dir
                        break
            if local_plugin is None:
                err(f"kimi-marketplace: {plugin_id}: no local plugin directory with .kimi-plugin/plugin.json found")

# --- 5. required files per managed-agent -----------------------------------
for d in sorted(MANAGED.iterdir()):
    if not d.is_dir():
        continue
    for req in ("agent.yaml", "README.md", "steering-examples.json"):
        if not (d / req).is_file():
            err(f"missing: {rel(d)}/{req}")

# --- report ----------------------------------------------------------------
if errors:
    print(f"FAIL — {len(errors)} issue(s) across {checked} file(s):\n", file=sys.stderr)
    for e in errors:
        print(f"  ✗ {e}", file=sys.stderr)
    sys.exit(1)
print(f"OK — {checked} file(s) checked, 0 issues.")
