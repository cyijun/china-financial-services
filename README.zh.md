# 中国金融服务

[English](README.md) | 中文

面向中国 A 股研究、可由 Codex 和 Claude Code 直接注册的多插件 Marketplace，并保留 Kimi Code CLI 的本地 Marketplace 兼容。主数据源为 [Tushare](https://tushare.pro/)，AKShare 仅作受控补充。

> **重要声明：** 本仓库中的任何内容均不构成投资、法律、税务或会计建议。这些智能体仅起草分析师工作底稿，供合格专业人士审阅。它们不提供投资建议、不执行交易、不承担风险。所有输出均需经人工确认后方可使用。

## 包含内容

| 智能体 | 说明 | 输出 |
|---|---|---|
| **china-market-researcher** | 行业/主题 → 行业概览 → 竞争格局 → 可比公司估值 → 投资点子筛选 | 研究纪要或幻灯片 |
| **china-model-builder** | A 股公司 DCF、可比分析、三表预测模型 | Excel 工作簿 |

| 垂直插件 | Skills | 说明 |
|---|---|---|
| **financial-analysis** | `tushare-data`、`china-dcf-model`、`china-comps-analysis`、`3-statement-model`、`audit-xls`、`china-macro-overview` | 核心财务建模、审计与宏观工具；Claude声明方法论依赖 |
| **equity-research** | `china-initiating-coverage` | 中国 A 股首次覆盖报告 |
| **china-research-methodology** | `china-market-data` + 8个方法Skill | 6000积分Tushare主源、AKShare受控降级、PIT证据链、财务取证、估值、论点、因子验证与红队 |

## 仓库结构

```
.agents/plugins/marketplace.json    # Codex Marketplace
.claude-plugin/marketplace.json     # Claude Code Marketplace
kimi-marketplace.json               # Kimi 本地克隆 Marketplace
plugins/
  china-research-methodology/       # 共享方法论与数据路由源
  financial-analysis/               # 共享建模与估值源
  equity-research/                  # 共享权益研究源
  china-market-researcher/          # 自包含工作流 + vendored skills
  china-model-builder/              # 自包含工作流 + vendored skills
scripts/
  check.py                        # 校验所有清单
  sync-agent-skills.py            # 将共享源同步到工作流包
  preflight.py                    # 检查Python、运行时与凭证就绪状态
  tushare_live_acceptance.py      # 脱敏、只读的真实接口验收
  akshare_live_acceptance.py      # AKShare全声明路由的脱敏只读验收
```

## 示例

仓库保留了版本化示例产物，位于[`out/`](out/)：

![命令行示例](out/demo.png)

- [`portfolio_2026Q2.xlsx`](out/portfolio_2026Q2.xlsx)及其[渲染预览](out/excel_report.png)
- [`portfolio_roadshow_2026Q2.pptx`](out/portfolio_roadshow_2026Q2.pptx)及其[渲染预览](out/ppt_report.png)

## 安装

### Codex（CLI / 桌面端）

仓库通过 `.agents/plugins/marketplace.json` 提供原生 [Codex Marketplace](https://learn.chatgpt.com/docs/build-plugins)。只需注册一次 GitHub 仓库，再按需添加插件：

```bash
codex plugin marketplace add cyijun/china-financial-services --ref main
codex plugin add china-research-methodology@china-financial-services
codex plugin add financial-analysis@china-financial-services
codex plugin add equity-research@china-financial-services
```

两个自包含工作流包可独立安装：

```bash
codex plugin add china-market-researcher@china-financial-services
codex plugin add china-model-builder@china-financial-services
```

Codex 不消费 Claude 的插件依赖声明。任务需要同时使用方法论、财务分析和权益研究时，请按上面的顺序安装三个共享插件。本仓库明确不包含远程 Managed Agent 部署能力，也不包含 command hooks。

### Kimi Code（CLI）

Kimi Code CLI 0.33.0 支持[自定义 Marketplace JSON](https://www.kimi.com/code/docs/kimi-code-cli/customization/plugins.html#custom-marketplace-json)，但其远程安装器目前不能可靠解析 monorepo 子目录中的插件（[上游问题](https://github.com/MoonshotAI/kimi-code/issues/2945)）。克隆仓库后，从仓库根目录启动 Kimi 并浏览本地目录：

```bash
git clone https://github.com/cyijun/china-financial-services.git
cd china-financial-services
kimi
```

进入 Kimi TUI 后运行：

```text
/plugins marketplace ./kimi-marketplace.json
```

如需不安装、只在当前会话加载，可重复使用 `--skills-dir`：

```bash
kimi --skills-dir ./plugins/china-research-methodology/skills \
  --skills-dir ./plugins/financial-analysis/skills
kimi --skills-dir ./plugins/china-market-researcher/skills
```

### Claude Code（CLI）

同一个仓库通过 `.claude-plugin/marketplace.json` 提供 [Claude Code Marketplace](https://code.claude.com/docs/zh-CN/plugin-marketplaces)。Claude 会解析 `financial-analysis` 与 `equity-research` 声明的同市场依赖：

```bash
claude plugin marketplace add cyijun/china-financial-services
claude plugin install china-research-methodology@china-financial-services
claude plugin install financial-analysis@china-financial-services
claude plugin install equity-research@china-financial-services
claude plugin install china-market-researcher@china-financial-services
claude plugin install china-model-builder@china-financial-services
```

### Claude Cowork（桌面端 / 网页版）

在 **设置 → 插件 → 添加插件** 中粘贴仓库 URL，或压缩 `plugins/` 下任意目录后上传。

## 开发

```bash
# 校验所有内容（CI 门禁）
python3 scripts/check.py

# 修改共享源 Skill 后，同步到工作流包
python3 scripts/sync-agent-skills.py

# 全部离线测试（无需SDK、Token或网络）
python3 -m unittest discover -v tests
```

GitHub Actions中的`repository-gates`负责离线测试、结构门禁和一次性Runner上的宿主加载验证；`tushare-live-acceptance`与`akshare-live-acceptance`均为手动触发、只读并上传脱敏JSON证据。真实验收与离线通过分开报告。

## 数据来源

- **Tushare Pro** — 主要结构化数据；6000积分用于规划VIP财务截面和同花顺板块能力，真实权限仍按接口返回验证
- **AKShare** — 补充公开网页行情、当前列表和交叉核对；无历史可得时点时不用于严格PIT回测
- **网页搜索** — 行业报告、政策解读、新闻
- **公司公告** — 经审计的数据及定性信息

## 致谢

本项目借鉴[Anthropic Financial Services cookbook](https://github.com/anthropics/financial-services)的插件与Skill架构；方法论来源、上游精确版本和修改边界见[`PROVENANCE.md`](PROVENANCE.md)与[`NOTICE`](NOTICE)。

## 许可证

见 [LICENSE](LICENSE)。
