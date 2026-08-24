---
name: tushare-data
description: 将A股行情、财务、估值、资金、行业与宏观查询映射到Tushare接口，并保留接口、参数、单位和抓取时间。用于当前数据查询或原始取数；历史研究、回测和多源降级必须改用china-market-data。
---

# Tushare原始数据助手

## 使用边界

- 当前、非PIT查询可直接使用本Skill。
- 涉及`as_of`、公告可得日、历史股票池、回测、AKShare降级或生产资格时，必须调用`china-market-data`，本Skill不能宣称数据“回测可用”。
- Token只从进程环境`TUSHARE_TOKEN`读取；不得调用全局Token缓存、打印、写入或提交凭证。

## 工作流

1. 将问题拆成接口、标的、日期、字段、频率、单位和预期行数。
2. 在Tushare官方文档核对接口名、参数、字段、积分与行数限制；6000积分只是规划画像，实际权限以本次调用为准。
3. 单票财务用`income`、`balancesheet`、`cashflow`、`fina_indicator`；全市场截面在权限允许时用对应`*_vip`接口。
4. 行情保存不复权价格与`adj_factor`，不把动态前复权序列直接称作PIT价格。
5. 分页或分段获取后检查主键、重复、空值、单位和行数上限。空表先诊断日期、参数、上市状态和权限，不自动换源。
6. 输出原始数据与元信息：接口、去敏参数、抓取时间、返回行数、单位、权限结果和限制。

## 常用接口

使用[references/数据接口.md](references/数据接口.md)中的精简清单。不要根据旧接口大全猜测名称或字段；清单外接口先查官方文档。

## 输出

区分`documented`、`live_call_succeeded`、`permission_denied`、`empty`和`partial`。未运行的接口不能标成可用，离线样例不能标成真实权限验证。
