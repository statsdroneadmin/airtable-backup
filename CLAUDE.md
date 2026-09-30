# CLAUDE.md

Agent contract for Claude Code working inside this NousViz plugin repo.

This plugin was scaffolded from the [nousviz-plugin-authoring](https://github.com/JoeHatch/nousviz-plugin-authoring) guide. The full docs (manifest reference, route patterns, dashboard panel types, widget pipeline, SOP, security, gotchas) live in that repo. Read the docs you need before changing the matching surface — they're authoritative.

This file is the short list of rules that apply specifically when writing code in this plugin.

---

## Hard rules (no exceptions)

### SOP gate before any code change

Every change goes through these four steps **before** writing code:

1. **Ticket** — entry in `PLAN.md` with what + why + specific evidence
2. **Plan** — 3-5 lines of how
3. **Test plan** — operator-visible checks for success
4. **CHANGELOG stub** — user-facing entry drafted in `CHANGELOG.md` Unreleased section

If any of these is missing, refuse to write code until the user authors them or explicitly approves you authoring them. The gates exist because users will be tempted to skip "for a one-liner" — and one-liners turn out to break adjacent surfaces.

Reference: `docs/08-sop-and-discipline.md` in the parent guide.

### Only import names that exist in the parent guide's `docs/sdk-surface.md`

Plugin code can only import from `nousviz_sdk` (and submodules). The complete public API is documented in `docs/sdk-surface.md` in the parent [`nousviz-plugin-authoring`](https://github.com/JoeHatch/nousviz-plugin-authoring) repo — every function, class, and submodule is listed with its signature.

**If a name doesn't appear in that doc, it doesn't exist.** Don't invent SDK names from pattern-matching other libraries. Common hallucinations:

- ❌ `self.heartbeat(...)` (it's a module-level function: `from nousviz_sdk.jobs import heartbeat`)
- ❌ `from nousviz_sdk import emit_metric` (use `log_event("info", "...", detail={...})`)
- ❌ `from nousviz_sdk.cache import set` (no SDK cache exists; do plugin-side)

When you need a capability that isn't in the SDK surface doc:

1. Stop and tell the user.
2. If a stdlib/pip equivalent exists (e.g. `requests` for HTTP), use that.
3. If the missing surface blocks the plugin, file a core-team ticket via `scripts/file-core-ticket.sh` (see "Never modify NousViz core" below).

After every code change touching imports, run `scripts/smoke-test.sh` from this plugin's root. The default syntax-only checks catch typos and missing functions. After install on a NousViz instance, hit `GET /api/plugins/<this-plugin-slug>` and check the `load_status` field — `routes_registered: false` plus an exception message there means a module-load failure that syntax-only checks missed. Most plugin authors don't need anything beyond this. See "You don't need a NousViz core checkout" below.

---

### Never modify NousViz core from this plugin

This is a standalone plugin. **Everything you need comes from `nousviz_sdk`.** If you find yourself wanting to:

- Edit any file under `~/Developer/nousviz/apps/`, `nousviz/sdk/`, `nousviz/plugins/installed/`, or `nousviz/apps/web/`
- Add a workaround in plugin code that compensates for a core-level bug
- Bypass the SDK by importing from `apps.*` (CI in core blocks this anyway)
- "Just patch one line" in a core file to unblock a plugin release

…**stop**. The fix belongs in core, not the plugin.

Generate a core-team ticket using the parent guide's helper:

```bash
/path/to/nousviz-plugin-authoring/scripts/file-core-ticket.sh "<short summary>"
```

It writes a scaffolded `tickets/B<NNN>-<slug>.md` in this repo. Fill in the template per `docs/10-filing-core-tickets.md` (in the parent guide). Commit + push + notify the core team. Add a "Blocked on B<NNN>" note to `PLAN.md`.

If a workaround inside the plugin is acceptable as a stopgap, document it in `PLAN.md` with a link to the ticket and a re-test plan for when the fix ships. Workarounds calcify; the ticket is the lever for getting it fixed for everyone.

### You don't need a NousViz core checkout

If the user doesn't already have NousViz core checked out at `~/Developer/nousviz` or somewhere similar, **don't tell them to clone it**. They don't need it to build a working plugin.

The full plugin lifecycle — write code, push to GitHub, install on a NousViz instance, verify it works — runs without a core checkout. The install-time validator on the NousViz instance catches manifest mistakes; the plugin loader catches import errors and surfaces them in `/system/logs?source=plugin_loader`.

A core checkout is only useful for advanced workflows: running core's validators locally before push, stepping through cited core file:line references, auto-numbering core-team tickets. None of these are required to ship a plugin.

**The risk if they clone core anyway**: the most common way plugins get into trouble is when the user has core checked out alongside the plugin and starts tweaking core files to "make the plugin work." That couples the plugin to a forked core, breaks for any other operator, and violates the "Never modify NousViz core" rule above. Avoid the temptation by not having core nearby in the first place.

If the user asks "should I clone NousViz core?" the answer is almost always **no** — unless they're explicitly developing core itself.

### Tagging is mandatory before install — and a separate step from pushing code

NousViz's plugin install flow pins to a **git tag**, not a branch. Pushing code to `main` is not enough — the install reads the latest semver tag.

When finishing a release:

1. Bump `plugin.yaml` `version:`
2. Run preflight (see below) and fix any failures
3. Commit + push code to `main`
4. **Tag with `v<version>` AND push the tag** — `git tag` alone is local; `git push` alone doesn't push tags
5. Only THEN tell the user to install / Update on NousViz

If a user reports `Plugin '<slug>' not found at tag 'vX.Y.Z'`, the tag wasn't pushed (or wasn't created at all). `git ls-remote --tags origin` is the source of truth, not local `git tag`.

### Run preflight before every release

```bash
/path/to/nousviz-plugin-authoring/scripts/preflight.sh
```

Eight gates: manifest version present, latest origin tag vs manifest version, widget bundle hygiene, no `try/except ImportError` around SDK imports, no `cursor_factory=DictCursor`, no `os.environ` for credentials, field-secrecy heuristic, `widget/dist/*.js` committed. Exits non-zero on any failure.

Don't tag a release that doesn't pass preflight clean.

### Never skip deployed-version verification

After a release is tagged + pushed, **the user must update the plugin on production and confirm the deployed version matches the tag** before the release is "verified." Pushed-and-tagged ≠ installed-and-running.

When the user reports a bug "still broken" after a release:

1. **First hypothesis is "deployed version != tagged version"**, not "the platform is broken."
2. Ask the user to confirm `plugin.yaml` version on disk matches the latest tag (via the plugin's `/health-check` route or SSH).
3. Only debug after confirming.

Skipping this step costs hours.

---

## Field secrecy — security-critical

A connection field in `plugin.yaml` is treated as secret iff `secret: true` OR `type: password`. Anything else writes the value plaintext to `/opt/nousviz/.env` and renders unmasked in the operator UI.

**Rule**: any field whose name contains `key | token | secret | password | auth | bearer | credential | private` MUST have `secret: true` or `type: password`. No exceptions, including for "internal-only" plugins.

```yaml
# WRONG — bearer token plaintext on disk and in the Settings UI
- { name: bearer_token, type: text, required: true }

# RIGHT
- { name: bearer_token, type: text, required: true, secret: true }
```

When reviewing this plugin's `plugin.yaml` connection block, audit every field against this rule before approving a release. The preflight script flags violations heuristically.

---

## Bash hygiene rules specific to plugin work

- **Never `cd <plugin-root>` then `git <command>`.** Use absolute paths with `git -C` or just `cd` once at the top of a multi-step command.
- **Always run `npm run typecheck` before `./build.sh`** in `widget/`. Saves you from shipping a broken bundle that builds clean but errors at runtime.
- **After every widget build**, verify hygiene invariants:
  ```bash
  grep -c ReactCurrentDispatcher widget/dist/*.js   # → 0
  grep -c "/api/widget-runtime/" widget/dist/*.js    # → ≥ 2 per file
  grep -Eoc 'from\s*"react"' widget/dist/*.js        # → 0
  ```
  If any check fails, the widget will explode at runtime regardless of typecheck.
- **Never run `git push --force`.** Always create new commits over rewriting history.
- **Always commit `widget/dist/*.js`** alongside the source. Don't trust your local `.gitignore` — verify with `git status` after staging.

---

## Module-name uniqueness

Every Python file under this plugin's `src/` directory MUST be slug-prefixed:

- ✅ `src/<slug>_sync.py`, `src/<slug>_helpers.py`
- ❌ `src/sync.py`, `src/helpers.py`, `src/_api_client.py`

Reason: when multiple plugins are installed on the same NousViz instance, their `src/` directories all end up on `sys.path`. Python caches modules by bare name across the interpreter, so `from sync import …` in plugin A and plugin B can resolve to the same module. The collision is silent and produces baffling KeyErrors in the wrong plugin's code. Reference: `docs/appendix-gotchas.md` G-1 in the parent guide.

Trade-off: none, as of NousViz core v0.9.5.8 (B201). The page-header "Run sync" button reads `sync.script:` from the manifest like every other path. Slug-prefixing is now zero-cost.

---

## SDK imports

Bare imports — never wrap `nousviz_sdk` imports in `try/except ImportError`. The plugin loader surfaces import failures in `/system/logs?source=plugin_loader` with a useful traceback. A defensive guard demotes that signal into a None-shaped runtime crash.

```python
# WRONG
try:
    from nousviz_sdk import get_pg_conn
except ImportError:
    get_pg_conn = None

# RIGHT
from nousviz_sdk import get_pg_conn
```

`BaseSyncScript` lives at `nousviz_sdk.sync.BaseSyncScript` — it's not re-exported from the package root. Import it from the submodule:

```python
from nousviz_sdk.sync import BaseSyncScript
from nousviz_sdk import get_pg_conn, DictCursor, log_event
```

---

## Auth + database hygiene

- **`DictCursor` is a wrapper class, not a `cursor_factory`**:
  ```python
  cur = DictCursor(conn.cursor())              # ✅ correct
  cur = conn.cursor(cursor_factory=DictCursor) # ❌ raises TypeError
  ```
  Reference: `docs/appendix-gotchas.md` G-2 in the parent guide.

- **Always parameterise SQL**:
  ```python
  cur.execute("SELECT … WHERE foo = %s", (value,))  # ✅
  cur.execute(f"SELECT … WHERE foo = '{value}'")    # ❌ injection
  ```

- **Cross-plugin queries always wrap in try/except** with a `{linked: false}` graceful fallback. Never assume sibling tables exist. Reference: G-13.

- **Plugin-shipped routes**: middleware enforces auth on data routes (B160, v0.9.4.9+) but ship belt-and-braces. Add `Depends(_require_analyst)` (or `_require_admin` for admin routes) to every data-bearing route. Reference: G-11, `docs/09-security.md` Rule 2.

---

## Widget bundle pipeline

The canonical build command is in `widget/build.sh`. Both `--alias` AND `--external` are required for `react` and `react/jsx-runtime`. After build, the bundle hygiene `grep` invariants must hold (see Bash hygiene above).

If you copied an esbuild command from a CHANGELOG entry dated before NousViz core v0.9.4.5, **ignore it** — that contract was wrong; v0.9.4.5+ supersedes. Reference: `docs/appendix-gotchas.md` G-3, G-5.

---

## Communication shape

- **Brief is good, silent is not.** State what you're about to do in one sentence before tool calls. Update at key moments. End with one or two sentences on what changed.
- **Verify before claiming.** Don't say "fixed" until: typecheck passes, build passes, hygiene checks pass, validators pass, preflight passes. If you can't verify on production, say so explicitly.
- **Cite sources.** When making a non-obvious claim about NousViz core, cite the file:line — e.g. `apps/api/src/plugin_predicates.py:106-129`. The user can verify against their core checkout.
- **Surface contract gaps.** When a manifest field doesn't behave as documented, mention the discrepancy. If the fix has to live in core, file a ticket via `scripts/file-core-ticket.sh` (see "Never modify NousViz core from this plugin" above). Don't silently work around.

---

## Where to read

When working on this plugin, the parent guide's docs are the reference:

- **Starting a new feature or plugin from scratch** → `docs/00-conversation-starter.md` (load first; eight intake questions before any code)
- **What you can import from the SDK** → `docs/sdk-surface.md` (anti-hallucination allowlist)
- Manifest fields → `docs/02-plugin-contract.md`
- Routes / database / role / auth → `docs/03-data-and-routes.md`
- YAML dashboard panels → `docs/04-dashboards-declarative.md`
- React widgets → `docs/05-widgets-custom-react.md`
- Sync / scheduling / hooks → `docs/06-sync-and-jobs.md`
- Versioning / install / update → `docs/07-shipping-and-operator-flow.md`
- Working discipline → `docs/08-sop-and-discipline.md`
- Security (secret routing, route auth, pre-release checklist) → `docs/09-security.md`
- Filing core-team tickets when the fix isn't yours → `docs/10-filing-core-tickets.md`
- Data catalog + manifest drift (v0.9.5.3+) → `docs/13-catalog-and-datasets.md`
- When something breaks → `docs/appendix-gotchas.md` (search by G-N)

The guide repo is at https://github.com/JoeHatch/nousviz-plugin-authoring.