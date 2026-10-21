"""
airtable_backup_sync.py — back up an Airtable account into Postgres.

One run:
  1. List every base the token can see; mark bases that vanished.
  2. For each included base (least-recently-synced first, so a run that times
     out still makes progress across runs):
       a. Fetch the schema; upsert tables; snapshot schema changes.
       b. Page through every table (100 records/request). Each record is
          scrubbed of expiring attachment URLs, hashed, and compared with the
          stored copy → created / updated / restored change rows.
       c. On the same page — while the 2-hour attachment URLs are still valid —
          download any attachment file not already stored.
       d. Optionally fetch comments for records whose comment count changed.
       e. After a COMPLETE pass of a table, records not seen are marked
          deleted. An interrupted pass never marks anything deleted.
  3. The first complete pass of a table is a baseline: no "created" rows.

Airtable has no "modified since" filter without a Last-modified field in every
table, so every run re-reads everything; hashing keeps unchanged records to a
single cheap UPDATE per page.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nousviz_sdk import get_pg_conn, get_credential, log_event  # noqa: E402
from nousviz_sdk.jobs import check_cancelled, get_run_id, heartbeat  # noqa: E402
from nousviz_sdk.settings import get_connection_field  # noqa: E402
from nousviz_sdk.sync import BaseSyncScript  # noqa: E402

import airtable_backup_format as fmt  # noqa: E402
from airtable_backup_client import AirtableClient, AirtableError, IteratorExpired  # noqa: E402

PLUGIN_SLUG = "airtable-backup"
logger = logging.getLogger(f"nousviz.plugin.{PLUGIN_SLUG}.sync")

MAX_ITERATOR_RESTARTS = 2
MAX_ERRORS_KEPT = 25


class Cancelled(Exception):
    pass


# ── config ───────────────────────────────────────────────────────────────────

def _truthy(value: Any, default: bool) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in ("yes", "true", "1", "on", "y")


def _number(value: Any, default: float) -> float:
    try:
        n = float(str(value).strip())
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default


def parse_base_filter(raw: Any) -> list[str]:
    if not raw:
        return []
    parts = str(raw).replace("\n", ",").split(",")
    return [p.strip().lower() for p in parts if p.strip()]


def base_included(base: dict, wanted: list[str]) -> bool:
    if not wanted:
        return True
    return str(base.get("id", "")).lower() in wanted or str(base.get("name", "")).strip().lower() in wanted


def load_config() -> dict[str, Any]:
    f = lambda name: get_connection_field(PLUGIN_SLUG, name)  # noqa: E731
    return {
        "token": (get_credential(PLUGIN_SLUG, "api_token") or "").strip(),
        "base_filter": parse_base_filter(f("bases")),
        "download_attachments": _truthy(f("download_attachments"), True),
        "max_attachment_bytes": int(_number(f("max_attachment_mb"), 100) * 1024 * 1024),
        "include_comments": _truthy(f("include_comments"), False),
    }


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _binary(data: bytes):
    import psycopg2  # present wherever the SDK's pg connection works

    return psycopg2.Binary(data)


# ── the sync ─────────────────────────────────────────────────────────────────

class AirtableBackupSync(BaseSyncScript):
    plugin_id = PLUGIN_SLUG

    def run(self, since: Any = None) -> dict[str, Any]:  # noqa: ARG002 — full pass every run
        cfg = load_config()
        if not cfg["token"]:
            raise RuntimeError("Airtable personal access token is not configured (Settings → Credentials).")
        self.cfg = cfg
        self.client = AirtableClient(cfg["token"])
        self.stats: dict[str, Any] = {
            "bases_visible": 0, "bases_included": 0, "bases_completed": 0,
            "tables_completed": 0, "records_seen": 0,
            "created": 0, "updated": 0, "deleted": 0, "restored": 0,
            "attachments_downloaded": 0, "attachment_bytes": 0,
            "attachments_failed": 0, "attachments_too_large": 0,
            "comments_saved": 0, "errors": [],
        }
        self.progress: dict[str, Any] = {}
        self.atb_run_id = self._atb_start_run()
        status = "success"
        try:
            bases = self.client.list_bases()
            self.stats["bases_visible"] = len(bases)
            self._upsert_bases(bases)
            included = [b for b in bases if base_included(b, cfg["base_filter"])]
            self.stats["bases_included"] = len(included)
            for i, base in enumerate(self._stalest_first(included)):
                self.progress = {"bases_done": i, "bases_total": len(included), "base": base.get("name")}
                try:
                    if self._sync_base(base):
                        self.stats["bases_completed"] += 1
                except AirtableError as e:
                    self._error(base, None, e)
                    self._set_base_error(base["id"], str(e))
            if self.stats["errors"]:
                status = "partial"
        except Cancelled:
            status = "cancelled"
        except Exception as e:
            self._atb_finish_run("error", str(e))
            raise
        self._atb_finish_run(status, None)
        log_event("info", f"Airtable backup {status}", detail={k: v for k, v in self.stats.items() if k != "errors"})
        self.log_sync_result(self.stats["records_seen"], len(self.stats["errors"]), self.stats)
        return {"rows_synced": self.stats["records_seen"], "status": status, "cancelled": status == "cancelled", **self.stats}

    # ── bookkeeping ──────────────────────────────────────────────────────────
    # Helpers are `_atb_`-prefixed: BaseSyncScript has private methods of its
    # own (_start_run, _complete_run, …) that main() calls, and a same-named
    # method here would silently replace them.

    def _atb_start_run(self) -> int:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO atb_runs (job_run_id) VALUES (%s) RETURNING id", (get_run_id(),))
            run_id = cur.fetchone()[0]
            conn.commit()
        return run_id

    def _atb_finish_run(self, status: str, error: str | None) -> None:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE atb_runs SET finished_at=now(), status=%s, stats=%s::jsonb, error=%s WHERE id=%s",
                (status, _j(self.stats), error, self.atb_run_id),
            )
            conn.commit()

    def _error(self, base: dict | None, table: dict | None, e: Exception) -> None:
        entry = {"base": (base or {}).get("name"), "table": (table or {}).get("name"), "error": str(e)[:500]}
        if len(self.stats["errors"]) < MAX_ERRORS_KEPT:
            self.stats["errors"].append(entry)
        log_event("warning", "Airtable backup error", detail=entry)

    def _beat(self, **extra: Any) -> None:
        heartbeat(progress={**self.progress, **extra, "records_seen": self.stats["records_seen"]})
        if check_cancelled():
            raise Cancelled()

    def _stalest_first(self, bases: list[dict]) -> list[dict]:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT base_id, last_synced_at FROM atb_bases")
            synced = {r[0]: r[1] for r in cur.fetchall()}
        # Never-synced first, then oldest.
        return sorted(bases, key=lambda b: (synced.get(b["id"]) is not None, synced.get(b["id"]) or 0))

    # ── bases + schema ───────────────────────────────────────────────────────

    def _upsert_bases(self, bases: list[dict]) -> None:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            for b in bases:
                cur.execute(
                    """INSERT INTO atb_bases (base_id, name, permission_level)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (base_id) DO UPDATE SET
                         name=EXCLUDED.name, permission_level=EXCLUDED.permission_level,
                         last_seen_at=now(), deleted_at=NULL""",
                    (b["id"], b.get("name") or b["id"], b.get("permissionLevel")),
                )
            cur.execute(
                "UPDATE atb_bases SET deleted_at=now() WHERE deleted_at IS NULL AND NOT (base_id = ANY(%s))",
                ([b["id"] for b in bases],),
            )
            conn.commit()

    def _set_base_error(self, base_id: str, error: str | None) -> None:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE atb_bases SET last_error=%s WHERE base_id=%s", (error, base_id))
            conn.commit()

    def _sync_base(self, base: dict) -> bool:
        base_id = base["id"]
        self._beat(phase="schema")
        tables = self.client.base_schema(base_id)
        self._upsert_tables(base_id, tables)
        all_ok = True
        for t_index, table in enumerate(tables):
            self.progress.update({"table": table.get("name"), "tables_done": t_index, "tables_total": len(tables)})
            try:
                self._sync_table(base_id, table)
                self.stats["tables_completed"] += 1
            except AirtableError as e:
                all_ok = False
                self._error(base, table, e)
                with get_pg_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE atb_tables SET last_error=%s WHERE table_id=%s", (str(e)[:1000], table["id"]))
                    conn.commit()
        with get_pg_conn() as conn:
            cur = conn.cursor()
            if all_ok:
                cur.execute("UPDATE atb_bases SET last_synced_at=now(), last_error=NULL WHERE base_id=%s", (base_id,))
            conn.commit()
        return all_ok

    def _upsert_tables(self, base_id: str, tables: list[dict]) -> None:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT table_id, schema_hash FROM atb_tables WHERE base_id=%s", (base_id,))
            known = dict(cur.fetchall())
            for pos, t in enumerate(tables):
                fields, views = t.get("fields") or [], t.get("views") or []
                h = fmt.schema_hash(t)
                if known.get(t["id"]) != h:
                    cur.execute(
                        """INSERT INTO atb_schema_history (table_id, base_id, name, fields, views, schema_hash)
                           VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)""",
                        (t["id"], base_id, t.get("name") or t["id"], _j(fields), _j(views), h),
                    )
                cur.execute(
                    """INSERT INTO atb_tables (table_id, base_id, name, description, primary_field_id,
                                               fields, views, schema_hash, position)
                       VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                       ON CONFLICT (table_id) DO UPDATE SET
                         base_id=EXCLUDED.base_id, name=EXCLUDED.name, description=EXCLUDED.description,
                         primary_field_id=EXCLUDED.primary_field_id, fields=EXCLUDED.fields,
                         views=EXCLUDED.views, schema_hash=EXCLUDED.schema_hash,
                         position=EXCLUDED.position, last_seen_at=now(), deleted_at=NULL""",
                    (t["id"], base_id, t.get("name") or t["id"], t.get("description"),
                     t.get("primaryFieldId"), _j(fields), _j(views), h, pos),
                )
            cur.execute(
                "UPDATE atb_tables SET deleted_at=now() WHERE base_id=%s AND deleted_at IS NULL "
                "AND NOT (table_id = ANY(%s))",
                (base_id, [t["id"] for t in tables]),
            )
            conn.commit()

    # ── records ──────────────────────────────────────────────────────────────

    def _sync_table(self, base_id: str, table: dict) -> None:
        table_id = table["id"]
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT baseline_complete FROM atb_tables WHERE table_id=%s", (table_id,))
            row = cur.fetchone()
        log_changes = bool(row and row[0])
        att_fields = fmt.attachment_field_ids(table.get("fields") or [])

        restarts = 0
        seen = 0
        while True:
            try:
                self.stats["records_seen"] -= seen  # don't double-count a restarted pass
                seen = 0
                for page in self.client.iter_record_pages(
                        base_id, table_id, with_comment_count=self.cfg["include_comments"]):
                    comment_targets = self._write_page(base_id, table_id, page, log_changes)
                    seen += len(page)
                    self.stats["records_seen"] += len(page)
                    if att_fields:
                        self._store_attachments(base_id, table_id, page, att_fields)
                    for record_id in comment_targets:
                        self._sync_comments(base_id, table_id, record_id)
                    self._beat(phase="records", table_records=seen)
                break
            except IteratorExpired:
                restarts += 1
                if restarts > MAX_ITERATOR_RESTARTS:
                    raise
                log_event("warning", "Airtable list iterator expired; restarting table",
                          detail={"table_id": table_id, "restart": restarts})

        # Complete pass → anything not seen this run is gone from Airtable.
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """UPDATE atb_records SET deleted_at=now(), last_changed_at=now()
                   WHERE table_id=%s AND deleted_at IS NULL
                     AND last_seen_run_id IS DISTINCT FROM %s
                   RETURNING record_id""",
                (table_id, self.atb_run_id),
            )
            gone = [r[0] for r in cur.fetchall()]
            if gone and log_changes:
                cur.executemany(
                    """INSERT INTO atb_record_changes (run_id, base_id, table_id, record_id, change_type)
                       VALUES (%s, %s, %s, %s, 'deleted')""",
                    [(self.atb_run_id, base_id, table_id, rid) for rid in gone],
                )
            self.stats["deleted"] += len(gone) if log_changes else 0
            cur.execute(
                """UPDATE atb_tables SET baseline_complete=true, last_synced_at=now(), last_error=NULL
                   WHERE table_id=%s""",
                (table_id,),
            )
            conn.commit()

    def _write_page(self, base_id: str, table_id: str, records: list[dict], log_changes: bool) -> list[str]:
        """Upsert one page. Returns record IDs whose comments need (re)fetching."""
        if not records:
            return []
        ids = [r["id"] for r in records]
        comment_targets: list[str] = []
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT record_id, content_hash, fields, deleted_at IS NOT NULL, comment_count
                   FROM atb_records WHERE table_id=%s AND record_id = ANY(%s)""",
                (table_id, ids),
            )
            existing = {r[0]: r for r in cur.fetchall()}
            unchanged: list[str] = []
            for rec in records:
                rid = rec["id"]
                fields = fmt.scrub(rec.get("fields") or {})
                h = fmt.content_hash(fields)
                cc = rec.get("commentCount")
                prev = existing.get(rid)
                prev_cc = prev[4] if prev else None

                if self.cfg["include_comments"] and cc is not None and cc != prev_cc and (cc > 0 or (prev_cc or 0) > 0):
                    comment_targets.append(rid)

                if prev is None:
                    cur.execute(
                        """INSERT INTO atb_records (table_id, record_id, base_id, created_time, fields,
                                                    content_hash, comment_count, last_seen_run_id)
                           VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)""",
                        (table_id, rid, base_id, rec.get("createdTime"), _j(fields), h, cc, self.atb_run_id),
                    )
                    if log_changes:
                        self._change(cur, base_id, table_id, rid, "created", sorted(fields), None)
                        self.stats["created"] += 1
                    continue

                _, old_hash, old_fields, was_deleted, _ = prev
                if was_deleted or old_hash != h:
                    diff = fmt.changed_fields(old_fields or {}, fields)
                    previous = {k: (old_fields or {}).get(k) for k in diff}
                    cur.execute(
                        """UPDATE atb_records SET fields=%s::jsonb, content_hash=%s, comment_count=%s,
                                  created_time=COALESCE(%s, created_time), last_changed_at=now(),
                                  last_seen_at=now(), last_seen_run_id=%s, deleted_at=NULL
                           WHERE table_id=%s AND record_id=%s""",
                        (_j(fields), h, cc, rec.get("createdTime"), self.atb_run_id, table_id, rid),
                    )
                    kind = "restored" if was_deleted else "updated"
                    if log_changes or was_deleted:
                        self._change(cur, base_id, table_id, rid, kind, diff, previous)
                        self.stats[kind] += 1
                elif cc != prev_cc:
                    cur.execute(
                        """UPDATE atb_records SET comment_count=%s, last_seen_at=now(), last_seen_run_id=%s
                           WHERE table_id=%s AND record_id=%s""",
                        (cc, self.atb_run_id, table_id, rid),
                    )
                else:
                    unchanged.append(rid)

            if unchanged:
                cur.execute(
                    """UPDATE atb_records SET last_seen_at=now(), last_seen_run_id=%s
                       WHERE table_id=%s AND record_id = ANY(%s)""",
                    (self.atb_run_id, table_id, unchanged),
                )
            conn.commit()
        return comment_targets

    def _change(self, cur, base_id: str, table_id: str, record_id: str, kind: str,
                field_ids: list[str], previous: dict | None) -> None:
        cur.execute(
            """INSERT INTO atb_record_changes (run_id, base_id, table_id, record_id, change_type,
                                              changed_field_ids, previous_fields)
               VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)""",
            (self.atb_run_id, base_id, table_id, record_id, kind, field_ids,
             _j(previous) if previous is not None else None),
        )

    # ── attachments ──────────────────────────────────────────────────────────

    def _store_attachments(self, base_id: str, table_id: str, records: list[dict], att_fields: set[str]) -> None:
        found: list[tuple[dict, str, str]] = []
        for rec in records:
            for fid in att_fields:
                for att in (rec.get("fields") or {}).get(fid) or []:
                    if fmt.is_attachment(att):
                        found.append((att, rec["id"], fid))
        if not found:
            return

        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT attachment_id, status FROM atb_attachments WHERE attachment_id = ANY(%s)",
                ([a["id"] for a, _, _ in found],),
            )
            status = dict(cur.fetchall())
            for att, rid, fid in found:
                if att["id"] not in status:
                    cur.execute(
                        """INSERT INTO atb_attachments (attachment_id, base_id, table_id, record_id, field_id,
                                                        filename, content_type, size_bytes, width, height, status)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (attachment_id) DO NOTHING""",
                        (att["id"], base_id, table_id, rid, fid, att.get("filename"), att.get("type"),
                         att.get("size"), att.get("width"), att.get("height"),
                         "pending" if self.cfg["download_attachments"] else "disabled"),
                    )
            conn.commit()

        if not self.cfg["download_attachments"]:
            return
        limit = self.cfg["max_attachment_bytes"]
        for att, _, _ in found:
            if status.get(att["id"]) in ("stored", "too_large") or not att.get("url"):
                continue
            declared = att.get("size")
            if isinstance(declared, (int, float)) and declared > limit:
                self._set_attachment(att["id"], "too_large", error=f"{int(declared)} bytes > limit {limit}")
                self.stats["attachments_too_large"] += 1
                continue
            try:
                data, ctype, digest = self.client.download(att["url"], limit)
            except AirtableError as e:
                kind = "too_large" if e.status == 413 else "failed"
                self._set_attachment(att["id"], kind, error=str(e)[:500])
                self.stats["attachments_too_large" if kind == "too_large" else "attachments_failed"] += 1
                continue
            self._set_attachment(att["id"], "stored", data=data, sha=digest,
                                 ctype=att.get("type") or ctype)
            status[att["id"]] = "stored"
            self.stats["attachments_downloaded"] += 1
            self.stats["attachment_bytes"] += len(data)
            self._beat(phase="attachments")

    def _set_attachment(self, attachment_id: str, status: str, *, data: bytes | None = None,
                        sha: str | None = None, ctype: str | None = None, error: str | None = None) -> None:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            if status == "stored":
                cur.execute(
                    """UPDATE atb_attachments SET status='stored', content=%s, sha256=%s, size_bytes=%s,
                              content_type=COALESCE(%s, content_type), downloaded_at=now(), error=NULL
                       WHERE attachment_id=%s""",
                    (_binary(data or b""), sha, len(data or b""), ctype, attachment_id),
                )
            else:
                cur.execute("UPDATE atb_attachments SET status=%s, error=%s WHERE attachment_id=%s",
                            (status, error, attachment_id))
            conn.commit()

    # ── comments ─────────────────────────────────────────────────────────────

    def _sync_comments(self, base_id: str, table_id: str, record_id: str) -> None:
        try:
            comments = self.client.list_comments(base_id, table_id, record_id)
        except AirtableError as e:
            self._error({"name": base_id}, {"name": f"{table_id}/{record_id} comments"}, e)
            return
        with get_pg_conn() as conn:
            cur = conn.cursor()
            for c in comments:
                raw = fmt.scrub(c)
                cur.execute(
                    """INSERT INTO atb_comments (comment_id, base_id, table_id, record_id, parent_comment_id,
                                                 author, text, created_time, last_updated_time, raw)
                       VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb)
                       ON CONFLICT (comment_id) DO UPDATE SET
                         text=EXCLUDED.text, last_updated_time=EXCLUDED.last_updated_time,
                         author=EXCLUDED.author, raw=EXCLUDED.raw, last_seen_at=now(), deleted_at=NULL""",
                    (c["id"], base_id, table_id, record_id, c.get("parentCommentId"), _j(c.get("author")),
                     c.get("text"), c.get("createdTime"), c.get("lastUpdatedTime"), _j(raw)),
                )
            cur.execute(
                """UPDATE atb_comments SET deleted_at=now()
                   WHERE table_id=%s AND record_id=%s AND deleted_at IS NULL AND NOT (comment_id = ANY(%s))""",
                (table_id, record_id, [c["id"] for c in comments]),
            )
            conn.commit()
        self.stats["comments_saved"] += len(comments)


if __name__ == "__main__":
    AirtableBackupSync().main()
