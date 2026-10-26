-- Staffing: who works where, when they can work, shifts, time off, and the time clock.
-- Every person is a row in users; staff_profiles holds their employment details.

CREATE TABLE locations (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    address    TEXT,
    color      TEXT,
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- Roles people are scheduled into: Press Operator, Designer, Bindery, Front Desk, Driver...
CREATE TABLE positions (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color        TEXT,
    default_rate REAL,
    is_active    INTEGER NOT NULL DEFAULT 1,
    position     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE skills (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);

CREATE TABLE staff_profiles (
    user_id             INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    employee_number     TEXT,
    employment_type     TEXT NOT NULL DEFAULT 'full_time'
                        CHECK (employment_type IN ('full_time', 'part_time', 'contractor', 'seasonal')),
    hourly_rate         REAL,
    hire_date           TEXT,
    target_hours_week   REAL,
    max_hours_week      REAL,
    default_position_id INTEGER REFERENCES positions(id) ON DELETE SET NULL,
    default_location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    pto_hours_per_year  REAL,
    emergency_contact   TEXT,
    notes               TEXT,
    is_schedulable      INTEGER NOT NULL DEFAULT 1,
    updated_at          TEXT
);

CREATE TABLE staff_positions (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, position_id)
);

CREATE TABLE staff_skills (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    level    INTEGER NOT NULL DEFAULT 1,   -- 1 trainee, 2 competent, 3 expert/trainer
    PRIMARY KEY (user_id, skill_id)
);

-- Recurring weekly availability. weekday: 0=Monday ... 6=Sunday (Python's convention).
CREATE TABLE availability (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    weekday    INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_time TEXT NOT NULL,
    end_time   TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'available' CHECK (kind IN ('available', 'preferred', 'unavailable')),
    note       TEXT
);
CREATE INDEX idx_availability_user ON availability(user_id, weekday);

CREATE TABLE time_off_requests (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL DEFAULT 'vacation'
                CHECK (kind IN ('vacation', 'sick', 'personal', 'unpaid', 'other')),
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    start_time  TEXT,                  -- partial day when both times are set
    end_time    TEXT,
    hours       REAL,
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'denied', 'cancelled')),
    reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TEXT,
    review_note TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_time_off_user ON time_off_requests(user_id, start_date);

-- user_id NULL = open shift anyone qualified can pick up.
CREATE TABLE shifts (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    position_id   INTEGER REFERENCES positions(id) ON DELETE SET NULL,
    location_id   INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    start_at      TEXT NOT NULL,
    end_at        TEXT NOT NULL,
    break_minutes INTEGER NOT NULL DEFAULT 0,
    notes         TEXT,
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
    job_id        INTEGER,
    created_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT,
    published_at  TEXT,
    reminded_at   TEXT                -- "your shift starts soon" was sent
);
CREATE INDEX idx_shifts_range ON shifts(start_at, end_at);
CREATE INDEX idx_shifts_user ON shifts(user_id, start_at);

CREATE TABLE shift_templates (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    position_id   INTEGER REFERENCES positions(id) ON DELETE SET NULL,
    location_id   INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    start_time    TEXT NOT NULL,
    end_time      TEXT NOT NULL,
    break_minutes INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

-- drop: give a shift away (becomes open once approved); pickup: claim an open shift;
-- swap: trade with target_user_id (their target_shift_id, if any). A swap needs the
-- coworker to accept before a manager approves.
CREATE TABLE shift_requests (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('drop', 'pickup', 'swap')),
    shift_id        INTEGER NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
    requester_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_user_id  INTEGER REFERENCES users(id) ON DELETE CASCADE,
    target_shift_id INTEGER REFERENCES shifts(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'accepted', 'approved', 'denied', 'cancelled')),
    note            TEXT,
    decided_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    decided_at      TEXT,
    decision_note   TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_shift_requests_status ON shift_requests(status);
CREATE INDEX idx_shift_requests_shift ON shift_requests(shift_id);

-- Time clock punches. clock_out NULL = currently clocked in. breaks_json: [{"start", "end"}].
CREATE TABLE time_entries (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shift_id      INTEGER REFERENCES shifts(id) ON DELETE SET NULL,
    job_id        INTEGER,
    clock_in      TEXT NOT NULL,
    clock_out     TEXT,
    breaks_json   TEXT NOT NULL DEFAULT '[]',
    break_minutes INTEGER NOT NULL DEFAULT 0,
    notes         TEXT,
    source        TEXT NOT NULL DEFAULT 'clock' CHECK (source IN ('clock', 'kiosk', 'manual')),
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'approved')),
    flag          TEXT,              -- needs review, e.g. auto_clock_out
    approved_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_at   TEXT,
    created_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT
);
CREATE INDEX idx_time_entries_user ON time_entries(user_id, clock_in);
CREATE INDEX idx_time_entries_job ON time_entries(job_id);
CREATE INDEX idx_time_entries_open ON time_entries(clock_out);
