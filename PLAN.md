# PLAN.md

The SOP for this plugin. Every change goes through these gates **before** code is written:

1. **Ticket** — what's broken / what's missing, with specific evidence
2. **Plan** — 3-5 lines of how
3. **Test plan** — what success looks like (operator-visible checks — see `docs/11-verification-spec.md` in the parent guide for the template)
4. **CHANGELOG stub** — draft the user-facing entry

If any gate is missing, you don't have permission to write code.

Reference: `docs/08-sop-and-discipline.md` in the parent `nousviz-plugin-authoring` guide.

---

## Implementation phases

### v0.1.1 — Fix: every sync fails with `_start_run() got an unexpected keyword argument 'source'`

**Ticket.** On first install, every sync fails immediately:
`TypeError: AirtableBackupSync._start_run() got an unexpected keyword argument 'source'`.
Cause: core's `BaseSyncScript.main()` calls `self._start_run(source=args.source)`
(`sdk/nousviz_sdk/sync.py:273` in nousviz/nousviz-app, defined at line 132) to
create or adopt the `job_runs` row. Our subclass defined its own private
`_start_run()` with no parameters, silently overriding the base method. The v0.1.0
harness missed it because its stub `BaseSyncScript` didn't have the private
method. No other name collides with the base class (`logger`, `_run_id`,
`_rows_synced`, `_rows_failed`, `_details`, `_start_run`, `_complete_run`,
`_record_standalone_success`).

**Plan.**
1. Rename the plugin's run-bookkeeping helpers to `_atb_start_run` / `_atb_finish_run`
   and the attribute `run_id` → `atb_run_id` so nothing shadows the base class.
2. Point the local harness at core's real `sync.py` instead of a stub, so
   base-class collisions are caught locally from now on.
3. Rerun the full harness; bump to 0.1.1; tag.

**Test plan.**
- [ ] Harness passes using core's real `BaseSyncScript.main()` (job_runs row created + completed)
- [ ] On NousViz: Update plugin → `/health-check` shows `0.1.1`
- [ ] Run sync → job reaches `success`; Overview shows bases / tables / records
- [ ] `scripts/smoke-test.sh` + `scripts/preflight.sh` pass; `git ls-remote --tags origin` shows `v0.1.1`

**CHANGELOG stub.** See `CHANGELOG.md` "[0.1.1]".

---

### v0.1.0 — Airtable account backup (mirror + change log + attachments + export)

**Ticket.** The operator wants a complete, self-hosted backup ("clone") of
their Airtable account, pulled with a Personal Access Token. Airtable offers no
account-level export; attachment URLs returned by the API **expire 2 hours after
retrieval** (airtable.com/developers/web/api/field-model), so a backup that only
keeps URLs is not a backup.

Intake decisions (operator, 2026-09-30):
- Scope: Postgres mirror + export (JSON/CSV). Restore-to-Airtable deferred.
- Attachments: download and store the bytes.
- History: latest copy + change log (created / updated / deleted / restored,
  previous values kept).
- Record comments: optional toggle, off by default.

Constraint: the `nousviz_plugin` role has no DDL, so per-Airtable-table Postgres
tables are impossible. Records are stored as JSONB in a fixed schema, keyed by
Airtable field ID (stable across renames); field names resolve via the stored
table schema.

Verified Airtable API facts (developer docs, 2026-09-30):
- `GET /v0/meta/whoami` (no scope), `GET /v0/meta/bases` (schema.bases:read,
  `offset` pagination), `GET /v0/meta/bases/{baseId}/tables` (schema.bases:read,
  fields + views).
- `POST /v0/{baseId}/{tableId}/listRecords` (data.records:read), pageSize ≤ 100,
  `offset` pagination, `returnFieldsByFieldId`, `recordMetadata: ["commentCount"]`.
  Empty fields are omitted from records.
- `GET /v0/{baseId}/{tableId}/{recordId}/comments` (data.recordComments:read).
- Rate limit 5 req/s per base, 50 req/s per token; 429 → wait 30 s.

Unverified (handled defensively, needs live confirmation):
- A list-records `offset` may expire mid-table (`LIST_RECORDS_ITERATOR_NOT_AVAILABLE`,
  422). Not in the published error docs. Sync restarts the table (max 2 times);
  the upsert is idempotent so a restart is safe.

