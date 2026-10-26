# Switchboard

Switchboard is a shared team inbox (in the spirit of Missive) with staffing and job
scheduling built in. Email, text messages, WhatsApp, website chat and web forms land in
one collaborative inbox; the same app schedules your people (shifts, time off, time
clock, timesheets) and your work (jobs moving through stages, operations scheduled on
equipment and staff).

It runs as a single Python process with a SQLite database — no external services
required — and the web app needs no build step.

- [Quick start](#quick-start)
- [What's included](#whats-included)
- [Connecting channels](#connecting-channels)
- [Roles and permissions](#roles-and-permissions)
- [Running it for real](#running-it-for-real)
- [How it's built](#how-its-built)
- [API, tokens and webhooks](#api-tokens-and-webhooks)
- [Known limits](#known-limits)
- [Development](#development)

## Quick start

```bash
pip install -e .                 # from the repository root
pps switchboard seed             # optional: a demo print-shop workspace to explore
pps switchboard run              # http://localhost:5050
```

Or double-click / run `python switchboard.py` (add `--demo` the first time to load the
demo, `--lan` to let other computers on your network connect).

With the demo loaded, sign in as `morgan@pps.demo` (owner), `casey@pps.demo` (manager),
`sam@pps.demo` (front desk), `jordan@pps.demo` (designer) or `alex@pps.demo` (press
operator, staff-only) — the password for every demo account is `switchboard`. Without the
demo, the first visit asks you to create the workspace and its owner account.

Data lives in `./switchboard_data` (database, attachments, session key). Set
`SWITCHBOARD_DATA_DIR` to put it elsewhere.

## What's included

### Team inbox

- **Every channel in one place**: email (IMAP/SMTP — Gmail, Outlook/Office 365, Yahoo,
  iCloud or any provider), SMS and WhatsApp (Twilio), a website chat widget, website
  contact/quote forms, and an API channel for anything else.
- **Shared and personal**: shared accounts feed team inboxes; personal accounts stay
  private to their owner. Each person has their own Inbox, Assigned to me, Starred,
  Snoozed, Drafts, Scheduled and Sent views; team inboxes split into Open / Unassigned /
  Assigned / Closed.
- **Collaborate in the thread**: internal comments with @mentions and emoji reactions
  next to the customer's messages; internal-only discussions; live presence ("Jordan is
  replying") so two people never answer the same customer; shared drafts that teammates
  can open and co-edit.
- **Assignment**: assign one or more people; automatic assignment per team (round robin,
  load balanced, or *whoever is on shift right now* — straight from the schedule).
  "Take next" grabs the longest-waiting unassigned conversation.
- **Organize**: shared and personal labels (drag conversations onto a label), close /
  reopen for everyone, remove from just your inbox, star, snooze, priority, move between
  teams, merge duplicate threads, spam and block sender, trash.
- **Write faster**: rich text composer, canned responses with variables (type `/`),
  signatures (personal or per account), attachments, send later, send & close, undo send,
  SMS segment counter, AI drafting/rewriting/translation when an Anthropic API key is set.
- **Follow up**: "remind me" (optionally only if nobody replied), snooze, read receipts
  for email, overdue flags against a first-response target.
- **Rules**: on incoming / new / outgoing messages and comments — match on sender,
  recipients, subject, body, channel, attachments, labels, assignment, team, contact
  group, business hours or weekday — then assign, label, move, close, snooze, set
  priority, mark spam, auto-reply, forward, add a note, notify people or call a webhook.
- **Find anything**: full-text search with operators (`from:`, `to:`, `subject:`,
  `label:`, `assignee:`, `is:unread`, `has:attachment`, `channel:sms`, `team:`, `before:`,
  `after:`, `in:trash` …), saved searches, and a ⌘K / Ctrl+K command palette across
  conversations, contacts, jobs and people.
- **Contacts**: built automatically from conversations; organizations (auto-linked by
  email domain), groups, notes, merge duplicates, CSV import/export, and the customer's
  history, jobs and tasks next to every conversation.
- **Sidebar apps**: iframe integrations and WooCommerce orders for the customer you're
  talking to.

### Staffing

- People with positions, skills, pay rates, hire dates, hour targets and limits.
- Weekly availability, time-off requests with approvals.
- Drag-and-drop weekly schedule with templates, copy last week, open shifts, publish
  (people are notified), conflict warnings (double-booked, time off, unavailable,
  overtime, too little rest, missing position) and live hours/cost totals.
- Shift swaps, drops and pickups with coworker acceptance and manager approval.
- Time clock (in/out, breaks, optional job), a shared-tablet kiosk with PINs,
  timesheets with regular vs. overtime hours, approvals and a payroll CSV export.
- Shift reminders, and a private calendar feed people can subscribe to on their phone.

### Job scheduling

- Jobs (work orders) with numbers, customer, due date, priority, quantity, quote, PO and
  custom spec fields (paper stock, finished size, ink, finishing …), checklists, files and
  proofs, comments with mentions, linked conversations and tasks.
- A Kanban board over configurable stages, plus list and "my jobs" views.
- Job templates that create the usual operations (prepress → print → finish → pack).
- A scheduling board: operations on equipment and people over a day or week timeline,
  drag to schedule and resize, conflicts (double-booked machine or person, person off
  shift or on time off, finishing after the due date, out of order), and an
  auto-scheduler that fills machines by due date with qualified people who are on shift.
- Create a job straight from a customer conversation (optionally filled in by AI),
  and send customers a link to check status and approve proofs.
- Actual hours from the time clock against estimates.

### And around it

- Team chat: channels, direct messages, threads, reactions, mentions, file sharing, and
  sharing an inbox conversation into a chat.
- Tasks (standalone or attached to conversations and jobs), calendars with recurring
  events, overlays for shifts, job due dates and time off, ICS subscriptions and feeds.
- My Day: your clock, shifts, inbox, jobs, tasks and agenda on one page.
- Reports on response times, volume, workload, busiest hours, labor hours and cost,
  overtime, job throughput and on-time delivery — with CSV export.
- Notifications in the app and on the desktop, keyboard shortcuts everywhere (`?`), dark
  mode, and a layout that works on phones (a bottom tab bar, with everything else under
  More).

## Connecting channels

Settings → Channels (admins).

- **Gmail / Google Workspace**: turn on 2-step verification and create an app password,
  then use IMAP `imap.gmail.com:993` and SMTP `smtp.gmail.com:587` (STARTTLS) with the
  app password.
- **Outlook / Office 365**: IMAP `outlook.office365.com:993`, SMTP
  `smtp.office365.com:587`. Your tenant must allow IMAP/SMTP AUTH for the mailbox.
- **Any other provider**: the IMAP/SMTP settings from your host. Switchboard fetches new
  mail every minute and never marks mail read on the server; on first connect it imports
  the last week.
- **SMS / WhatsApp (Twilio)**: create the channel with your Account SID, Auth Token and
  number, then paste the webhook URLs shown on the channel into the Twilio console
  (incoming messages and status callbacks). Twilio must be able to reach your server —
  set `SWITCHBOARD_BASE_URL` to its public https URL.
- **Website chat**: create a chat channel and paste the one-line `<script>` snippet into
  your site (for WordPress, a header/footer scripts plugin or the theme's custom code
  area). Conversations show up in the team inbox; replies go back to the visitor live.
- **Website forms**: point a form's `action` at the form channel's URL (shown in its
  settings) to turn quote requests into conversations.
- **Anything else**: post messages into an API channel with an API token.

Outgoing email is sent from the shared address with the agent's name ("Sam Patel"
<orders@…>) by default; each channel can instead use the channel name or "Sam at
Priority Print Service".

## Roles and permissions

| | Owner | Admin | Manager | Agent | Staff |
|---|:-:|:-:|:-:|:-:|:-:|
| Team inbox, contacts | ✓ | ✓ | ✓ | ✓ | |
| Create and schedule jobs | ✓ | ✓ | ✓ | ✓ | |
| Jobs floor (view, comment, checklists, progress) | ✓ | ✓ | ✓ | ✓ | ✓ |
| Build schedules, approve time off/swaps/timesheets | ✓ | ✓ | ✓ | | |
| See pay rates and labor cost, reports | ✓ | ✓ | ✓ | | |
| Own schedule, time clock, time off, chat, tasks, calendar | ✓ | ✓ | ✓ | ✓ | ✓ |
| Settings, channels, rules, people, integrations | ✓ | ✓ | | | |

Staff see conversations only when someone brings them in (for example by @mentioning
them in an internal discussion). Personal email accounts are visible only to their owner.

## Running it for real

- **One process, many threads.** Live updates are broadcast inside the process, so run a
  single server process. `pps switchboard run --host 0.0.0.0` is fine for a shop network.
  Behind a reverse proxy you can also use `gunicorn -w 1 --threads 64
  'pps_tools.switchboard:create_app()'` (one worker, many threads).
- **HTTPS and the public URL.** Set `SWITCHBOARD_BASE_URL=https://inbox.example.com` —
  it's used for links in emails, Twilio signature checks, the chat widget, calendar feeds
  and read receipts. Session cookies are marked Secure automatically on https.
- **Reverse proxy.** Disable response buffering for `/api/events` (live updates use
  Server-Sent Events; with nginx: `proxy_buffering off;` — the app also sends
  `X-Accel-Buffering: no`) and allow uploads up to 60 MB. Set
  `SWITCHBOARD_PROXY_COUNT=1` (the number of proxies in front of the app) so sign-in
  throttling and the public chat/form rate limits see visitors' real addresses;
  without it, `X-Forwarded-For` is ignored because anyone can fake it.
- **Backups.** `pps switchboard backup /path/to/backup.db` makes a consistent copy while
  the server runs (admins can also download one from Settings → Import & export). Back up
  the `files/` folder in the data directory too — it holds attachments.
- **Secrets.** Mail and Twilio credentials are stored in the database and never sent to
  the browser. The session key is generated once into the data directory (or set
  `SWITCHBOARD_SECRET_KEY`).
- **Email for invites and password resets** goes through the first shared email channel
  (or the one chosen in settings); until one is connected, admins can copy invite/reset
  links from Settings → People.

Environment variables: `SWITCHBOARD_DATA_DIR`, `SWITCHBOARD_BASE_URL`,
`SWITCHBOARD_SECRET_KEY`, `SWITCHBOARD_PROXY_COUNT` (behind a reverse proxy),
`ANTHROPIC_API_KEY` (optional, for AI assists), `SWITCHBOARD_MODULES` (development:
load only some modules).

## How it's built

```
src/pps_tools/switchboard/
  app.py, config.py, db.py, web.py   Flask app factory, config, SQLite access, HTTP helpers
  realtime.py, worker.py             SSE broadcast + presence; background task runner
  modules.py                         the feature modules and their contract
  schema/NNN_*.sql                   migrations, applied in order at startup
  services/                          business logic (inbox, outbox, search, sanitize, …)
  channels/                          adapters: email, Twilio, chat widget, API
  api/<module>.py                    one Flask blueprint per feature module
  demo/<module>.py                   demo workspace content
  static/                            the web app (Preact + htm, no build step)
```

- **Modules.** Each feature (`inbox`, `channels`, `rules`, `staffing`, `jobs`, `chat`,
  `tasks`, `calendar`, `contacts`, `analytics`, `ai`, `admin`, …) is an `api/<name>.py`
  file exposing a blueprint plus optional hooks: reference data for the app's bootstrap,
  background tasks, rail badge counts, command-palette search results, workspace defaults
  and demo data. Modules talk to each other through domain events
  (`services/hooks.py`: `message.received`, `conversation.assigned`, `job.stage_changed`,
  `shift.published` …) instead of importing each other.
- **Database.** SQLite in WAL mode, one connection per thread, explicit `BEGIN
  IMMEDIATE` transactions; instants are stored as UTC ISO strings; full-text search uses
  FTS5. Schema changes are new numbered files in `schema/`.
- **Live updates.** Every browser tab holds one `GET /api/events` stream. Server code
  calls `realtime.emit()` and the event goes out after the transaction commits; the web
  app refetches what it shows. Presence (viewing / replying / commenting) rides on the
  same channel.
- **Background worker.** A thread runs periodic tasks: the outbox (send-later, undo
  window, retries), mailbox sync, snooze wake-ups, reminders, webhook delivery, shift
  reminders, due-soon job alerts, calendar subscriptions.
- **Email safety.** Inbound HTML is cleaned by an allow-list sanitizer and shown in a
  sandboxed iframe with a strict Content-Security-Policy (no scripts, optional remote
  image blocking). Uploaded files are served with a sandbox CSP and HTML/SVG are always
  downloaded, never rendered.
- **Web app.** Preact + htm loaded as plain ES modules (vendored in `static/vendor`), a
  small UI kit (`static/js/ui`), one folder per module under `static/js/views`, and CSS
  tokens with light and dark themes.

## API, tokens and webhooks

Everything the web app does goes through the JSON API under `/api`, so integrations can
do the same:

- Create a token in Settings → API & webhooks and send `Authorization: Bearer sb_…`.
  (Browser sessions instead send the `X-Requested-With` header on every write; that is
  the CSRF protection.)
- Errors look like `{"error": {"code": "not_found", "message": "…"}}`.
- Webhooks receive JSON `{id, event, data, occurred_at, sent_at}` with
  `X-Switchboard-Event` and `X-Switchboard-Signature: sha256=<HMAC of the body with your
  webhook secret>`, retried with backoff. Events cover messages, conversations, comments,
  contacts, tasks, jobs (including customer proof decisions) and staffing; Settings → API
  & webhooks lists them all. Team chat is never sent out.

A few useful endpoints:

| | |
|---|---|
| `GET /api/conversations?mailbox=inbox&q=…` | list / search conversations |
| `GET /api/conversations/<id>` | thread with messages, comments, events, drafts |
| `POST /api/conversations/actions` | `{ids, action, …}` — close, assign, label, snooze, … |
| `POST /api/drafts`, `POST /api/drafts/<id>/send` | compose and send (`send_at` for later) |
| `POST /api/conversations/<id>/comments` | internal comment |
| `POST /api/channels/<id>/messages` | push an inbound message into an API channel |
| `GET /api/jobs`, `POST /api/jobs` | jobs |
| `GET /api/schedule?start=&end=` | production schedule (job steps on equipment and people) |
| `GET /api/shifts?start=&end=` | staff schedule |
| `GET /api/timesheets/export.csv?start=&end=` | payroll CSV |
| `GET /api/contacts?q=` | contacts |
| `GET /api/tasks?view=mine`, `POST /api/tasks` | tasks |
| `GET /api/calendar/events?start=&end=&overlays=` | calendar events, plus shift/job/time-off overlays |

## Known limits

- The production schedule can't be dragged by touch; on phones and tablets, tap a step
  and change its time, machine or person from its card. The auto-scheduler books the
  earliest-due work first in 15-minute slots and never moves steps already scheduled.
- Recurring calendar events support daily, weekly, monthly and yearly repeats with an
  interval, weekdays, an end date or count, and skipped dates — not every iCalendar rule.
- Contacts import from CSV (not vCard). Team chat has no pinned messages or in-room
  search (the ⌘K search covers chat messages).
- The in-app backup is the database only; copy the `files/` folder for attachments.
- Times show in each person's own time zone; shifts, timesheets and the production
  schedule use the workspace time zone (Settings → General).
- Messenger and Instagram aren't connected (they need Meta app review); everything else
  can come in through the API channel.

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/test_switchboard -q
SWITCHBOARD_MODULES=inbox,staffing python -m pytest tests/test_switchboard -q   # a subset
pps switchboard run --debug --port 5051
```

`SWITCHBOARD_MODULES` also works for the server: the web app hides areas, settings,
My Day widgets and conversation panels whose module isn't running.

Adding a feature module: create `api/<name>.py` with a blueprint `bp` (and any of
`bootstrap`, `worker_tasks`, `on_setup`, `seed`, `badges`, `search`), add the name to
`MODULE_NAMES` in `modules.py`, put tables in a new `schema/NNN_<name>.sql`, and add a
`static/js/views/<name>/index.js` page registered in `static/js/modules.js`.
