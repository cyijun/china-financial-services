# Upstream provenance

Snapshot date: 2026-08-24. This repository is an independent, modified A-share adaptation; it is not an official product of Anthropic, HKUDS, any broker, Tushare, AKShare, or the other upstream authors.

| Upstream | Pinned revision inspected | License | Local use |
|---|---|---|---|
| [anthropics/financial-services](https://github.com/anthropics/financial-services) | `33a3d8a9d6e5c3d4861731933a8857cc5e03315d` | Apache-2.0 | Plugin/Skill layout; the financial-analysis, equity-research, market-researcher and model-builder workflow families. Local copies are translated, renamed, adapted to China-market data, or materially modified. |
| [prof-little-bear/cc-equity-research](https://github.com/prof-little-bear/cc-equity-research) | `7c428944a6718c35461f839c618ae66334b6371b` | Apache-2.0 | The five-line business-model decomposition from `community-skills/analyze/business-model.md`; disclosure-quality and financial-forensics prompts from `community-skills/analyze/reporting-quality.md` and `financial-forensics.md`. |
| [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | `99e84abaad965f75dd15cab2fcb0f3f61d30577b` | MIT | Narrow implementation inspiration for factor registries, look-ahead tests, costs, cross-validation and multiple-testing diagnostics. No Vibe-Trading runtime, market connector, factor library, UI, or trading engine is vendored here. |
| [wshobson/agents](https://github.com/wshobson/agents) | `d82998e7df393c671ede2387a8435075f0b633f5` | MIT | Backtest-bias taxonomy, walk-forward/OOS and transaction-cost checklist from `plugins/quantitative-trading/skills/backtesting-frameworks/`. Its sample implementation is not copied. |

## Local mapping and modification status

- `plugins/financial-analysis/` and `plugins/equity-research/` descend from the corresponding Anthropic workflow families. China-specific names, Tushare/AKShare integration, evidence controls and executable validation are local modifications.
- `plugins/china-market-researcher/` and `plugins/china-model-builder/` descend from Anthropic's `market-researcher` and `model-builder` plugin shapes, but are self-contained Skill bundles in this repository.
- `a-share-company-underwriting` maps the cc-equity-research five-line structure to Chinese annual reports, prospectuses, exchange inquiries, administrative pricing and A-share governance evidence.
- `a-share-financial-forensics` combines independently written A-share accounting checks with the upstream disclosure-quality lenses; it does not output fraud probabilities.
- `a-share-factor-validation/scripts/` is a new, dependency-light local implementation. It reports diagnostics and remains `inconclusive` until caller-defined preregistered gates are evaluated; it is not a trading engine.
- `china-market-data` and the live acceptance suite are local implementations based on official TuShare Pro and AKShare documentation, not on the four repositories above.

The `sources/upstream/` working copies used for comparison are deliberately outside this Git repository and are not redistributed. See `NOTICE` and the root Apache-2.0 `LICENSE` for redistribution terms.
