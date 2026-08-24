# 全量修复与验证记录

- 基线提交：`84e1dfeca74092838cc3a69f518f64ce2e97acfd`
- 验证日期：2026-08-24（Asia/Shanghai）
- 安装边界：未安装插件、Skill、Python包或其他依赖；本记录随修复提交推送，未部署Managed Agent。

## 已运行

| 检查 | 结果 | 能证明 | 不能证明 |
|---|---|---|---|
| `python3 -m unittest discover -v tests` | 30/30通过 | 时刻级PIT、财务保守生效、历史成员/生命周期、数据集特定代码、schema/单位、降级闸门、截断、Mock隔离、论点哈希链与实盘验收器脱敏 | 未于当次单元测中发起真实网络请求、实盘策略有效性 |
| `python3 scripts/check.py` | 60个文件、0错误 | 清单、依赖、Agent工具、Skill闭包、本地链接、Kimi字段、递归vendored一致性、Agent/Kimi正文一致、hooks和已知方法论回归均有效 | 外部平台实际安装与加载成功 |
| `bash scripts/test-cookbooks.sh` | 2/2通过 | 两个Managed Agent可解析为非空请求体；所需工具已启用 | 真实API部署成功 |
| Skill Creator `quick_validate.py` | 44个Skill目录、0失败 | Skill名称、frontmatter和基础结构 | 方法在真实公司的分析质量 |
| AKShare真实只读冒烟 | `stock_info_a_code_name`成功，5549行，`status=full` | 2026-08-24当次上游代码表schema兼容；`920xxx`映射到`.BJ` | 其他AKShare接口稳定性、长期可用性 |
| Tushare全接口真实只读验收 | 19项检查中18项通过，所有必需项通过；仅独立授权的`yc_cb`不可用 | 交易日历、单票日线、四类单票财务、四类VIP横截面、历史申万成员、历史ST、同花顺指数/成员及4项仓库路由集成调用在2026-08-24当次可用 | 未授权的`yc_cb`；未来权限、限流和上游schema不会变化 |

## 环境发现

- 当前登录`zsh`环境存在`TUSHARE_TOKEN`；已完成全接口及仓库路由只读验收，全程未输出、记录或写入Token。脱敏JSON证据见`docs/validation/tushare-live-acceptance-2026-08-24.json`。
- GitHub仓库已配置名为`TUSHARE_TOKEN`的Actions Secret；仅验证Secret名称和更新时间，Token值未进入仓库、日志或验收报告。
- 系统Python 3.14没有`tushare`、`akshare`或PyYAML；已有conda Python 3.13包含三者。本次没有安装新依赖。
- `check.py`在系统Python下通过Ruby Psych后备解析YAML；Managed Agent干跑同样不再强制依赖PyYAML。

## 数据能力边界

- 6000积分只用于选择VIP截面的规划，不等于Token实时拥有每项权限。
- `yc_cb`经实测返回无权限，与官方文档“单独权限接口”一致；这不是6000积分档失效。
- `index_member_all(is_new="N")`实际返回2458行，高于官方当前文档的2000行上限；路由现将此标记为文档上限漂移，不再误报为命中截断。
- Tushare财务行可按公告可得日过滤，但当次返回不能证明完整双时态修订史；`require_revision_history=true`会失败关闭。
- AKShare财务报表未纳入规范自动降级，因为中文schema、单位和公告时点契约尚不兼容。
- Tushare同花顺成员接口按当前快照处理，不能用于严格历史PIT。
- 路由不含自动交易、账户写入或隐式Mock降级。

## Tushare生产验收结论

核心只读数据链标记为`core_readonly_live_verified`：当次所有必需接口与仓库路由集成调用均通过。`yc_cb`单独标记为`optional_permission_missing`，除非后续向Tushare申请独立授权，否则不得将国债收益率曲线声称为可用能力。该验收不证明完整双时态修订史，也不证明任何投资策略有效。
