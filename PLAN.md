# PLAN.md

The SOP for this plugin. Every change goes through these gates **before** code is written:

1. **Ticket** — what's broken / what's missing, with specific evidence
2. **Plan** — 3-5 lines of how
3. **Test plan** — what success looks like (operator-visible checks — see `docs/11-verification-spec.md` in the parent guide for the template)
4. **CHANGELOG stub** — draft the user-facing entry

If any gate is missing, you don't have permission to write code. Same applies to Claude Code — it refuses without these gates filled in.

For a brand-new plugin: walk through the eight intake questions in `docs/00-conversation-starter.md` (parent guide) before filling in the v0.1.0 ticket below. The intake answers BECOME the ticket + plan + test plan.

Reference: see `docs/08-sop-and-discipline.md` in the parent `nousviz-plugin-authoring` guide.

---

## Implementation phases

### v0.1.0 — Initial scaffold

**Ticket.** New plugin scaffolded from `nousviz-plugin-authoring` skeleton. First version proves the install flow works end-to-end on a NousViz instance.

**Plan.**
1. Walk the user through the eight intake questions in `docs/00-conversation-starter.md`. Capture answers here.
2. Customize plugin.yaml: identity (name, slug, repo URL, publisher), description, connections.fields (mark sensitive fields `secret: true`), category from the documented allowlist.
3. Customize migration: rename `airt_items` to fit your domain. Confirm column types match the row-shape from intake question 3.
4. Customize sync: replace `_fetch_items` fixture with real external fetch. Use credentials from `get_credential()` and config from `get_connection_field()`.
5. Customize routes: replace demo overview/items endpoints with what your widgets need. Add `Depends(_require_analyst)` to every data route.
6. Customize dashboard: pick KPIs that matter, point chart at real data. Confirm panels match the layout from intake question 4.
7. Customize widget: rename, change colour / value path / endpoint. If no custom widget needed, run `new-plugin.sh --no-widget` instead.
8. Run `scripts/smoke-test.sh`. Fix any failures.
9. Run `scripts/preflight.sh`. Fix any failures.
10. Tag v0.1.0 and install on dev NousViz instance.

**Test plan.** Use the template from `docs/11-verification-spec.md` in the parent guide. Replace every `<placeholder>` with values specific to this plugin. Below is the v0.1.0 minimum — copy the full template for richer test plans:

#### Install + first launch
- [ ] Install completes without error toast
- [ ] Sidebar shows the plugin's display name
- [ ] Click sidebar entry — page loads at `/plugin/<slug>` without "Plugin failed to load" banner
- [ ] No browser console errors

#### Settings tab
- [ ] Setup checklist shows 4 items
- [ ] Connection form has the expected fields
- [ ] Sensitive fields render as ●●●●●●●●; structural fields render as plain text

#### Configure → test → sync
- [ ] Save credentials → "Configure connection" item ticks green
- [ ] Click "Test connection" → success toast → "Verify connection" item ticks green
- [ ] Click "Run sync" → sync queues + completes → "Run the first sync" ticks green
- [ ] Within 30s of install, "Confirm automatic sync is scheduled" ticks green
- [ ] Setup checklist disappears (all 4 green)

#### Overview dashboard
- [ ] All KPI tiles show numeric values (no NaN)
- [ ] Bar chart renders with at least 1 bar
- [ ] Table renders with at least 1 row
- [ ] (If custom widget) Custom widget renders without placeholder
- [ ] Browser console clean across page load + tab switching

#### Pre-tag verification
- [ ] `git ls-remote --tags origin` shows `v0.1.0` (tag pushed, not just created locally)
- [ ] `plugin.yaml` `version:` field matches the latest tag exactly
- [ ] `scripts/smoke-test.sh` passes
- [ ] `scripts/preflight.sh` passes

**CHANGELOG stub.** See `CHANGELOG.md` "[0.1.0] — Initial scaffold".

---

<!--
Template for subsequent versions — copy-paste and fill in:

### vX.Y.Z — <one-line summary>

**Ticket.** What's broken / what's missing. Cite specific evidence (error
message, log entry, file:line). Why this needs fixing now vs later.

**Plan.**
1. First step.
2. Second step.

**Test plan.** Use the template from `docs/11-verification-spec.md`. The
full template covers install, settings, configure/test/sync, dashboards,
custom-widget interactions, update flow, and "what the operator should
NOT see." For a small change, include just the sections affected.

- [ ] `git ls-remote --tags origin` shows the new tag (not just local)
- [ ] `plugin.yaml` `version:` matches the tag
- [ ] `scripts/smoke-test.sh` passes
- [ ] `scripts/preflight.sh` passes
- [ ] Operator-visible check 1 (specific to this version's change)
- [ ] Operator-visible check 2
- [ ] No regression on X
- [ ] No browser console errors

**CHANGELOG stub.**
\```
### Fixed/Added/Changed — vX.Y.Z: <summary>
- Bullet 1
\```
-->