---
name: xlsx-author
description: 在无已打开Excel会话的无头环境中生成可审计的.xlsx文件。用于三表、DCF、可比公司等需要交付工作簿文件的任务；若有可控的实时Excel会话则优先使用实时工具。
---

# 无头Excel工作簿生成

## 使用场景

当CI、Codex、Claude Code或其他命令行环境没有实时Office工具，而下游Skill明确需要`.xlsx`文件时使用。默认通过Python `openpyxl`写入`./out/<name>.xlsx`；先创建`./out/`，最终返回相对路径供调用方收集。

## 工作簿约定

- 输入、公式与跨表链接分别使用蓝、黑、绿字体；所有硬编码输入必须集中在Inputs或Sources并带来源/`[ASSUMPTION]`。
- 计算单元格使用公式，不直接粘贴最终结果；需被报告引用的关键值建立命名范围。
- Checks页至少覆盖模型特有的勾稽、错误值、终值/价值桥或敏感性中心格。
- 默认每次创建新文件；除非用户明确要求，不覆盖现有工作簿。
- `openpyxl`写入公式不等于公式已由Excel/LibreOffice重算。未调用真实重算引擎时必须写`formula_recalculation_unverified`。

## 最小实现

用短Python脚本创建工作簿、样式、公式、命名范围和Checks页，保存到`./out/`。随后调用`audit-xls`检查结构、公式和错误值；只有实际执行过重算引擎，才可把公式状态从`implemented`提升为`formula_recalculated`。

## 不使用场景

若宿主提供并已连接实时Excel控制工具，使用实时工具并保留用户审阅检查点。本Skill只负责文件型回退，不驱动交易或账户系统。
