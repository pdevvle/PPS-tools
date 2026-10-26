-- Jobs: work orders moving through stages, broken into operations that are scheduled
-- onto resources (presses, cutters, vans...) and people.

CREATE TABLE job_stages (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    color      TEXT,
    position   INTEGER NOT NULL DEFAULT 0,
    is_done    INTEGER NOT NULL DEFAULT 0,   -- jobs here count as completed
    wip_limit  INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE resources (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    kind        TEXT,                        -- press, cutter, folder, vehicle, room...
    color       TEXT,
    location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    hourly_cost REAL,
    notes       TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

-- Custom spec fields shown on every job (Paper stock, Finished size, Ink, Finishing...).
CREATE TABLE job_fields (
    id           INTEGER PRIMARY KEY,
    key          TEXT NOT NULL UNIQUE,
    label        TEXT NOT NULL,
    type         TEXT NOT NULL DEFAULT 'text' CHECK (type IN ('text', 'number', 'select', 'checkbox', 'date', 'textarea')),
    options_json TEXT NOT NULL DEFAULT '[]',
    position     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

-- Reusable job recipes: default operations, checklist and specs.
-- operations_json: [{"name", "resource_id", "skill_id", "duration_minutes"}]
CREATE TABLE job_templates (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    operations_json TEXT NOT NULL DEFAULT '[]',
    checklist_json  TEXT NOT NULL DEFAULT '[]',
    specs_json      TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT
);

CREATE TABLE jobs (
    id                INTEGER PRIMARY KEY,
    number            TEXT NOT NULL UNIQUE,
    title             TEXT NOT NULL,
    description       TEXT,
    stage_id          INTEGER REFERENCES job_stages(id) ON DELETE SET NULL,
    priority          TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'rush')),
    contact_id        INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    organization_id   INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    template_id       INTEGER REFERENCES job_templates(id) ON DELETE SET NULL,
    due_at            TEXT,
    quantity          INTEGER,
    specs_json        TEXT NOT NULL DEFAULT '{}',
    quote_amount      REAL,
    estimated_minutes INTEGER,
    po_number         TEXT,
    address           TEXT,
    tags_json         TEXT NOT NULL DEFAULT '[]',
    position          REAL NOT NULL DEFAULT 0,   -- order within its stage column
    public_token      TEXT UNIQUE,               -- customer status / proof approval page
    proof_status      TEXT CHECK (proof_status IN ('pending', 'approved', 'changes_requested')),
    proof_decided_at  TEXT,
    proof_decided_by  TEXT,                      -- name the customer typed on the proof page
    stage_entered_at  TEXT,                      -- when it reached its current stage
    created_by        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT,
    completed_at      TEXT,
    archived_at       TEXT
);
CREATE INDEX idx_jobs_stage ON jobs(stage_id, position);
CREATE INDEX idx_jobs_due ON jobs(due_at);
CREATE INDEX idx_jobs_contact ON jobs(contact_id);

CREATE TABLE job_assignees (
    job_id  INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (job_id, user_id)
);

CREATE TABLE job_conversations (
    job_id          INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (job_id, conversation_id)
);
CREATE INDEX idx_job_conversations_conversation ON job_conversations(conversation_id);

-- One step of a job. Scheduled when start_at/end_at are set; the board places it on its
-- resource row and/or the assigned person's row.
CREATE TABLE job_operations (
    id               INTEGER PRIMARY KEY,
    job_id           INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    sequence         INTEGER NOT NULL DEFAULT 0,
    resource_id      INTEGER REFERENCES resources(id) ON DELETE SET NULL,
    user_id          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    skill_id         INTEGER REFERENCES skills(id) ON DELETE SET NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    start_at         TEXT,
    end_at           TEXT,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'in_progress', 'done')),
    notes            TEXT,
    started_at       TEXT,
    started_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    completed_at     TEXT,
    completed_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL
);
CREATE INDEX idx_job_operations_job ON job_operations(job_id, sequence);
CREATE INDEX idx_job_operations_schedule ON job_operations(start_at, end_at);
CREATE INDEX idx_job_operations_resource ON job_operations(resource_id, start_at);
CREATE INDEX idx_job_operations_user ON job_operations(user_id, start_at);

CREATE TABLE job_checklist (
    id       INTEGER PRIMARY KEY,
    job_id   INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    title    TEXT NOT NULL,
    is_done  INTEGER NOT NULL DEFAULT 0,
    done_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    done_at  TEXT,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_job_checklist_job ON job_checklist(job_id, position);

-- Comments (type 'comment', body = sanitized HTML) and history (type = event name).
CREATE TABLE job_activity (
    id         INTEGER PRIMARY KEY,
    job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    type       TEXT NOT NULL,
    body       TEXT,
    data_json  TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_job_activity_job ON job_activity(job_id, created_at);

-- Job files (attachments with owner_type 'job') the customer sees on the proof page.
CREATE TABLE job_proofs (
    attachment_id INTEGER PRIMARY KEY REFERENCES attachments(id) ON DELETE CASCADE,
    job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_job_proofs_job ON job_proofs(job_id);
