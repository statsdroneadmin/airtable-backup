-- 001_atb_core.sql
--
-- Airtable Backup schema. The nousviz_plugin role has no DDL, so an Airtable
-- table can't become its own Postgres table. Instead every Airtable object
-- lives in a fixed set of tables:
--
--   atb_runs            one row per sync run (stats, status)
--   atb_bases           every base the token has ever seen
--   atb_tables          every table: current fields + views (JSONB)
--   atb_schema_history  a snapshot each time a table's schema changes
--   atb_records         current copy of every record (fields keyed by field ID)
--   atb_record_changes  created / updated / deleted / restored log
--   atb_attachments     attachment files, bytes stored verbatim (BYTEA)
--   atb_comments        record comments (optional)
--
-- Every CREATE has a matching DROP in 001_atb_core_down.sql.

CREATE TABLE IF NOT EXISTS atb_runs (
    id            BIGSERIAL PRIMARY KEY,
    job_run_id    BIGINT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'running',   -- running | success | partial | cancelled | error
    stats         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS atb_bases (
    base_id           TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    permission_level  TEXT,
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at    TIMESTAMPTZ,                   -- last complete pass of every table
    deleted_at        TIMESTAMPTZ,                   -- no longer visible to the token
    last_error        TEXT
);

CREATE TABLE IF NOT EXISTS atb_tables (
    table_id           TEXT PRIMARY KEY,
    base_id            TEXT NOT NULL,
    name               TEXT NOT NULL,
    description        TEXT,
    primary_field_id   TEXT,
    fields             JSONB NOT NULL DEFAULT '[]'::jsonb,
    views              JSONB NOT NULL DEFAULT '[]'::jsonb,
    schema_hash        TEXT,
    position           INTEGER NOT NULL DEFAULT 0,
    first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    baseline_complete  BOOLEAN NOT NULL DEFAULT false, -- first full pass done
    last_synced_at     TIMESTAMPTZ,
    deleted_at         TIMESTAMPTZ,
    last_error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_atb_tables_base ON atb_tables (base_id);

CREATE TABLE IF NOT EXISTS atb_schema_history (
    id           BIGSERIAL PRIMARY KEY,
    table_id     TEXT NOT NULL,
    base_id      TEXT NOT NULL,
    captured_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    name         TEXT NOT NULL,
    fields       JSONB NOT NULL,
    views        JSONB NOT NULL,
    schema_hash  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_atb_schema_history_table ON atb_schema_history (table_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS atb_records (
    table_id          TEXT NOT NULL,
    record_id         TEXT NOT NULL,
    base_id           TEXT NOT NULL,
    created_time      TIMESTAMPTZ,
    fields            JSONB NOT NULL DEFAULT '{}'::jsonb, -- keyed by field ID; attachment URLs scrubbed
    content_hash      TEXT NOT NULL,
    comment_count     INTEGER,
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_changed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_run_id  BIGINT,
    deleted_at        TIMESTAMPTZ,
    PRIMARY KEY (table_id, record_id)
);
CREATE INDEX IF NOT EXISTS idx_atb_records_base ON atb_records (base_id);
CREATE INDEX IF NOT EXISTS idx_atb_records_record ON atb_records (record_id);
CREATE INDEX IF NOT EXISTS idx_atb_records_created ON atb_records (table_id, created_time);

CREATE TABLE IF NOT EXISTS atb_record_changes (
    id                 BIGSERIAL PRIMARY KEY,
    run_id             BIGINT,
    base_id            TEXT NOT NULL,
    table_id           TEXT NOT NULL,
    record_id          TEXT NOT NULL,
    change_type        TEXT NOT NULL,          -- created | updated | deleted | restored
    changed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    changed_field_ids  TEXT[] NOT NULL DEFAULT '{}',
    previous_fields    JSONB                   -- values before an update/restore (changed fields only)
);
CREATE INDEX IF NOT EXISTS idx_atb_changes_record ON atb_record_changes (table_id, record_id, changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_atb_changes_time ON atb_record_changes (changed_at DESC);

CREATE TABLE IF NOT EXISTS atb_attachments (
    attachment_id  TEXT PRIMARY KEY,
    base_id        TEXT NOT NULL,
    table_id       TEXT NOT NULL,
    record_id      TEXT NOT NULL,
    field_id       TEXT NOT NULL,
    filename       TEXT,
    content_type   TEXT,
    size_bytes     BIGINT,
    width          INTEGER,
    height         INTEGER,
    status         TEXT NOT NULL DEFAULT 'pending', -- pending | stored | failed | too_large | disabled
    sha256         TEXT,
    content        BYTEA,
    error          TEXT,
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    downloaded_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_atb_attachments_record ON atb_attachments (table_id, record_id);
CREATE INDEX IF NOT EXISTS idx_atb_attachments_status ON atb_attachments (status);

CREATE TABLE IF NOT EXISTS atb_comments (
    comment_id         TEXT PRIMARY KEY,
    base_id            TEXT NOT NULL,
    table_id           TEXT NOT NULL,
    record_id          TEXT NOT NULL,
    parent_comment_id  TEXT,
    author             JSONB,
    text               TEXT,
    created_time       TIMESTAMPTZ,
    last_updated_time  TIMESTAMPTZ,
    raw                JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_atb_comments_record ON atb_comments (table_id, record_id);
