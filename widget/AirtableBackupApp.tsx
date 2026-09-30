/// <reference path="./nousviz_widget_types.d.ts" />
//
// AirtableBackupApp.tsx — the whole Airtable Backup overview in one panel:
// totals, base → table → record browser, record drawer (fields, attachment
// downloads, change history, comments), exports, and recent changes.
//
// Styling uses host theme tokens (hsl(var(--card)) etc.) so it reads in light
// and dark dashboards (G-18/G-19). All hooks are declared before any early
// return (React #310). Downloads go through apiFetch → blob so the session
// token is sent; a plain <a href> would not carry it.

import { useCallback, useEffect, useMemo, useState } from "react";

const SLUG = "airtable-backup";
const api = (path: string) => window.NousViz.widgets.apiFetch(`/api/plugins/${SLUG}${path}`);
const qs = (o: Record<string, string | number | boolean | undefined | null>) =>
  Object.entries(o)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");

type Field = { id: string; name: string; type: string; description?: string };
type Base = { base_id: string; name: string; tables: number; records: number; last_synced_at: string | null; deleted_at: string | null; last_error: string | null };
type Table = { table_id: string; name: string; fields: Field[]; primary_field_id: string; records: number; deleted_records: number; last_synced_at: string | null; deleted_at: string | null; last_error: string | null };
type Rec = { record_id: string; created_time: string | null; fields: Record<string, any>; deleted_at: string | null; last_changed_at: string | null };

// ── tokens ───────────────────────────────────────────────────────────────────
const C = {
  card: "hsl(var(--card))",
  bg: "hsl(var(--background))",
  fg: "hsl(var(--foreground))",
  muted: "hsl(var(--muted))",
  mutedFg: "hsl(var(--muted-foreground))",
  border: "hsl(var(--border))",
  primary: "hsl(var(--primary))",
  primaryFg: "hsl(var(--primary-foreground))",
};
const STATUS: Record<string, string> = {
  created: "142 71% 38%",
  updated: "217 91% 55%",
  deleted: "0 72% 51%",
  restored: "38 92% 50%",
};
const pill = (hsl: string): React.CSSProperties => ({
  display: "inline-block", padding: "1px 8px", borderRadius: 999, fontSize: 11, fontWeight: 600,
  color: `hsl(${hsl})`, background: `hsl(${hsl} / 0.12)`, border: `1px solid hsl(${hsl} / 0.3)`,
});
const btn: React.CSSProperties = {
  padding: "5px 10px", borderRadius: 6, border: `1px solid ${C.border}`, background: C.card,
  color: C.fg, fontSize: 12, cursor: "pointer", whiteSpace: "nowrap",
};
const input: React.CSSProperties = {
  padding: "6px 10px", borderRadius: 6, border: `1px solid ${C.border}`, background: C.bg,
  color: C.fg, fontSize: 13, colorScheme: "light dark", minWidth: 0,
};

// ── formatting ───────────────────────────────────────────────────────────────
const num = (n: number | null | undefined) => window.NousViz.widgets.formatNumber(Number(n ?? 0));
const bytes = (n: number | null | undefined) => window.NousViz.widgets.formatBytes(Number(n ?? 0));
const rel = (iso: string | null | undefined) => window.NousViz.widgets.formatRelativeTime(iso ?? null);
const abs = (iso: string | null | undefined) => window.NousViz.widgets.formatAbsoluteTime(iso ?? null);

function isAttachment(v: any) {
  return v && typeof v === "object" && typeof v.id === "string" && v.id.startsWith("att") && "filename" in v;
}

function cellText(v: any): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "✓" : "";
  if (typeof v === "number" || typeof v === "string") return String(v);
  if (Array.isArray(v)) return v.map(cellText).filter(Boolean).join(", ");
  if (typeof v === "object") {
    if (isAttachment(v)) return v.filename || v.id;
    if ("email" in v) return v.name || v.email;
    if ("label" in v && "url" in v) return v.label || v.url;
    if (typeof v.value === "string" || typeof v.value === "number") return String(v.value);
    if (typeof v.text === "string") return v.text;
    if (v.specialValue !== undefined) return String(v.specialValue);
    if (v.error) return `#ERROR ${v.error}`;
    return JSON.stringify(v);
  }
  return String(v);
}

