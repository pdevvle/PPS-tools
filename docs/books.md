# PPS Books

Double-entry bookkeeping and invoicing for a small business, with **Stripe for every online payment**. It runs as a web app (`pps books serve`) on your own machine or server, stores everything in one SQLite database (or Postgres), and covers what a QuickBooks Online Plus/Advanced user works with day to day.

- [Quick start](#quick-start)
- [What's in it](#whats-in-it)
- [Stripe](#stripe)
- [Moving from QuickBooks Online](#moving-from-quickbooks-online)
- [Running it for real](#running-it-for-real)
- [Configuration](#configuration)
- [Command line](#command-line)
- [REST API](#rest-api)
- [How the books work](#how-the-books-work)
- [Not included yet](#not-included-yet)

## Quick start

```bash
pip install -e ".[dev]"
pps books demo                          # a print shop with six months of activity, in ./books-demo
pps books serve --data-dir books-demo   # http://127.0.0.1:5080, sign in as demo@example.com / demo-books-123
```

For your own company, run `pps books serve` and fill in the setup page (or `pps books setup`). It creates a chart of accounts for a print shop or a general business, default terms and payment methods, and the first admin user.

## What's in it

**Sales.** Estimates (accept or decline online), invoices, sales receipts, credit memos, refund receipts, delayed charges and credits, receive payment (applies to oldest first or as you choose, uses credits), deposits from *Payments to deposit*, refunds of customer credit. Progress invoicing (bill an estimate in parts: a percentage or whatever is left), billable expenses and time pulled onto invoices with markup, statements (balance forward, open item, transaction), payment reminders and late fees, a customer portal, custom fields, invoice PDFs with your logo and colors, emailed with the PDF attached.

**Expenses.** Bills, bill payments (pay several at once), checks with check printing, expenses, credit card charges and credits, vendor credits, purchase orders received in part or full, 1099 tracking with per-box account mapping and a filing export (thresholds: $600 through 2025, $2,000 from 2026; royalties $10; attorneys' gross proceeds $600).

**Banking.** Upload CSV, OFX, QFX or QBO (Web Connect) files from any bank or card; importing the same file twice adds nothing. Bank rules (conditions, splits, auto-add), matching to what's already in the books (including open invoices, bills and undeposited payments), receipts inbox, transfers, credit card payments, and reconciliation with service charges, interest, a discrepancy adjustment, reports and undo. Optional: Claude suggests categories and reads receipts.

**Products and inventory.** Services, non-inventory and inventory items, bundles, categories, FIFO costing that replays history when you backdate, quantity adjustments, reorder points, inventory valuation reports.

**Sales tax.** Agencies, single and combined rates, exemptions, overrides, a sales tax center by filing period (monthly, quarterly, yearly) with payments and adjustments.

**Projects, time and mileage.** Projects as sub-customers with job costing (income, expenses, labor at cost rates), single time entries and a weekly timesheet, billable rates, mileage log at the IRS rate in effect on each trip's date (72.5¢ in 2026).

**Accounting.** Chart of accounts with sub-accounts and numbers, journal entries, recurring transactions (scheduled, reminder, unscheduled; email automatically; autopay through Stripe), budgets by month split by customer, class or location, classes, locations, tags, closing date with password, an audit log of every change with before and after.

**Reports.** 80 reports, all with date presets, cash or accrual basis, columns by month/quarter/year/customer/class/location, comparisons, % of income, drill-down to transactions, CSV and PDF export, saved customizations and scheduled email: Profit and Loss (and by month, customer, class, location, comparison), Balance Sheet, Statement of Cash Flows, Trial Balance, General Ledger, Journal, A/R and A/P aging, customer and vendor balances, open invoices, collections, sales by customer and by product, expenses by vendor, 1099 summary, sales tax liability, inventory valuation, budget vs. actuals, project profitability, time, mileage, Stripe fees and payouts, reconciliation reports, and more.

**People.** Roles: company admin, accountant, standard (all), sales only, purchases only, reports only, time only, view only. Locked after repeated failed sign-ins; changing a password signs out other sessions.

**Data.** CSV import of customers, vendors, products, the chart of accounts (with opening balances) and journal entries, with column matching; migration from QuickBooks Online; everything as a ZIP of CSVs; a SQLite backup; a REST API.

## Stripe

All online payments go through Stripe: cards (including Apple Pay and Google Pay), US bank accounts (ACH), partial payments if you allow them, saved cards for autopay on recurring invoices, refunds, and disputes.

### Connect

1. In the Stripe Dashboard, copy your **secret key** (or a restricted key with read/write on Checkout Sessions, Customers, PaymentIntents and Refunds, and read on Charges, Balance, Balance Transactions, Payouts and Disputes).
2. Add a webhook endpoint at `https://<your BOOKS_BASE_URL>/stripe/webhook` for these events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `payment_intent.succeeded`, `charge.refunded`, `refund.updated`, `charge.dispute.created`, `charge.dispute.closed`, `payout.paid`, `payout.failed`. Copy its signing secret.
3. Put both in the environment (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`) or in **Settings → Payments**, choose the bank account Stripe pays out to, and turn on online payments.

Test mode keys (`sk_test_…`) work the same way, so you can try the whole flow first. Locally, `stripe listen --forward-to localhost:5080/stripe/webhook` forwards events.

### How the money is recorded

A bank-type account, **Stripe Balance**, mirrors your Stripe balance:

| In Stripe | In the books |
|---|---|
| A customer pays an invoice | A payment into Stripe Balance, applied to the invoice |
| Stripe keeps its fee | An expense from Stripe Balance to *Merchant Processing Fees* (or the account you choose) |
| A payout | A transfer from Stripe Balance to your bank account; when the bank file comes in, it matches the transfer |
| A refund | A refund receipt out of Stripe Balance (*Refunds & Allowances*) |
| A dispute | A chargeback expense, and its fee; won disputes put the money back |
| A charge made outside the books (Payment Link, Dashboard) | Picked up by **Payments → Sync** or `pps books stripe-sync` as a payment flagged for review |

Every Stripe object is recorded once, however many times its webhook arrives, and the success page records the payment straight away if the webhook is slow. Stripe Balance in the books should equal the balance in Stripe; the Payments page shows both.

## Moving from QuickBooks Online

**Settings → Import data → From QuickBooks Online** connects with your Intuit app (`QBO_CLIENT_ID` and `QBO_CLIENT_SECRET`, redirect URI `<BOOKS_BASE_URL>/settings/import/qbo/callback`) and brings over, as of a conversion date you choose:

- lists: accounts (mapped to the built-in A/R, A/P, Undeposited Funds, Opening Balance Equity and similar), terms, payment methods, classes, locations, sales tax agencies and rates, customers and projects, vendors with 1099 flags, employees, products and services;
- every open invoice, bill, credit memo, vendor credit and unapplied payment, with its original number, date and due date, so aging and statements carry on;
- inventory quantities at purchase cost, and the trial balance on the conversion date as one journal entry, with bank and card balances marked reconciled.

Open items and inventory come in against Opening Balance Equity, and A/R, A/P and inventory are left out of the trial-balance entry, so nothing is counted twice; when the details agree with QuickBooks, Opening Balance Equity ends where it was there. The results page lists any difference and what to check. History before the conversion date stays in QuickBooks; save its reports before you cancel. Running the import again skips what's already here.

Without API access, export lists from QuickBooks as CSV and use the CSV importers, then enter opening balances on the accounts.

## Running it for real

```bash
BOOKS_DATA_DIR=/srv/books BOOKS_BASE_URL=https://books.example.com \
  gunicorn --workers 2 --bind 127.0.0.1:5080 'pps_tools.books.web.app:create_app()'
```

- Put it behind HTTPS (nginx, Caddy, a cloud load balancer). With an `https://` base URL, session cookies are marked secure.
- Run scheduled work from cron as well, for nights when nobody uses the app: `15 * * * * pps books run-scheduled` creates recurring transactions, sends reminders, adds late fees and emails scheduled reports. The app also runs it at most hourly while people use it.
- Back up the data folder: `pps books backup /backups/books-$(date +%F).sqlite` plus the `attachments` folder.
- `pps books check` confirms every transaction balances and A/R and A/P tie out to open documents.
- SQLite is what the tests run on and what's recommended for one company. `BOOKS_DATABASE_URL` takes any SQLAlchemy URL if you want a server database; test it with `pps books check` before relying on it.

## Configuration

| Variable | |
|---|---|
| `BOOKS_DATA_DIR` | Database, attachments and the session key (default `./books-data`) |
| `BOOKS_DATABASE_URL` | SQLAlchemy URL; default SQLite in the data folder |
| `BOOKS_BASE_URL` | The address customers and Stripe reach, for pay links and the webhook |
| `BOOKS_SECRET_KEY` | Session signing key; generated into the data folder if unset |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY` | Stripe; these override keys saved in Settings |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS` | Outgoing email. Without a server, email waits in the outbox (Settings → Email) |
| `ANTHROPIC_API_KEY`, `BOOKS_AI_MODEL` | Optional Claude help with categorizing and receipts (`claude-opus-5-5` by default) |
| `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, `QBO_ENVIRONMENT` | Optional, for the QuickBooks Online migration |

## Command line

| Command | |
|---|---|
| `pps books serve [--host --port]` | The web app |
| `pps books setup` | Create the company and first admin without the browser |
| `pps books demo` | A demo company in an empty data folder |
| `pps books run-scheduled` | Recurring transactions, reminders, late fees, scheduled reports |
| `pps books stripe-sync [--days 30]` | Record Stripe activity the webhook may have missed |
| `pps books check` | Verify the ledger |
| `pps books backup FILE` | SQLite backup without stored credentials |
| `pps books reset-password EMAIL` | Set a password and unlock the account |
| `pps books recompute-inventory` | Replay FIFO costing for every item |

Every command takes `--data-dir`.

## REST API

Create a token under **Settings → API access**; it acts as the user who made it, with that user's role.

```bash
curl -H "Authorization: Bearer pbk_…" https://books.example.com/api/v1/customers?q=harbor
curl -H "Authorization: Bearer pbk_…" -H "Content-Type: application/json" \
  -d '{"type":"invoice","customer_id":12,"lines":[{"item_id":3,"qty":"500"}]}' \
  https://books.example.com/api/v1/transactions
```

| | |
|---|---|
| `GET /api/v1/company` | Company and the token's user |
| `GET, POST /api/v1/customers`, `/vendors`, `/items`; `GET, PATCH …/<id>` | Names and products (`?q=`, `?active=all`, `?updated_since=`, `limit`, `offset`) |
| `GET /api/v1/accounts` | Chart of accounts |
| `GET /api/v1/transactions?type=invoice,payment&since=2026-01-01&open=true` | Transactions |
| `GET, PUT, PATCH, DELETE /api/v1/transactions/<id>`, `POST …/<id>/void` | One transaction, with lines and ledger entries |
| `POST /api/v1/transactions` | Create any transaction type, with the same fields as the forms |
| `GET /api/v1/reports`, `GET /api/v1/reports/<key>?preset=this_year&basis=cash` | Any report, as JSON |

Amounts in responses are integer cents. Validation errors return 422 with the message and field, closed-period edits 409.

## How the books work

- **Double entry, integer cents.** Every transaction writes ledger entries (debits positive, credits negative) that sum to zero; quantities and rates are exact decimals. Saving rebuilds a transaction's entries, keeping cleared and reconciled marks.
- **One transaction table.** Each type (invoice, bill, deposit…) is described once in `txn_types.py`; forms, posting, lists and reports read that table.
- **Open balances** come from links between documents (payment → invoice, credit → invoice), so applying, unapplying, voiding and editing keep A/R and A/P right.
- **Cash basis** is computed from the accrual ledger by recognizing each invoice and bill in proportion to when it was paid.
- **FIFO inventory** replays an item's history whenever an earlier transaction changes, and records cost of goods sold on each sale.
- **Closing date.** Changes on or before it need the closing password and are listed in *Exceptions to Closing Date*.

Code: `models/` (tables), `services/` (all the rules, no Flask), `web/` (pages and the API), `templates/`, `static/`. Tests: `tests/test_books/`.

## Not included yet

- Live bank connections. Bank and card activity comes in from files your bank lets you download (CSV, OFX, QFX, QBO); Stripe activity syncs automatically.
- Payroll. Record payroll from your provider's journal export or as journal entries.
- Multiple currencies. Books are kept in one home currency; Stripe charges in other currencies are recorded at the amount Stripe settles in yours.
- Filing. 1099s and sales tax returns are prepared and exported, not e-filed.
- A phone app. The web app works on phones, with receipts uploadable from the camera.
