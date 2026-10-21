#!/usr/bin/env bash
# tests/run.sh — end-to-end harness for airtable-backup.
#
# Starts a throwaway Postgres (PG 14+ binaries on PATH or PG_BIN), applies the
# migration, grants the nousviz_plugin role only CRUD + sequence usage (like a
# real install), downloads NousViz core's real sdk/nousviz_sdk/sync.py so
# BaseSyncScript collisions are caught, runs tests/test_e2e.py, tears down.
#
# Needs: python3 with psycopg2 + fastapi + httpx (for TestClient), curl.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
PG_BIN="${PG_BIN:-$(dirname "$(command -v initdb 2>/dev/null || echo /opt/homebrew/opt/postgresql@16/bin/initdb)")}"
PORT="${ATB_PG_PORT:-55432}"
CORE_REF="${NOUSVIZ_CORE_REF:-main}"
TMP="$(mktemp -d /tmp/atb-test.XXXXXX)"
cleanup() { "$PG_BIN/pg_ctl" -D "$TMP/pg" stop -m fast >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT

curl -fsSL "https://raw.githubusercontent.com/nousviz/nousviz-app/$CORE_REF/sdk/nousviz_sdk/sync.py" \
  -o "$HERE/sdk_stub/nousviz_sdk/sync.py"

"$PG_BIN/initdb" -D "$TMP/pg" -U admin --auth=trust >/dev/null
"$PG_BIN/pg_ctl" -D "$TMP/pg" -o "-p $PORT -k '' -c listen_addresses=127.0.0.1" -l "$TMP/pg.log" start >/dev/null
for _ in $(seq 20); do "$PG_BIN/pg_isready" -h 127.0.0.1 -p "$PORT" >/dev/null 2>&1 && break; sleep 0.5; done
psql() { "$PG_BIN/psql" -h 127.0.0.1 -p "$PORT" -U admin -v ON_ERROR_STOP=1 -q "$@"; }
psql -d postgres -c "CREATE DATABASE atb;" -c "CREATE ROLE nousviz_plugin LOGIN PASSWORD 'test';"
psql -d atb -f "$ROOT/storage/migrations/001_atb_core.sql"
psql -d atb -c "
CREATE TABLE job_runs (id BIGSERIAL PRIMARY KEY, job_id TEXT, status TEXT, source TEXT,
  started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, duration_ms INT, rows_written INT,
  details JSONB, error TEXT);
GRANT USAGE ON SCHEMA public TO nousviz_plugin;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nousviz_plugin;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO nousviz_plugin;"

ATB_ADMIN_DSN="host=127.0.0.1 port=$PORT dbname=atb user=admin" \
ATB_DSN="host=127.0.0.1 port=$PORT dbname=atb user=nousviz_plugin password=test" \
  python3 "$HERE/test_e2e.py"
