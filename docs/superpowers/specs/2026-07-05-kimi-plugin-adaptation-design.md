# 中国A股金融插件 Kimi Code 适配设计

## 目标

在保留现有 Claude Code 兼容性的前提下，为 `china-financial-services` 仓库增加 Kimi Code 插件支持。文件组织参考 `../superpowers` 的多 harness 模式。

## 背景

当前仓库是 Claude 插件市场 + Managed Agents cookbook，包含 4 个插件：

- `plugins/vertical-plugins/financial-analysis`
- `plugins/vertical-plugins/equity-research`
- `plugins/agent-plugins/china-market-researcher`
- `plugins/agent-plugins/china-model-builder`

每个插件已有 `.claude-plugin/plugin.json` 和 `skills/` 目录；agent 插件还有 `agents/<name>.md`。Kimi Code 插件使用 `kimi.plugin.json`（本设计采用与 superpowers 一致的 `.kimi-plugin/plugin.json` 布局）。

## 设计决策

1. **多 harness 共存**：保留全部 `.claude-plugin/` 结构不动，仅新增 `.kimi-plugin/plugin.json`。
2. **Agent 插件入口**：Kimi 没有原生 agent 概念，将 `agents/<name>.md` 改写为 `skills/<name>/SKILL.md`，并在 manifest 中设置 `sessionStart.skill` 为 `<name>`，使插件加载后自动进入该工作流。
3. **Hooks 暂不适配**：现有 hooks 使用 `${CLAUDE_PLUGIN_ROOT}` 等 Claude 专用环境变量，superpowers 的 Kimi manifest 也未引用 hooks，因此 Kimi 端先不配置 hooks。
4. **不实装 MCP server**：现有 skill 通过 Bash 调用 Python/Tushare，属于 agent 执行层行为，本次仅做文件组织适配，不改为 MCP 工具。
5. **更新 CI 与文档**：`scripts/check.py` 增加 Kimi manifest 校验；`README.md` 增加 Kimi Code 安装说明。

## 文件变更清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `plugins/vertical-plugins/financial-analysis/.kimi-plugin/plugin.json` | Kimi manifest，指向 `./skills/` |
| `plugins/vertical-plugins/equity-research/.kimi-plugin/plugin.json` | 同上 |
| `plugins/agent-plugins/china-market-researcher/.kimi-plugin/plugin.json` | Kimi manifest，指向 `./skills/`，并设置 `sessionStart.skill` |
| `plugins/agent-plugins/china-model-builder/.kimi-plugin/plugin.json` | 同上 |
| `plugins/agent-plugins/china-market-researcher/skills/china-market-researcher/SKILL.md` | 由 `agents/china-market-researcher.md` 改写 |
| `plugins/agent-plugins/china-model-builder/skills/china-model-builder/SKILL.md` | 由 `agents/china-model-builder.md` 改写 |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `scripts/check.py` | 增加 Kimi manifest 存在性、JSON 合法性、name 格式、skills 路径、sessionStart.skill 存在性校验 |
| `README.md` | 新增 Kimi Code 安装段落 |

### 不变文件

- 所有 `.claude-plugin/plugin.json`
- 所有 `hooks/`
- 所有现有 `skills/*/SKILL.md` 内容
- `managed-agent-cookbooks/`
- `out/`

## Manifest 示例

### Vertical 插件

```json
{
  "name": "financial-analysis",
  "version": "1.0.1",
  "description": "Core financial modeling and analysis tools powered by Tushare: A-share market data, financial statements, valuation, and macro data",
  "author": { "name": "Tushare Edition" },
  "skills": "./skills/",
  "interface": {
    "displayName": "Financial Analysis",
    "shortDescription": "A-share financial modeling and macro data tools",
    "longDescription": "Core financial modeling and analysis tools powered by Tushare for China A-share market research.",
    "developerName": "Tushare Edition",
    "capabilities": ["Read", "Write", "Bash", "WebSearch"],
    "websiteURL": "https://github.com/cyijun/china-financial-services"
  }
}
```

### Agent 插件

```json
{
  "name": "china-market-researcher",
  "version": "1.0.1",
  "description": "A-share market research agent — sector primers, competitive landscape, peer comps, and thematic idea generation powered by Tushare and web research.",
  "author": { "name": "cyijun" },
  "skills": "./skills/",
  "sessionStart": {
    "skill": "china-market-researcher"
  },
  "interface": { ... }
}
```

## Agent skill 转换规则

1. 复制 `agents/<name>.md` 到 `skills/<name>/SKILL.md`。
2. 保留原 frontmatter 中的 `name`、`description`；将 `tools` 列表映射为 Kimi 能力描述（可保留在 description 中或省略，因为 capabilities 已在 manifest 中声明）。
3. 正文内容保持不变，仅修正对 skill 名称的引用格式（如反引号包裹的 skill 名）。
4. 新 skill 目录与现有 skills 平级，因此 `skills` 字段统一指向 `./skills/` 即可自动包含。

## 校验规则

`scripts/check.py` 增加以下检查：

1. 每个插件目录必须存在 `.kimi-plugin/plugin.json`。
2. 文件必须是合法 JSON。
3. `name` 必须匹配 `[a-z0-9][a-z0-9_-]{0,63}`。
4. `skills` 字段必须存在且以 `./` 开头。
5. 若存在 `sessionStart.skill`，对应的 `skills/<name>/SKILL.md` 必须存在。
6. `interface` 中 `capabilities` 如存在，必须是合法能力列表（可选校验）。

## 验证计划

1. 本地运行 `python3 scripts/check.py` 通过。
2. 在 Kimi Code CLI 中执行 `/plugins install <path>` 安装每个插件。
3. 执行 `/plugins info <id>` 确认无错误。
4. 执行 `/reload` 后验证插件可被加载。

## 不在本次范围

- 创建 MCP server 替代 Bash/Python 调用。
- 将现有 skill 改为调用 `mcp__plugin-*` 工具。
- 为 Kimi 配置 command hooks（如年份校验）。
- 修改 Claude 端行为或文件。
