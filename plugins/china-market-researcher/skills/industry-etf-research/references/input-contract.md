# 确定性快照输入契约

根对象使用`schema_version: industry-etf-input/v1`，至少包含：

```json
{
  "schema_version": "industry-etf-input/v1",
  "as_of": "2026-08-25",
  "require_pit": false,
  "horizons": [20, 60, 120],
  "industry": {
    "name": "半导体",
    "taxonomy": "申万2021",
    "scope": "研究边界说明",
    "evidence_ids": ["ev-industry"]
  },
  "indices": [],
  "etfs": [],
  "state_assessment": {
    "fundamental_state": "unclear",
    "market_state": "unclear",
    "fundamental_evidence_ids": [],
    "market_evidence_ids": []
  },
  "counterevidence": ["至少一条反证或待验证假设"],
  "limitations": ["至少一项数据或方法限制"],
  "evidence": []
}
```

## 指数对象

`index_code`、`name`、`methodology_url`、`evidence_ids`、`constituents_as_of`、`constituents_pit_grade`和`constituents`为必需。`constituents_pit_grade`可写`trade_date`、`historical_snapshot`、`current_snapshot`或`unverified`；严格PIT只接受前两种。每个成分至少有`ts_code`和非负`weight_pct`；可选：

- `industry_match`: `true`、`false`或缺失；
- `industry_revenue_share_pct`: 0到100；
- `return_pct`: 用于成分广度的同窗收益；
- `above_ma`: 用于均线上方广度；
- `levels`: 指数点位序列，元素为`trade_date`、`close`。

## ETF对象

至少有`ts_code`、`name`、`index_code`、`evidence_ids`和`price_basis`。可选序列：

- `price_bars`: `trade_date`、`close`和可选`amount`；有成交额时必须声明`amount_unit`为`CNY`或`thousand_CNY`；
- `adjusted_nav`: `nav_date`、`adj_nav`和可选`unit_nav`、`ann_date`；严格PIT时每行必须有`ann_date`，且按日期字段次日可用；
- `shares`: `trade_date`、`shares`；ETF对象必须声明`share_unit`为`shares`或`ten_thousand_shares`；严格PIT时每行还要有已归档的`available_at`时间戳；
- `realtime_snapshot`: 同一`observed_at`下的`price`和`iopv`。

序列日期不可重复且不得晚于`as_of`。脚本按日期排序，N期收益指最后N个观测间隔。`require_pit=true`时，交易价格只接受`raw`；总回报使用带公告可得日的复权净值。

## 证据对象

每条证据必须有唯一`id`、`title`、`source`和`observed_at`或`available_at`。结构化取数另保留`provider`、`interface`、`request_params`、`pit_grade`、`response_sha256`；网页证据保留原始URL和抓取时刻。

非`unclear`的基本面/市场状态必须引用证据ID。指数、ETF和行业对象也必须引用证据，所有引用ID必须存在。
