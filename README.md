# China Financial Services

English | [中文](README.zh.md)

A multi-plugin marketplace for China A-share research on Codex and Claude Code, with local Marketplace compatibility for Kimi Code CLI. Structured data comes primarily from [Tushare](https://tushare.pro/), with controlled AKShare supplements.

> **Important:** Nothing in this repository constitutes investment, legal, tax, or accounting advice. These agents draft analyst work product for review by a qualified professional. They do not make investment recommendations, execute transactions, or bind risk. Every output is staged for human sign-off.

## What's included

| Agent | Description | Output |
|---|---|---|
| **china-market-researcher** | Sector/theme/industry ETF → industry and index-exposure audit → competition → peer comps | Research note or slides |
| **china-model-builder** | DCF, trading comps, 3-statement model for A-share companies | Excel workbook |

| Vertical Plugin | Skills | Description |
|---|---|---|
| **financial-analysis** | `tushare-data`, `china-dcf-model`, `china-comps-analysis`, `3-statement-model`, `audit-xls`, `china-macro-overview` | Financial modeling, audit, and macro tools; declares its methodology dependency for Claude |
| **equity-research** | `china-initiating-coverage` | Initiating coverage reports for China A-share |
| **china-research-methodology** | `china-market-data` plus 9 methodology skills | Tushare/AKShare routing, PIT evidence, industry-ETF penetration, forensics, valuation, thesis, factor validation, and red-team review |

## Repository Structure

```
.agents/plugins/marketplace.json    # Codex marketplace
.claude-plugin/marketplace.json     # Claude Code marketplace
kimi-marketplace.json               # Kimi local-clone marketplace
plugins/
  china-research-methodology/       # Shared methods and data-routing source
  financial-analysis/               # Shared modeling and valuation source
  equity-research/                  # Shared equity-research source
  china-market-researcher/          # Self-contained workflow + vendored skills
  china-model-builder/              # Self-contained workflow + vendored skills
scripts/
  check.py                        # Lint and verify all manifests
  sync-agent-skills.py            # Sync workflow bundles from shared sources
  preflight.py                    # Verify Python/runtime/credential readiness
  tushare_live_acceptance.py      # Sanitized, read-only live acceptance
  akshare_live_acceptance.py      # Sanitized acceptance for every declared AKShare route
```

## Examples

Versioned sample artifacts are available in [`out/`](out/).

![CLI demo](out/demo.png)

- [`portfolio_2026Q2.xlsx`](out/portfolio_2026Q2.xlsx) with [rendered preview](out/excel_report.png)
- [`portfolio_roadshow_2026Q2.pptx`](out/portfolio_roadshow_2026Q2.pptx) with [rendered preview](out/ppt_report.png)

## Installation

### Codex (CLI / desktop)

The repository is a native [Codex Marketplace](https://learn.chatgpt.com/docs/build-plugins) through `.agents/plugins/marketplace.json`. Register it once, then add only the plugins you need:

```bash
codex plugin marketplace add cyijun/china-financial-services --ref main
codex plugin add china-research-methodology@china-financial-services
codex plugin add financial-analysis@china-financial-services
codex plugin add equity-research@china-financial-services
```

The two self-contained workflow bundles can be installed independently:

```bash
codex plugin add china-market-researcher@china-financial-services
codex plugin add china-model-builder@china-financial-services
```

Codex does not consume Claude's plugin dependency declarations. Install the shared plugins in the displayed order when a task spans methodology, financial analysis, and equity research. This repository intentionally contains neither remote Managed Agent deployment nor command hooks.

### Kimi Code (CLI)

Kimi Code CLI 0.33.0 supports [custom Marketplace JSON](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/plugins.html#custom-marketplace-json), but its current remote installer does not reliably resolve plugins stored in monorepo subdirectories ([upstream issue](https://github.com/MoonshotAI/kimi-code/issues/2945)). After cloning this repository, open Kimi from the repository root and browse the local catalog:

```bash
git clone https://github.com/cyijun/china-financial-services.git
cd china-financial-services
kimi
```

Then run inside the Kimi TUI:

```text
/plugins marketplace ./kimi-marketplace.json
```

For a no-install, session-scoped load, use repeatable `--skills-dir` flags:

```bash
kimi --skills-dir ./plugins/china-research-methodology/skills \
  --skills-dir ./plugins/financial-analysis/skills
kimi --skills-dir ./plugins/china-market-researcher/skills
```

### Claude Code (CLI)

The same repository is a [Claude Code Marketplace](https://code.claude.com/docs/en/plugin-marketplaces) through `.claude-plugin/marketplace.json`. Claude resolves the declared same-marketplace dependencies for `financial-analysis` and `equity-research`:

```bash
claude plugin marketplace add cyijun/china-financial-services
claude plugin install china-research-methodology@china-financial-services
claude plugin install financial-analysis@china-financial-services
claude plugin install equity-research@china-financial-services
claude plugin install china-market-researcher@china-financial-services
claude plugin install china-model-builder@china-financial-services
```

### Claude Cowork (Desktop / Web)

Paste the repo URL in **Settings → Plugins → Add plugin**, or zip any directory under `plugins/` and upload it.

## Development

```bash
# Lint everything (CI gate)
python3 scripts/check.py

# After editing a shared source skill, sync the workflow bundles
python3 scripts/sync-agent-skills.py

# Offline tests (no SDK, token, or network required)
python3 -m unittest discover -v tests
```

The `repository-gates` GitHub Action runs offline tests, structural gates and disposable-runner host loading. `tushare-live-acceptance` and `akshare-live-acceptance` are separate, manually dispatched, read-only workflows that upload sanitized JSON evidence; offline success is never presented as live availability.

## Data Sources

- **Tushare Pro** — primary structured data; the 6000-point profile plans for VIP financial cross-sections and THS sector endpoints, with live permission checks still required
- **AKShare** — supplemental public-web data, including raw ETF history; never a silent fallback when strict point-in-time evidence is unavailable
- **Web search** — industry reports, policy interpretation, news
- **Company announcements** — audited figures and qualitative details

## Credits

This project is adapted from the [Anthropic Financial Services cookbook](https://github.com/anthropics/financial-services) plugin/skill architecture. Methodology provenance, exact upstream revisions and modification boundaries are recorded in [`PROVENANCE.md`](PROVENANCE.md) and [`NOTICE`](NOTICE).

## License

See [LICENSE](LICENSE).
