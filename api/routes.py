"""
api/routes.py — HTTP routes for airtable-backup.

Routes are mounted at /api/plugins/<slug>/* by the plugin loader. The
file MUST export a `router` variable (a FastAPI APIRouter).

Patterns demonstrated here:
- DictCursor used correctly: DictCursor(conn.cursor()), NOT
  conn.cursor(cursor_factory=DictCursor). See appendix-gotchas.md G-2.
- Action handlers that write job_runs rows so the setup-checklist
  predicates flip. See docs/06-sync-and-jobs.md.
- Parameterised queries always — never f-strings, never .format().
- Structured logging via log_event for failures.

Reference: docs/03-data-and-routes.md
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

# SDK contract — never import from apps.*. Bare imports on purpose: a defensive
# try/except ImportError demotes a hard load failure into a silent runtime
# crash. The plugin loader surfaces real import errors in
# /system/logs?source=plugin_loader. See docs/07-shipping-and-operator-flow.md.
from nousviz_sdk import get_pg_conn, DictCursor, log_event


router = APIRouter()
PLUGIN_SLUG = "airtable-backup"
BASE = f"/plugins/{PLUGIN_SLUG}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_action_run(
    *, job_id: str, status: str, duration_ms: int, detail: dict[str, Any]
) -> None:
    """Write a job_runs row so action handlers advance the setup checklist.

    `last_test_success` predicate looks at the most recent terminal status
    of any job_runs row matching `sync:<slug>` OR `hook:<slug>:*`. This
    helper writes a `hook:<slug>:test_connection` row when the test action
    fires.
    """
    try:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO job_runs (
                    job_id, status, source, started_at, completed_at,
                    duration_ms, details
                )
                VALUES (%s, %s, 'manual', now(), now(), %s, %s::jsonb)
                """,
                (job_id, status, duration_ms, json.dumps(detail)),
            )
            conn.commit()
    except Exception as exc:
        # Don't bring down the action just because audit logging failed.
        log_event(
            "warning",
            f"Failed to write job_runs row for {job_id}",
            detail={"error": str(exc)},
        )


# ── Health ──────────────────────────────────────────────────────────────────


