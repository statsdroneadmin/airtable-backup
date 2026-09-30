"""
api/routes.py — HTTP routes for airtable-backup.

Mounted at /api/plugins/airtable-backup/* by the plugin loader.

Read-only toward Airtable: only /test-connection calls the Airtable API; every
other route reads the local backup. All data routes require an authenticated
identity (G-11). Exports stream from Postgres in batches so a large base never
has to fit in memory at once.

Reference: docs/03-data-and-routes.md
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from nousviz_sdk import DictCursor, get_pg_conn, log_event

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(_PLUGIN_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT / "src"))
import airtable_backup_format as fmt  # noqa: E402
import airtable_backup_sync as sync_mod  # noqa: E402
from airtable_backup_client import AirtableClient, AirtableError  # noqa: E402

router = APIRouter()
PLUGIN_SLUG = "airtable-backup"
BASE = f"/plugins/{PLUGIN_SLUG}"
EXPORT_BATCH = 2000


def _require_analyst(request: Request) -> str:
    identity = getattr(request.state, "user_identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="Auth required")
    return identity


def _plugin_version() -> str | None:
    try:
        m = re.search(r"^version:\s*([^\s#]+)", (_PLUGIN_ROOT / "plugin.yaml").read_text(), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


def _row(r: dict) -> dict:
    return {k: _iso(v) for k, v in dict(r).items()}


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", name or "").strip() or "download"
    return cleaned[:150]


def _record_action_run(*, job_id: str, status: str, duration_ms: int, detail: dict[str, Any]) -> None:
    try:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO job_runs (job_id, status, source, started_at, completed_at, duration_ms, details)
                   VALUES (%s, %s, 'manual', now(), now(), %s, %s::jsonb)""",
                (job_id, status, duration_ms, json.dumps(detail)),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        log_event("warning", f"Failed to write job_runs row for {job_id}", detail={"error": str(exc)})


