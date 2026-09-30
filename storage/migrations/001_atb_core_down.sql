-- 001_atb_core_down.sql
--
-- Down companion to 001_atb_core.sql. Core runs this on "Uninstall with
-- Remove data". The filename must be <NNN>_<base>_down.sql (G-32).

DROP INDEX IF EXISTS idx_atb_comments_record;
DROP TABLE IF EXISTS atb_comments;

DROP INDEX IF EXISTS idx_atb_attachments_status;
DROP INDEX IF EXISTS idx_atb_attachments_record;
DROP TABLE IF EXISTS atb_attachments;

DROP INDEX IF EXISTS idx_atb_changes_time;
DROP INDEX IF EXISTS idx_atb_changes_record;
DROP TABLE IF EXISTS atb_record_changes;

DROP INDEX IF EXISTS idx_atb_records_created;
DROP INDEX IF EXISTS idx_atb_records_record;
DROP INDEX IF EXISTS idx_atb_records_base;
DROP TABLE IF EXISTS atb_records;

DROP INDEX IF EXISTS idx_atb_schema_history_table;
DROP TABLE IF EXISTS atb_schema_history;

DROP INDEX IF EXISTS idx_atb_tables_base;
DROP TABLE IF EXISTS atb_tables;

DROP TABLE IF EXISTS atb_bases;
DROP TABLE IF EXISTS atb_runs;
