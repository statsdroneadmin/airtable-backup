"""
src/airtable_backup_sync.py — Sync script for airtable-backup.

Subclasses BaseSyncScript so every invocation gets a job_runs row,
heartbeat support, and cancel-check support automatically.

The filename is slug-prefixed (`airtable_backup_sync.py`, not bare
`sync.py`) so it can't collide with a sibling plugin's `sync.py`
via Python's sys.modules cache. See appendix-gotchas.md G-1.

Reference: docs/06-sync-and-jobs.md
"""

from __future__ import annotations

from typing import Any

# SDK imports — never import from apps.* (those are core internals).
# nousviz_sdk is the stable plugin contract.
#
# BaseSyncScript lives at nousviz_sdk.sync — it's not re-exported from the
# package root. Import it from the submodule. Everything else comes from the
# package root.
#
# Imports are bare on purpose. NEVER wrap SDK imports in try/except ImportError:
# the plugin loader surfaces import failures in /system/logs?source=plugin_loader
# with a useful stack. A defensive guard here would silently demote a hard
# failure into a None-shaped runtime crash later. See docs/02-plugin-contract.md
# "Validator" notes and docs/07-shipping-and-operator-flow.md "Plugin failed to
# load".
from nousviz_sdk.sync import BaseSyncScript
from nousviz_sdk.jobs import heartbeat, check_cancelled
from nousviz_sdk import (
    get_pg_conn,
    get_credential,
    get_connection_field,
    log_event,
)


PLUGIN_SLUG = "airtable-backup"
DEFAULT_BASE_URL = "https://api.example.com"


class ExamplePluginSync(BaseSyncScript):
    """One run = one full refresh of airt_items.

    A real plugin would fetch from an external API. This skeleton just
    upserts a fixed set of demo rows so the dashboard has something to
    show after first install. Replace `_fetch_items` with your real
    fetch logic.
    """

    plugin_id = PLUGIN_SLUG

    def run(self, since: str | None = None) -> dict[str, Any]:
        # Read non-secret config + secret credential. Both go through
        # the SDK; never read os.environ or .env directly.
        api_key = get_credential(PLUGIN_SLUG, "api_key") or ""
        base_url = get_connection_field(PLUGIN_SLUG, "base_url") or DEFAULT_BASE_URL

        if not api_key:
            raise RuntimeError(
                "api_key credential not configured. Have the operator save "
                "credentials on the Settings tab first."
            )

        self._log("info", f"Sync starting against {base_url}")

        # 1. Fetch
        items = self._fetch_items(base_url, api_key, since=since)
        # heartbeat() and check_cancelled() are MODULE-LEVEL functions in
        # nousviz_sdk.jobs — NOT methods on BaseSyncScript. See docs/sdk-surface.md.
        heartbeat(progress={"phase": "fetched", "rows_seen": len(items)})

        # 2. Upsert in batches; check for cancellation between batches.
        rows_written = 0
        for batch in self._batches(items, size=100):
            if check_cancelled():
                self._log("warning", "Sync cancelled by operator")
                return {"rows_synced": rows_written, "cancelled": True}

            self._upsert_batch(batch)
            rows_written += len(batch)
            heartbeat(progress={
                "phase": "writing",
                "rows_written": rows_written,
                "rows_seen": len(items),
            })

        # 3. Update the sync-state checkpoint.
        self._update_checkpoint(rows_written)

        self._log("info", f"Sync complete: {rows_written} items")
        return {"rows_synced": rows_written}

    # ── Fetch ────────────────────────────────────────────────────────────

    def _fetch_items(
        self, base_url: str, api_key: str, since: str | None
    ) -> list[dict[str, Any]]:
        """Replace this with your real fetch.

        For the skeleton, return a small fixture so the dashboard has
        data on first run. In a real plugin, do something like:

            import requests
            r = requests.get(
                f"{base_url}/items",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"since": since} if since else {},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()["items"]
        """
        return [
            {"external_id": "alpha-1", "name": "Alpha", "category": "type-a", "score": 87.5, "is_active": True},
            {"external_id": "alpha-2", "name": "Alpha 2", "category": "type-a", "score": 91.2, "is_active": True},
            {"external_id": "beta-1",  "name": "Beta",  "category": "type-b", "score": 72.0, "is_active": True},
            {"external_id": "beta-2",  "name": "Beta 2","category": "type-b", "score": 65.8, "is_active": False},
            {"external_id": "gamma-1", "name": "Gamma", "category": "type-c", "score": 55.1, "is_active": True},
        ]

    # ── Database ─────────────────────────────────────────────────────────

    def _upsert_batch(self, batch: list[dict[str, Any]]) -> None:
        """Idempotent UPSERT — safe to retry."""
        with get_pg_conn() as conn:
            cur = conn.cursor()
            for item in batch:
                cur.execute(
                    """
                    INSERT INTO airt_items (
                        external_id, name, category, score, is_active,
                        raw_data, synced_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, now(), now())
                    ON CONFLICT (external_id) DO UPDATE SET
                        name      = EXCLUDED.name,
                        category  = EXCLUDED.category,
                        score     = EXCLUDED.score,
                        is_active = EXCLUDED.is_active,
                        raw_data  = EXCLUDED.raw_data,
                        synced_at = EXCLUDED.synced_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        item["external_id"],
                        item["name"],
                        item.get("category"),
                        item.get("score"),
                        item.get("is_active", True),
                        "{}",
                    ),
                )
            conn.commit()

    def _update_checkpoint(self, rows_written: int) -> None:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO airt_sync_state (key, value, updated_at)
                VALUES ('last_sync', %s::jsonb, now())
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = EXCLUDED.updated_at
                """,
                ('{"rows_written": %d}' % rows_written,),
            )
            conn.commit()

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _batches(rows: list, size: int):
        for i in range(0, len(rows), size):
            yield rows[i : i + size]

    def _log(self, level: str, message: str, detail: dict | None = None) -> None:
        """Forward to nousviz_sdk.log_event for structured /system/logs entries."""
        log_event(level, message, detail=detail)


if __name__ == "__main__":
    ExamplePluginSync().main()
