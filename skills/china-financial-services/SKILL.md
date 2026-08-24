---
name: china-financial-services
description: 中国A股金融服务仓库的目录入口。介绍5个可独立安装的子插件、依赖与使用边界；本入口本身不递归加载或路由子插件Skill。
---

# China Financial Services

本Skill只是仓库目录和加载指南。根目录不会递归加载下面5个子插件，也不能直接路由它们；需要使用哪一项，就把对应的`skills/`目录交给当前宿主。

| 插件 | 类型 | 说明 |
|---|---|---|
| `financial-analysis` | 垂直插件 | 核心财务建模与宏观数据工具 |
| `equity-research` | 垂直插件 | 盈利分析、首次覆盖报告 |
| `china-research-methodology` | 垂直插件 | Tushare/AKShare数据路由、证据链、财务取证、估值、论点、因子验证与红队 |
| `china-market-researcher` | 智能体插件 | 行业/主题研究、竞争格局、可比公司、点子筛选 |
| `china-model-builder` | 智能体插件 | DCF、可比分析、三表预测 Excel 模型 |

## 使用方式

安装相应子插件后，可以描述例如：

- "分析半导体行业竞争格局"
- "给宁德时代搭一个 DCF 模型"
- "对比银行板块主要银行的 PB/ROE"
- "按2025年末可得数据审计一个因子是否有未来函数"

安装后的对应子插件会根据任务触发自己的Skill；根入口不承担此路由。

## Kimi CLI加载独立Skill集合

Kimi Code CLI 0.33.0使用`--skills-dir`，一次指向一个Skill集合：

```bash
kimi --skills-dir ./plugins/vertical-plugins/china-research-methodology/skills \
  --skills-dir ./plugins/vertical-plugins/financial-analysis/skills
kimi --skills-dir ./plugins/vertical-plugins/equity-research/skills
kimi --skills-dir ./plugins/agent-plugins/china-market-researcher/skills
kimi --skills-dir ./plugins/agent-plugins/china-model-builder/skills
```

`--skills-dir`可重复使用，适合不安装的临时加载。Kimi交互式TUI另支持`/plugins install <path-or-url>`；安装仓库根目录只加载本目录Skill，不会递归加载子插件。纵向插件存在方法依赖；若宿主不解析依赖，应同时加载其所需集合。两个Agent插件已经自带所引用Skill的副本，可独立加载。

## 数据来源

- **Tushare Pro** — 主要结构化数据，当前按6000积分能力规划并在运行时验证权限
- **AKShare** — 公开网页数据补充，严格PIT任务不得无条件降级
- **网页搜索** — 行业报告、政策解读、新闻
- **公司公告** — 经审计数据及定性信息

> **重要声明：** 所有输出均为分析师工作底稿，需经人工审阅；不构成投资建议。
