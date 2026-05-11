#!/usr/bin/env bash
# Fast cross-year detector for PostToolUse.
# Emits a systemMessage when both 2025 and 2026 appear in tool_result,
# so the agent treats mixed-year output with care. Always exits 0 with valid JSON.
#
# Replaces the previous 15s prompt-based hook with a millisecond grep.
set -euo pipefail

input=$(cat)

# Pull tool_result as a flat string; tostring handles object/array results gracefully.
result=$(printf '%s' "$input" | jq -r '.tool_result // "" | tostring' 2>/dev/null || true)

if [ -z "$result" ]; then
  echo '{}'
  exit 0
fi

# LC_ALL=C forces byte-level matching so \b works around CJK characters
# (e.g. "2025年"). Under UTF-8 locales BSD grep treats CJK as word chars.
if LC_ALL=C grep -qE '\b2025\b' <<<"$result" && LC_ALL=C grep -qE '\b2026\b' <<<"$result"; then
  cat <<'EOF'
{"continue": true, "systemMessage": "【跨年数据注意】输出同时包含 2025 与 2026 年数据。引用、汇总、计算同比/环比或对比分析时请严格区分年份，避免将 2025 数据误当作 2026 使用。"}
EOF
else
  echo '{}'
fi
