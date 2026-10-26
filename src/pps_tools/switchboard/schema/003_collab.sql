-- Tasks, calendars and team chat.

CREATE TABLE tasks (
    id                  INTEGER PRIMARY KEY,
    title               TEXT NOT NULL,
    description         TEXT,              -- sanitized basic HTML
    status              TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'done')),
    priority            TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    due_at              TEXT,
    assignee_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    team_id             INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    conversation_id     INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
    job_id              INTEGER,           -- REFERENCES jobs(id); jobs are created in 005
    position            REAL NOT NULL DEFAULT 0,
    created_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT,
    completed_at        TEXT,
    completed_by        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    due_notified_at     TEXT,              -- "due within the hour" sent
    overdue_notified_at TEXT               -- "overdue" sent
);
CREATE INDEX idx_tasks_assignee ON tasks(assignee_id, status);
CREATE INDEX idx_tasks_conversation ON tasks(conversation_id);
CREATE INDEX idx_tasks_job ON tasks(job_id);
CREATE INDEX idx_tasks_due ON tasks(status, due_at);

-- kind: personal (owner only), shared (everyone), subscription (read-only ICS URL;
-- private to its owner when owner_user_id is set).
CREATE TABLE calendars (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    color           TEXT,
    kind            TEXT NOT NULL DEFAULT 'shared' CHECK (kind IN ('personal', 'shared', 'subscription')),
    owner_user_id   INTEGER REFERENCES users(id) ON DELETE CASCADE,
    ics_url         TEXT,
    sync_error      TEXT,
    last_sync_at    TEXT,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL
);

-- Times are UTC instants. All-day events start at local midnight (org timezone) and end
-- at the local midnight after their last day. Recurrence is expanded in the org
-- timezone so "Mondays 8am" stays at 8am across daylight-saving changes.
-- A single changed occurrence of a series is its own row with parent_id + original_start
-- (and the series lists original_start in exdates_json).
CREATE TABLE calendar_events (
    id               INTEGER PRIMARY KEY,
    calendar_id      INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    description      TEXT,
    location         TEXT,
    start_at         TEXT NOT NULL,
    end_at           TEXT NOT NULL,
    all_day          INTEGER NOT NULL DEFAULT 0,
    rrule            TEXT,             -- RFC 5545 subset: FREQ, INTERVAL, BYDAY, BYMONTHDAY, COUNT, UNTIL
    exdates_json     TEXT NOT NULL DEFAULT '[]',   -- occurrence starts (UTC instants) removed from the series
    attendees_json   TEXT NOT NULL DEFAULT '[]',   -- [{"user_id": 3}] or [{"email": ..., "name": ...}]
    reminder_minutes INTEGER,
    color            TEXT,
    parent_id        INTEGER REFERENCES calendar_events(id) ON DELETE CASCADE,
    original_start   TEXT,
    conversation_id  INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    job_id           INTEGER,
    external_uid     TEXT,
    created_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT
);
CREATE INDEX idx_calendar_events_range ON calendar_events(calendar_id, start_at);
CREATE INDEX idx_calendar_events_uid ON calendar_events(calendar_id, external_uid);
CREATE INDEX idx_calendar_events_parent ON calendar_events(parent_id);

-- One row per (event, occurrence) reminder already sent.
CREATE TABLE calendar_reminders_sent (
    event_id         INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
    occurrence_start TEXT NOT NULL,
    sent_at          TEXT NOT NULL,
    PRIMARY KEY (event_id, occurrence_start)
);

-- kind 'channel' = named room; 'dm' = direct message (dm_key = sorted member ids).
-- is_default rooms (#general) are joined automatically the first time someone opens chat.
CREATE TABLE chat_rooms (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL DEFAULT 'channel' CHECK (kind IN ('channel', 'dm')),
    name            TEXT,
    topic           TEXT,
    is_private      INTEGER NOT NULL DEFAULT 0,
    is_default      INTEGER NOT NULL DEFAULT 0,
    dm_key          TEXT UNIQUE,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    archived_at     TEXT,
    last_message_at TEXT
);

-- left_at set = they left (the row stays so default rooms don't re-add them).
CREATE TABLE chat_members (
    room_id      INTEGER NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_read_at TEXT,
    muted        INTEGER NOT NULL DEFAULT 0,
    joined_at    TEXT NOT NULL,
    left_at      TEXT,
    PRIMARY KEY (room_id, user_id)
);
CREATE INDEX idx_chat_members_user ON chat_members(user_id);

CREATE TABLE chat_messages (
    id              INTEGER PRIMARY KEY,
    room_id         INTEGER NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    body            TEXT NOT NULL,     -- sanitized HTML, mentions as <span data-mention>
    mentions_json   TEXT NOT NULL DEFAULT '[]',
    parent_id       INTEGER REFERENCES chat_messages(id) ON DELETE CASCADE,  -- thread replies
    reply_count     INTEGER NOT NULL DEFAULT 0,
    last_reply_at   TEXT,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,  -- shared inbox conversation
    job_id          INTEGER,
    created_at      TEXT NOT NULL,
    edited_at       TEXT,
    deleted_at      TEXT
);
CREATE INDEX idx_chat_messages_room ON chat_messages(room_id, created_at);
CREATE INDEX idx_chat_messages_parent ON chat_messages(parent_id);
