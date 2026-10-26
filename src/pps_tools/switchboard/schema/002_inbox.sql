-- Team inbox: channels, contacts, conversations, messages, collaboration.

-- A channel is one connected account: an email address, a Twilio number, a website chat
-- widget, or an API/form endpoint. Shared channels deliver into their team's inbox;
-- personal channels deliver only to their owner.
CREATE TABLE channels (
    id              INTEGER PRIMARY KEY,
    type            TEXT NOT NULL CHECK (type IN ('email', 'sms', 'whatsapp', 'chat', 'api')),
    name            TEXT NOT NULL,
    address         TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    visibility      TEXT NOT NULL DEFAULT 'shared' CHECK (visibility IN ('shared', 'personal')),
    owner_user_id   INTEGER REFERENCES users(id) ON DELETE CASCADE,
    team_id         INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    config_json     TEXT NOT NULL DEFAULT '{}',   -- credentials & options; never sent to clients raw
    signature_html  TEXT,
    public_key      TEXT NOT NULL UNIQUE,         -- used in webhook / widget URLs
    sync_state_json TEXT NOT NULL DEFAULT '{}',
    last_sync_at    TEXT,
    sync_error      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT
);

CREATE TABLE organizations (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    domain      TEXT COLLATE NOCASE,
    phone       TEXT,
    website     TEXT,
    address     TEXT,
    notes       TEXT,
    custom_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE INDEX idx_organizations_domain ON organizations(domain);

CREATE TABLE contacts (
    id              INTEGER PRIMARY KEY,
    name            TEXT,
    email           TEXT COLLATE NOCASE,          -- primary handles, mirrored in contact_handles
    phone           TEXT,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    title           TEXT,
    address         TEXT,
    notes           TEXT,
    custom_json     TEXT NOT NULL DEFAULT '{}',
    is_blocked      INTEGER NOT NULL DEFAULT 0,    -- mail from blocked contacts goes to spam
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT
);
CREATE INDEX idx_contacts_org ON contacts(organization_id);

CREATE TABLE contact_handles (
    id         INTEGER PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('email', 'phone', 'chat')),
    value      TEXT NOT NULL COLLATE NOCASE,
    label      TEXT,
    UNIQUE (kind, value)
);
CREATE INDEX idx_contact_handles_contact ON contact_handles(contact_id);

