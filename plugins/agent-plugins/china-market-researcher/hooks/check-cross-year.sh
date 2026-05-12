#!/usr/bin/env bash
# PostToolUse hook: 当工具结果同时出现 2025 与 2026 年时,
# 通过 additionalContext 提醒 Claude 区分年份。毫秒级 grep,始终 exit 0 + 有效 JSON。
set -euo pipefail

input=$(cat)

# tool_response 是 PostToolUse 的正确字段(规范);tostring 兜底对象/数组结果
result=$(printf '%s' "$input" | jq -r '.tool_response // "" | tostring' 2>/dev/null || true)

if [ -z "$result" ]; then
  echo '{}'
  exit 0
fi

# LC_ALL=C 强制字节级匹配,这样 \b 在 "2025年" 这类含 CJK 的字符串里也能正常工作
if LC_ALL=C grep -qE '\b2025\b' <<<"$result" && LC_ALL=C grep -qE '\b2026\b' <<<"$result"; then
  cat <<'EOF'
{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"【跨年数据注意】输出同时包含 2025 与 2026 年数据。引用、汇总、计算同比/环比或对比分析时请严格区分年份,避免将 2025 数据误当作 2026 使用。"}}
EOF
else
  echo '{}'
fi
