# Claude for China Market

Claude plugins and managed-agent templates for China A-share market research, powered by [Tushare](https://tushare.pro/).

> **Important:** Nothing in this repository constitutes investment, legal, tax, or accounting advice. These agents draft analyst work product for review by a qualified professional. They do not make investment recommendations, execute transactions, or bind risk. Every output is staged for human sign-off.

## What's included

| Agent | Description | Output |
|---|---|---|
| **china-market-researcher** | Sector/theme → industry overview → competitive landscape → peer comps → ideas shortlist | Research note or slides |
| **china-model-builder** | DCF, trading comps, 3-statement model for A-share companies | Excel workbook |

| Vertical Plugin | Description |
|---|---|
| **financial-analysis** | Core financial modeling tools: A-share comps, DCF, macro data, Tushare data skill |
| **equity-research** | Initiating coverage reports, earnings analysis for China A-share |

## Repository Structure

```
plugins/
  agent-plugins/
    china-market-researcher/      # Named end-to-end workflow agent
    china-model-builder/
  vertical-plugins/
    financial-analysis/           # Skills, commands
    equity-research/
managed-agent-cookbooks/
  china-market-researcher/        # Deploy manifest for POST /v1/agents
  china-model-builder/
scripts/
  check.py                        # Lint and verify all manifests
  sync-agent-skills.py            # Sync bundled skills from vertical sources
  deploy-managed-agent.sh         # Deploy a cookbook to CMA
  test-cookbooks.sh               # Dry-run all cookbooks
```

## Installation

### Claude Cowork (Desktop / Web)

Paste the repo URL in **Settings → Plugins → Add plugin**, or zip any directory under `plugins/` and upload it.

### Claude Code (CLI)

```bash
claude plugin marketplace add <your-org>/claude-for-china-market
claude plugin install china-market-researcher@china-financial-services
claude plugin install china-model-builder@china-financial-services
```

### Claude Managed Agents (API)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
scripts/deploy-managed-agent.sh china-market-researcher
```

Requires `jq`, `zip`, `curl`, and `python3 + pyyaml`.

## Development

```bash
# Lint everything
python3 scripts/check.py

# After editing a skill in vertical-plugins/, sync to agent bundles
python3 scripts/sync-agent-skills.py

# Dry-run all cookbooks
bash scripts/test-cookbooks.sh
```

## Data Sources

- **Tushare Pro** — primary structured data (financial statements, valuations, macro data)
- **Web search** — industry reports, policy interpretation, news
- **Company announcements** — audited figures and qualitative details

## License

See [LICENSE](LICENSE).
