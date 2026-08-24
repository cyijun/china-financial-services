# China Financial Services

English | [中文](README.zh.md)

Portable Codex, Claude Code and Kimi skills/plugins for China A-share market research, powered by [Tushare](https://tushare.pro/) and controlled AKShare supplements.

> **Important:** Nothing in this repository constitutes investment, legal, tax, or accounting advice. These agents draft analyst work product for review by a qualified professional. They do not make investment recommendations, execute transactions, or bind risk. Every output is staged for human sign-off.

## What's included

| Agent | Description | Output |
|---|---|---|
| **china-market-researcher** | Sector/theme → industry overview → competitive landscape → peer comps → ideas shortlist | Research note or slides |
| **china-model-builder** | DCF, trading comps, 3-statement model for A-share companies | Excel workbook |

| Vertical Plugin | Skills | Description |
|---|---|---|
| **financial-analysis** | `tushare-data`, `china-dcf-model`, `china-comps-analysis`, `3-statement-model`, `audit-xls`, `china-macro-overview` | Financial modeling, audit, and macro tools; declares its methodology dependency for Claude |
| **equity-research** | `china-initiating-coverage` | Initiating coverage reports for China A-share |
| **china-research-methodology** | `china-market-data` plus 8 methodology skills | Tushare/AKShare routing, PIT evidence, forensics, valuation, thesis, factor validation, and red-team review |

## Repository Structure

```
plugins/
  agent-plugins/
    china-market-researcher/      # End-to-end workflow agent + bundled skills
    china-model-builder/
  vertical-plugins/
    financial-analysis/           # Skills (source of truth)
    equity-research/
    china-research-methodology/   # Evidence-first methods and China data routing
scripts/
  check.py                        # Lint and verify all manifests
  sync-agent-skills.py            # Sync bundled skills from vertical sources
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

All five sub-plugins include native `.codex-plugin/plugin.json` manifests. Register the GitHub repository as a marketplace and add only the packages you need. These commands were checked against the local `codex-cli 0.149.0`; this repository does not install plugins for you.

```bash
codex plugin marketplace add cyijun/china-financial-services --ref main
codex plugin add china-research-methodology@china-financial-services
codex plugin add financial-analysis@china-financial-services
codex plugin add equity-research@china-financial-services
```

The two self-contained workflow bundles can also be added independently:

```bash
codex plugin add china-market-researcher@china-financial-services
codex plugin add china-model-builder@china-financial-services
```

Codex loads each plugin's `skills/` directory. Agent plugins run as self-contained skill workflows; this repository intentionally contains neither remote-agent deployment support nor command hooks. Add vertical plugins in this order: `china-research-methodology` → `financial-analysis` → `equity-research`.

### Kimi Code (CLI)

For a no-install, session-scoped load, Kimi Code CLI 0.33.0 exposes repeatable `--skills-dir` flags:

```bash
kimi --skills-dir ./plugins/vertical-plugins/china-research-methodology/skills \
  --skills-dir ./plugins/vertical-plugins/financial-analysis/skills
kimi --skills-dir ./plugins/agent-plugins/china-market-researcher/skills
```

Kimi's interactive TUI also supports persistent `/plugins install <path-or-url>` and recognizes `.kimi-plugin/plugin.json`; this repository does not run that command for you. Installing the repository root loads only its catalog Skill, while each agent plugin vendors every Skill its workflow invokes and can be loaded independently.

### Claude Code (CLI)

Automatic dependency resolution requires Claude Code 2.1.110 or later. On older versions, install `china-research-methodology`, then `financial-analysis`, then `equity-research` manually.

```bash
claude plugin marketplace add cyijun/china-financial-services
claude plugin install china-market-researcher@china-financial-services
claude plugin install china-model-builder@china-financial-services
claude plugin install china-research-methodology@china-financial-services
```

### Claude Cowork (Desktop / Web)

Paste the repo URL in **Settings → Plugins → Add plugin**, or zip any directory under `plugins/` and upload it.

## Development

```bash
# Lint everything (CI gate)
python3 scripts/check.py

# After editing a skill in vertical-plugins/, sync to agent bundles
python3 scripts/sync-agent-skills.py

# Offline tests (no SDK, token, or network required)
python3 -m unittest discover -v tests
```

The `repository-gates` GitHub Action runs offline tests, structural gates and disposable-runner host loading. `tushare-live-acceptance` and `akshare-live-acceptance` are separate, manually dispatched, read-only workflows that upload sanitized JSON evidence; offline success is never presented as live availability.

## Data Sources

- **Tushare Pro** — primary structured data; the 6000-point profile plans for VIP financial cross-sections and THS sector endpoints, with live permission checks still required
- **AKShare** — supplemental public-web data; never a silent fallback when strict point-in-time evidence is unavailable
- **Web search** — industry reports, policy interpretation, news
- **Company announcements** — audited figures and qualitative details

## Credits

This project is adapted from the [Anthropic Financial Services cookbook](https://github.com/anthropics/financial-services) plugin/skill architecture. Methodology provenance, exact upstream revisions and modification boundaries are recorded in [`PROVENANCE.md`](PROVENANCE.md) and [`NOTICE`](NOTICE).

## License

See [LICENSE](LICENSE).
