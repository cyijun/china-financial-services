#!/usr/bin/env bash
# Deploy a managed-agent template to POST /v1/agents.
#
# Resolves manifest conveniences before posting:
#   system: {file: ...}                  -> inlined string
#   skills: [{path: ...}]                -> uploaded, referenced by skill_id
#   callable_agents: [{manifest: ...}]   -> created first, referenced by agent id
#
# `output_schema` is intentionally rejected until the deployed API can enforce
# it. Silently deleting a requested contract would create false assurance.
#
# Usage: scripts/deploy-managed-agent.sh <slug>
#   e.g. scripts/deploy-managed-agent.sh gl-reconciler

set -euo pipefail

ROLE="${1:?usage: deploy-managed-agent.sh <slug> [--dry-run]}"
DRY_RUN=0; [[ "${2:-}" == "--dry-run" ]] && DRY_RUN=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/managed-agent-cookbooks/$ROLE"
API="${ANTHROPIC_API_BASE:-https://api.anthropic.com}"
[[ $DRY_RUN -eq 1 ]] || : "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY must be set}"

[[ -f "$DIR/agent.yaml" ]] || { echo "no manifest at $DIR/agent.yaml" >&2; exit 1; }

req() {
  curl -sS -H "x-api-key: $ANTHROPIC_API_KEY" \
           -H "anthropic-version: 2023-06-01" \
           -H "anthropic-beta: managed-agents-2026-04-01" \
           -H "content-type: application/json" "$@"
}

# jq plus either PyYAML or Ruby Psych do the manifest→payload transform.
command -v jq >/dev/null || { echo "requires jq" >&2; exit 1; }
if python3 -c 'import yaml' 2>/dev/null; then
  YAML_IMPL=python
elif command -v ruby >/dev/null && ruby -e 'require "yaml"; require "json"' 2>/dev/null; then
  YAML_IMPL=ruby
else
  echo "requires python3 + pyyaml or ruby + psych" >&2
  exit 1
fi
yaml2json() {
  if [[ "$YAML_IMPL" == python ]]; then
    python3 -c '
import sys,os,re,yaml,json
SAFE = re.compile(r"^[A-Za-z0-9._/:@-]*$")
def sub(m):
    name = m.group(1)
    v = os.environ.get(name)
    if v is None:
        return m.group(0)
    if not SAFE.fullmatch(v):
        sys.exit(f"refusing ${{{name}}}: value contains characters outside [A-Za-z0-9._/:@-]")
    return v
t = open(sys.argv[1]).read()
t = re.sub(r"\$\{([A-Z0-9_]+)\}", sub, t)
json.dump(yaml.safe_load(t), sys.stdout)
' "$1"
  else
    ruby -ryaml -rjson -e '
safe = /^[A-Za-z0-9._\/:@-]*$/
text = File.read(ARGV[0])
text = text.gsub(/\$\{([A-Z0-9_]+)\}/) do |match|
  name = Regexp.last_match(1)
  value = ENV[name]
  next match if value.nil?
  abort("refusing ${#{name}}: value contains characters outside [A-Za-z0-9._/:@-]") unless safe.match?(value)
  value
end
print JSON.generate(YAML.safe_load(text, permitted_classes: [], aliases: false))
' "$1"
  fi
}

