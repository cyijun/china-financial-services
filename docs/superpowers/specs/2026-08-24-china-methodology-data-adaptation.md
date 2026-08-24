# 中国市场方法论与数据源适配设计

## 目标

在保留原有Anthropic派生插件结构、Claude/Kimi兼容性和人工签核边界的基础上，增加一套可独立安装的A股方法论插件，并把Tushare 6000积分与AKShare纳入可审计数据路由。

## 架构

新增`plugins/vertical-plugins/china-research-methodology`作为唯一源，包含：

- `china-market-data`：Tushare优先、AKShare受控降级、Mock显式离线测试；
- `a-share-research-evidence`：所有下游研究的PIT证据闸门；
- 公司承保式研究、财务取证、财报预期差、多方法估值、论点追踪、因子验证和研究红队八个方法Skill。

`china-market-researcher`打包全部九项；`china-model-builder`只打包数据、证据、取证和估值四项。Vertical目录永远是源，agent目录是机械vendored副本。

## 6000积分策略

按2026-08-24官方文档，6000积分足以规划：

- 2000起：`stock_basic`、`trade_cal`、`daily_basic`、三表基础接口、`fina_indicator`、`forecast`、`express`、`index_classify`、`index_member_all`；
- 3000起：`stock_st`；
- 5000起：三表、指标、预告和快报VIP全市场截面；
- 6000：`ths_index`、`ths_member`。

`anns_d`属于单独权限；当前文档显示`adj_factor`为2000积分起，`yc_cb`等仍可能有单独权限。积分档案只做规划，不能替代真实Token权限验证。

## PIT与降级

- 财务数据用`ann_date`/`f_ann_date`过滤，字段并存时采用较晚日期；只有日期无时刻时从上海时区次日00:00起可用。该过滤不声称具备完整双时态修订历史。
- `disclosure_date`只是计划日期。
- 原始行情与复权因子分开保存。
- AKShare日线可在保留交易日期和来源时补充；当前股票/行业列表与无公告日期财务报表不能用于严格历史PIT。
- 主源空表不触发自动换源；只有依赖、凭证、权限、限流、网络、服务或SDK缺失才进入降级判断，程序和schema错误失败关闭。
- Mock永远不出现在自动生产路由中。

## 安全

- Token只从`TUSHARE_TOKEN`读取并传给进程内客户端，不调用持久化Token API。
- 元数据和异常文本对Token做替换，不写配置文件。
- 数据脚本只读，不包含账户、委托、撤单或交易状态写入。

## 验证层级

1. 标准库Fake客户端测试：VIP路由、保守公告日过滤、AKShare字段标准化、降级血缘、严格PIT拒绝和Mock隔离。
2. Skill结构、插件manifest、vendored一致性和cookbook dry-run。
3. 真实Tushare/AKShare冒烟：仅在依赖和Token存在后运行；本设计不把离线通过写成生产可用。
