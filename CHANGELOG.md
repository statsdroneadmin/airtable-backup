# Changelog

All notable changes to this plugin are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(Draft your CHANGELOG entry here BEFORE writing code. See `PLAN.md` for the SOP.)

---

## [0.1.0] — Initial scaffold

### Added

- Plugin manifest declaring connection (api_key + base_url), database (`airt_items`), navigation, dashboards, sync, hooks, actions, setup checklist, and one frontend widget.
- One Postgres migration creating `airt_items` and `airt_sync_state`.
- Sync script subclassing `BaseSyncScript` — populates `airt_items` from a fixture (replace with real fetch).
- HTTP routes: `/health-check`, `/test-connection`, `/sync-now`, `/overview`, `/items`, `/items/filters`.
- Lifecycle hooks: `on_credentials_saved`, `on_first_run_success`.
- Overview dashboard with one stat KPI, one bar chart, one custom-widget panel, one declarative table.
- One custom React widget (`AirtableBackupKpiCard`) demonstrating the v0.9.4.7+ build pipeline (alias + external for `react` and `react/jsx-runtime`).

### Plugin author release checklist (every release)

1. Bump `version:` in `plugin.yaml` to match this CHANGELOG entry's heading.
2. Commit code: `git commit -m "feat/fix: ..."`.
3. Push code: `git push origin main`.
4. **Tag the release**: `git tag -a v0.1.0 -m "v0.1.0 — ..."`.
5. **Push the tag**: `git push origin v0.1.0`. (`git push` alone doesn't push tags.)
6. Only then tell operators to install / Update.

NousViz pulls the latest semver tag — without step 4+5, install fails with `Plugin not found at tag vX.Y.Z`.

### Operator workflow on first install

- Install plugin → click **Trust this plugin** when the consent banner appears → hard-refresh the page once.
- Configure credentials on the Settings tab → click **Test connection** → click **Run sync**.
- Setup checklist guides you through the four steps; once all four are checked, the plugin is fully operational.
