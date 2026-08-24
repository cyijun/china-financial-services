---
name: industry-etf-research
description: 以中国A股行业ETF和跟踪指数为观察入口，穿透指数编制、成分权重和上市公司基本面，研究行业价值链、景气、估值、市场确认与证据分歧。用于行业画像、ETF行业代表性检查和同主题指数比较；不用于单纯ETF筛选、自动轮动、买卖或仓位建议。
---

# 行业 ETF 穿透研究

ETF是行业研究入口和市场验证载体，不是行业定义本身。指数方法、成分暴露和公司基本面分别取证，最后才做综合判断。

## 工作流

1. 固定`as_of`、研究问题、行业分类版本与边界。先读 [references/methodology.md](references/methodology.md)，把需求、供给、周期、政策和价值链驱动拆成可证伪问题。
2. 建立ETF到跟踪指数的映射。不得从ETF简称猜指数；使用基金合同、招募说明书、交易所或指数公司材料核验。读取 [references/china-data-map.md](references/china-data-map.md) 选择数据源。
3. 审计指数暴露。取得当时有效的编制方案、成分和权重，计算集中度、指数重叠、行业匹配权重、收入纯度及覆盖率；历史研究不得用当前成分回填。
4. 沿价值链研究公司基本面。需求、供给、价格/利润、库存/产能、政策和估值分栏保存，不把规则分、概率、RPS或ETF涨幅当作基本面结论。行业驱动选择见 [references/industry-driver-library.md](references/industry-driver-library.md)。
5. 检查市场确认。分别观察ETF交易价格、复权净值、跟踪差/跟踪误差、成交额、成分广度、收盘价对NAV溢价、盘中价格对IOPV溢价和份额变化。份额变化只能形成“估算净申赎”，不能称为机构或主力资金流。
6. 将结构化证据整理为 [references/input-contract.md](references/input-contract.md) 的JSON，运行：

   ```bash
   python3 scripts/build_industry_etf_snapshot.py --input evidence.json --output snapshot.json
   python3 scripts/validate_industry_etf_report.py snapshot.json
   ```

7. 用“基本面状态 × 市场确认状态”矩阵综合，不生成统一总分。结论必须同时列支持证据、反证、数据缺口和失效条件；格式见 [references/report-contract.md](references/report-contract.md)。公式与口径见 [references/metrics-and-formulas.md](references/metrics-and-formulas.md)。

## 强制边界

- ETF名称相似不代表行业暴露相同；先核验指数规则和成分。
- 原始交易价格收益不冒充含分红总回报。优先用带公告可得时点的`adj_nav`研究基金总回报；AKShare动态qfq/hfq只能用于非严格PIT现状研究并标明口径。
- 收盘NAV溢价与盘中IOPV溢价分列；不同时间戳不得混算。
- 指数权重、行业归属和财务数据都保留可得时点。无历史快照时明确写`unverified`，不得伪造PIT。
- 不输出买卖、目标价、轮动、仓位、胜率或概率建议；需要公司层深挖时调用`a-share-company-underwriting`，需要证据审计时调用`a-share-research-evidence`和`a-share-research-red-team`。