async function downloadFrom(path: string, fallback: string) {
  const r = await api(path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const blob = await r.blob();
  const cd = r.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename="([^"]+)"/);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = m ? m[1] : fallback;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

async function getJson(path: string) {
  const r = await api(path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ── component ────────────────────────────────────────────────────────────────
const PAGE = 50;

export default function AirtableBackupApp(_: CustomWidgetProps) {
  const [summary, setSummary] = useState<any>(null);
  const [bases, setBases] = useState<Base[]>([]);
  const [baseId, setBaseId] = useState<string | null>(null);
  const [tables, setTables] = useState<Table[]>([]);
  const [tableId, setTableId] = useState<string | null>(null);
  const [records, setRecords] = useState<Rec[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [qApplied, setQApplied] = useState("");
  const [showDeleted, setShowDeleted] = useState(false);
  const [changes, setChanges] = useState<any[]>([]);
  const [drawer, setDrawer] = useState<{ table_id: string; record_id: string } | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [recLoading, setRecLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const table = useMemo(() => tables.find((t) => t.table_id === tableId) || null, [tables, tableId]);
  const columns = useMemo(() => {
    if (!table) return [] as Field[];
    const f = table.fields || [];
    const primary = f.find((x) => x.id === table.primary_field_id);
    const rest = f.filter((x) => x.id !== table.primary_field_id);
    return (primary ? [primary, ...rest] : rest).slice(0, 8);
  }, [table]);

  const loadTop = useCallback(async () => {
    try {
      const [s, b, c] = await Promise.all([getJson("/summary"), getJson("/bases"), getJson("/changes?limit=30")]);
      setSummary(s);
      setBases(b.bases || []);
      setChanges(c.changes || []);
      setErr(null);
      setBaseId((cur) => cur ?? (b.bases || []).find((x: Base) => !x.deleted_at)?.base_id ?? null);
    } catch (e: any) {
      setErr(`Couldn't load the backup: ${e?.message || e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTop();
  }, [loadTop]);

  useEffect(() => {
    if (!baseId) return;
    let live = true;
    getJson(`/tables?${qs({ base_id: baseId })}`)
      .then((d) => {
        if (!live) return;
        const ts: Table[] = d.tables || [];
        setTables(ts);
        setTableId(ts.find((t) => !t.deleted_at)?.table_id ?? ts[0]?.table_id ?? null);
        setOffset(0);
      })
      .catch((e) => live && setErr(`Couldn't load tables: ${e?.message || e}`));
    return () => {
      live = false;
    };
  }, [baseId]);

  useEffect(() => {
    if (!tableId) {
      setRecords([]);
      setTotal(0);
      return;
    }
    let live = true;
    setRecLoading(true);
    getJson(`/records?${qs({ table_id: tableId, q: qApplied, include_deleted: showDeleted, limit: PAGE, offset })}`)
      .then((d) => {
        if (!live) return;
        setRecords(d.records || []);
        setTotal(d.total || 0);
      })
      .catch((e) => live && setErr(`Couldn't load records: ${e?.message || e}`))
      .finally(() => live && setRecLoading(false));
    return () => {
      live = false;
    };
  }, [tableId, qApplied, showDeleted, offset]);

  useEffect(() => {
    if (!drawer) {
      setDetail(null);
      return;
    }
    let live = true;
    getJson(`/record?${qs(drawer)}`)
      .then((d) => live && setDetail(d))
      .catch((e) => live && setDetail({ error: String(e?.message || e) }));
    return () => {
      live = false;
    };
  }, [drawer]);

  async function doDownload(key: string, path: string, name: string) {
    setBusy(key);
    setNotice(null);
    try {
      await downloadFrom(path, name);
    } catch (e: any) {
      setNotice(`Download failed: ${e?.message || e}`);
    } finally {
      setBusy(null);
    }
  }

  // ── render ─────────────────────────────────────────────────────────────────
  const shell: React.CSSProperties = { color: C.fg, fontSize: 13, display: "flex", flexDirection: "column", gap: 14 };
  const panel: React.CSSProperties = { background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14 };

  if (loading) return <div style={{ ...shell, color: C.mutedFg, padding: 24 }}>Loading backup…</div>;
  if (err && !summary) return <div style={{ ...panel, color: "hsl(0 72% 51%)" }}>{err}</div>;

  const t = summary?.totals || {};
  const last = summary?.last_run;
  const neverRun = !last && !(bases || []).length;

  if (neverRun) {
    return (
      <div style={{ ...panel, lineHeight: 1.6 }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>No backup yet</div>
        <ol style={{ margin: 0, paddingLeft: 20, color: C.mutedFg }}>
          <li>Create a Personal Access Token at airtable.com/create/tokens with <code>data.records:read</code> and <code>schema.bases:read</code> (plus <code>data.recordComments:read</code> for comments), with access to the bases to back up.</li>
          <li>Open this plugin's <b>Settings</b> tab, paste the token, click <b>Test connection</b>.</li>
          <li>Click <b>Run sync</b>. The first backup appears here when it finishes.</li>
        </ol>
      </div>
    );
  }

  const kpis: [string, string, string?][] = [
    ["Bases", num(t.bases)],
    ["Tables", num(t.tables)],
    ["Records", num(t.records), t.deleted_records ? `${num(t.deleted_records)} deleted kept` : undefined],
    ["Attachments", num(t.attachments_stored), bytes(t.attachment_bytes)],
    ["Changes (7d)", num(t.changes_7d)],
    ["Last backup", summary?.last_success_at ? rel(summary.last_success_at) : "—",
      last ? `last run: ${last.status}` : undefined],
  ];
  const attWarn = (t.attachments_failed || 0) + (t.attachments_too_large || 0);
  const lastErrors: any[] = last?.stats?.errors || [];

  return (
    <div style={shell}>
      {/* KPIs */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
        {kpis.map(([label, value, sub]) => (
          <div key={label} style={panel}>
            <div style={{ fontSize: 11, color: C.mutedFg, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
            <div style={{ fontSize: 22, fontWeight: 600, marginTop: 2 }} title={label === "Last backup" ? abs(summary?.last_success_at) : undefined}>{value}</div>
            {sub && <div style={{ fontSize: 11, color: C.mutedFg, marginTop: 2 }}>{sub}</div>}
          </div>
        ))}
      </div>

      {(attWarn > 0 || lastErrors.length > 0 || last?.status === "running") && (
        <div style={{ ...panel, borderColor: "hsl(38 92% 50% / 0.5)", background: "hsl(38 92% 50% / 0.08)", fontSize: 12 }}>
          {last?.status === "running" && <div>A backup is running (started {rel(last.started_at)}).</div>}
          {attWarn > 0 && (
            <div>
              {num(t.attachments_failed)} attachment(s) failed to download and {num(t.attachments_too_large)} exceeded the size limit.
              Failed ones are retried on the next sync while Airtable still lists them.
            </div>
          )}
          {lastErrors.slice(0, 5).map((e, i) => (
            <div key={i} style={{ color: C.mutedFg }}>
              {e.base}{e.table ? ` / ${e.table}` : ""}: {e.error}
            </div>
          ))}
        </div>
      )}
      {t.attachments_not_downloaded > 0 && (
        <div style={{ fontSize: 12, color: C.mutedFg }}>
          {num(t.attachments_not_downloaded)} attachment(s) recorded without files ("Download attachment files" is off).
        </div>
      )}
      {notice && <div style={{ fontSize: 12, color: "hsl(0 72% 51%)" }}>{notice}</div>}

      {/* Browser */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(200px, 260px) 1fr", gap: 12, alignItems: "start" }}>
        <div style={{ ...panel, padding: 8, display: "flex", flexDirection: "column", gap: 2, maxHeight: 640, overflow: "auto" }}>
          <div style={{ fontSize: 11, color: C.mutedFg, textTransform: "uppercase", padding: "4px 8px" }}>Bases</div>
          {bases.map((b) => (
            <div key={b.base_id}>
              <button
                onClick={() => setBaseId(b.base_id)}
                style={{
                  width: "100%", textAlign: "left", padding: "6px 8px", borderRadius: 6, border: "none", cursor: "pointer",
                  background: b.base_id === baseId ? C.muted : "transparent", color: C.fg, fontSize: 13,
                  opacity: b.deleted_at ? 0.55 : 1,
                }}
                title={b.last_error || (b.deleted_at ? "No longer visible to the token" : b.base_id)}
              >
                <div style={{ fontWeight: b.base_id === baseId ? 600 : 400 }}>{b.name}{b.last_error ? " ⚠" : ""}</div>
                <div style={{ fontSize: 11, color: C.mutedFg }}>
                  {num(b.tables)} tables · {num(b.records)} records{b.deleted_at ? " · gone" : ""}
                </div>
              </button>
              {b.base_id === baseId && tables.map((tb) => (
                <button
                  key={tb.table_id}
                  onClick={() => { setTableId(tb.table_id); setOffset(0); }}
                  style={{
                    width: "100%", textAlign: "left", padding: "4px 8px 4px 20px", borderRadius: 6, border: "none",
                    cursor: "pointer", fontSize: 12, color: tb.table_id === tableId ? C.fg : C.mutedFg,
                    background: tb.table_id === tableId ? `hsl(var(--primary) / 0.12)` : "transparent",
                    opacity: tb.deleted_at ? 0.55 : 1,
                  }}
                  title={tb.last_error || undefined}
                >
                  {tb.name} <span style={{ color: C.mutedFg }}>({num(tb.records)})</span>{tb.last_error ? " ⚠" : ""}
                </button>
              ))}
            </div>
          ))}
        </div>

        <div style={{ ...panel, display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <div style={{ fontSize: 15, fontWeight: 600, marginRight: "auto" }}>
              {table ? table.name : "Select a table"}
              {table && <span style={{ fontWeight: 400, color: C.mutedFg, fontSize: 12 }}> · {num(total)} {showDeleted ? "records incl. deleted" : "records"}</span>}
            </div>
            {table && (
              <>
                <button style={btn} disabled={busy === "csv"}
                  onClick={() => doDownload("csv", `/export/table?${qs({ table_id: table.table_id, format: "csv", include_deleted: showDeleted })}`, `${table.name}.csv`)}>
                  {busy === "csv" ? "Exporting…" : "Export CSV"}
                </button>
                <button style={btn} disabled={busy === "json"}
                  onClick={() => doDownload("json", `/export/table?${qs({ table_id: table.table_id, format: "json", include_deleted: showDeleted })}`, `${table.name}.json`)}>
                  {busy === "json" ? "Exporting…" : "Export JSON"}
                </button>
              </>
            )}
            {baseId && (
              <button style={btn} disabled={busy === "base"}
                onClick={() => doDownload("base", `/export/base?${qs({ base_id: baseId })}`, "base.json")}>
                {busy === "base" ? "Exporting…" : "Export whole base (JSON)"}
              </button>
            )}
          </div>

          {table && (
            <form
              onSubmit={(e) => { e.preventDefault(); setOffset(0); setQApplied(q.trim()); }}
              style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}
            >
              <input style={{ ...input, flex: "1 1 220px" }} placeholder="Search any field or record ID…" value={q}
                onChange={(e) => setQ(e.target.value)} />
              <button type="submit" style={btn}>Search</button>
              {qApplied && <button type="button" style={btn} onClick={() => { setQ(""); setQApplied(""); setOffset(0); }}>Clear</button>}
              <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12, color: C.mutedFg }}>
                <input type="checkbox" checked={showDeleted} onChange={(e) => { setShowDeleted(e.target.checked); setOffset(0); }} />
                Include deleted
              </label>
            </form>
          )}

          {table && (
            <div style={{ overflowX: "auto", border: `1px solid ${C.border}`, borderRadius: 8 }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ background: C.muted }}>
                    {columns.map((f) => (
                      <th key={f.id} style={{ textAlign: "left", padding: "8px 10px", fontWeight: 600, whiteSpace: "nowrap", borderBottom: `1px solid ${C.border}` }}>
                        {f.name}
                      </th>
                    ))}
                    <th style={{ textAlign: "left", padding: "8px 10px", fontWeight: 600, borderBottom: `1px solid ${C.border}`, whiteSpace: "nowrap" }}>Changed</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((r) => (
                    <tr key={r.record_id}
                      onClick={() => setDrawer({ table_id: table.table_id, record_id: r.record_id })}
                      style={{ cursor: "pointer", borderBottom: `1px solid ${C.border}`, opacity: r.deleted_at ? 0.55 : 1 }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = C.muted)}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    >
                      {columns.map((f, i) => (
                        <td key={f.id} style={{ padding: "7px 10px", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: i === 0 ? 500 : 400 }}>
                          {i === 0 && r.deleted_at && <span style={{ ...pill(STATUS.deleted), marginRight: 6 }}>deleted</span>}
                          {cellText(r.fields?.[f.id]) || <span style={{ color: C.mutedFg }}>{i === 0 ? r.record_id : ""}</span>}
                        </td>
                      ))}
                      <td style={{ padding: "7px 10px", color: C.mutedFg, whiteSpace: "nowrap" }} title={abs(r.last_changed_at)}>{rel(r.last_changed_at)}</td>
                    </tr>
                  ))}
                  {!recLoading && records.length === 0 && (
                    <tr><td colSpan={columns.length + 1} style={{ padding: 18, textAlign: "center", color: C.mutedFg }}>
                      {qApplied ? "No records match." : "No records in this table."}
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
          {table && total > PAGE && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: C.mutedFg }}>
              <button style={btn} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Prev</button>
              <span>{num(offset + 1)}–{num(Math.min(offset + PAGE, total))} of {num(total)}</span>
              <button style={btn} disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next →</button>
            </div>
          )}
          {table && table.fields.length > columns.length && (
            <div style={{ fontSize: 11, color: C.mutedFg }}>Showing {columns.length} of {table.fields.length} fields. Open a record for all of them.</div>
          )}
        </div>
      </div>

      {/* Recent changes */}
      <div style={panel}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Recent changes</div>
        {changes.length === 0 ? (
          <div style={{ color: C.mutedFg, fontSize: 12 }}>
            No changes recorded yet. The first backup of each table is a baseline; later syncs record creates, edits and deletes.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {changes.map((c) => (
              <button key={c.id} onClick={() => setDrawer({ table_id: c.table_id, record_id: c.record_id })}
                style={{ display: "flex", gap: 10, alignItems: "center", padding: "6px 4px", border: "none", borderBottom: `1px solid ${C.border}`, background: "transparent", color: C.fg, cursor: "pointer", textAlign: "left", fontSize: 12 }}>
                <span style={{ ...pill(STATUS[c.change_type] || "220 9% 46%"), minWidth: 62, textAlign: "center" }}>{c.change_type}</span>
                <span style={{ fontWeight: 500, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 260 }}>{c.primary_value || c.record_id}</span>
                <span style={{ color: C.mutedFg, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                  {c.base_name} / {c.table_name}
                  {c.change_type === "updated" && c.changed_field_names?.length ? ` · ${c.changed_field_names.join(", ")}` : ""}
                </span>
                <span style={{ color: C.mutedFg, whiteSpace: "nowrap" }} title={abs(c.changed_at)}>{rel(c.changed_at)}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {drawer && (
        <RecordDrawer detail={detail} onClose={() => setDrawer(null)} busy={busy} onDownload={doDownload} />
      )}
    </div>
  );
}

// ── record drawer ────────────────────────────────────────────────────────────

function RecordDrawer({ detail, onClose, busy, onDownload }: {
  detail: any; onClose: () => void; busy: string | null;
  onDownload: (key: string, path: string, name: string) => void;
}) {
  const fields: Field[] = detail?.table?.fields || [];
  const names = useMemo(() => Object.fromEntries(fields.map((f) => [f.id, f.name])), [fields]);
  const rec = detail?.record;

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgb(0 0 0 / 0.35)", zIndex: 50, display: "flex", justifyContent: "flex-end" }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ width: "min(640px, 100%)", height: "100%", overflow: "auto", background: C.card, color: C.fg, borderLeft: `1px solid ${C.border}`, padding: 18, display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ fontSize: 16, fontWeight: 600, marginRight: "auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
            {rec ? (cellText(rec.fields?.[detail.table.primary_field_id]) || rec.record_id) : "Record"}
          </div>
          <button style={btn} onClick={onClose}>Close</button>
        </div>

        {!detail && <div style={{ color: C.mutedFg }}>Loading…</div>}
        {detail?.error && <div style={{ color: "hsl(0 72% 51%)" }}>{detail.error}</div>}

        {rec && (
          <>
            <div style={{ fontSize: 11, color: C.mutedFg, lineHeight: 1.6 }}>
              {detail.table.base_name} / {detail.table.name} · <code>{rec.record_id}</code><br />
              Created {abs(rec.created_time)} · backed up since {abs(rec.first_seen_at)}
              {rec.deleted_at && <><br /><span style={pill(STATUS.deleted)}>deleted in Airtable {rel(rec.deleted_at)}</span></>}
            </div>

            <Section title="Fields">
              {fields.map((f) => {
                const v = rec.fields?.[f.id];
                if (v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0)) return null;
                return (
                  <div key={f.id} style={{ display: "grid", gridTemplateColumns: "150px 1fr", gap: 10, padding: "6px 0", borderBottom: `1px solid ${C.border}` }}>
                    <div style={{ color: C.mutedFg, fontSize: 12 }} title={`${f.type} · ${f.id}`}>{f.name}</div>
                    <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 13 }}>{cellText(v)}</div>
                  </div>
                );
              })}
              {Object.keys(rec.fields || {}).filter((k) => !names[k]).map((k) => (
                <div key={k} style={{ display: "grid", gridTemplateColumns: "150px 1fr", gap: 10, padding: "6px 0", borderBottom: `1px solid ${C.border}` }}>
                  <div style={{ color: C.mutedFg, fontSize: 12 }} title="Field no longer in the table schema">{k} (removed)</div>
                  <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{cellText(rec.fields[k])}</div>
                </div>
              ))}
            </Section>

            {detail.attachments?.length > 0 && (
              <Section title={`Attachments (${detail.attachments.length})`}>
                {detail.attachments.map((a: any) => (
                  <div key={a.attachment_id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "5px 0", borderBottom: `1px solid ${C.border}`, fontSize: 12 }}>
                    <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={a.filename}>{a.filename}</span>
                    <span style={{ color: C.mutedFg }}>{a.size_bytes != null ? bytes(a.size_bytes) : ""}</span>
                    {a.status === "stored" ? (
                      <button style={btn} disabled={busy === a.attachment_id}
                        onClick={() => onDownload(a.attachment_id, `/attachments/${encodeURIComponent(a.attachment_id)}`, a.filename || a.attachment_id)}>
                        {busy === a.attachment_id ? "…" : "Download"}
                      </button>
                    ) : (
                      <span style={pill(a.status === "failed" ? STATUS.deleted : "220 9% 46%")} title={a.error || undefined}>{a.status.replace("_", " ")}</span>
                    )}
                  </div>
                ))}
              </Section>
            )}

            <Section title="History">
              {(detail.changes || []).length === 0 ? (
                <div style={{ color: C.mutedFg, fontSize: 12 }}>No changes since the baseline backup.</div>
              ) : (detail.changes || []).map((c: any) => (
                <div key={c.id} style={{ padding: "6px 0", borderBottom: `1px solid ${C.border}`, fontSize: 12 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span style={pill(STATUS[c.change_type] || "220 9% 46%")}>{c.change_type}</span>
                    <span style={{ color: C.mutedFg }} title={abs(c.changed_at)}>{rel(c.changed_at)}</span>
                  </div>
                  {c.previous_fields && Object.keys(c.previous_fields).length > 0 && (
                    <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 2 }}>
                      {Object.entries(c.previous_fields).map(([fid, v]) => (
                        <div key={fid} style={{ color: C.mutedFg, wordBreak: "break-word" }}>
                          <b style={{ color: C.fg, fontWeight: 500 }}>{names[fid] || fid}</b> was: {cellText(v) || <i>empty</i>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </Section>

            {detail.comments?.length > 0 && (
              <Section title={`Comments (${detail.comments.length})`}>
                {detail.comments.map((c: any) => (
                  <div key={c.comment_id} style={{ padding: "6px 0", borderBottom: `1px solid ${C.border}`, fontSize: 12, paddingLeft: c.parent_comment_id ? 16 : 0, opacity: c.deleted_at ? 0.55 : 1 }}>
                    <div style={{ color: C.mutedFg }}>
                      <b style={{ color: C.fg, fontWeight: 500 }}>{c.author?.name || c.author?.email || "Someone"}</b> · {abs(c.created_time)}{c.deleted_at ? " · deleted" : ""}
                    </div>
                    <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", marginTop: 2 }}>{c.text}</div>
                  </div>
                ))}
              </Section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: C.mutedFg, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>{title}</div>
      {children}
    </div>
  );
}
