#!/usr/bin/env python3
"""Repository lint for plugin structure, mirrored skills and behavior contracts."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"
SOURCE_PLUGIN_NAMES = (
    "china-research-methodology",
    "financial-analysis",
    "equity-research",
)
BUNDLE_PLUGIN_NAMES = (
    "china-market-researcher",
    "china-model-builder",
)
PLUGIN_NAMES = (*SOURCE_PLUGIN_NAMES, *BUNDLE_PLUGIN_NAMES)
errors: list[str] = []
checked = 0


try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


def err(message: str) -> None:
    errors.append(message)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load_yaml_text(text: str, label: str) -> Any:
    if yaml is not None:
        try:
            return yaml.safe_load(text)
        except Exception as error:
            raise ValueError(f"{label}: {error}") from error
    try:
        result = subprocess.run(
            ["ruby", "-ryaml", "-rjson", "-e", "print JSON.generate(YAML.safe_load(STDIN.read, permitted_classes: [], aliases: false))"],
            input=text,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise ValueError(f"{label}: YAML parser unavailable or parse failed: {detail.strip()}") from error


def load_yaml(path: Path) -> Any:
    return load_yaml_text(path.read_text(encoding="utf-8"), rel(path))


def frontmatter(path: Path) -> tuple[Dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError("missing leading ---")
    try:
        _, raw, body = text.split("---", 2)
    except ValueError as error:
        raise ValueError("unterminated frontmatter") from error
    parsed = load_yaml_text(raw, rel(path)) or {}
    if not isinstance(parsed, dict):
        raise ValueError("frontmatter must be a mapping")
    return parsed, body.strip()


def json_file(path: Path) -> Dict[str, Any]:
    global checked
    checked += 1
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        err(f"JSON parse: {rel(path)}: {error}")
        return {}
    if not isinstance(value, dict):
        err(f"JSON shape: {rel(path)}: root must be object")
        return {}
    return value


def tree_signature(path: Path) -> Dict[str, str]:
    signature: Dict[str, str] = {}
    for item in sorted(path.rglob("*")):
        if not item.is_file() or item.name == ".DS_Store" or "__pycache__" in item.parts or item.suffix == ".pyc":
            continue
        signature[str(item.relative_to(path))] = hashlib.sha256(item.read_bytes()).hexdigest()
    return signature


# Host marketplaces. All three catalogs must expose the same ordered plugin
# inventory while retaining their host-specific schemas.
claude_marketplace = json_file(ROOT / ".claude-plugin" / "marketplace.json")
codex_marketplace = json_file(ROOT / ".agents" / "plugins" / "marketplace.json")
kimi_marketplace = json_file(ROOT / "kimi-marketplace.json")

if claude_marketplace.get("name") != "china-financial-services":
    err("claude-marketplace: invalid name")
if not claude_marketplace.get("description"):
    err("claude-marketplace: missing description")
if codex_marketplace.get("name") != "china-financial-services":
    err("codex-marketplace: invalid name")
if (codex_marketplace.get("interface") or {}).get("displayName") != "China Financial Services":
    err("codex-marketplace: invalid interface.displayName")
if kimi_marketplace.get("version") != "2":
    err("kimi-marketplace: version must be '2'")

claude_entries = claude_marketplace.get("plugins") or []
codex_entries = codex_marketplace.get("plugins") or []
kimi_entries = kimi_marketplace.get("plugins") or []
claude_names = [entry.get("name") for entry in claude_entries]
codex_names = [entry.get("name") for entry in codex_entries]
kimi_names = [entry.get("id") for entry in kimi_entries]
expected_names = list(PLUGIN_NAMES)
for host, names in (
    ("claude", claude_names),
    ("codex", codex_names),
    ("kimi", kimi_names),
):
    if names != expected_names:
        err(f"{host}-marketplace: plugin order/inventory {names!r} != {expected_names!r}")

for entry in claude_entries:
    name = entry.get("name")
    source_value = entry.get("source")
    if not isinstance(source_value, str) or source_value != f"./plugins/{name}":
        err(f"claude-marketplace: {name} has invalid source {source_value!r}")
    source = (ROOT / str(source_value)).resolve()
    if source.parent != PLUGINS.resolve() or source.name != name:
        err(f"claude-marketplace: {name} source escapes flat plugins directory")
        continue
    if not (source / ".claude-plugin" / "plugin.json").is_file():
        err(f"claude-marketplace: {name} source has no Claude manifest")

for entry in codex_entries:
    name = entry.get("name")
    source = entry.get("source") or {}
    if source != {"source": "local", "path": f"./plugins/{name}"}:
        err(f"codex-marketplace: {name} has invalid local source {source!r}")
    policy = entry.get("policy") or {}
    if policy.get("installation") not in {"NOT_AVAILABLE", "AVAILABLE", "INSTALLED_BY_DEFAULT"}:
        err(f"codex-marketplace: {name} has invalid installation policy")
    if policy.get("authentication") not in {"ON_INSTALL", "ON_USE"}:
        err(f"codex-marketplace: {name} has invalid authentication policy")
    if not entry.get("category"):
        err(f"codex-marketplace: {name} missing category")

for entry in kimi_entries:
    name = entry.get("id")
    if entry.get("source") != f"./plugins/{name}":
        err(f"kimi-marketplace: {name} has invalid local source {entry.get('source')!r}")
    if not entry.get("displayName") or not entry.get("description"):
        err(f"kimi-marketplace: {name} missing display metadata")

actual_plugin_dirs = sorted(path.name for path in PLUGINS.iterdir() if path.is_dir())
if actual_plugin_dirs != sorted(PLUGIN_NAMES):
    err(f"plugins: flat directory inventory {actual_plugin_dirs!r} != {sorted(PLUGIN_NAMES)!r}")
for plugin_name in PLUGIN_NAMES:
    plugin_root = PLUGINS / plugin_name
    for host_dir in (".claude-plugin", ".codex-plugin", ".kimi-plugin"):
        if not (plugin_root / host_dir / "plugin.json").is_file():
            err(f"plugins: {plugin_name} missing {host_dir}/plugin.json")

claude_manifests: Dict[Path, Dict[str, Any]] = {}
for path in sorted(ROOT.glob("plugins/*/.claude-plugin/plugin.json")):
    manifest = json_file(path)
    plugin_root = path.parent.parent.resolve()
    claude_manifests[plugin_root] = manifest
    if manifest.get("name") != plugin_root.name:
        err(f"claude-manifest: {rel(path)} name differs from plugin directory")
    for dependency in manifest.get("dependencies") or []:
        name = dependency if isinstance(dependency, str) else dependency.get("name") if isinstance(dependency, dict) else None
        if name not in PLUGIN_NAMES:
            err(f"claude-dependency: {rel(path)} -> {dependency} is not in marketplace")

KIMI_INTERFACE_FIELDS = {"displayName", "shortDescription", "longDescription", "developerName", "websiteURL"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
for path in sorted(ROOT.glob("plugins/*/.kimi-plugin/plugin.json")):
    manifest = json_file(path)
    name = manifest.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        err(f"kimi-manifest: {rel(path)} invalid name {name!r}")
    plugin_root = path.parent.parent
    if name != plugin_root.name:
        err(f"kimi-manifest: {rel(path)} name differs from plugin directory")
    skills = manifest.get("skills")
    if not isinstance(skills, str) or not skills.startswith("./") or not (plugin_root / skills).resolve().is_dir():
        err(f"kimi-manifest: {rel(path)} invalid skills path {skills!r}")
    session_skill = (manifest.get("sessionStart") or {}).get("skill")
    if session_skill and not (plugin_root / str(skills) / session_skill / "SKILL.md").is_file():
        err(f"kimi-manifest: {rel(path)} missing sessionStart skill {session_skill}")
    bad_interface = set((manifest.get("interface") or {}).keys()) - KIMI_INTERFACE_FIELDS
    if bad_interface:
        err(f"kimi-manifest: {rel(path)} unsupported interface fields {sorted(bad_interface)}")
    claude_manifest = claude_manifests.get(plugin_root.resolve())
    if claude_manifest and (manifest.get("name"), manifest.get("version")) != (claude_manifest.get("name"), claude_manifest.get("version")):
        err(f"manifest-parity: {rel(path)} name/version differs from Claude manifest")
    if manifest.get("license") != "Apache-2.0":
        err(f"license: {rel(path)} must declare Apache-2.0")

CODEX_INTERFACE_REQUIRED = {
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
    "capabilities",
    "defaultPrompt",
}
codex_roots: set[Path] = set()
for path in sorted(ROOT.glob("plugins/*/.codex-plugin/plugin.json")):
    manifest = json_file(path)
    plugin_root = path.parent.parent.resolve()
    codex_roots.add(plugin_root)
    name = manifest.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name != plugin_root.name:
        err(f"codex-manifest: {rel(path)} invalid name {name!r}")
    skills = manifest.get("skills")
    if not isinstance(skills, str) or not skills.startswith("./") or not (plugin_root / skills).resolve().is_dir():
        err(f"codex-manifest: {rel(path)} invalid skills path {skills!r}")
    interface = manifest.get("interface") or {}
    missing_interface = CODEX_INTERFACE_REQUIRED - set(interface)
    if missing_interface:
        err(f"codex-manifest: {rel(path)} missing interface fields {sorted(missing_interface)}")
    if not isinstance(interface.get("capabilities"), list):
        err(f"codex-manifest: {rel(path)} capabilities must be a list")
    if manifest.get("license") != "Apache-2.0":
        err(f"license: {rel(path)} must declare Apache-2.0")
    claude_manifest = claude_manifests.get(plugin_root)
    if claude_manifest and (manifest.get("name"), manifest.get("version")) != (claude_manifest.get("name"), claude_manifest.get("version")):
        err(f"manifest-parity: {rel(path)} name/version differs from Claude manifest")

for plugin_root in claude_manifests:
    if plugin_root not in codex_roots:
        err(f"codex-manifest: {rel(plugin_root)} has no .codex-plugin/plugin.json")


# Skill contracts and local links.
skill_files = sorted(PLUGINS.glob("*/skills/*/SKILL.md"))
skill_dirs: Dict[str, list[Path]] = {}
for path in skill_files:
    checked += 1
    try:
        meta, body = frontmatter(path)
    except ValueError as error:
        err(f"skill-frontmatter: {rel(path)}: {error}")
        continue
    if meta.get("name") != path.parent.name:
        err(f"skill-frontmatter: {rel(path)} name {meta.get('name')!r} != directory")
    if not meta.get("description"):
        err(f"skill-frontmatter: {rel(path)} missing description")
    unsupported_legacy = {"author", "version", "credentials", "requirements"} & set(meta)
    if unsupported_legacy:
        err(f"skill-frontmatter: {rel(path)} unsupported legacy keys {sorted(unsupported_legacy)}")
    skill_dirs.setdefault(path.parent.name, []).append(path.parent)
    for raw_target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", body):
        target = raw_target.strip().strip("<>").split(" ", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        resolved = (path.parent / target.split("#", 1)[0]).resolve()
        if not resolved.exists():
            err(f"skill-link: {rel(path)} -> {target} not found")


# Agent frontmatter, skill closure and exact Kimi wrapper parity.
for plugin_name in BUNDLE_PLUGIN_NAMES:
  for path in sorted((PLUGINS / plugin_name / "agents").glob("*.md")):
    checked += 1
    try:
        meta, body = frontmatter(path)
    except ValueError as error:
        err(f"agent-frontmatter: {rel(path)}: {error}")
        continue
    slug = path.parents[1].name
    description = str(meta.get("description", ""))
    if "用于" not in description and "use when" not in description.lower():
        err(f"agent-frontmatter: {rel(path)} description lacks an explicit use-when trigger")
    bundle = {item.name for item in (path.parents[1] / "skills").iterdir() if item.is_dir()}
    section = re.search(r"## Skills this agent uses\s*(.*?)(?:\n## |\Z)", body, re.DOTALL)
    refs = set(re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", section.group(1) if section else ""))
    for ref in sorted(refs - bundle):
        err(f"agent-skill: {rel(path)} references missing bundled skill {ref}")
    tools = {item.strip() for item in str(meta.get("tools", "")).split(",") if item.strip()}
    if refs and "Skill" not in tools:
        err(f"agent-tools: {rel(path)} invokes skills but omits Skill")
    wrapper = path.parents[1] / "skills" / slug / "SKILL.md"
    if wrapper.is_file():
        try:
            wrapper_meta, wrapper_body = frontmatter(wrapper)
            if body != wrapper_body or meta.get("name") != wrapper_meta.get("name") or meta.get("description") != wrapper_meta.get("description"):
                err(f"agent-wrapper: {rel(wrapper)} drifted from {rel(path)}")
        except ValueError as error:
            err(f"agent-wrapper: {rel(wrapper)}: {error}")


# Source plugins own shared skills; bundled workflow copies must match recursively.
shared_sources: Dict[str, Path] = {}
for plugin_name in SOURCE_PLUGIN_NAMES:
    for source in sorted((PLUGINS / plugin_name / "skills").iterdir()):
        if not source.is_dir():
            continue
        if source.name in shared_sources:
            err(f"source-skill: duplicate name {source.name}")
        shared_sources[source.name] = source
for plugin_name in BUNDLE_PLUGIN_NAMES:
    for bundled in sorted((PLUGINS / plugin_name / "skills").iterdir()):
        if not bundled.is_dir():
            continue
        source = shared_sources.get(bundled.name)
        if source and tree_signature(source) != tree_signature(bundled):
            err(f"bundled-skill: {rel(bundled)} drifted from {rel(source)}")

# Every explicit cross-skill call in an agent bundle must close locally. Codex
# manifests do not resolve Claude-style dependencies, so vendoring is required.
known_skill_names = set(skill_dirs)
for plugin_name in BUNDLE_PLUGIN_NAMES:
    agent_root = PLUGINS / plugin_name
    if not agent_root.is_dir() or not (agent_root / "skills").is_dir():
        continue
    bundle = {item.name for item in (agent_root / "skills").iterdir() if item.is_dir()}
    for skill_path in sorted((agent_root / "skills").glob("*/SKILL.md")):
        text = skill_path.read_text(encoding="utf-8")
        refs = {name for name in re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", text) if name in known_skill_names}
        for ref in sorted(refs - bundle):
            err(f"skill-closure: {rel(skill_path)} calls missing bundled skill {ref}")


# High-risk stale patterns should never re-enter active methodology.
STALE_PATTERNS = {
    "recalc.py": "references a non-bundled formula runner",
    "TROUBLESHOOTING.md": "references a missing resource",
    "china-earnings-reviewer": "references a missing skill",
    "目标价 = 当前价": "mechanical target-price mapping",
    "等待回调至XX元介入": "trading instruction",
    "设置止损位XX元": "trading instruction",
    "`us_tycr` 或 `shibor_lpr`": "wrong China risk-free-rate fallback",
}
agent_files = [
    path
    for plugin_name in BUNDLE_PLUGIN_NAMES
    for path in sorted((PLUGINS / plugin_name / "agents").glob("*.md"))
]
for path in skill_files + agent_files:
    text = path.read_text(encoding="utf-8")
    for pattern, reason in STALE_PATTERNS.items():
        if pattern in text:
            err(f"method-boundary: {rel(path)} contains {pattern!r}: {reason}")

for path in sorted(ROOT.glob("plugins/**/scripts/*.py")):
    if "ts.get_token(" in path.read_text(encoding="utf-8"):
        err(f"credential: {rel(path)} reads a global Tushare token cache")

# Removed runtime shapes must not silently re-enter this Skill-only project.
for forbidden in (
    ROOT / "managed-agent-cookbooks",
    ROOT / ".kimi-plugin" / "plugin.json",
    ROOT / "skills" / "china-financial-services",
    ROOT / "scripts" / "deploy-managed-agent.sh",
    ROOT / "scripts" / "test-cookbooks.sh",
    ROOT / "scripts" / "sync-hooks.py",
    ROOT / "scripts" / "orchestrate.py",
    ROOT / "scripts" / "validate.py",
    ROOT / "tests" / "test_hooks.py",
):
    if forbidden.exists():
        err(f"removed-runtime: {rel(forbidden)} must not exist")
for hooks in sorted(PLUGINS.glob("**/hooks")):
    if hooks.is_dir():
        err(f"removed-runtime: {rel(hooks)} must not exist")

# Attribution is an acceptance gate, not an unverified prose convention.
provenance = (ROOT / "PROVENANCE.md").read_text(encoding="utf-8") if (ROOT / "PROVENANCE.md").is_file() else ""
for revision in (
    "33a3d8a9d6e5c3d4861731933a8857cc5e03315d",
    "7c428944a6718c35461f839c618ae66334b6371b",
    "99e84abaad965f75dd15cab2fcb0f3f61d30577b",
    "d82998e7df393c671ede2387a8435075f0b633f5",
):
    if revision not in provenance:
        err(f"provenance: missing pinned upstream revision {revision}")
if not (ROOT / "NOTICE").is_file():
    err("provenance: root NOTICE is missing")

# Direct pins must be present in the hashed transitive lock.
runtime_requirements = (ROOT / "requirements" / "runtime.txt").read_text(encoding="utf-8").splitlines()
runtime_lock = (ROOT / "requirements" / "runtime-lock.txt").read_text(encoding="utf-8")
for requirement in runtime_requirements:
    pin = requirement.strip()
    if pin and not pin.startswith("#") and pin.lower() not in runtime_lock.lower():
        err(f"dependency-lock: direct pin missing from runtime-lock.txt: {pin}")
live_requirements = (ROOT / "requirements" / "live-acceptance.txt").read_text(encoding="utf-8").splitlines()
live_lock_path = ROOT / "requirements" / "live-acceptance-lock.txt"
live_lock = live_lock_path.read_text(encoding="utf-8") if live_lock_path.is_file() else ""
for requirement in live_requirements:
    pin = requirement.strip()
    if pin and not pin.startswith("#") and pin.lower() not in live_lock.lower():
        err(f"dependency-lock: direct pin missing from live-acceptance-lock.txt: {pin}")

if errors:
    print(f"FAIL — {len(errors)} issue(s) across {checked} checked files:", file=sys.stderr)
    for issue in errors:
        print(f"  ✗ {issue}", file=sys.stderr)
    raise SystemExit(1)
parser_name = "PyYAML" if yaml is not None else "Ruby Psych fallback"
print(f"OK — {checked} files checked, 0 issues ({parser_name}).")
