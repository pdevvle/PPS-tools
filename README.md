# PPS-Tools

Tools for running Priority Print Service.

| Tool | What it does | Start it |
|---|---|---|
| **Switchboard** | Shared team inbox (email, SMS, WhatsApp, website chat and forms) with staffing (schedules, time off, time clock, timesheets) and job scheduling (jobs, stages, equipment schedule). See [docs/switchboard.md](docs/switchboard.md). | `pps switchboard run` or `python switchboard.py` |
| Competitor pricing | Discover, scrape, compare and report competitor print pricing. | `pps --help` |
| Pricing dashboard | Point-and-click front end for the pricing tool. | `python dashboard.py` |
| QuickBooks categorizer | Claude-suggested categories for uncategorized QuickBooks Online transactions, approved and written back from a web page. | `pps qb-categorize` |

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env      # QuickBooks and Anthropic keys, if you use those tools
python -m pytest -q
```

Python 3.10 or newer.
