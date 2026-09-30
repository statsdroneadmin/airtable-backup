"""
airtable_backup_format.py — pure helpers shared by the sync and the routes.

No database, network or SDK imports, so everything here is unit-testable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

# Keys on an attachment object that change on every API response (signed,
# expiring URLs). Stripped before hashing and storing so a re-read of an
# unchanged record is not reported as a change.
VOLATILE_ATTACHMENT_KEYS = ("url", "thumbnails")


def is_attachment(obj: Any) -> bool:
    return isinstance(obj, dict) and str(obj.get("id", "")).startswith("att") and "filename" in obj


def scrub(value: Any) -> Any:
    """Return a copy of a cell value with volatile attachment URLs removed.
    Recursive so attachments nested in lookups are handled too."""
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        if is_attachment(value):
            return {k: scrub(v) for k, v in value.items() if k not in VOLATILE_ATTACHMENT_KEYS}
        return {k: scrub(v) for k, v in value.items()}
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(fields: dict) -> str:
    return hashlib.sha256(canonical_json(fields).encode()).hexdigest()


def schema_hash(table: dict) -> str:
    return content_hash({
        "name": table.get("name"),
        "description": table.get("description"),
        "primaryFieldId": table.get("primaryFieldId"),
        "fields": table.get("fields") or [],
        "views": table.get("views") or [],
    })


def changed_fields(old: dict, new: dict) -> list[str]:
    """Field IDs whose value differs. Airtable omits empty fields, so a key
    present on one side only is a change (set ↔ cleared)."""
    keys = set(old) | set(new)
    return sorted(k for k in keys if canonical_json(old.get(k)) != canonical_json(new.get(k)))


def attachment_field_ids(fields_schema: Iterable[dict]) -> set[str]:
    """Field IDs of direct attachment fields (not lookups of attachments —
    those files belong to the other table and are stored when it syncs)."""
    return {f["id"] for f in fields_schema if f.get("type") == "multipleAttachments" and f.get("id")}


def cell_to_text(value: Any) -> str:
    """Flatten a cell value for CSV. Mirrors what Airtable shows in a grid,
    without losing data: lists join with ", ", objects fall back to JSON."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(cell_to_text(v) for v in value)
    if isinstance(value, dict):
        if is_attachment(value):
            return str(value.get("filename") or value.get("id"))
        # Collaborator
        if "email" in value and ("name" in value or "id" in value):
            return str(value.get("name") or value.get("email"))
        # Button
        if "label" in value and "url" in value:
            return str(value.get("url") or value.get("label"))
        # AI text / barcode style objects
        for key in ("value", "text"):
            if isinstance(value.get(key), (str, int, float)):
                return str(value[key])
        if value.get("specialValue") is not None:
            return str(value["specialValue"])
        if "error" in value:
            return f"#ERROR {value.get('error')}"
        return canonical_json(value)
    return str(value)


def fields_by_name(fields: dict, schema: list[dict]) -> dict:
    """Re-key a record's field-ID dict by field name, in schema order. Fields
    no longer in the schema keep their ID as the key so nothing is dropped."""
    names = {f["id"]: f.get("name") or f["id"] for f in schema if f.get("id")}
    out: dict[str, Any] = {}
    for f in schema:
        fid = f.get("id")
        if fid in fields:
            out[names[fid]] = fields[fid]
    for fid, v in fields.items():
        if fid not in names:
            out[fid] = v
    return out
