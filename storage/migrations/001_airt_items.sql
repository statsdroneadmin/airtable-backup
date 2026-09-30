-- 001_airt_items.sql
--
-- Demo table populated by the sync. Replace with whatever your plugin
-- actually stores. The `ex_` prefix matches `databases.postgres.table_prefix`
-- in plugin.yaml.
--
-- Migration files run in lexicographic order at install time. Number them
-- 001_, 002_, … to keep ordering predictable. Each migration runs once per
-- install. Don't edit a migration that's already shipped — write a new one.
--
-- Every CREATE here MUST have a matching DROP IF EXISTS in the companion
-- 001_airt_items_down.sql, which core runs in reverse-lex order on
-- "Uninstall with Remove data". See docs/02-plugin-contract.md
-- "Migrations: up + down pairs" and appendix-gotchas.md G-32.

CREATE TABLE IF NOT EXISTS airt_items (
    id              BIGSERIAL PRIMARY KEY,
    external_id     TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    category        TEXT,
    score           NUMERIC(5, 2),
    is_active       BOOLEAN DEFAULT true,
    raw_data        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_airt_items_category ON airt_items (category);
CREATE INDEX IF NOT EXISTS idx_airt_items_is_active ON airt_items (is_active);

-- Sync state table — used by the sync to track checkpoints, last successful
-- run, etc. Two columns: a key + a JSON blob. Schema-less by design.

CREATE TABLE IF NOT EXISTS airt_sync_state (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