SKILL_CACHE_FILE="$(mktemp)"
trap 'rm -f "$SKILL_CACHE_FILE"' EXIT
upload_skill() {
  local path="$1" key cached
  key="$(printf '%s' "$(cd "$path" && pwd)" | shasum -a 256 | awk '{print $1}')"
  cached=$(grep -m1 "^${key}=" "$SKILL_CACHE_FILE" 2>/dev/null | cut -d= -f2-)
  if [[ -n "$cached" ]]; then printf '%s' "$cached"; return; fi
  if [[ $DRY_RUN -eq 1 ]]; then
    cached=$(printf '{"type":"custom","skill_id":"DRYRUN_%s","version":"latest"}' "$key")
    echo "${key}=${cached}" >>"$SKILL_CACHE_FILE"
    printf '%s' "$cached"; return
  fi
  local resp id zip zip_dir
  zip_dir="$(mktemp -d)"
  zip="$zip_dir/skill.zip"
  (cd "$(dirname "$path")" && zip -qr "$zip" "$(basename "$path")")
  # /v1/skills uses its own beta header and multipart, not the managed-agents JSON path
  resp=$(curl -sS "$API/v1/skills" \
    -H "x-api-key: $ANTHROPIC_API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "anthropic-beta: skills-2025-10-02" \
    -F "display_title=${SKILL_TITLE_PREFIX:-}$(basename "$path")" \
    -F "files[]=@$zip")
  rm -rf "$zip_dir"
  id=$(jq -r '.id // empty' <<<"$resp")
  if [[ -z "$id" ]]; then
    echo "POST /v1/skills failed for $path:" >&2
    echo "$resp" | jq . >&2 2>/dev/null || echo "$resp" >&2
    exit 1
  fi
  cached=$(printf '{"type":"custom","skill_id":"%s","version":"latest"}' "$id")
  echo "${key}=${cached}" >>"$SKILL_CACHE_FILE"
  printf '%s' "$cached"
}

resolve_manifest() {
  local file="$1" base
  base="$(cd "$(dirname "$file")" && pwd)"
  local json
  json=$(yaml2json "$file")
  # Expand every {from_plugin: <dir>} into one upload per skills/* directory.
  local fp plugdir expanded="[]"
  while IFS= read -r fp; do
    [[ -n "$fp" ]] || continue
    plugdir="$(cd "$base/$fp" && pwd)"
    for sk in "$plugdir"/skills/*/; do
      [[ -d "$sk" ]] || continue
      expanded=$(jq --arg p "${sk%/}" '. + [{__upload:$p}]' <<<"$expanded")
    done
  done < <(jq -r '.skills[]? | .from_plugin // empty' <<<"$json")
  json=$(jq --argjson e "$expanded" \
    '.skills = ((.skills // [] | map(select(has("from_plugin") | not))) + $e)' <<<"$json")
  jq --arg base "$base" '
    .skills = ((.skills // []) | map(
      if .path then {__upload: ($base + "/" + .path)}
      elif .__upload then .
      else . end))
  ' <<<"$json"
}

inline_system() {
  local json="$1" base="$2" sysfile text append body
  if jq -e '.system | type == "object"' >/dev/null <<<"$json"; then
    sysfile=$(jq -r '.system.file // empty' <<<"$json")
    text=$(jq -r '.system.text // empty' <<<"$json")
    append=$(jq -r '.system.append // empty' <<<"$json")
    body="$text"
    if [[ -n "$sysfile" ]]; then
      [[ -f "$base/$sysfile" ]] || { echo "system.file not found: $base/$sysfile" >&2; exit 1; }
      body="$(cat "$base/$sysfile")"
    fi
    [[ -n "$append" ]] && body="${body}"$'\n\n'"${append}"
    jq --arg s "$body" '.system=$s' <<<"$json"
  else
    printf '%s' "$json"
  fi
}

create_agent() {
  local file="$1" base json sub_ids skills_json
  base="$(cd "$(dirname "$file")" && pwd)"
  json=$(resolve_manifest "$file")
  json=$(inline_system "$json" "$base")

  if jq -e '.output_schema != null' >/dev/null <<<"$json"; then
    echo "output_schema is declared in $file but this deployer cannot enforce it" >&2
    exit 1
  fi

  skills_json="[]"
  while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    [[ -d "$p" ]] || { echo "skill path not found: $p" >&2; exit 1; }
    skills_json=$(jq ". + [$(upload_skill "$p")]" <<<"$skills_json")
  done < <(jq -r '.skills[]? | select(.__upload) | .__upload' <<<"$json")
  json=$(jq --argjson s "$skills_json" '.skills=$s' <<<"$json")

  sub_ids="[]"
  while IFS= read -r m; do
    [[ -z "$m" ]] && continue
    local out sid sver
    out=$(create_agent "$base/$m")
    sid=${out%% *}; sver=${out##* }
    sub_ids=$(jq --arg i "$sid" --argjson v "$sver" '. + [{type:"agent", id:$i, version:$v}]' <<<"$sub_ids")
  done < <(jq -r '.callable_agents[]?.manifest // empty' <<<"$json")
  json=$(jq --argjson c "$sub_ids" '.callable_agents=$c' <<<"$json")
  [[ -n "${DEPLOY_DEBUG:-}" ]] && jq -c '{name, callable_agents}' <<<"$json" >&2

  if [[ $DRY_RUN -eq 1 ]]; then
    echo "$json" >>"$DRY_OUT"
    jq -r '"DRYRUN_" + .name + " 1"' <<<"$json"; return
  fi
  local resp id ver
  resp=$(req -X POST "$API/v1/agents" -d "$json")
  id=$(jq -r '.id // empty' <<<"$resp")
  ver=$(jq -r '.version // 1' <<<"$resp")
  if [[ -z "$id" ]]; then
    echo "POST /v1/agents failed for $(jq -r .name <<<"$json"):" >&2
    echo "$resp" | jq . >&2 2>/dev/null || echo "$resp" >&2
    exit 1
  fi
  echo "$id $ver"
}

if [[ $DRY_RUN -eq 1 ]]; then
  DRY_OUT="$(mktemp)"
  create_agent "$DIR/agent.yaml" >/dev/null
  echo "# --dry-run: resolved POST /v1/agents bodies (subagents first, orchestrator last)"
  jq -s '.' "$DRY_OUT"
  rm -f "$DRY_OUT"
  exit 0
fi

OUT=$(create_agent "$DIR/agent.yaml")
AGENT_ID=${OUT%% *}
echo "deployed: $ROLE"
echo "agent id: $AGENT_ID"
echo "console:  https://console.anthropic.com/agents/$AGENT_ID"
