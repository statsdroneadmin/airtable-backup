"""End-to-end harness: real Postgres (as a non-superuser nousviz_plugin role),
real HTTP to a fake Airtable, core's REAL BaseSyncScript (sync.py fetched by
tests/run.sh), stub for the rest of the SDK. Run via tests/run.sh.
"""
import csv
import importlib.util
import io
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path[:0] = [str(HERE / "sdk_stub"), str(HERE), str(PLUGIN / "src")]

import psycopg2  # noqa: E402
import nousviz_sdk  # noqa: E402
from nousviz_sdk import jobs as sdk_jobs, settings as sdk_settings  # noqa: E402
from nousviz_sdk.sync import BaseSyncScript  # noqa: E402
import fake_airtable as fa  # noqa: E402
import airtable_backup_client as client_mod  # noqa: E402
import airtable_backup_sync as sync_mod  # noqa: E402

assert hasattr(BaseSyncScript, "_start_run"), "expected core's real sync.py, got a stub"

ADMIN = os.environ.get("ATB_ADMIN_DSN", "host=127.0.0.1 port=55432 dbname=atb user=admin")
srv = fa.start()
client_mod.API_ROOT = f"http://127.0.0.1:{srv.server_address[1]}/v0"
client_mod.MIN_INTERVAL_S = 0.0
client_mod.RATE_LIMIT_WAIT_S = 0.05
nousviz_sdk.CREDS["api_token"] = fa.TOKEN
sdk_settings.FIELDS.update({"bases": "CRM", "include_comments": "yes", "max_attachment_mb": "1"})
sys.argv = [sys.argv[0]]  # core main() parses argv
S = fa.STATE
FAILS = []


def check(cond, label):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        FAILS.append(label)


def q(sql, args=()):
    with psycopg2.connect(ADMIN) as c:
        cur = c.cursor()
        cur.execute(sql, args)
        return cur.fetchall() if cur.description else []


def one(sql, args=()):
    return q(sql, args)[0][0]


def last_job():
    return q("SELECT id, status, rows_written FROM job_runs WHERE job_id='sync:airtable-backup' ORDER BY id DESC LIMIT 1")[0]


def run():
    """Drive the REAL core BaseSyncScript.main() (argparse, _start_run, _complete_run)."""
    sdk_jobs.STATE["checks"] = 0
    s = sync_mod.AirtableBackupSync()
    s.main()
    return {**s.stats, "status": one("SELECT status FROM atb_runs ORDER BY id DESC LIMIT 1")}


print("\n== Run 1: baseline ==")
r1 = run()
job = last_job()
check(r1["status"] == "success", "run 1 success (429 retried transparently)")
check(job[1] == "success" and job[2] == 253, f"core main() created + completed job_runs row {job}")
check(one("SELECT job_run_id FROM atb_runs ORDER BY id DESC LIMIT 1") == job[0], "atb_runs linked to core's job_runs id")
check(one("SELECT count(*) FROM atb_bases") == 2, "both bases recorded (list is unfiltered)")
check(one("SELECT count(*) FROM atb_tables") == 2, "only CRM's 2 tables synced (filter 'CRM')")
check(one("SELECT count(*) FROM atb_records") == 253, "253 records stored")
check(one("SELECT count(*) FROM atb_record_changes") == 0, "baseline produced no change rows")
check(one("SELECT count(*) FROM atb_schema_history") == 2, "schema snapshot per table")
check(one("SELECT count(*) FROM atb_attachments WHERE status='stored'") == 7, "7 attachments stored")
check(one("SELECT count(*) FROM atb_attachments WHERE status='too_large'") == 1, "oversized attachment marked too_large")
check("attHuge" not in S.downloads, "oversized attachment never fetched")
stored = bytes(q("SELECT content FROM atb_attachments WHERE attachment_id='attLead50'")[0][0])
check(stored == S.files["attLead50"], "stored bytes match source exactly")
check(one("SELECT count(*) FROM atb_records WHERE fields::text LIKE '%%sig=%%'") == 0, "no signed URLs persisted")
check(one("SELECT count(*) FROM atb_comments") == 1, "comment backed up")
downloads_after_1 = len(S.downloads)

print("\n== Run 2: no changes ==")
r2 = run()
check(r2["updated"] == 0 and r2["created"] == 0 and r2["deleted"] == 0, "fresh signed URLs → 0 changes")
check(len(S.downloads) == downloads_after_1, "no attachment re-downloaded")

print("\n== Run 3: edit, delete, add, schema change, new comment ==")
leads = S.records["tblLeads"]
leads[5]["fields"]["fldNotes"] = "EDITED"
leads[5]["fields"].pop("fldStatus")
deleted = leads.pop(7)
leads.append({"id": "recNEW", "createdTime": "2024-05-01T00:00:00.000Z",
              "fields": {"fldName": "New lead", "fldFiles": [S.att("attLead0", "lead0.pdf", "application/pdf")]}})
S.schema["appCRM"][0]["fields"].append({"id": "fldScore", "name": "Score", "type": "number"})
S.comments["recL002"] = [{"id": "comB", "text": "second", "createdTime": "2024-03-02T00:00:00.000Z", "author": {"name": "Bo"}}]
r3 = run()
check(r3["updated"] == 1 and r3["created"] == 1 and r3["deleted"] == 1, "1 updated / 1 created / 1 deleted")
row = q("SELECT changed_field_ids, previous_fields FROM atb_record_changes WHERE record_id='recL005' AND change_type='updated'")
check(bool(row) and sorted(row[0][0]) == ["fldNotes", "fldStatus"], "update lists Notes + Status")
check(bool(row) and row[0][1] == {"fldNotes": None, "fldStatus": "Lost"}, "previous values kept")
check(one("SELECT deleted_at IS NOT NULL FROM atb_records WHERE record_id='recL007'") is True, "deleted record kept")
check(one("SELECT fields->>'fldName' FROM atb_records WHERE record_id='recL007'") == "Lead 7", "deleted record keeps last values")
check(one("SELECT count(*) FROM atb_schema_history WHERE table_id='tblLeads'") == 2, "schema change snapshotted")
check(one("SELECT count(*) FROM atb_comments") == 2, "new comment picked up")
check(len(S.downloads) == downloads_after_1, "known attachment id not re-downloaded")

