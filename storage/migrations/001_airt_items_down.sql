-- 001_airt_items_down.sql
--
-- Down companion to 001_airt_items.sql. Core's uninstall handler runs every
-- *_down.sql in this directory in REVERSE lexicographic order when an
-- operator selects "Uninstall with Remove data" — without this file, the
-- plugin's tables would leak across uninstalls. See:
--
--   apps/api/src/routes/plugins.py: _run_down_migrations()
--   docs/02-plugin-contract.md     "Migrations: up + down pairs"
--   docs/appendix-gotchas.md       G-32
--
-- Naming convention is load-bearing: this file MUST be named
-- <NNN>_<base>_down.sql where <NNN>_<base>.sql is the up migration. Core
-- strips `_down.sql` from the filename to match against
-- `schema_migrations.filename` and delete the row.
--
-- Drops here mirror the creates in the up file in reverse dependency
-- order: indexes before their tables, dependent tables before their
-- parents. Use DROP … IF EXISTS so re-running is idempotent.

-- Sync state table (no dependents).
DROP TABLE IF EXISTS airt_sync_state;

-- Indexes on airt_items. Postgres would CASCADE these with `DROP TABLE`, but
-- explicit DROPs keep the intent readable and survive partial-migration
-- recovery.
DROP INDEX IF EXISTS idx_airt_items_is_active;
DROP INDEX IF EXISTS idx_airt_items_category;

-- The items table itself.
DROP TABLE IF EXISTS airt_items;
