"""
airtable_backup_client.py — read-only Airtable Web API client.

stdlib `urllib` only: `requests`/`httpx` are not guaranteed on the NousViz host
(a plugin that imports them can fail to load), and plugins don't ship runtime
requirements.

Airtable facts this relies on (airtable.com/developers/web/api, 2026-09-30):
  - 5 requests/second per base, 50/second per token. 429 → wait 30 seconds.
  - listRecords pageSize ≤ 100, `offset` pagination.
  - Attachment URLs expire 2 hours after the API returns them.

The client is deliberately synchronous and single-threaded: one request at a
time, so the per-base throttle below is the whole rate-limit story.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterator

API_ROOT = "https://api.airtable.com/v0"
USER_AGENT = "nousviz-airtable-backup/0.1"

MIN_INTERVAL_S = 0.22          # ≈ 4.5 req/s — under the 5 req/s per-base limit
RATE_LIMIT_WAIT_S = 30         # Airtable: wait 30 s after a 429
MAX_RETRIES = 5
REQUEST_TIMEOUT_S = 60
DOWNLOAD_TIMEOUT_S = 300
DOWNLOAD_CHUNK = 1024 * 1024


class AirtableError(Exception):
    """Non-retryable API error. `status` is the HTTP status (0 = network)."""

    def __init__(self, status: int, message: str, error_type: str | None = None):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status
        self.error_type = error_type


class IteratorExpired(AirtableError):
    """The listRecords offset is no longer valid; restart the table."""


class AirtableClient:
    def __init__(self, token: str, sleep: Callable[[float], None] = time.sleep):
        if not token:
            raise AirtableError(0, "No Airtable token configured")
        self._token = token.strip()
        self._sleep = sleep
        self._last_call: dict[str, float] = {}

    # ── low level ────────────────────────────────────────────────────────────

    def _throttle(self, bucket: str) -> None:
        last = self._last_call.get(bucket)
        if last is not None:
            wait = MIN_INTERVAL_S - (time.monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_call[bucket] = time.monotonic()

    def _request(self, method: str, path: str, *, bucket: str = "meta",
                 query: dict[str, Any] | None = None, body: dict | None = None) -> dict:
        url = f"{API_ROOT}{path}"
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        attempt = 0
        while True:
            attempt += 1
            self._throttle(bucket)
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                    raw = resp.read()
                return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                status = e.code
                err_type, message = _parse_error(e)
                if status == 429 and attempt <= MAX_RETRIES:
                    self._sleep(RATE_LIMIT_WAIT_S)
                    continue
                if status in (500, 502, 503, 504) and attempt <= MAX_RETRIES:
                    self._sleep(min(2 ** attempt, 60))
                    continue
                if status == 422 and err_type and "ITERATOR" in err_type.upper():
                    raise IteratorExpired(status, message, err_type) from None
                raise AirtableError(status, message, err_type) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt <= MAX_RETRIES:
                    self._sleep(min(2 ** attempt, 60))
                    continue
                raise AirtableError(0, f"Network error: {e}") from None

    # ── metadata ─────────────────────────────────────────────────────────────

    def whoami(self) -> dict:
        return self._request("GET", "/meta/whoami")

    def list_bases(self) -> list[dict]:
        bases: list[dict] = []
        offset: str | None = None
        while True:
            page = self._request("GET", "/meta/bases", query={"offset": offset})
            bases.extend(page.get("bases") or [])
            offset = page.get("offset")
            if not offset:
                return bases

    def base_schema(self, base_id: str) -> list[dict]:
        page = self._request("GET", f"/meta/bases/{_q(base_id)}/tables", bucket=base_id)
        return page.get("tables") or []

    # ── data ─────────────────────────────────────────────────────────────────

    def iter_record_pages(self, base_id: str, table_id: str, *,
                          with_comment_count: bool = False) -> Iterator[list[dict]]:
        """Yield pages (≤100 records) of a table, fields keyed by field ID."""
        offset: str | None = None
        while True:
            body: dict[str, Any] = {"pageSize": 100, "returnFieldsByFieldId": True}
            if with_comment_count:
                body["recordMetadata"] = ["commentCount"]
            if offset:
                body["offset"] = offset
            page = self._request("POST", f"/{_q(base_id)}/{_q(table_id)}/listRecords",
                                 bucket=base_id, body=body)
            yield page.get("records") or []
            offset = page.get("offset")
            if not offset:
                return

    def list_comments(self, base_id: str, table_id: str, record_id: str) -> list[dict]:
        comments: list[dict] = []
        offset: str | None = None
        while True:
            page = self._request(
                "GET", f"/{_q(base_id)}/{_q(table_id)}/{_q(record_id)}/comments",
                bucket=base_id, query={"pageSize": 100, "offset": offset},
            )
            comments.extend(page.get("comments") or [])
            offset = page.get("offset")
            if not offset:
                return comments

    # ── attachment bytes ─────────────────────────────────────────────────────

    def download(self, url: str, max_bytes: int) -> tuple[bytes, str | None, str]:
        """Fetch an attachment URL. Returns (bytes, content_type, sha256).

        Raises AirtableError(413) when the file exceeds max_bytes. The signed
        URL carries its own auth, so no Authorization header is sent.
        """
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        attempt = 0
        while True:
            attempt += 1
            try:
                with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S) as resp:
                    declared = resp.headers.get("Content-Length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise AirtableError(413, f"File is {int(declared)} bytes (limit {max_bytes})")
                    h = hashlib.sha256()
                    chunks: list[bytes] = []
                    total = 0
                    while True:
                        chunk = resp.read(DOWNLOAD_CHUNK)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise AirtableError(413, f"File exceeds limit of {max_bytes} bytes")
                        h.update(chunk)
                        chunks.append(chunk)
                    return b"".join(chunks), resp.headers.get("Content-Type"), h.hexdigest()
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt <= 3:
                    self._sleep(min(5 * attempt, 30))
                    continue
                raise AirtableError(e.code, f"Download failed: {e.reason}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt <= 3:
                    self._sleep(min(5 * attempt, 30))
                    continue
                raise AirtableError(0, f"Download failed: {e}") from None


def _q(segment: str) -> str:
    return urllib.parse.quote(segment, safe="")


def _parse_error(e: urllib.error.HTTPError) -> tuple[str | None, str]:
    """Airtable errors look like {"error": {"type": ..., "message": ...}} or
    {"error": "NOT_FOUND"}. Never echoes the request (no token leak)."""
    try:
        payload = json.loads(e.read() or b"{}")
    except Exception:  # noqa: BLE001
        return None, str(e.reason)
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        return err.get("type"), str(err.get("message") or err.get("type") or e.reason)
    if isinstance(err, str):
        return err, err
    return None, str(e.reason)
