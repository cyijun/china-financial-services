# 中国市场数据映射

快照日期：2026-08-25。接口权限和网页上游可能变化；积分只代表规划门槛，真实可用性以当次调用为准。

## 6000积分可用主链

| 研究对象 | `china-market-data`数据集 / Tushare接口 | 口径与边界 |
|---|---|---|
| 场内基金池 | `fund_master` / `fund_basic` | 2000积分；历史池同时拉L/D/I并按上市/摘牌区间过滤。`benchmark`可作当前映射线索，但不是历史指数映射快照 |
| ETF交易行情 | `fund_daily_bar` / `fund_daily` | 5000积分；原始OHLCV，成交量为手、成交额为千元 |
| 基金净值 | `fund_nav` / `fund_nav` | 2000积分；总回报优先`adj_nav`，严格PIT按`ann_date`生效 |
| ETF份额 | `fund_share` / `fund_share` | 2000积分；`fd_share`为万份，`trade_date`是交易/变动日期；官方未给日内发布时间，不能单独满足严格PIT |
| 指数权重 | `index_weight` / `index_weight` | 2000积分；按指数和月份循环，权重为百分比 |
| 行业分类与成员 | `industry_classification`、`industry_membership` | 申万版本和进出日期进入历史PIT |
| 公司财务与估值 | 三表、`financial_indicator`、`daily_basic` | 财务按公告可得日；累计季报转单季后再做行业聚合 |

`etf_master` / `etf_basic`和`etf_index_master` / `etf_index`需要8000积分，只在能力清单中作为可选增强项；当前6000积分不能宣称可用。6000积分下先用`fund_basic.benchmark`发现线索，再以基金合同、招募说明书、交易所或指数公司页面核验ETF—指数关系。

## AKShare补充

- `fund_etf_hist_em`可补充ETF历史行情，并提供动态`qfq`/`hfq`。动态复权不能进入严格PIT回测；当前研究也要记录AKShare版本、抓取时间和`adjust`参数。
- `fund_etf_spot_em`适合当前行情、IOPV和折溢价线索，不可回填历史。
- `fund_etf_scale_sse(date)`可取得指定日期的沪市ETF份额；`fund_etf_scale_szse()`主要是当前深市公开快照。两者字段和上游网页可能变化。
- `index_stock_cons_weight_csindex`适合当前中证指数权重交叉核对；没有历史快照时不得冒充历史权重。

AKShare接口文档：[公募基金数据](https://akshare.akfamily.xyz/data/fund/fund_public.html)。规范路由没有声明的接口由研究者显式调用并附来源，不能伪装成`china-market-data`已验证能力。

## 指数映射顺序

1. 基金合同、招募说明书或产品资料概要中的业绩比较基准/标的指数；
2. 交易所ETF产品页；
3. 指数公司指数详情与编制方案；
4. `etf_basic.index_code`（有8000积分且真实验证时）；
5. `fund_basic.benchmark`仅作线索，歧义必须人工核验。

禁止仅凭ETF简称、基金名称中的行业词或搜索摘要建立映射。
