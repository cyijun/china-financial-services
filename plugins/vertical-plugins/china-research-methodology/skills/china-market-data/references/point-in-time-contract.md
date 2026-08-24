# Point-in-time 数据契约

## 最小元数据

每次获取必须保留：

| 字段 | 含义 |
|---|---|
| `provider` / `interface` | 实际数据源与接口 |
| `request_params` | 去除凭证后的参数 |
| `requested_at` | 实际抓取时刻 |
| `as_of` / `as_of_precision` | 上海时区研究截止时刻及日期/时刻精度 |
| `pit_grade` | 数据是否具备交易日、公告日或成员区间 |
| `availability_fields` | 用于可得时点过滤的字段 |
| `row_count_before_pit_filter` / `row_count` | 过滤前后行数 |
| `future_rows_dropped` | 因晚于as_of被剔除的行数 |
| `fallback_from` | 主源失败和降级原因 |
| `units` / `primary_key` | 规范单位和主键 |
| `status` / `truncation_suspected` | full、empty、quality_warning或partial，以及是否撞到行数上限 |
| `pagination_complete` / `request_segment_row_counts` | 是否由短页证明分页完成及各页/分段行数 |
| `response_sha256` | 规范化响应记录哈希，用于验收与快照绑定 |

## 财务数据

- `end_date` 只表示报告期。
- 使用 `ann_date`、`f_ann_date` 或交易所精确发布时间决定数据何时可用；字段并存时采取保守的较晚时点。只有日期没有时刻时，从上海时区次日00:00起视为可用。
- 更正公告建立新版本，不静默覆盖旧研究快照。
- Tushare当次返回行即使带`update_flag`也不能证明完整双时态修订史；`require_revision_history=true`必须失败，除非接入已归档快照。
- 利润表和现金流量表季度值通常累计：单季值 = 本期累计 − 上期累计；一季度不相减。
- 若只有AKShare历史报表而没有公告日期，标记 `unsafe_for_historical_pit`。

## 行情与复权

- 原始OHLCV和复权因子分别保存。
- 路由器把当日日线可得时点保守设为上海时区16:00；用收盘形成的信号最早假设下一可成交时点。
- 前复权序列可能随未来分红送转变化。历史策略使用当时可得因子或明确定义的总回报构造。
- `adjust`派生器只接受原始行情和复权因子，锚点限定在`as_of`以内；缺因子时失败，不以今日动态qfq/hfq结果补齐。

## 基金

- `fund_basic`严格PIT时同时提取L（上市）、D（摘牌）、I（发行）状态，按`list_date`/`delist_date`过滤；摘牌日含当日，下一日剔除。
- `fund_daily`是ETF交易行情，按交易日16:00保守生效；`fund_nav`是公募基金净值，严格PIT按`ann_date`次日00:00保守生效。
- `nav_date`表示净值归属日期，不证明当时已对外发布；没有`ann_date`的净值行不得进入严格PIT研究。

## 股票池与成交

- 用当时的上市、退市、ST、停牌、涨跌停和指数/行业成员状态。
- 北交所、科创板、创业板及主板的代码、涨跌幅规则和投资者门槛不可混为一谈。
- T+1约束、最小交易单位、印花税方向和不可成交状态进入回测，而不是只写免责声明。

## 降级规则

- 严格PIT请求只接受 `calendar_date`、`trade_date`、`market_rule_date`、`reported_with_availability`、`listing_interval`或`membership_interval`等可核验等级；`reported_with_availability`不等同于完整修订历史。
- `stk_limit`按官方约9点更新保守设为09:00可用；`suspend_d`只有日期时仍不能证明盘中精确公告时点。
- 当前快照、披露计划和无公告日期历史表不能替代历史可得事实。
- `MockProvider` 结果必须带 `mock=true` 与 `production_eligible=false`，且生产路由不得自动选择它。
