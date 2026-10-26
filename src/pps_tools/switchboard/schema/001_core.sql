-- Core: organization settings, people, teams, files, notifications, search.
--
-- Conventions used by every schema file:
--   * Instants are TEXT in UTC, always 'YYYY-MM-DDTHH:MM:SS.mmmZ' (util.iso), so they
--     sort and compare correctly as strings.
--   * Calendar dates are 'YYYY-MM-DD'; times of day are 'HH:MM' (org timezone).
--   * Columns ending in _json hold JSON text (db.jload / db.jdump).

CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE users (
    id                INTEGER PRIMARY KEY,
    email             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name              TEXT NOT NULL,
    password_hash     TEXT,
    -- owner/admin: everything; manager: + staffing approvals and pay; agent: inbox + jobs;
    -- staff: their own schedule, time clock, chat, tasks and the jobs floor (no inbox).
    role              TEXT NOT NULL DEFAULT 'agent'
                      CHECK (role IN ('owner', 'admin', 'manager', 'agent', 'staff')),
    is_active         INTEGER NOT NULL DEFAULT 1,
    title             TEXT,
    phone             TEXT,
    color             TEXT,
    timezone          TEXT,
    prefs_json        TEXT NOT NULL DEFAULT '{}',
    session_version   INTEGER NOT NULL DEFAULT 1,
    pin_hash          TEXT,                       -- time clock kiosk PIN
    invite_token      TEXT UNIQUE,
    invite_expires_at TEXT,
    reset_token       TEXT UNIQUE,
    reset_expires_at  TEXT,
    feed_token        TEXT UNIQUE,                -- private iCal feed URL
    last_seen_at      TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT
);

CREATE TABLE teams (
    id                 INTEGER PRIMARY KEY,
    name               TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color              TEXT,
    description        TEXT,
    -- Also drop new conversations into every member's personal Inbox.
    deliver_to_members INTEGER NOT NULL DEFAULT 0,
    -- How new conversations in this team get an owner.
    assignment_mode    TEXT NOT NULL DEFAULT 'manual'
                       CHECK (assignment_mode IN ('manual', 'round_robin', 'load_balanced', 'on_shift')),
    rr_last_user_id    INTEGER,
    created_at         TEXT NOT NULL
);

CREATE TABLE team_members (
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (team_id, user_id)
);
CREATE INDEX idx_team_members_user ON team_members(user_id);

CREATE TABLE api_tokens (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    prefix       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT
);

-- Files belong to one owner row (owner_type/owner_id): 'message', 'draft', 'comment',
-- 'chat_message', 'job', 'task', 'contact', 'event', ... Unowned uploads are
-- garbage-collected after a day.
CREATE TABLE attachments (
    id           INTEGER PRIMARY KEY,
    token        TEXT NOT NULL UNIQUE,
    filename     TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size         INTEGER NOT NULL DEFAULT 0,
    storage_key  TEXT NOT NULL,
    content_id   TEXT,
    is_inline    INTEGER NOT NULL DEFAULT 0,
    owner_type   TEXT,
    owner_id     INTEGER,
    uploaded_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_attachments_owner ON attachments(owner_type, owner_id);

CREATE TABLE notifications (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT,
    link        TEXT,
    actor_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    entity_type TEXT,
    entity_id   INTEGER,
    created_at  TEXT NOT NULL,
    read_at     TEXT
);
CREATE INDEX idx_notifications_user ON notifications(user_id, created_at);

CREATE TABLE reactions (
    id          INTEGER PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id   INTEGER NOT NULL,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    emoji       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (target_type, target_id, user_id, emoji)
);
CREATE INDEX idx_reactions_target ON reactions(target_type, target_id);

CREATE TABLE webhooks (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    url              TEXT NOT NULL,
    secret           TEXT NOT NULL,
    events_json      TEXT NOT NULL DEFAULT '["*"]',
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL,
    last_delivery_at TEXT,
    last_status      INTEGER,
    last_error       TEXT
);

CREATE TABLE webhook_deliveries (
    id              INTEGER PRIMARY KEY,
    webhook_id      INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    event           TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'delivered', 'failed')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    response_code   INTEGER,
    error           TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_webhook_deliveries_due ON webhook_deliveries(status, next_attempt_at);

-- Sidebar integrations shown next to conversations (iframe apps, WooCommerce orders, ...).
CREATE TABLE integrations (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    is_active   INTEGER NOT NULL DEFAULT 1,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    entity_type TEXT,
    entity_id   INTEGER,
    data_json   TEXT,
    ip          TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_audit_log_created ON audit_log(created_at);

-- Full-text index across modules. kind: 'message' | 'comment' (parent_id = conversation),
-- 'contact', 'organization', 'job', 'task', 'chat' (parent_id = room). Maintained by
-- services.search.
CREATE VIRTUAL TABLE search_index USING fts5(
    title,
    body,
    kind UNINDEXED,
    ref_id UNINDEXED,
    parent_id UNINDEXED,
    tokenize = 'porter unicode61 remove_diacritics 2'
);
