# PPS-Tools

Tools for running Priority Print Service.

| Tool | What it does | Start it |
|---|---|---|
| **PPS Books** | Double-entry bookkeeping and invoicing with Stripe for online payments: sales, expenses, bank files and reconciliation, inventory, sales tax, projects and time, budgets, 80 reports, a REST API, and a QuickBooks Online migration. See [docs/books.md](docs/books.md). | `pps books serve` (try `pps books demo` first) |
| Competitor pricing | Discover, scrape, compare and report competitor print pricing. | `pps --help` |
| Pricing dashboard | Point-and-click front end for the pricing tool. | `python dashboard.py` |
| QuickBooks categorizer | Claude-suggested categories for uncategorized QuickBooks Online transactions, approved and written back from a web page. | `pps qb-categorize` |

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env      # QuickBooks, Stripe and Anthropic keys, if you use those tools
python -m pytest -q
```

Python 3.10 or newer.
