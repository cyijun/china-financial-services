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


# JSON manifests.
marketplace = json_file(ROOT / ".claude-plugin" / "marketplace.json")
if not marketplace.get("description"):
    err("marketplace: missing description")
market_names = {plugin.get("name") for plugin in marketplace.get("plugins") or []}
for plugin in marketplace.get("plugins") or []:
    source = (ROOT / plugin.get("source", "")).resolve()
    if not (source / ".claude-plugin" / "plugin.json").is_file():
        err(f"marketplace: {plugin.get('name')} source has no Claude manifest")
    if not (source / ".codex-plugin" / "plugin.json").is_file():
        err(f"marketplace: {plugin.get('name')} source has no Codex manifest")

claude_manifests: Dict[Path, Dict[str, Any]] = {}
for path in sorted(ROOT.glob("plugins/**/.claude-plugin/plugin.json")):
    manifest = json_file(path)
    claude_manifests[path.parent.parent.resolve()] = manifest
    for dependency in manifest.get("dependencies") or []:
        name = dependency.split("@", 1)[0] if isinstance(dependency, str) else ""
        if name not in market_names:
            err(f"claude-dependency: {rel(path)} -> {dependency} is not in marketplace")

KIMI_INTERFACE_FIELDS = {"displayName", "shortDescription", "longDescription", "developerName", "websiteURL"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
for path in sorted([*ROOT.glob("plugins/**/.kimi-plugin/plugin.json"), ROOT / ".kimi-plugin" / "plugin.json"]):
    manifest = json_file(path)
    name = manifest.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        err(f"kimi-manifest: {rel(path)} invalid name {name!r}")
    plugin_root = ROOT if path.parent == ROOT / ".kimi-plugin" else path.parent.parent
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
    if manifest.get("license") not in (None, "Apache-2.0"):
        err(f"license: {rel(path)} must use Apache-2.0 when a license field is present")

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
for path in sorted(ROOT.glob("plugins/**/.codex-plugin/plugin.json")):
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
skill_files = sorted([*PLUGINS.glob("**/skills/*/SKILL.md"), *(ROOT / "skills").glob("*/SKILL.md")])
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
for path in sorted(PLUGINS.glob("agent-plugins/*/agents/*.md")):
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


# Vertical skills are sources of truth; bundled copies must match recursively.
vertical_sources: Dict[str, Path] = {}
for source in sorted(PLUGINS.glob("vertical-plugins/*/skills/*")):
    if not source.is_dir():
        continue
    if source.name in vertical_sources:
        err(f"vertical-skill: duplicate name {source.name}")
    vertical_sources[source.name] = source
for bundled in sorted(PLUGINS.glob("agent-plugins/*/skills/*")):
    source = vertical_sources.get(bundled.name)
    if source and tree_signature(source) != tree_signature(bundled):
        err(f"bundled-skill: {rel(bundled)} drifted from {rel(source)}")

# Every explicit cross-skill call in an agent bundle must close locally. Codex
# manifests do not resolve Claude-style dependencies, so vendoring is required.
known_skill_names = set(skill_dirs)
for agent_root in sorted(PLUGINS.glob("agent-plugins/*")):
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
for path in skill_files + sorted(PLUGINS.glob("agent-plugins/*/agents/*.md")):
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
