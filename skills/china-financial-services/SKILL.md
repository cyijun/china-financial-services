---
name: china-financial-services
description: 中国 A 股金融服务插件包入口。介绍包含的 4 个子插件及安装/使用方式。
---

# China Financial Services

本插件是一个汇总入口，包含 4 个可独立使用的中国 A 股投研插件：

| 插件 | 类型 | 说明 |
|---|---|---|
| `financial-analysis` | 垂直插件 | 核心财务建模与宏观数据工具 |
| `equity-research` | 垂直插件 | 盈利分析、首次覆盖报告 |
| `china-market-researcher` | 智能体插件 | 行业/主题研究、竞争格局、可比公司、点子筛选 |
| `china-model-builder` | 智能体插件 | DCF、可比分析、三表预测 Excel 模型 |

## 使用方式

本入口插件加载后，你可以直接描述投研任务，例如：

- "分析半导体行业竞争格局"
- "给宁德时代搭一个 DCF 模型"
- "对比银行板块主要银行的 PB/ROE"

系统会根据任务调用对应子插件中的 skill。

## 安装独立插件

如果你只想安装某个子插件，可在 Kimi Code 中使用本地路径：

```bash
/plugins install ./plugins/vertical-plugins/financial-analysis
/plugins install ./plugins/vertical-plugins/equity-research
/plugins install ./plugins/agent-plugins/china-market-researcher
/plugins install ./plugins/agent-plugins/china-model-builder
```

## 数据来源

- **Tushare Pro** — 主要结构化数据
- **网页搜索** — 行业报告、政策解读、新闻
- **公司公告** — 经审计数据及定性信息

> **重要声明：** 所有输出均为分析师工作底稿，需经人工审阅；不构成投资建议。
