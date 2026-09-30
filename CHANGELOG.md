# Changelog

All notable changes to this plugin are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

---

## [0.1.0] — Airtable account backup

### Added

- Backs up every Airtable base your Personal Access Token can see (or a chosen
  subset) into NousViz: base and table schema (fields, views), every record,
  attachment files, and optionally record comments.
- **Attachments are downloaded and stored**, because Airtable's attachment
  links expire 2 hours after they are issued. Each file is fetched once.
- **Change log.** Each sync compares every record with the stored copy and
  records what was created, updated (with the previous values), deleted or
  restored. Deleted records are kept, with their last values.
- **Schema history.** A table's fields and views are snapshotted whenever they
  change.
- **Overview page:** backup totals, a base → table → record browser with
  search, a record drawer (all fields, attachment downloads, change history,
  comments), and recent changes.
- **Export:** a table as CSV or JSON, or a whole base (schema + records) as JSON.
- Daily automatic sync (03:00 UTC) plus a **Run sync** button. Stays within
  Airtable's rate limit (5 requests/second per base).

### Token scopes

Create the token at airtable.com/create/tokens with:
`data.records:read`, `schema.bases:read`, and (only for comments)
`data.recordComments:read`. Give it access to the bases (or workspaces) you want
backed up. The plugin never writes to Airtable.

### Operator workflow on first install

- Install → click **Trust this plugin** → hard-refresh the page once.
- Settings → paste the token → **Test connection** → **Run sync**.
- The first sync is a baseline and records no changes; later syncs record
  changes.

### Plugin author release checklist (every release)

1. Bump `version:` in `plugin.yaml` to match this CHANGELOG entry's heading.
2. Commit + push code.
3. `git tag -a vX.Y.Z -m "…"` then `git push origin vX.Y.Z`.
4. Only then Update on NousViz.
