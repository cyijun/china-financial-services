---
name: idea-generation
description: 从A股行业研究、公司承保、财务取证和估值分歧中生成可继续验证的研究候选。用于建立研究队列和提出可证伪问题；不生成买卖、做多做空、入场、止损或仓位指令。
---

# A股研究候选生成

## 工作流

1. 固定`as_of`、可投资范围、排除规则和研究容量；历史筛选调用`china-market-data`并保留历史上市、退市和成员状态。
2. 从行业结构变化、盈利驱动变化、财报预期差、会计质量、资本配置和价格隐含预期中提出机制明确的候选。
3. 每个筛选条件先写经济逻辑、公式、方向、数据可得时点和潜在混杂；不得先看结果再改规则。
4. 涉及因子、历史胜率或回测时调用`a-share-factor-validation`。未通过PIT、样本外、成本和统计功效检查的结果只能标为探索性。
5. 调用`a-share-company-underwriting`验证真实业务暴露，调用`a-share-financial-forensics`检查盈利质量，调用`a-share-valuation-triangulation`检查隐含假设。
6. 为每个候选写核心问题、机制、支持证据、最强反证、未知、失效条件和下一条最小取证。
7. 用`a-share-research-red-team`挑战优先级；若同一上下文执行，标记`structured challenge`而非独立审查。

## 输出状态

只使用`screen hit`、`research candidate`、`inconclusive`或`invalidated`。排序依据是证据完整度、可证伪性和研究价值，不是预期收益或主观确定性。

输出研究队列与后续取证计划，不给买卖、做多做空、目标价、入场位、止损或仓位动作。