**Plan.**
1. Migration `001_atb_core.sql`: `atb_runs`, `atb_bases`, `atb_tables`,
   `atb_schema_history`, `atb_records`, `atb_record_changes`, `atb_attachments`
   (BYTEA), `atb_comments`.
2. `src/airtable_backup_client.py` — stdlib `urllib` client (no requests/httpx:
   not guaranteed on host), per-base throttle ≤ 4.5 req/s, 429 → 30 s wait,
   5xx backoff, bounded attachment download.
3. `src/airtable_backup_sync.py` — per run: list bases → per included base
   (stalest first) fetch schema → per table page all records, content-hash
   (attachment URLs scrubbed so signed-URL churn is not a "change"), write
   created/updated/restored change rows, download new attachment bytes on the
   same page, mark unseen records deleted **only after a complete table pass**.
   First complete pass of a table is a baseline (no "created" noise).
4. `api/routes.py` — test-connection, sync-now, summary, bases, tables, records,
   record detail, changes, table export (CSV/JSON), base export (JSON, streamed),
   attachment download. All data routes `Depends(_require_analyst)`.
5. One consolidated Overview widget `AirtableBackupApp`: KPIs, base/table
   browser, record grid (search, include-deleted), record drawer (fields,
   attachments, history, comments), exports, recent changes.

**Test plan.**

#### Install + first launch
- [ ] Install from `git@github.com:statsdroneadmin/airtable-backup.git` completes, no error toast
- [ ] Trust banner → Trust → hard-refresh; sidebar shows "Airtable Backup"
- [ ] `/plugin/airtable-backup/overview` loads, no "Plugin failed to load" banner
- [ ] Overview shows the empty state ("No backup yet…") before first sync

#### Settings
- [ ] Credential form shows: Personal access token (masked), Bases to include,
      Download attachments, Max attachment size (MB), Back up record comments
- [ ] Save token → "Save your Airtable token" ticks
- [ ] Test connection → toast "Connected as usr… — N base(s) visible" → checklist ticks
- [ ] Bad token → error toast mentioning 401, no crash

#### First sync
- [ ] Run sync → job appears in `/system/jobs` with progress (base / table / records)
- [ ] Completes `success`; KPIs show bases / tables / records matching Airtable
- [ ] Spot-check 3 records against Airtable UI (text, linked record, attachment, date)
- [ ] Attachments: count stored = count in Airtable; one downloaded file opens correctly
- [ ] Recent changes is empty after the first (baseline) sync

#### Change detection (second sync)
- [ ] Edit 1 record, delete 1 record, add 1 record in Airtable → Run sync
- [ ] Recent changes shows exactly 1 updated (with previous value), 1 deleted, 1 created
- [ ] Unchanged records produce no change rows (re-run sync with no edits → 0 changes)
- [ ] Deleted record still visible with "Include deleted", with its last values

#### Export
- [ ] Table CSV opens in a spreadsheet with field-name headers
- [ ] Table JSON and Base JSON download and parse (`python -m json.tool`)

#### Comments (toggle on)
- [ ] With "Back up record comments = yes", records with comments show them in the drawer

#### Pre-tag verification
- [ ] `scripts/smoke-test.sh` passes
- [ ] `scripts/preflight.sh` passes
- [ ] Widget typecheck + build; hygiene greps (0 / ≥2 / 0)
- [ ] `git ls-remote --tags origin` shows `v0.1.0`; `plugin.yaml` version matches

**CHANGELOG stub.** See `CHANGELOG.md` "[0.1.0]".

**Deferred (v0.2+).** Restore/clone into a new Airtable base via the Web API
(computed fields — formula/lookup/rollup — and linked records need special
handling); per-base include toggles in the UI; view `visibleFieldIds`;
comment-edit detection (v0.1 refetches comments only when a record's comment
count changes).

---

<!--
Template for subsequent versions — copy-paste and fill in:

### vX.Y.Z — <one-line summary>

**Ticket.** What's broken / what's missing. Cite specific evidence.

**Plan.**
1. First step.

**Test plan.**
- [ ] `git ls-remote --tags origin` shows the new tag (not just local)
- [ ] `plugin.yaml` `version:` matches the tag
- [ ] `scripts/smoke-test.sh` passes
- [ ] `scripts/preflight.sh` passes
- [ ] Operator-visible check

**CHANGELOG stub.**
-->
