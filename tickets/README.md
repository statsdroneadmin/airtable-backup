# tickets/

Outbound core-team tickets filed from this plugin live here.

When you hit an issue that requires a fix in NousViz core (`apps/`, `sdk/`, frontend) rather than in this plugin, generate a ticket using the helper script in the parent guide repo:

```bash
/path/to/nousviz-plugin-authoring/scripts/file-core-ticket.sh "<short summary>"
```

The script writes a scaffolded `B<NNN>-<slug>.md` here, opens it in `$EDITOR`, and prints the commit/notify workflow. Full template, severity guide, and worked examples in:

[`docs/10-filing-core-tickets.md`](../../../docs/10-filing-core-tickets.md) (relative path is to the parent authoring repo)

## Why this directory exists

Plugins are standalone. **Never edit core from a plugin repo.** When the fix has to live in core, the audit trail is:

1. File the ticket here (this directory)
2. Add a "Blocked on B<NNN>" note to `PLAN.md` for the in-flight version
3. Push and notify the core team
4. When core ships the fix, re-test and remove the workaround in your next release

Tickets in this directory are **outbound drafts**. Once the core team intakes them, the authoritative copy lives in the core repo's `todo/<version>/tickets/` directory. You can leave the local copy here as a record, or delete it once the fix is in.