def _table_or_404(cur, table_id: str) -> dict:
    cur.execute(
        """SELECT t.table_id, t.base_id, t.name, t.description, t.primary_field_id, t.fields, t.views,
                  t.deleted_at, b.name AS base_name
           FROM atb_tables t LEFT JOIN atb_bases b ON b.base_id = t.base_id
           WHERE t.table_id = %s""",
        (table_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Table not found in backup")
    return dict(row)


# ── Health ──────────────────────────────────────────────────────────────────

@router.get(f"{BASE}/health-check")
def health_check(_: str = Depends(_require_analyst)) -> dict[str, Any]:
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM atb_records WHERE deleted_at IS NULL")
        (records,) = cur.fetchone()
    return {"status": "ok", "version": _plugin_version(), "records": records}


# ── Action: Test connection ─────────────────────────────────────────────────

@router.post(f"{BASE}/test-connection")
def test_connection(_: str = Depends(_require_analyst)) -> dict[str, Any]:
    started = time.monotonic()
    job_id = f"hook:{PLUGIN_SLUG}:test_connection"
    try:
        cfg = sync_mod.load_config()
        client = AirtableClient(cfg["token"])
        who = client.whoami()
        bases = client.list_bases()
        included = [b for b in bases if sync_mod.base_included(b, cfg["base_filter"])]
        # Prove data.records:read on the first included base, if any.
        records_ok = None
        if included:
            tables = client.base_schema(included[0]["id"])
            if tables:
                next(client.iter_record_pages(included[0]["id"], tables[0]["id"]), [])
                records_ok = True
        duration_ms = int((time.monotonic() - started) * 1000)
        _record_action_run(job_id=job_id, status="success", duration_ms=duration_ms,
                           detail={"user_id": who.get("id"), "bases_visible": len(bases),
                                   "bases_included": len(included)})
        note = f"{len(included)} of {len(bases)} base(s) selected" if cfg["base_filter"] else f"{len(bases)} base(s) visible"
        if cfg["base_filter"] and not included:
            note += " — none match 'Bases to include'"
        return {"ok": True, "level": "info" if included else "warning",
                "toast": f"Connected as {who.get('id', '?')} — {note}."
                         + (" Record read OK." if records_ok else ""),
                "duration_ms": duration_ms}
    except AirtableError as e:
        duration_ms = int((time.monotonic() - started) * 1000)
        hint = {401: " Token invalid or revoked.",
                403: " Token lacks a scope (needs data.records:read + schema.bases:read) or base access."}.get(e.status, "")
        _record_action_run(job_id=job_id, status="error", duration_ms=duration_ms, detail={"error": str(e)})
        return {"ok": False, "level": "error", "toast": f"Airtable: {str(e)[:150]}.{hint}"}
    except Exception as e:  # noqa: BLE001
        duration_ms = int((time.monotonic() - started) * 1000)
        _record_action_run(job_id=job_id, status="error", duration_ms=duration_ms,
                           detail={"error": f"{e.__class__.__name__}: {e}"})
        return {"ok": False, "level": "error", "toast": f"Test connection: {e.__class__.__name__}: {str(e)[:150]}"}


# ── Action: Run sync ────────────────────────────────────────────────────────

@router.post(f"{BASE}/sync-now")
def sync_now(_: str = Depends(_require_analyst)) -> dict[str, Any]:
    job_id = f"sync:{PLUGIN_SLUG}"
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT EXISTS (SELECT 1 FROM job_runs WHERE job_id=%s
                 AND status IN ('queued','running','cancelling'))""",
            (job_id,),
        )
        (active,) = cur.fetchone()
        if active:
            return {"level": "warning", "toast": "A backup is already running — see System → Jobs."}
        cur.execute(
            """INSERT INTO job_runs (job_id, status, source, started_at, details)
               VALUES (%s, 'queued', 'manual', now(), %s::jsonb) RETURNING id""",
            (job_id, json.dumps({"via": "plugin_action"})),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
    return {"level": "info", "toast": f"Backup queued (job #{run_id}).",
            "navigate": f"/plugin/{PLUGIN_SLUG}/overview"}


# ── Summary + browse ────────────────────────────────────────────────────────

@router.get(f"{BASE}/summary")
def summary(_: str = Depends(_require_analyst)) -> dict[str, Any]:
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute(
            """SELECT
                 (SELECT count(*) FROM atb_bases WHERE deleted_at IS NULL) AS bases,
                 (SELECT count(*) FROM atb_tables WHERE deleted_at IS NULL) AS tables,
                 (SELECT count(*) FROM atb_records WHERE deleted_at IS NULL) AS records,
                 (SELECT count(*) FROM atb_records WHERE deleted_at IS NOT NULL) AS deleted_records,
                 (SELECT count(*) FROM atb_attachments WHERE status='stored') AS attachments_stored,
                 (SELECT COALESCE(sum(size_bytes),0) FROM atb_attachments WHERE status='stored') AS attachment_bytes,
                 (SELECT count(*) FROM atb_attachments WHERE status IN ('failed','pending')) AS attachments_failed,
                 (SELECT count(*) FROM atb_attachments WHERE status='too_large') AS attachments_too_large,
                 (SELECT count(*) FROM atb_attachments WHERE status='disabled') AS attachments_not_downloaded,
                 (SELECT count(*) FROM atb_comments WHERE deleted_at IS NULL) AS comments,
                 (SELECT count(*) FROM atb_record_changes WHERE changed_at > now() - interval '7 days') AS changes_7d"""
        )
        totals = _row(cur.fetchone())
        cur.execute("SELECT id, started_at, finished_at, status, stats, error FROM atb_runs ORDER BY id DESC LIMIT 1")
        last = cur.fetchone()
        cur.execute(
            """SELECT max(finished_at) AS t FROM atb_runs WHERE status IN ('success','partial')"""
        )
        last_ok = cur.fetchone()["t"]
    return {"totals": totals, "last_run": _row(last) if last else None, "last_success_at": _iso(last_ok)}


@router.get(f"{BASE}/bases")
def list_bases(_: str = Depends(_require_analyst)) -> dict[str, Any]:
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute(
            """SELECT b.base_id, b.name, b.permission_level, b.last_synced_at, b.deleted_at, b.last_error,
                      (SELECT count(*) FROM atb_tables t WHERE t.base_id=b.base_id AND t.deleted_at IS NULL) AS tables,
                      (SELECT count(*) FROM atb_records r WHERE r.base_id=b.base_id AND r.deleted_at IS NULL) AS records
               FROM atb_bases b ORDER BY b.deleted_at IS NOT NULL, lower(b.name)"""
        )
        return {"bases": [_row(r) for r in cur.fetchall()]}


@router.get(f"{BASE}/tables")
def list_tables(base_id: str = Query(...), _: str = Depends(_require_analyst)) -> dict[str, Any]:
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute(
            """SELECT t.table_id, t.name, t.description, t.primary_field_id, t.fields, t.views,
                      t.last_synced_at, t.deleted_at, t.last_error,
                      (SELECT count(*) FROM atb_records r WHERE r.table_id=t.table_id AND r.deleted_at IS NULL) AS records,
                      (SELECT count(*) FROM atb_records r WHERE r.table_id=t.table_id AND r.deleted_at IS NOT NULL) AS deleted_records
               FROM atb_tables t WHERE t.base_id=%s
               ORDER BY t.deleted_at IS NOT NULL, t.position, lower(t.name)""",
            (base_id,),
        )
        return {"tables": [_row(r) for r in cur.fetchall()]}


@router.get(f"{BASE}/records")
def list_records(
    table_id: str = Query(...),
    q: str | None = Query(None, max_length=200),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: str = Depends(_require_analyst),
) -> dict[str, Any]:
    where = ["table_id = %s"]
    args: list[Any] = [table_id]
    if not include_deleted:
        where.append("deleted_at IS NULL")
    if q and q.strip():
        where.append("(fields::text ILIKE %s OR record_id = %s)")
        args += [f"%{q.strip()}%", q.strip()]
    clause = " AND ".join(where)
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        table = _table_or_404(cur, table_id)
        cur.execute(f"SELECT count(*) AS n FROM atb_records WHERE {clause}", args)
        total = cur.fetchone()["n"]
        cur.execute(
            f"""SELECT record_id, created_time, fields, comment_count, last_changed_at, deleted_at
                FROM atb_records WHERE {clause}
                ORDER BY created_time NULLS LAST, record_id LIMIT %s OFFSET %s""",
            args + [limit, offset],
        )
        rows = [_row(r) for r in cur.fetchall()]
    return {"table": _row(table), "total": total, "records": rows}


@router.get(f"{BASE}/record")
def record_detail(table_id: str = Query(...), record_id: str = Query(...),
                  _: str = Depends(_require_analyst)) -> dict[str, Any]:
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        table = _table_or_404(cur, table_id)
        cur.execute(
            """SELECT record_id, created_time, fields, comment_count, first_seen_at, last_changed_at,
                      last_seen_at, deleted_at
               FROM atb_records WHERE table_id=%s AND record_id=%s""",
            (table_id, record_id),
        )
        rec = cur.fetchone()
        if not rec:
            raise HTTPException(status_code=404, detail="Record not found in backup")
        cur.execute(
            """SELECT id, change_type, changed_at, changed_field_ids, previous_fields
               FROM atb_record_changes WHERE table_id=%s AND record_id=%s
               ORDER BY changed_at DESC, id DESC LIMIT 200""",
            (table_id, record_id),
        )
        changes = [_row(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT attachment_id, field_id, filename, content_type, size_bytes, width, height,
                      status, error, downloaded_at
               FROM atb_attachments WHERE table_id=%s AND record_id=%s ORDER BY first_seen_at""",
            (table_id, record_id),
        )
        attachments = [_row(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT comment_id, parent_comment_id, author, text, created_time, last_updated_time, deleted_at
               FROM atb_comments WHERE table_id=%s AND record_id=%s ORDER BY created_time""",
            (table_id, record_id),
        )
        comments = [_row(r) for r in cur.fetchall()]
    return {"table": _row(table), "record": _row(rec), "changes": changes,
            "attachments": attachments, "comments": comments}


@router.get(f"{BASE}/changes")
def recent_changes(
    base_id: str | None = Query(None),
    table_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    _: str = Depends(_require_analyst),
) -> dict[str, Any]:
    where, args = ["true"], []
    if base_id:
        where.append("c.base_id = %s")
        args.append(base_id)
    if table_id:
        where.append("c.table_id = %s")
        args.append(table_id)
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute(
            f"""SELECT c.id, c.change_type, c.changed_at, c.table_id, c.record_id, c.changed_field_ids,
                       t.name AS table_name, b.name AS base_name, t.primary_field_id,
                       r.fields -> t.primary_field_id AS primary_value, t.fields AS table_fields
                FROM atb_record_changes c
                LEFT JOIN atb_tables t ON t.table_id = c.table_id
                LEFT JOIN atb_bases b ON b.base_id = c.base_id
                LEFT JOIN atb_records r ON r.table_id = c.table_id AND r.record_id = c.record_id
                WHERE {' AND '.join(where)}
                ORDER BY c.changed_at DESC, c.id DESC LIMIT %s""",
            args + [limit],
        )
        out = []
        for r in cur.fetchall():
            d = _row(r)
            names = {f.get("id"): f.get("name") for f in (d.pop("table_fields") or [])}
            d["changed_field_names"] = [names.get(fid, fid) for fid in d.get("changed_field_ids") or []]
            d["primary_value"] = fmt.cell_to_text(d.get("primary_value"))
            out.append(d)
    return {"changes": out}


# ── Attachments ─────────────────────────────────────────────────────────────

@router.get(f"{BASE}/attachments/{{attachment_id}}")
def attachment_file(attachment_id: str, _: str = Depends(_require_analyst)) -> Response:
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute(
            "SELECT filename, content_type, content, status FROM atb_attachments WHERE attachment_id=%s",
            (attachment_id,),
        )
        row = cur.fetchone()
    if not row or row["status"] != "stored" or row["content"] is None:
        raise HTTPException(status_code=404, detail="Attachment file not stored")
    return Response(
        content=bytes(row["content"]),
        media_type=row["content_type"] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{_safe_filename(row["filename"])}"',
                 "X-Content-Type-Options": "nosniff"},
    )


# ── Export ──────────────────────────────────────────────────────────────────

def _iter_records(table_id: str, include_deleted: bool) -> Iterator[dict]:
    """Keyset-paginate a table's records so exports never hold it all at once."""
    after = ""
    while True:
        with get_pg_conn() as conn:
            cur = DictCursor(conn.cursor())
            cur.execute(
                f"""SELECT record_id, created_time, fields, deleted_at FROM atb_records
                    WHERE table_id=%s AND record_id > %s {'' if include_deleted else 'AND deleted_at IS NULL'}
                    ORDER BY record_id LIMIT %s""",
                (table_id, after, EXPORT_BATCH),
            )
            rows = cur.fetchall()
        if not rows:
            return
        for r in rows:
            yield dict(r)
        after = rows[-1]["record_id"]


def _record_json(r: dict, schema: list[dict]) -> dict:
    out = {"id": r["record_id"], "createdTime": _iso(r["created_time"]),
           "fields": fmt.fields_by_name(r["fields"] or {}, schema)}
    if r.get("deleted_at"):
        out["deletedAt"] = _iso(r["deleted_at"])
    return out


@router.get(f"{BASE}/export/table")
def export_table(
    table_id: str = Query(...),
    format: str = Query("csv", pattern="^(csv|json)$"),
    include_deleted: bool = Query(False),
    _: str = Depends(_require_analyst),
) -> StreamingResponse:
    with get_pg_conn() as conn:
        table = _table_or_404(DictCursor(conn.cursor()), table_id)
    schema = table["fields"] or []
    stem = _safe_filename(f"{table.get('base_name') or table['base_id']} - {table['name']}")

    if format == "json":
        def gen_json() -> Iterator[bytes]:
            head = {"base": {"id": table["base_id"], "name": table.get("base_name")},
                    "table": {"id": table["table_id"], "name": table["name"],
                              "description": table.get("description"),
                              "primaryFieldId": table.get("primary_field_id"),
                              "fields": schema, "views": table.get("views") or []}}
            yield (json.dumps(head, ensure_ascii=False)[:-1] + ',"records":[').encode()
            first = True
            for r in _iter_records(table_id, include_deleted):
                yield (("" if first else ",") + json.dumps(_record_json(r, schema), ensure_ascii=False)).encode()
                first = False
            yield b"]}"
        return StreamingResponse(gen_json(), media_type="application/json",
                                 headers={"Content-Disposition": f'attachment; filename="{stem}.json"'})

    def gen_csv() -> Iterator[bytes]:
        buf = io.StringIO()
        w = csv.writer(buf)
        header = ["Record ID", "Created time"] + [f.get("name") or f.get("id") for f in schema]
        if include_deleted:
            header.append("Deleted at")
        yield ("﻿").encode()  # BOM so Excel reads UTF-8
        w.writerow(header)
        n = 0
        for r in _iter_records(table_id, include_deleted):
            fields = r["fields"] or {}
            row = [r["record_id"], _iso(r["created_time"]) or ""]
            row += [fmt.cell_to_text(fields.get(f.get("id"))) for f in schema]
            if include_deleted:
                row.append(_iso(r["deleted_at"]) or "")
            w.writerow(row)
            n += 1
            if n % 500 == 0:
                yield buf.getvalue().encode()
                buf.seek(0)
                buf.truncate()
        # Values of fields since removed from the schema aren't CSV columns;
        # the JSON exports keep them (keyed by field ID).
        yield buf.getvalue().encode()

    return StreamingResponse(gen_csv(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'})


@router.get(f"{BASE}/export/base")
def export_base(base_id: str = Query(...), include_deleted: bool = Query(False),
                _: str = Depends(_require_analyst)) -> StreamingResponse:
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute("SELECT base_id, name, permission_level FROM atb_bases WHERE base_id=%s", (base_id,))
        base = cur.fetchone()
        if not base:
            raise HTTPException(status_code=404, detail="Base not found in backup")
        cur.execute(
            """SELECT table_id, name, description, primary_field_id, fields, views, deleted_at
               FROM atb_tables WHERE base_id=%s ORDER BY position, lower(name)""",
            (base_id,),
        )
        tables = [dict(t) for t in cur.fetchall()]
    base = dict(base)

    def gen() -> Iterator[bytes]:
        yield (json.dumps({"id": base["base_id"], "name": base["name"],
                           "exportedBy": "nousviz airtable-backup", "exportedAt": datetime.now(timezone.utc).isoformat()},
                          ensure_ascii=False)[:-1] + ',"tables":[').encode()
        for ti, t in enumerate(tables):
            schema = t["fields"] or []
            head = {"id": t["table_id"], "name": t["name"], "description": t.get("description"),
                    "primaryFieldId": t.get("primary_field_id"), "fields": schema, "views": t.get("views") or []}
            if t.get("deleted_at"):
                head["deletedAt"] = _iso(t["deleted_at"])
            yield (("," if ti else "") + json.dumps(head, ensure_ascii=False)[:-1] + ',"records":[').encode()
            first = True
            for r in _iter_records(t["table_id"], include_deleted):
                yield (("" if first else ",") + json.dumps(_record_json(r, schema), ensure_ascii=False)).encode()
                first = False
            yield b"]}"
        yield b"]}"

    stem = _safe_filename(base["name"] or base_id)
    return StreamingResponse(gen(), media_type="application/json",
                             headers={"Content-Disposition": f'attachment; filename="{stem}.json"'})
