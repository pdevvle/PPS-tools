-- Channels & automation bookkeeping.

-- One row per rule that fired on a message/comment: run history in Settings → Rules,
-- the "at most one auto-reply per contact per rule per day" limit, and idempotency
-- (a rule never runs twice for the same message).
CREATE TABLE rule_runs (
    id              INTEGER PRIMARY KEY,
    rule_id         INTEGER NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    trigger         TEXT NOT NULL,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
    message_id      INTEGER,
    comment_id      INTEGER,
    contact_id      INTEGER,
    actions_json    TEXT NOT NULL DEFAULT '[]',   -- [{"type", "ok", "detail"}]
    auto_replied    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_rule_runs_rule ON rule_runs(rule_id, created_at);
CREATE INDEX idx_rule_runs_contact ON rule_runs(contact_id, rule_id, auto_replied, created_at);
CREATE INDEX idx_rule_runs_message ON rule_runs(rule_id, message_id);

-- Website chat: the newest agent reply already emailed to a visitor who left the page.
ALTER TABLE chat_visitors ADD COLUMN emailed_up_to INTEGER;
CREATE INDEX idx_chat_visitors_conversation ON chat_visitors(conversation_id);