print("\n== Run 4: restore + iterator expiry ==")
leads.insert(7, deleted)
S.iterator_expire_on_page = 1
r4 = run()
check(r4["restored"] == 1 and r4["deleted"] == 0, "restored logged; restart caused no bogus deletes")
check(r4["records_seen"] == 254, f"records_seen not double-counted ({r4['records_seen']})")
check(r4["status"] == "success", "run 4 success")

print("\n== Run 5: cancelled ==")
leads.pop(0)
sdk_jobs.STATE["cancel_after"] = 2
r5 = run()
sdk_jobs.STATE["cancel_after"] = None
check(r5["status"] == "cancelled", "run reports cancelled")
check(one("SELECT count(*) FROM atb_records WHERE record_id='recL000' AND deleted_at IS NOT NULL") == 0,
      "interrupted pass marks nothing deleted")

print("\n== Run 6: bad token ==")
nousviz_sdk.CREDS["api_token"] = "patWRONG"
try:
    run()
    check(False, "bad token raises")
except client_mod.AirtableError as e:
    check(e.status == 401, "bad token → AirtableError 401")
check(one("SELECT status FROM atb_runs ORDER BY id DESC LIMIT 1") == "error", "atb_runs error")
check(last_job()[1] == "error", "core marked job_runs error")
nousviz_sdk.CREDS["api_token"] = fa.TOKEN

print("\n== Run 7: all bases, downloads off ==")
sdk_settings.FIELDS["bases"] = ""
sdk_settings.FIELDS["download_attachments"] = "no"
S.schema["appOTHER"][0]["fields"].append({"id": "fldAtt", "name": "Att", "type": "multipleAttachments"})
S.files["attX"] = b"xfile"
S.records["tblX"][0]["fields"]["fldAtt"] = [S.att("attX", "x.txt", "text/plain")]
r7 = run()
check(r7["bases_included"] == 2 and r7["status"] == "success", "blank filter → all bases")
check(one("SELECT status FROM atb_attachments WHERE attachment_id='attX'") == "disabled" and "attX" not in S.downloads,
      "downloads off → metadata only")

print("\n== Routes ==")
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

spec = importlib.util.spec_from_file_location("atb_routes", PLUGIN / "api" / "routes.py")
routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routes)
app = FastAPI()


@app.middleware("http")
async def fake_auth(request: Request, call_next):
    if request.headers.get("X-Test-User"):
        request.state.user_identity = request.headers["X-Test-User"]
    return await call_next(request)

app.include_router(routes.router, prefix="/api")
tc = TestClient(app)
H = {"X-Test-User": "tester"}
P = "/api/plugins/airtable-backup"
check(tc.get(f"{P}/summary").status_code == 401, "unauthenticated → 401")
s = tc.get(f"{P}/summary", headers=H).json()
check(s["totals"]["attachments_stored"] == 7, "summary totals")
check({x["name"] for x in tc.get(f"{P}/bases", headers=H).json()["bases"]} == {"CRM", "Other Base"}, "bases listed")
rec = tc.get(f"{P}/records", params={"table_id": "tblLeads", "q": "EDITED"}, headers=H).json()
check(rec["total"] == 1 and rec["records"][0]["record_id"] == "recL005", "search")
check(tc.get(f"{P}/records", params={"table_id": "tblLeads", "include_deleted": True}, headers=H).json()["total"] == 251,
      "include_deleted (250 live + 1 deleted)")
d = tc.get(f"{P}/record", params={"table_id": "tblLeads", "record_id": "recL005"}, headers=H).json()
check(len(d["changes"]) == 1, "record history")
a = tc.get(f"{P}/attachments/attLead50", headers=H)
check(a.status_code == 200 and a.content == S.files["attLead50"], "attachment download")
c = tc.get(f"{P}/export/table", params={"table_id": "tblLeads", "format": "csv"}, headers=H)
rows = list(csv.reader(io.StringIO(c.content.decode("utf-8-sig"))))
check(rows[0][:4] == ["Record ID", "Created time", "Name", "Notes"] and len(rows) == 251, f"CSV ({len(rows) - 1} rows)")
bj = tc.get(f"{P}/export/base", params={"base_id": "appCRM"}, headers=H).json()
check([x["name"] for x in bj["tables"]] == ["Leads", "Companies"], "base JSON")
tcn = tc.post(f"{P}/test-connection", headers=H).json()
check(tcn["ok"] and "usrTEST" in tcn["toast"], f"test-connection: {tcn['toast']}")
hc = tc.get(f"{P}/health-check", headers=H).json()
check(hc["version"] == routes._plugin_version(), f"health-check version {hc['version']}")

print("\n== Hooks ==")
spec = importlib.util.spec_from_file_location("atb_hooks", PLUGIN / "hooks" / "lifecycle.py")
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)
from nousviz_sdk.hooks import HookContext  # noqa: E402
hr = hooks.on_credentials_saved(HookContext("airtable-backup", "on_credentials_saved"))
check(hr.ok, f"hook: {hr.message}")

print("\n" + ("ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
srv.shutdown()
sys.exit(1 if FAILS else 0)
