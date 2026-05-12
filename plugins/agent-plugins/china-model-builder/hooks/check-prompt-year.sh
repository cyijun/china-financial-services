#!/usr/bin/env bash
# UserPromptSubmit hook: 检测涉及日期/年份/财报/行情等主题时,
# 通过 additionalContext 注入年份提醒。毫秒级 grep,始终 exit 0 + 有效 JSON。
set -euo pipefail

input=$(cat)
prompt=$(printf '%s' "$input" | jq -r '.prompt // ""' 2>/dev/null || echo "")

if [ -z "$prompt" ]; then
  echo '{}'
  exit 0
fi

# LC_ALL=C 走字节级匹配,避免 BSD grep 在 UTF-8 环境下对 CJK 误处理
if LC_ALL=C grep -qE '年份|日期|时间|财报|年报|季报|半年报|行情|历史|同比|环比|本年|去年|今年|明年|本季|上季|当前|最新|近期|past|previous|recent|latest|[0-9]{4}年|Q[1-4]|FY[0-9]{2,4}' <<<"$prompt"; then
  cat <<'EOF'
{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"【年份确认】当前是 2026 年。生成查询参数或进行日期计算时请使用正确年份,避免将 2026 误写为 2025。"}}
EOF
else
  echo '{}'
fi