CREATE TABLE contact_groups (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color      TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE contact_group_members (
    group_id   INTEGER NOT NULL REFERENCES contact_groups(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, contact_id)
);

-- Conversation state shared by everyone. Per-user state (personal inbox, star, read
-- position, following) lives in conversation_users.
CREATE TABLE conversations (
    id                INTEGER PRIMARY KEY,
    subject           TEXT,
    channel_id        INTEGER REFERENCES channels(id) ON DELETE SET NULL,
    team_id           INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    contact_id        INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    thread_key        TEXT,            -- sms/whatsapp: remote number; chat: visitor token
    status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    priority          TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    is_spam           INTEGER NOT NULL DEFAULT 0,
    deleted_at        TEXT,            -- in Trash
    snoozed_until     TEXT,
    snoozed_by        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    merged_into_id    INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    message_count     INTEGER NOT NULL DEFAULT 0,
    comment_count     INTEGER NOT NULL DEFAULT 0,
    preview           TEXT,
    last_message_at   TEXT,
    last_inbound_at   TEXT,
    last_outbound_at  TEXT,
    last_activity_at  TEXT NOT NULL,   -- last message or comment: drives sort order & unread
    first_response_at TEXT,            -- first outbound after the first inbound (reporting)
    closed_at         TEXT,
    closed_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_by        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at        TEXT NOT NULL
);
CREATE INDEX idx_conversations_activity ON conversations(last_activity_at);
CREATE INDEX idx_conversations_team ON conversations(team_id, status, last_activity_at);
CREATE INDEX idx_conversations_thread ON conversations(channel_id, thread_key);
CREATE INDEX idx_conversations_contact ON conversations(contact_id);
CREATE INDEX idx_conversations_snoozed ON conversations(snoozed_until);

CREATE TABLE conversation_users (
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    following       INTEGER NOT NULL DEFAULT 1,   -- new activity returns it to this user's Inbox
    in_inbox        INTEGER NOT NULL DEFAULT 0,
    starred         INTEGER NOT NULL DEFAULT 0,
    last_read_at    TEXT,
    PRIMARY KEY (conversation_id, user_id)
);
CREATE INDEX idx_conversation_users_user ON conversation_users(user_id, in_inbox);

CREATE TABLE conversation_assignees (
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assigned_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    assigned_at     TEXT NOT NULL,
    PRIMARY KEY (conversation_id, user_id)
);
CREATE INDEX idx_conversation_assignees_user ON conversation_assignees(user_id);

CREATE TABLE labels (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    color         TEXT,
    parent_id     INTEGER REFERENCES labels(id) ON DELETE CASCADE,
    visibility    TEXT NOT NULL DEFAULT 'shared' CHECK (visibility IN ('shared', 'personal')),
    owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE conversation_labels (
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    label_id        INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    added_by        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    added_at        TEXT NOT NULL,
    PRIMARY KEY (conversation_id, label_id)
);
CREATE INDEX idx_conversation_labels_label ON conversation_labels(label_id);

CREATE TABLE messages (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    channel_id      INTEGER REFERENCES channels(id) ON DELETE SET NULL,
    direction       TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    kind            TEXT NOT NULL CHECK (kind IN ('email', 'sms', 'whatsapp', 'chat', 'api')),
    from_name       TEXT,
    from_handle     TEXT,
    to_json         TEXT NOT NULL DEFAULT '[]',   -- [{"name": ..., "handle": ...}]
    cc_json         TEXT NOT NULL DEFAULT '[]',
    bcc_json        TEXT NOT NULL DEFAULT '[]',
    reply_to        TEXT,
    subject         TEXT,
    body_text       TEXT,
    body_html       TEXT,                         -- sanitized on the way in
    snippet         TEXT,
    external_id     TEXT,                         -- RFC 5322 Message-ID, Twilio SID, ...
    in_reply_to     TEXT,
    references_json TEXT NOT NULL DEFAULT '[]',
    author_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,   -- outbound
    contact_id      INTEGER REFERENCES contacts(id) ON DELETE SET NULL, -- inbound sender
    -- received | scheduled (send later / undo window) | sending | sent | delivered | read | failed
    status          TEXT NOT NULL DEFAULT 'received',
    scheduled_at    TEXT,
    sent_at         TEXT,
    opened_at       TEXT,
    error           TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    track_token     TEXT UNIQUE,
    is_auto         INTEGER NOT NULL DEFAULT 0,   -- auto-reply / bulk: never auto-replied to
    draft_json      TEXT,                         -- composer state, so "Undo" can restore it
    raw_key         TEXT,                         -- original MIME in the file store
    headers_json    TEXT NOT NULL DEFAULT '{}',
    date            TEXT NOT NULL,                -- when it was sent/received
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_messages_conversation ON messages(conversation_id, date);
CREATE INDEX idx_messages_external ON messages(external_id);
CREATE INDEX idx_messages_outbox ON messages(status, scheduled_at);
CREATE INDEX idx_messages_author ON messages(author_id, date);

-- Internal discussion next to the messages. body is sanitized HTML; mentions are
-- <span data-mention="user-id">.
CREATE TABLE comments (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    body            TEXT NOT NULL,
    mentions_json   TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    edited_at       TEXT,
    deleted_at      TEXT
);
CREATE INDEX idx_comments_conversation ON comments(conversation_id, created_at);

-- Timeline entries: assigned, labeled, closed, rule applied, merged, ...
CREATE TABLE conversation_events (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    type            TEXT NOT NULL,
    data_json       TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_conversation_events_conversation ON conversation_events(conversation_id, created_at);

CREATE TABLE drafts (
    id                  INTEGER PRIMARY KEY,
    conversation_id     INTEGER REFERENCES conversations(id) ON DELETE CASCADE, -- NULL = new conversation
    channel_id          INTEGER REFERENCES channels(id) ON DELETE SET NULL,
    mode                TEXT NOT NULL DEFAULT 'reply'
                        CHECK (mode IN ('new', 'reply', 'reply_all', 'forward')),
    reply_to_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    to_json             TEXT NOT NULL DEFAULT '[]',
    cc_json             TEXT NOT NULL DEFAULT '[]',
    bcc_json            TEXT NOT NULL DEFAULT '[]',
    subject             TEXT,
    body_html           TEXT NOT NULL DEFAULT '',
    include_signature   INTEGER NOT NULL DEFAULT 1,
    is_shared           INTEGER NOT NULL DEFAULT 1,  -- teammates can see and co-edit it
    version             INTEGER NOT NULL DEFAULT 1,
    created_by          INTEGER REFERENCES users(id) ON DELETE CASCADE,
    updated_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX idx_drafts_conversation ON drafts(conversation_id);
CREATE INDEX idx_drafts_creator ON drafts(created_by);

CREATE TABLE canned_responses (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    subject       TEXT,
    body_html     TEXT NOT NULL DEFAULT '',
    shortcut      TEXT,
    folder        TEXT,
    visibility    TEXT NOT NULL DEFAULT 'shared' CHECK (visibility IN ('shared', 'personal', 'team')),
    owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    team_id       INTEGER REFERENCES teams(id) ON DELETE CASCADE,
    usage_count   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT
);

-- Automation. trigger: incoming | outgoing | new_conversation | comment.
-- conditions_json: [{"field", "op", "value"}]; actions_json: [{"type", ...params}].
CREATE TABLE rules (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    trigger         TEXT NOT NULL DEFAULT 'incoming',
    match           TEXT NOT NULL DEFAULT 'all' CHECK (match IN ('all', 'any')),
    conditions_json TEXT NOT NULL DEFAULT '[]',
    actions_json    TEXT NOT NULL DEFAULT '[]',
    stop_processing INTEGER NOT NULL DEFAULT 0,
    position        INTEGER NOT NULL DEFAULT 0,
    run_count       INTEGER NOT NULL DEFAULT 0,
    last_run_at     TEXT,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT
);

-- "Remind me" follow-ups. condition 'no_reply' only fires if nobody answered meanwhile.
CREATE TABLE reminders (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    remind_at       TEXT NOT NULL,
    condition       TEXT NOT NULL DEFAULT 'always' CHECK (condition IN ('always', 'no_reply')),
    note            TEXT,
    created_at      TEXT NOT NULL,
    done_at         TEXT
);
CREATE INDEX idx_reminders_due ON reminders(done_at, remind_at);

-- Website chat widget visitors.
CREATE TABLE chat_visitors (
    id              INTEGER PRIMARY KEY,
    channel_id      INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    token           TEXT NOT NULL UNIQUE,
    name            TEXT,
    email           TEXT,
    contact_id      INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    page_url        TEXT,
    user_agent      TEXT,
    ip              TEXT,
    created_at      TEXT NOT NULL,
    last_seen_at    TEXT
);
