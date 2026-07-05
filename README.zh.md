# 中国金融服务

[English](README.md) | 中文

面向中国 A 股市场研究的 AI 智能体插件与管理代理模板，基于 [Tushare](https://tushare.pro/) 数据驱动。

> **重要声明：** 本仓库中的任何内容均不构成投资、法律、税务或会计建议。这些智能体仅起草分析师工作底稿，供合格专业人士审阅。它们不提供投资建议、不执行交易、不承担风险。所有输出均需经人工确认后方可使用。

## 包含内容

| 智能体 | 说明 | 输出 |
|---|---|---|
| **china-market-researcher** | 行业/主题 → 行业概览 → 竞争格局 → 可比公司估值 → 投资点子筛选 | 研究纪要或幻灯片 |
| **china-model-builder** | A 股公司 DCF、可比分析、三表预测模型 | Excel 工作簿 |

| 垂直插件 | Skills | 说明 |
|---|---|---|
| **financial-analysis** | `tushare-data`、`china-dcf-model`、`china-comps-analysis`、`china-macro-overview` | 核心财务建模与宏观数据工具 |
| **equity-research** | `china-initiating-coverage` | 中国 A 股首次覆盖报告 |

## 仓库结构

```
plugins/
  agent-plugins/
    china-market-researcher/      # 端到端工作流智能体 + 打包 skills
    china-model-builder/
  vertical-plugins/
    financial-analysis/           # Skills（唯一数据源）
    equity-research/
managed-agent-cookbooks/
  china-market-researcher/        # 部署清单，用于 POST /v1/agents
  china-model-builder/
scripts/
  check.py                        # 校验所有清单
  sync-agent-skills.py            # 将 vertical skills 同步到 agent 包
  sync-hooks.py                   # 将年份校验 hooks 同步到所有插件
  deploy-managed-agent.sh         # 将 cookbook 部署到 CMA
  test-cookbooks.sh               # 所有 cookbook 的干跑验证
  validate.py                     # 输出 schema 校验辅助
  orchestrate.py                  # 跨智能体交接的参考事件循环
```

## 示例

智能体生成的示例输出见 [`out/`](out/)。

### 命令行使用

![CLI Demo](out/demo.png)

### 交付物

**Excel 工作簿**（[`portfolio_2026Q2.xlsx`](out/portfolio_2026Q2.xlsx)）——由 `china-model-builder` 生成：

![Excel Report](out/excel_report.png)

**幻灯片**（[`portfolio_roadshow_2026Q2.pptx`](out/portfolio_roadshow_2026Q2.pptx)）——由 `china-market-researcher` 生成：

![PPT Report](out/ppt_report.png)

## 安装

### Kimi Code（CLI）

#### 方式 A：将本仓库添加为插件市场

在 Kimi Code 插件市场设置中添加 `https://github.com/cyijun/china-financial-services`。插件市场会自动下载最新的 Release zip 包。然后安装所需插件：

```bash
/plugins install financial-analysis
/plugins install equity-research
/plugins install china-market-researcher
/plugins install china-model-builder
```

#### 方式 B：从本地目录安装

```bash
/plugins install ./plugins/vertical-plugins/financial-analysis
/plugins install ./plugins/vertical-plugins/equity-research
/plugins install ./plugins/agent-plugins/china-market-researcher
/plugins install ./plugins/agent-plugins/china-model-builder
```

然后运行 `/plugins info <plugin-name>` 验证，并运行 `/reload` 激活。

智能体插件（`china-market-researcher`、`china-model-builder`）加载后会通过 `sessionStart.skill` 自动启动工作流。

#### 发布 Kimi 插件

创建 GitHub Release 时，`.github/workflows/release-kimi-plugins.yml` 会自动将每个插件打包成 zip 并上传到 Release 附件。根目录的 `marketplace.json` 始终指向最新的 Release 资源。

### Claude Code（CLI）

```bash
claude plugin marketplace add cyijun/china-financial-services
claude plugin install china-market-researcher@china-financial-services
claude plugin install china-model-builder@china-financial-services
```

### Claude Cowork（桌面端 / 网页版）

在 **设置 → 插件 → 添加插件** 中粘贴仓库 URL，或压缩 `plugins/` 下任意目录后上传。

### 托管智能体（API）

> 当前使用 Claude Managed Agents API。后续可能增加同等的 Kimi 部署支持。

```bash
export ANTHROPIC_API_KEY=sk-ant-...
scripts/deploy-managed-agent.sh china-market-researcher
```

需要 `jq`、`zip`、`curl` 以及 `python3 + pyyaml`。

## 开发

```bash
# 校验所有内容（CI 门禁）
python3 scripts/check.py

# 修改 vertical-plugins/ 中的 skill 后，同步到 agent 包
python3 scripts/sync-agent-skills.py

# 修改 financial-analysis/ 中的 hooks 后，同步到所有插件
python3 scripts/sync-hooks.py

# 所有 cookbook 干跑验证（CI 门禁）
bash scripts/test-cookbooks.sh
```

## 数据来源

- **Tushare Pro** — 主要结构化数据（财务报表、估值指标、宏观数据）
- **网页搜索** — 行业报告、政策解读、新闻
- **公司公告** — 经审计的数据及定性信息

## 致谢

本项目改编自 [Anthropic Financial Services cookbook](https://github.com/anthropics/financial-services)，其提供了此处使用的底层插件架构、管理代理模式及智能体集成框架。

## 许可证

见 [LICENSE](LICENSE)。
