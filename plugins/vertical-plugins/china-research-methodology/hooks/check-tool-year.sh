#!/usr/bin/env bash
# PreToolUse hook (WebSearch|WebFetch): 当工具参数含 2025 且无明显历史/对比上下文时,
# 注入年份提醒(始终 allow,不阻止调用)。毫秒级 grep,始终 exit 0 + 有效 JSON。
set -euo pipefail

input=$(cat)
tool_input=$(printf '%s' "$input" | jq -c '.tool_input // {}' 2>/dev/null || echo '{}')

# 同时覆盖 WebSearch.query / WebFetch.url / WebFetch.prompt
combined=$(printf '%s' "$tool_input" | jq -r '[.query, .url, .prompt] | map(select(. != null)) | join(" ")' 2>/dev/null || echo "")

if [ -z "$combined" ]; then
  echo '{}'
  exit 0
fi

if LC_ALL=C grep -qE '\b2025\b' <<<"$combined" \
   && ! LC_ALL=C grep -qE '历史|去年|往年|过去|同比|环比|年报|季报|半年报|2025 年报|past|previous|last year|prior year|year-over-year|yoy' <<<"$combined"; then
  cat <<'EOF'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","additionalContext":"⚠️ 年份检查:参数中提到 2025,而当前是 2026 年。请确认是否为故意查询历史数据;若需要最新数据,请改写为 2026。"}}
EOF
else
  echo '{}'
fi
