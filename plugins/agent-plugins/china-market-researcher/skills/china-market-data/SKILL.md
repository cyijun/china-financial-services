---
name: china-market-data
description: 为中国A股研究选择并调用Tushare Pro或AKShare数据源，输出带接口、参数、抓取时间、可得时点和降级记录的结构化数据。用于行情、财务、估值、行业、ST状态及回测数据准备；严格PIT任务不得静默使用不具备历史可得时点的备用数据。
---

# 中国市场数据路由

先确定研究问题和可得时点要求，再选择数据接口。不要从“哪个接口方便”倒推研究口径。

## 数据源策略

1. 法定披露与交易所原文是高影响事实的最终依据。
2. Tushare Pro 是结构化主源。本项目按6000积分规划，但每次真实任务仍以运行时返回的权限为准。
3. AKShare 是补充源，适合公开网页行情、当前股票/行业列表和交叉核对；其上游网页、字段和可用性可能变化。
4. `MockProvider` 只用于显式离线测试，绝不能作为生产自动降级。

## 工作流

1. 把请求规范化为数据集、标的、期间、字段、`as_of`、是否严格PIT及预期行数。
2. 读取 [references/provider-matrix.md](references/provider-matrix.md) 选择主接口与备选接口；涉及历史研究或回测时同时读取 [references/point-in-time-contract.md](references/point-in-time-contract.md)。
3. 先调用Tushare。跨全市场财务截面在6000积分规划下使用 `income_vip`、`balancesheet_vip`、`cashflow_vip`、`fina_indicator_vip`、`forecast_vip` 或 `express_vip`。
4. 只有主源发生依赖、网络、权限、限流或服务错误时才考虑AKShare；参数、schema和代码错误不得触发降级，主源返回空表也不自动等于失败。
5. 若请求 `require_pit=true`，备用接口没有公告可得时点或历史成员区间时必须停止，不得静默降级。
6. 清洗后执行schema、主键、日期、单位、重复、空值和行数检查。达到接口上限时标记`partial`，`require_complete=true`则失败关闭并要求分段。
7. 输出数据及元信息：provider、interface、参数、抓取时间、`as_of`、PIT等级、过滤行数、权限是否真实验证和降级链。

## 中国市场不变量

- 财务报表按 `ann_date` / `f_ann_date` 或可核验实际披露时间生效。只有日期无时刻时，路由器保守地从上海时区次日00:00起可用；这仍不能证明完整修订历史。
- `disclosure_date` 是披露计划，不等于实际发布时刻。
- 回测用价格默认取不复权日线和复权因子分别保存；不得用今天计算的前复权序列污染历史决策。
- 历史股票池必须处理上市/退市/过会未发行状态、ST、停牌、涨跌停、指数/行业成分进出和`920xxx.BJ`等北交所代码。
- Tushare的同花顺板块接口在当前文档中要求6000积分，但版权与商业使用边界仍需遵守。
- AKShare财务报表若没有可靠公告日期，只能用于当前研究或交叉核对，不能进入严格PIT回测。

## 脚本

`scripts/china_market_data.py` 提供：

- `capabilities`：输出6000积分规划矩阵，不访问网络；
- `fetch`：显式选择 `tushare`、`akshare`、`auto` 或 `mock`；
- Tushare优先、AKShare有条件降级；
- 日期或ISO-8601时刻级`as_of`过滤、Token进程内读取、schema/单位契约、截断检测和可审计元数据。

脚本只实现`capabilities`列出的规范数据集；Skill正文提到但清单未声明的数据必须由调用方提供带来源的数据，或现场扩展并测试路由，不能假装已有接口。

运行真实接口前检查依赖和 `TUSHARE_TOKEN`。不要打印、写入或提交Token。

运行环境为Python 3.9+；按实际启用的数据源安装`tushare`或`akshare`。Tushare认证只接受进程环境中的`TUSHARE_TOKEN`。

## 输出契约

返回 `dataset`、`records`、`metadata`。如果不能满足权限或PIT要求，返回结构化错误并说明缺口；不得伪造数据或宣称未运行的接口已经可用。
