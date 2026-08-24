# Provenance

本插件是在`china-financial-services`现有Anthropic派生架构内重新设计的方法层，不是任何券商或数据平台官方产品。

根目录[`PROVENANCE.md`](../../../PROVENANCE.md)记录上游URL、精确commit、许可证、文件族映射和修改状态。本插件的方法骨架范围为：

- Anthropic Financial Services：论点、财报、DCF和可比公司等工作流形状；Apache-2.0。
- cc-equity-research：五行商业模式、披露口径漂移和财务取证检查；Apache-2.0。
- HKUDS Vibe Trading：仅借鉴因子注册表、未来扰动、成本、交叉验证及多重检验等验证阶段思路；MIT。没有引入其运行时、行情连接器、因子库或交易引擎。
- wshobson/agents：回测偏差、样本外、walk-forward和成本概念清单；MIT。示例实现未复制。

数据能力参考Tushare Pro和AKShare官方接口文档。`provider-matrix.md`保存2026-08-24的积分与接口快照；运行时权限、上游网页、字段和商业使用边界仍需实时核对。

Skill文本为面向A股、只做分析的重新编写；不包含自动交易、账户写入、固定买卖映射或无校准的舞弊概率。
