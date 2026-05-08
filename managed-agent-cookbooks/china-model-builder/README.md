# China Model Builder — managed-agent template

## Overview

为中国A股公司构建机构级估值与财务模型——包括A股DCF模型、A股可比分析（Trading Comps）及三表预测模型。基于Tushare Pro数据，输出为Excel工作簿。Same source as the [`china-model-builder`](../../plugins/agent-plugins/china-model-builder) Cowork plugin — this directory is the Managed Agent cookbook for `POST /v1/agents`.

## Deploy

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export TUSHARE_MCP_URL=...
./scripts/deploy-managed-agent.sh china-model-builder
```

## Steering events

See [`steering-examples.json`](./steering-examples.json).

## Security & handoffs

Artifact isolation 与重新验证原则。模型构建按阶段隔离，计算单元格中不得出现硬编码数字：

| 阶段 | 工具 | 数据源 |
|---|---|---|
| 数据拉取 | `Read`, `Grep` | Tushare（只读） |
| 模型搭建与输出 | `Read`, `Write`, `Edit`, `Bash`（沙箱化） | 无外部连接 |
| 审计复核 | `Read`, `Grep` | 无外部连接 |

所有假设须在 Inputs 页清晰标注来源；若为用户估计则标记 `[ASSUMPTION]`。遵循蓝/黑/绿配色规范：蓝色=硬编码输入、黑色=公式、绿色=跨表链接。

关注A股特有的会计科目（如其他收益、资产处置收益）、非经常性损益、政府补助、关联交易等，必要时单独列示。

本 Agent 仅负责模型搭建；估值结论及投资决策由用户自行判断。所有输出暂存于 `./out/`，须经人工审阅后方可使用。

**Handoff:** 当被 `china-market-researcher` 或 `pitch-agent` 调用时，调用方的 `handoff_request` 由 `./scripts/orchestrate.py` 路由至此。
