---
name: china-initiating-coverage
description: 为A股上市公司组织证据优先的首次覆盖研究底稿，串联公司承保、财务取证、预测、估值、论点和红队审查。用于完整公司研究报告；不生成券商署名、评级、目标价或投资建议。
---

# A股首次覆盖研究

## 工作流

1. 明确公司、问题、覆盖范围、`as_of`、市场时区和受众；先调用`a-share-research-evidence`形成证据包。
2. 调用`a-share-company-underwriting`完成商业模式、盈利驱动、行业结构、竞争优势和治理研究。
3. 调用`a-share-financial-forensics`统一报告版本、累计/单季、三表勾稽、盈利质量和会计风险。
4. 如需预测或工作簿，调用`3-statement-model`；所有驱动、来源、情景和勾稽必须可复核。
5. 调用`a-share-valuation-triangulation`并列DCF、可比、历史、PB-ROE/剩余收益、SOTP或中周期方法，展示敏感性与价格隐含预期。
6. 调用`a-share-thesis-tracker`建立可证伪支柱、反证、失效条件和验证日历。
7. 在另一个独立上下文可用时由独立审阅者执行`a-share-research-red-team`；同一上下文执行只能标记为`structured challenge`，不能声称独立。
8. 汇编结论摘要、证据、未知和后续验证。图表只展示有来源、日期、单位和可复现定义的数据。

## 报告结构

- 研究问题与证据状态
- 公司与盈利驱动
- 行业、价值链和竞争机制
- 财务历史、预测与质量
- 多方法估值及隐含预期
- 核心论点、反证和失效条件
- 风险、未知、数据限制和验证日历
- 来源台账与附录

## 硬约束

- 不仿冒持牌券商、分析师署名、执业编号或合规审阅。
- 不使用报告发布日期之后的信息污染当时视角。
- 不把共识、行业中位数或DCF单点机械变成目标价。
- 不输出买入、卖出、仓位、止损或自动交易动作。
- 未执行的模型、审计、红队或真实数据调用不得写成通过。

## 渐进式资料

仅在对应阶段读取[公司研究](references/task1-company-research.md)、[财务建模](references/task2-financial-modeling.md)、[估值](references/task3-valuation.md)、[图表](references/task4-chart-generation.md)、[报告汇编](references/task5-report-assembly.md)和[估值方法](references/valuation-methodologies.md)。

## 输出

交付研究底稿及可选附件，并明确`evidence_status`、`as_of`、运行过的检查、未验证项、方法分歧与生产数据状态。
