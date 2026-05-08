# China Market Researcher — managed-agent template

## Overview

行业或主题 → 行业概览 → 竞争格局 → 同业估值比较 → 选股短名单 → 资金流向 → 中文研究报告。Same source as the [`china-market-researcher`](../../plugins/agent-plugins/china-market-researcher) Cowork plugin — this directory is the Managed Agent cookbook for `POST /v1/agents`.

## Deploy

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export TUSHARE_MCP_URL=...
./scripts/deploy-managed-agent.sh china-market-researcher
```

## Steering events

See [`steering-examples.json`](./steering-examples.json). Kick from a research-queue event or fan out across a coverage map.

## Security & handoffs

第三方报告与发行人材料不可信。Agent 遵循 defense-in-depth 原则，按操作类型隔离：

| 阶段 | 接触外部材料？ | 工具 | 数据源 |
|---|---|---|---|
| 读取外部材料 | **是** | `Read`, `Grep` only | 无直接 MCP |
| 数据分析与同业比较 | 否 | `Read`, `Grep`, `Glob` | Tushare（只读） |
| 报告撰写与输出 | 否 | `Read`, `Write`, `Edit` | 无外部连接 |

所有输出暂存于 `./out/`，须经人工审阅后方可使用。每个数字必须注明来源；若数据无法从 Tushare Pro 或公开财报中溯源，标注 `[未核实]`。

本 Agent 不对外发布报告；发布与传播在 Agent 外进行。每份报告结尾须包含政策风险、行业周期风险、流动性风险及数据口径说明。

**Handoff:** 当研究短名单中浮现需要深度建模的单个标的时，可发出 `handoff_request` 给 `china-model-builder`；由 `./scripts/orchestrate.py` 路由为新的 steering event。
