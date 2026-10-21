"""Fake Airtable Web API over real HTTP, so the stdlib client is exercised.

Mimics: whoami, list bases, base schema, POST listRecords (offset pagination,
returnFieldsByFieldId, recordMetadata=commentCount), comments, signed
attachment URLs that change on every response, one 429, an optional
iterator-expired 422.
"""
import copy
import itertools
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "patTEST.notarealtoken"
_url_counter = itertools.count()


class State:
    def __init__(self):
        self.bases = [
            {"id": "appCRM", "name": "CRM", "permissionLevel": "create"},
            {"id": "appOTHER", "name": "Other Base", "permissionLevel": "read"},
        ]
        self.files = {}
        self.schema = {
            "appCRM": [
                {"id": "tblLeads", "name": "Leads", "primaryFieldId": "fldName", "description": None,
                 "fields": [
                     {"id": "fldName", "name": "Name", "type": "singleLineText"},
                     {"id": "fldNotes", "name": "Notes", "type": "multilineText"},
                     {"id": "fldStatus", "name": "Status", "type": "singleSelect"},
                     {"id": "fldFiles", "name": "Files", "type": "multipleAttachments"},
                     {"id": "fldOwner", "name": "Owner", "type": "singleCollaborator"},
                     {"id": "fldCo", "name": "Company", "type": "multipleRecordLinks"},
                 ],
                 "views": [{"id": "viwGrid", "name": "Grid view", "type": "grid"}]},
                {"id": "tblCos", "name": "Companies", "primaryFieldId": "fldCoName", "description": "orgs",
                 "fields": [{"id": "fldCoName", "name": "Company name", "type": "singleLineText"},
                            {"id": "fldLogo", "name": "Logo", "type": "multipleAttachments"}],
                 "views": [{"id": "viwCo", "name": "All", "type": "grid"}]},
            ],
            "appOTHER": [
                {"id": "tblX", "name": "X", "primaryFieldId": "fldX",
                 "fields": [{"id": "fldX", "name": "X", "type": "singleLineText"}], "views": []},
            ],
        }
        self.records = {"tblLeads": [], "tblCos": [],
                        "tblX": [{"id": "recX1", "createdTime": "2024-01-01T00:00:00.000Z", "fields": {"fldX": "x"}}]}
        for i in range(3):
            att = f"attLogo{i}"
            self.files[att] = f"logo-{i}".encode() * 10
            self.records["tblCos"].append({"id": f"recCo{i}", "createdTime": "2024-01-01T00:00:00.000Z",
                                           "fields": {"fldCoName": f"Company {i}",
                                                      "fldLogo": [self.att(att, "logo.png", "image/png")]}})
        for i in range(250):
            f = {"fldName": f"Lead {i}", "fldStatus": ["New", "Won", "Lost"][i % 3],
                 "fldOwner": {"id": "usr1", "email": "a@example.com", "name": "Ann"}, "fldCo": [f"recCo{i % 3}"]}
            if i % 2 == 0:
                f["fldNotes"] = f"note {i}\nline2"
            if i % 50 == 0:
                att = f"attLead{i}"
                self.files[att] = (f"file for lead {i} ".encode()) * 100
                f["fldFiles"] = [self.att(att, f"lead{i}.pdf", "application/pdf")]
            if i == 100:
                self.files["attHuge"] = b"x" * 5000
                f["fldFiles"] = [self.att("attHuge", "huge.bin", "application/octet-stream", size=5_000_000_000)]
            self.records["tblLeads"].append({"id": f"recL{i:03d}",
                                             "createdTime": f"2024-02-{(i % 28) + 1:02d}T10:00:00.000Z", "fields": f})
        self.comments = {"recL001": [{"id": "comA", "text": "hello", "createdTime": "2024-03-01T00:00:00.000Z",
                                      "lastUpdatedTime": None,
                                      "author": {"id": "usr1", "email": "a@example.com", "name": "Ann"}}]}
        self.fail_429_once = True
        self.iterator_expire_on_page = None
        self.downloads = []

    def att(self, att_id, filename, ctype, size=None):
        return {"id": att_id, "filename": filename, "type": ctype,
                "size": size if size is not None else len(self.files[att_id])}


STATE = State()


def _fresh_urls(value, port):
    if isinstance(value, list):
        return [_fresh_urls(v, port) for v in value]
    if isinstance(value, dict):
        out = {k: _fresh_urls(v, port) for k, v in value.items()}
        if str(out.get("id", "")).startswith("att") and "filename" in out:
            sig = next(_url_counter)
            out["url"] = f"http://127.0.0.1:{port}/files/{out['id']}?sig={sig}"
            out["thumbnails"] = {"small": {"url": f"http://127.0.0.1:{port}/thumb/{out['id']}?sig={sig}"}}
        return out
    return value


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, raw=None, ctype="application/json"):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._send(401, {"error": {"type": "AUTHENTICATION_REQUIRED", "message": "Authentication required"}})
            return False
        return True

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        parts = u.path.strip("/").split("/")
        if parts[0] == "files":
            STATE.downloads.append(parts[1])
            return self._send(200, raw=STATE.files[parts[1]], ctype="application/octet-stream")
        if not self._auth():
            return
        if u.path == "/v0/meta/whoami":
            return self._send(200, {"id": "usrTEST"})
        if u.path == "/v0/meta/bases":
            return self._send(200, {"bases": STATE.bases})
        if len(parts) == 5 and parts[1] == "meta" and parts[4] == "tables":
            return self._send(200, {"tables": copy.deepcopy(STATE.schema[parts[3]])})
        if len(parts) == 5 and parts[4] == "comments":
            return self._send(200, {"comments": STATE.comments.get(parts[3], []), "offset": None})
        self._send(404, {"error": "NOT_FOUND"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        parts = u.path.strip("/").split("/")
        port = self.server.server_address[1]
        if not self._auth():
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if len(parts) == 4 and parts[3] == "listRecords":
            if STATE.fail_429_once:
                STATE.fail_429_once = False
                return self._send(429, {"errors": [{"error": "RATE_LIMIT_REACHED"}]})
            assert body.get("returnFieldsByFieldId") is True
            recs = STATE.records[parts[2]]
            start = int(body.get("offset") or 0)
            if STATE.iterator_expire_on_page is not None and start and start // 100 == STATE.iterator_expire_on_page:
                STATE.iterator_expire_on_page = None
                return self._send(422, {"error": {"type": "LIST_RECORDS_ITERATOR_NOT_AVAILABLE",
                                                  "message": "iterator expired"}})
            page = copy.deepcopy(recs[start:start + body.get("pageSize", 100)])
            for r in page:
                r["fields"] = _fresh_urls(r["fields"], port)
                if "commentCount" in (body.get("recordMetadata") or []):
                    r["commentCount"] = len(STATE.comments.get(r["id"], []))
            out = {"records": page}
            if start + 100 < len(recs):
                out["offset"] = str(start + 100)
            return self._send(200, out)
        self._send(404, {"error": "NOT_FOUND"})


def start():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
