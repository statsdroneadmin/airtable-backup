# airtable-backup

A NousViz plugin that keeps a complete, self-hosted backup of an Airtable
account, pulled with a Personal Access Token. Read-only toward Airtable.

## What it backs up

| Airtable | Stored in | Notes |
|---|---|---|
| Bases | `atb_bases` | Every base the token can see; bases that disappear are flagged, not dropped |
| Tables: fields + views | `atb_tables`, `atb_schema_history` | Snapshot on every schema change |
| Records | `atb_records` | JSONB keyed by **field ID** (stable across renames); deleted records kept |
| Record changes | `atb_record_changes` | created / updated (previous values) / deleted / restored |
| Attachment files | `atb_attachments` | **Bytes stored** (Airtable's URLs expire after 2 h); each file fetched once |
| Comments (optional) | `atb_comments` | Fetched only for records whose comment count changed |

Not available from the Airtable API, so not backed up: automations,
interfaces, extensions, and view filter/sort/visibility settings (only each
view's ID, name and type).

## Setup

1. Create a token at <https://airtable.com/create/tokens>:
   - scopes `data.records:read`, `schema.bases:read`
     (+ `data.recordComments:read` to back up comments)
   - access: the bases or workspaces to back up
2. Install via NousViz "Install from Git":
   `git@github.com:statsdroneadmin/airtable-backup.git` → **Trust** → hard-refresh.
3. Settings → paste the token → **Test connection** → **Run sync**.
4. It then runs daily at 03:00 UTC.

Settings: *Bases to include* (comma-separated names/IDs; blank = all),
*Download attachment files* (default yes), *Max attachment size (MB)*
(default 100), *Back up record comments* (default no).

## How a sync works

Each run re-reads everything, because Airtable has no "modified since" filter
unless every table has a Last-modified field. Records are hashed after removing
the expiring attachment URLs, so an unchanged record costs one cheap UPDATE per
page and no change row. The first complete pass of a table is a baseline with no
change rows. Records are marked deleted **only after a complete pass**: a
cancelled, timed-out or failed pass never deletes anything. Bases are processed
least-recently-synced first, so a run that hits the 4-hour timeout still moves
the backup forward across runs. The sync stays under Airtable's 5 requests/second
per base limit and waits 30 seconds after a 429.

## Overview page

KPIs, a base → table → record browser with search and "include deleted", a
record drawer (all fields, attachment downloads, change history, comments),
recent changes, and exports: a table as CSV or JSON, a whole base as JSON.

## Development

```bash
cd widget && npm install && npm run typecheck && ./build.sh   # commit widget/dist/*.js
~/devhub/sdk-plugins/scripts/smoke-test.sh
~/devhub/sdk-plugins/scripts/preflight.sh
```

HTTP uses stdlib `urllib` only: `requests`/`httpx` are not guaranteed on the
NousViz host.
