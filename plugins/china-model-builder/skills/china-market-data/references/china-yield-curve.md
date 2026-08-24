# 中国国债收益率曲线契约

## 用途边界

- 宏观研究使用期限结构、斜率及到期/即期曲线变化。
- A股DCF使用估值日、人民币同币种、期限匹配的中国国债收益率作为无风险利率证据。
- LPR、SHIBOR和美国国债收益率不能替代中国长期人民币无风险利率。

## 数据源与覆盖

| 路径 | 接口 | 覆盖 | 限制 |
|---|---|---|---|
| 主源 | Tushare `yc_cb` | `1001.CB`国债到期/即期稠密期限曲线 | 单独权限；6000积分不保证可用 |
| AKShare标准降级 | `bond_china_yield` | 中债国债到期收益率；3月、6月、1/3/5/7/10/30年 | 单次区间小于一年；不含即期曲线 |
| AKShare近期精细降级 | `bond_china_close_return` | 国债到期、即期和远期收益率的稠密期限 | 仅近3个月；单次不超过1个月 |

官方说明：[Tushare yc_cb](https://tushare.pro/document/2?doc_id=201)、[AKShare债券数据](https://akshare.akfamily.xyz/data/bond/bond.html)。

## 规范字段

| 字段 | 规则 |
|---|---|
| `trade_date` | `YYYYMMDD`观测日 |
| `ts_code` | 规范曲线标识`1001.CB`；AKShare路径由已验证的“国债/中债国债收益率曲线”映射产生 |
| `curve_name` | `中债国债收益率曲线` |
| `curve_type` | `0`到期收益率，`1`即期收益率 |
| `yield_type` | `maturity`或`spot` |
| `curve_term` | 年，例如3月=`0.25`、6月=`0.5` |
| `yield` | 百分数，例如`1.6832`表示`1.6832%` |

AKShare宽表必须先筛选`曲线名称 == 中债国债收益率曲线`，再转成长表；不得混入商业银行债或中短期票据曲线。

## 降级决策

1. 请求必须显式提供`curve_type`，避免把到期收益率静默冒充即期收益率。
2. `curve_type=0`且期限属于标准八档时，AKShare使用`bond_china_yield`。
3. `curve_type=1`或请求非标准期限时，只能在近3个月使用`bond_china_close_return`；路由器合并`period=0.1/0.5/1`三个分段并按规范主键去重，因为单个`period`只覆盖部分期限范围。
4. 超出近期精细接口覆盖时返回`historical_coverage_unavailable`，不得插值、改用LPR/SHIBOR或更换为美债。
5. 估值日无观测时，只能在明确请求区间内选取`trade_date <= valuation_date`的最近记录，并记录实际观测日。

在`china-market-data` Skill目录内运行：

```bash
python3 scripts/china_market_data.py fetch \
  --dataset china_yield_curve \
  --provider auto \
  --params '{"ts_code":"1001.CB","curve_type":"0","curve_term":10,"trade_date":"20260820"}' \
  --as-of 20260820 \
  --require-pit
```

## DCF换算与证据

数据层保留原始百分数；写入DCF配置时转换为小数：

```text
1.6832% -> risk_free_rate = 0.016832
```

`capital.risk_free_rate_evidence`至少保存观测日、期限、币种、provider、interface、curve_type、源值和源单位。DCF脚本会验证观测日不晚于估值日，并核对源值换算后与`risk_free_rate`一致。