@router.get(f"{BASE}/health-check")
def health_check() -> dict[str, Any]:
    """Liveness endpoint. Operators / scripts hit this to confirm the
    deployed version of the plugin matches what was tagged. See
    docs/08-sop-and-discipline.md "Verify deployed = tagged".
    """
    try:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM airt_items")
            (n,) = cur.fetchone()
        return {
            "plugin": PLUGIN_SLUG,
            "version": "0.1.0",   # bump alongside plugin.yaml.version
            "ok": True,
            "items_count": n,
            "as_of": _now_iso(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {e}")


# ── Action: Test connection ─────────────────────────────────────────────────


@router.post(f"{BASE}/test-connection")
def test_connection() -> dict[str, Any]:
    """Probe the external source. Writes a job_runs row so the operator's
    setup checklist's `last_test_success` predicate flips.

    Replace the body with a real probe. The skeleton just touches the
    database to demonstrate the action contract.
    """
    started = time.monotonic()

    try:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as e:
        cls = e.__class__.__name__
        msg = str(e)
        tb = traceback.format_exc()[-1500:]
        duration_ms = int((time.monotonic() - started) * 1000)

        _record_action_run(
            job_id=f"hook:{PLUGIN_SLUG}:test_connection",
            status="error",
            duration_ms=duration_ms,
            detail={"stage": "probe", "error": f"{cls}: {msg}", "traceback_tail": tb},
        )
        log_event(
            "error",
            f"Test connection failed: {cls}",
            detail={"error": msg, "traceback_tail": tb},
        )
        return {
            "ok": False,
            "level": "error",
            "toast": f"Test connection: {cls}: {msg[:100]}",
        }

    duration_ms = int((time.monotonic() - started) * 1000)
    _record_action_run(
        job_id=f"hook:{PLUGIN_SLUG}:test_connection",
        status="success",
        duration_ms=duration_ms,
        detail={"stage": "probe", "ok": True},
    )
    return {
        "ok": True,
        "level": "info",
        "toast": "Connection OK",
        "duration_ms": duration_ms,
    }


# ── Action: Run sync ────────────────────────────────────────────────────────


@router.post(f"{BASE}/sync-now")
def sync_now() -> dict[str, Any]:
    """Enqueue a sync. Plugin declares execution_mode: async, so this
    inserts a queued job_runs row; the jobs-worker claims it. Returns
    immediately — never call the sync function directly from a route
    (10-minute HTTP timeout will kill long syncs).
    """
    job_id = f"sync:{PLUGIN_SLUG}"

    try:
        with get_pg_conn() as conn:
            cur = conn.cursor()

            # Defence-in-depth check (concurrency_policy: skip_if_running
            # also prevents this at the scheduler level).
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM job_runs
                    WHERE job_id = %s
                      AND status IN ('queued', 'running', 'cancelling', 'paused')
                )
                """,
                (job_id,),
            )
            (active,) = cur.fetchone()
            if active:
                return {
                    "level": "warning",
                    "toast": "A sync is already running. Watch the Overview tab.",
                    "navigate": f"/plugin/{PLUGIN_SLUG}/overview",
                }

            cur.execute(
                """
                INSERT INTO job_runs (job_id, status, source, started_at, details)
                VALUES (%s, 'queued', 'manual', now(), %s::jsonb)
                RETURNING id
                """,
                (job_id, json.dumps({"via": "plugin_action"})),
            )
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                raise RuntimeError("INSERT into job_runs returned no row")
            run_id = row[0]
            conn.commit()

        return {
            "level": "info",
            "toast": f"Sync queued (job #{run_id}). Watch the Overview tab.",
            "navigate": f"/plugin/{PLUGIN_SLUG}/overview",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not enqueue sync: {e}")


# ── Data routes ─────────────────────────────────────────────────────────────


@router.get(f"{BASE}/overview")
def overview() -> dict[str, Any]:
    """One fetch returns everything the Overview dashboard needs.
    Custom widgets (SDIKpiCard, SDIKpiGrid in real plugins) read from
    here so a single network round-trip populates a whole panel.
    """
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())   # Correct DictCursor pattern (G-2)

        cur.execute("""
            SELECT
                COUNT(*)                                AS total_items,
                COUNT(*) FILTER (WHERE is_active)       AS active_items,
                COUNT(*) FILTER (WHERE NOT is_active)   AS inactive_items,
                ROUND(AVG(score), 1)                    AS avg_score,
                MAX(synced_at)                          AS last_synced
            FROM airt_items
        """)
        stats = dict(cur.fetchone() or {})

        cur.execute("""
            SELECT
                COALESCE(NULLIF(category, ''), '(uncategorized)') AS category,
                COUNT(*) AS count
            FROM airt_items
            GROUP BY COALESCE(NULLIF(category, ''), '(uncategorized)')
            ORDER BY count DESC
            LIMIT 10
        """)
        by_category = [dict(r) for r in cur.fetchall()]

    # Make timestamps JSON-serialisable
    if stats.get("last_synced") and hasattr(stats["last_synced"], "isoformat"):
        stats["last_synced"] = stats["last_synced"].isoformat()

    return {
        "stats": stats,
        "by_category": by_category,
        "data_as_of": _now_iso(),
    }


@router.get(f"{BASE}/items")
def items(
    limit:  int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    category: str | None = Query(None),
    active_only: bool = Query(False),
    sort: str = Query("name"),
    sort_dir: str = Query("asc"),
) -> dict[str, Any]:
    """Filterable + paginated list of items. Used by the
    SDIProgramsTable-style table widget pattern.

    Allowlist sort columns + sort direction to prevent SQL injection
    via `sort` query param.
    """
    SAFE_SORT = {"name", "category", "score", "synced_at"}
    safe_sort = sort if sort in SAFE_SORT else "name"
    safe_dir = "DESC" if sort_dir.upper() == "DESC" else "ASC"

    where = ["1=1"]
    params: list = []

    if search:
        where.append("name ILIKE %s")
        params.append(f"%{search}%")
    if category:
        where.append("category = %s")
        params.append(category)
    if active_only:
        where.append("is_active = true")

    where_sql = " AND ".join(where)

    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute(
            f"""
            SELECT id, external_id, name, category, score, is_active,
                   synced_at
            FROM airt_items
            WHERE {where_sql}
            ORDER BY {safe_sort} {safe_dir} NULLS LAST
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]

        cur.execute(f"SELECT COUNT(*) AS n FROM airt_items WHERE {where_sql}", params)
        total = cur.fetchone()["n"]

    for r in rows:
        if r.get("synced_at") and hasattr(r["synced_at"], "isoformat"):
            r["synced_at"] = r["synced_at"].isoformat()

    return {"rows": rows, "total": total, "data_as_of": _now_iso()}


@router.get(f"{BASE}/items/filters")
def items_filters() -> dict[str, Any]:
    """Returns dropdown options for filter controls. Read once at widget
    mount time."""
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute(
            "SELECT DISTINCT category FROM airt_items "
            "WHERE category IS NOT NULL AND category != '' "
            "ORDER BY category"
        )
        categories = [r["category"] for r in cur.fetchall()]
    return {"categories": categories}
