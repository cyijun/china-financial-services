---
name: china-dcf-model
description: 为A股非金融企业构建可审计的FCFF或FCFE估值模型，明确估值日、财务版本、现金流驱动、WACC、终值、企业价值桥和敏感性。用于估值建模与模型更新；不把模型结果机械写成目标价或投资建议。
---

# A股DCF模型

## 前置条件

1. 调用`a-share-research-evidence`冻结估值日、股价日、实际披露时点和财务版本。
2. 用`china-market-data`取得原始三表、股本、行情和估值数据；历史估值不得用当前修订值回填。
3. 调用`a-share-financial-forensics`统一合并范围、币种、累计/单季和一次性项目。
4. 银行、保险、券商等受监管金融机构不使用普通FCFF；改用剩余收益、DDM或PB-ROE并说明理由。

## 建模工作流

1. 选择FCFF或FCFE并保持现金流、折现率和价值桥口径一致。
2. 从收入量价、毛利、费用、税率、折旧、资本开支和营运资本建立历史到预测桥；每个硬编码输入带来源或`[ASSUMPTION]`。
3. 基础、压力、乐观情景由经营驱动形成，不赋主观精确概率。
4. WACC按估值日构建：
   - 无风险利率使用同币种、匹配期限的中国国债收益率，记录日期与来源；
   - ERP记录估计方法、样本区间和来源；
   - Beta记录回归频率、窗口、基准及去杠杆/再加杠杆过程；
   - 债务成本优先实际增量融资成本或信用风险匹配的市场收益率；
   - 权重使用股权市值与有息债务毛额，现金只进入企业价值到股权价值桥；
   - 税率使用可持续有效税率，并披露优惠到期风险。
5. 终值同时用永续增长和退出倍数交叉检查。永续增长不得高于与现金流币种一致的长期名义经济增长而不解释。
6. 企业价值桥单列现金、有息债务、租赁、少数股东、非经营资产、联营投资、养老金及稀释股本。
7. 输出WACC×永续增长、关键经营驱动和价值桥敏感性；中心格必须等于基础情景。
8. 调用`a-share-valuation-triangulation`并列其他方法和反向隐含预期。

## 可执行计算

用`scripts/dcf_model.py config.json --output dcf-report.json`生成可复核FCFF计算。配置必须包含`valuation_date`、非空`sources`、`revenue_base`、逐年`forecast_years`、`capital`、`terminal_growth`、`bridge`和`sensitivity`；脚本不提供行业默认增长率、Beta、ERP或终值假设。它会计算CAPM股权成本、税后债务成本、市场价值权重WACC、逐年NOPAT/D&A/Capex/营运资本变化、终值、价值桥和敏感性中心格检查。

该脚本输出JSON计算底稿，不替代工作簿样式、公式重算引擎或原始数据验证；如果再由`xlsx-author`落入工作簿，仍需`audit-xls`验收。

## 工作簿契约

- 至少包含`Sources`、`Inputs`、`Historicals`、`Forecast`、`DCF`、`Sensitivity`、`Checks`。
- 蓝色为硬编码输入、黑色为本表公式、绿色为跨表链接；计算单元格不直接输入结果。
- Checks至少覆盖三表勾稽、现金流桥、折现期、终值占比、价值桥、每股价值和敏感性中心格。
- 使用`xlsx-author`生成文件，并调用`audit-xls`检查公式、错误值和结构。只有实际执行了重算引擎才能声明公式已重算；否则标记`formula_execution_unverified`。

## 硬约束

- 不使用跨日期固定的无风险利率、ERP、Beta、债务成本或永续增长率。
- 不把LPR、SHIBOR或美国国债收益率冒充中国长期无风险利率。
- 缺少可核证输入时扩大敏感性或停止，不编造单点。
- 输出区间、敏感性和不确定性，不自动给评级、买卖或仓位动作。

## 输出

交付工作簿、输入来源表、关键假设、检查结果、未验证项和方法分歧。区分`implemented`、`offline_checked`、`formula_recalculated`和`production_data_verified`。
