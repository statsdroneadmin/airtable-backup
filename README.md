# airtable-backup

A NousViz plugin scaffold. After running `scripts/new-plugin.sh` from the parent guide repo, this README is renamed for your plugin and you start editing.

This file is what operators read when they look at your plugin's GitHub page or marketplace listing. Replace this paragraph with what your plugin actually does.

---

## What this plugin does

(Describe the use case in 2-3 paragraphs. Who is this for, what does it pull in, what does it surface.)

---

## Setup

1. **Install** via NousViz's "Add private plugin" flow with the SSH URL of this repo.
2. **Configure connection** on the Settings tab. Paste API key + base URL (default works for production).
3. **Test connection** — click the action button. You should see a success toast.
4. **Run sync** — click the action button. Wait ~30 seconds for the first sync to complete.
5. **Trust frontend** — if a banner appears, click "Trust this plugin" then hard-refresh.

The setup checklist on the plugin page guides you through these steps.

---

## Modules / Tabs

- **Overview** — KPI tiles, items-by-category chart, recent items table.

(Add more sections as you add tabs.)

---

## Data

- Imports into `airt_items` (rename to fit your domain) on a 6-hourly cron.
- Sync is idempotent — running it twice produces the same state.
- Schema in `storage/migrations/`.

---

## Operator runbook

### Deploy key (one per plugin)

NousViz core v0.9.5.9 (ticket B204) requires a per-repo deploy key. A single `github.com`-wide key no longer works — each plugin's repo needs its own entry registered against the exact `repo_url` (e.g. `git@github.com:<your-org>/plugin-example.git`).

Set this up via **Settings → Deploy Keys → Add deploy key** in the NousViz admin UI. Paste the private key, set the repo URL exactly, click the row's **Test** button to confirm. If you skip this step or use a key registered for a different repo, the install / update flow fails with `Permission denied (publickey)` and a `/system/logs` entry pointing you here.

Full walkthrough: see `docs/12-installing-on-nousviz.md` Step 1 in the [nousviz-plugin-authoring](https://github.com/JoeHatch/nousviz-plugin-authoring) guide.

### When something goes wrong

| Symptom | Where to look |
|---|---|
| Setup checklist stuck at N/4 | Each item maps to a predicate — see `plugin.yaml`'s `setup_checklist` block. Cross-reference `docs/appendix-gotchas.md G-6` in the parent guide. |
| Plugin install fails | `/system/logs?source=plugin_install` (since core v0.9.5.9 / B203). Look for `[airtable-backup]` prefix on log lines. |
| Plugin update / "Check for updates" fails | `/system/logs?source=plugin_update`. Common cause: missing per-repo deploy key (B204 — see above). |
| Sync fails | `/system/logs?source=sync&plugin_id=airtable-backup` |
| Action button shows error toast | Read the toast text — it includes the exception class. Full traceback at `/system/logs?source=plugin_route` |
| Hook (install / on_install / on_uninstall) failed | `/system/logs?source=plugin_install` or `?source=plugin_uninstall` (since core v0.9.5.9 / B203). |
| Custom widget shows placeholder card | Trust the plugin or hard-refresh. If still broken, browser console has the error |

---

## Development

```bash
# One-time setup (only if you ship a custom widget)
cd widget && npm install

# Make changes, then rebuild widget
cd widget && ./build.sh

# Quick "did the code work?" check (no NousViz core checkout needed)
/path/to/nousviz-plugin-authoring/scripts/smoke-test.sh

# Pre-tag release-readiness (security audit + bundle hygiene)
/path/to/nousviz-plugin-authoring/scripts/preflight.sh

# Commit + tag + push
git add -A && git commit -m "feat: ..."
git tag -a v0.1.1 -m "v0.1.1 — ..."
git push origin main && git push origin v0.1.1
```

The version in `plugin.yaml` and the git tag must match.

You don't need a local NousViz core checkout to develop this plugin — the install-time validator on your NousViz instance catches manifest and import errors. See `docs/01-getting-started.md` "Two paths to choose between" in the parent guide for the rare cases where a checkout helps.

---

## Updating

Operators update by clicking **Update** on the plugin's Settings page. NousViz pulls the latest `v*` tag and runs migrations. If `frontend.components` changed, the operator must re-trust the plugin.

Update notes go in `CHANGELOG.md` per release. The first line under each version's heading is what operators see.
