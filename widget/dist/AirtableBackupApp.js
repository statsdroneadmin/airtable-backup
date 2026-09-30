// AirtableBackupApp.tsx
import { useCallback, useEffect, useMemo, useState } from "/api/widget-runtime/react.js";
import { Fragment, jsx, jsxs } from "/api/widget-runtime/react-jsx-runtime.js";
var SLUG = "airtable-backup";
var api = (path) => window.NousViz.widgets.apiFetch(`/api/plugins/${SLUG}${path}`);
var qs = (o) => Object.entries(o).filter(([, v]) => v !== void 0 && v !== null && v !== "").map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");
var C = {
  card: "hsl(var(--card))",
  bg: "hsl(var(--background))",
  fg: "hsl(var(--foreground))",
  muted: "hsl(var(--muted))",
  mutedFg: "hsl(var(--muted-foreground))",
  border: "hsl(var(--border))",
  primary: "hsl(var(--primary))",
  primaryFg: "hsl(var(--primary-foreground))"
};
var STATUS = {
  created: "142 71% 38%",
  updated: "217 91% 55%",
  deleted: "0 72% 51%",
  restored: "38 92% 50%"
};
var pill = (hsl) => ({
  display: "inline-block",
  padding: "1px 8px",
  borderRadius: 999,
  fontSize: 11,
  fontWeight: 600,
  color: `hsl(${hsl})`,
  background: `hsl(${hsl} / 0.12)`,
  border: `1px solid hsl(${hsl} / 0.3)`
});
var btn = {
  padding: "5px 10px",
  borderRadius: 6,
  border: `1px solid ${C.border}`,
  background: C.card,
  color: C.fg,
  fontSize: 12,
  cursor: "pointer",
  whiteSpace: "nowrap"
};
var input = {
  padding: "6px 10px",
  borderRadius: 6,
  border: `1px solid ${C.border}`,
  background: C.bg,
  color: C.fg,
  fontSize: 13,
  colorScheme: "light dark",
  minWidth: 0
};
var num = (n) => window.NousViz.widgets.formatNumber(Number(n ?? 0));
var bytes = (n) => window.NousViz.widgets.formatBytes(Number(n ?? 0));
var rel = (iso) => window.NousViz.widgets.formatRelativeTime(iso ?? null);
var abs = (iso) => window.NousViz.widgets.formatAbsoluteTime(iso ?? null);
function isAttachment(v) {
  return v && typeof v === "object" && typeof v.id === "string" && v.id.startsWith("att") && "filename" in v;
}
function cellText(v) {
  if (v === null || v === void 0) return "";
  if (typeof v === "boolean") return v ? "\u2713" : "";
  if (typeof v === "number" || typeof v === "string") return String(v);
  if (Array.isArray(v)) return v.map(cellText).filter(Boolean).join(", ");
  if (typeof v === "object") {
    if (isAttachment(v)) return v.filename || v.id;
    if ("email" in v) return v.name || v.email;
    if ("label" in v && "url" in v) return v.label || v.url;
    if (typeof v.value === "string" || typeof v.value === "number") return String(v.value);
    if (typeof v.text === "string") return v.text;
    if (v.specialValue !== void 0) return String(v.specialValue);
    if (v.error) return `#ERROR ${v.error}`;
    return JSON.stringify(v);
  }
  return String(v);
}
async function downloadFrom(path, fallback) {
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
  setTimeout(() => URL.revokeObjectURL(url), 1e4);
}
async function getJson(path) {
  const r = await api(path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
var PAGE = 50;
function AirtableBackupApp(_) {
  const [summary, setSummary] = useState(null);
  const [bases, setBases] = useState([]);
  const [baseId, setBaseId] = useState(null);
  const [tables, setTables] = useState([]);
  const [tableId, setTableId] = useState(null);
  const [records, setRecords] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [qApplied, setQApplied] = useState("");
  const [showDeleted, setShowDeleted] = useState(false);
  const [changes, setChanges] = useState([]);
  const [drawer, setDrawer] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [recLoading, setRecLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(null);
  const table = useMemo(() => tables.find((t2) => t2.table_id === tableId) || null, [tables, tableId]);
  const columns = useMemo(() => {
    if (!table) return [];
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
      setBaseId((cur) => cur ?? (b.bases || []).find((x) => !x.deleted_at)?.base_id ?? null);
    } catch (e) {
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
    getJson(`/tables?${qs({ base_id: baseId })}`).then((d) => {
      if (!live) return;
      const ts = d.tables || [];
      setTables(ts);
      setTableId(ts.find((t2) => !t2.deleted_at)?.table_id ?? ts[0]?.table_id ?? null);
      setOffset(0);
    }).catch((e) => live && setErr(`Couldn't load tables: ${e?.message || e}`));
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
    getJson(`/records?${qs({ table_id: tableId, q: qApplied, include_deleted: showDeleted, limit: PAGE, offset })}`).then((d) => {
      if (!live) return;
      setRecords(d.records || []);
      setTotal(d.total || 0);
    }).catch((e) => live && setErr(`Couldn't load records: ${e?.message || e}`)).finally(() => live && setRecLoading(false));
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
    getJson(`/record?${qs(drawer)}`).then((d) => live && setDetail(d)).catch((e) => live && setDetail({ error: String(e?.message || e) }));
    return () => {
      live = false;
    };
  }, [drawer]);
  async function doDownload(key, path, name) {
    setBusy(key);
    setNotice(null);
    try {
      await downloadFrom(path, name);
    } catch (e) {
      setNotice(`Download failed: ${e?.message || e}`);
    } finally {
      setBusy(null);
    }
  }
  const shell = { color: C.fg, fontSize: 13, display: "flex", flexDirection: "column", gap: 14 };
  const panel = { background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14 };
  if (loading) return /* @__PURE__ */ jsx("div", { style: { ...shell, color: C.mutedFg, padding: 24 }, children: "Loading backup\u2026" });
  if (err && !summary) return /* @__PURE__ */ jsx("div", { style: { ...panel, color: "hsl(0 72% 51%)" }, children: err });
  const t = summary?.totals || {};
  const last = summary?.last_run;
  const neverRun = !last && !(bases || []).length;
  if (neverRun) {
    return /* @__PURE__ */ jsxs("div", { style: { ...panel, lineHeight: 1.6 }, children: [
      /* @__PURE__ */ jsx("div", { style: { fontSize: 16, fontWeight: 600, marginBottom: 6 }, children: "No backup yet" }),
      /* @__PURE__ */ jsxs("ol", { style: { margin: 0, paddingLeft: 20, color: C.mutedFg }, children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Create a Personal Access Token at airtable.com/create/tokens with ",
          /* @__PURE__ */ jsx("code", { children: "data.records:read" }),
          " and ",
          /* @__PURE__ */ jsx("code", { children: "schema.bases:read" }),
          " (plus ",
          /* @__PURE__ */ jsx("code", { children: "data.recordComments:read" }),
          " for comments), with access to the bases to back up."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Open this plugin's ",
          /* @__PURE__ */ jsx("b", { children: "Settings" }),
          " tab, paste the token, click ",
          /* @__PURE__ */ jsx("b", { children: "Test connection" }),
          "."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Click ",
          /* @__PURE__ */ jsx("b", { children: "Run sync" }),
          ". The first backup appears here when it finishes."
        ] })
      ] })
    ] });
  }
  const kpis = [
    ["Bases", num(t.bases)],
    ["Tables", num(t.tables)],
    ["Records", num(t.records), t.deleted_records ? `${num(t.deleted_records)} deleted kept` : void 0],
    ["Attachments", num(t.attachments_stored), bytes(t.attachment_bytes)],
    ["Changes (7d)", num(t.changes_7d)],
    [
      "Last backup",
      summary?.last_success_at ? rel(summary.last_success_at) : "\u2014",
      last ? `last run: ${last.status}` : void 0
    ]
  ];
  const attWarn = (t.attachments_failed || 0) + (t.attachments_too_large || 0);
  const lastErrors = last?.stats?.errors || [];
  return /* @__PURE__ */ jsxs("div", { style: shell, children: [
    /* @__PURE__ */ jsx("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }, children: kpis.map(([label, value, sub]) => /* @__PURE__ */ jsxs("div", { style: panel, children: [
      /* @__PURE__ */ jsx("div", { style: { fontSize: 11, color: C.mutedFg, textTransform: "uppercase", letterSpacing: 0.4 }, children: label }),
      /* @__PURE__ */ jsx("div", { style: { fontSize: 22, fontWeight: 600, marginTop: 2 }, title: label === "Last backup" ? abs(summary?.last_success_at) : void 0, children: value }),
      sub && /* @__PURE__ */ jsx("div", { style: { fontSize: 11, color: C.mutedFg, marginTop: 2 }, children: sub })
    ] }, label)) }),
    (attWarn > 0 || lastErrors.length > 0 || last?.status === "running") && /* @__PURE__ */ jsxs("div", { style: { ...panel, borderColor: "hsl(38 92% 50% / 0.5)", background: "hsl(38 92% 50% / 0.08)", fontSize: 12 }, children: [
      last?.status === "running" && /* @__PURE__ */ jsxs("div", { children: [
        "A backup is running (started ",
        rel(last.started_at),
        ")."
      ] }),
      attWarn > 0 && /* @__PURE__ */ jsxs("div", { children: [
        num(t.attachments_failed),
        " attachment(s) failed to download and ",
        num(t.attachments_too_large),
        " exceeded the size limit. Failed ones are retried on the next sync while Airtable still lists them."
      ] }),
      lastErrors.slice(0, 5).map((e, i) => /* @__PURE__ */ jsxs("div", { style: { color: C.mutedFg }, children: [
        e.base,
        e.table ? ` / ${e.table}` : "",
        ": ",
        e.error
      ] }, i))
    ] }),
    t.attachments_not_downloaded > 0 && /* @__PURE__ */ jsxs("div", { style: { fontSize: 12, color: C.mutedFg }, children: [
      num(t.attachments_not_downloaded),
      ' attachment(s) recorded without files ("Download attachment files" is off).'
    ] }),
    notice && /* @__PURE__ */ jsx("div", { style: { fontSize: 12, color: "hsl(0 72% 51%)" }, children: notice }),
    /* @__PURE__ */ jsxs("div", { style: { display: "grid", gridTemplateColumns: "minmax(200px, 260px) 1fr", gap: 12, alignItems: "start" }, children: [
      /* @__PURE__ */ jsxs("div", { style: { ...panel, padding: 8, display: "flex", flexDirection: "column", gap: 2, maxHeight: 640, overflow: "auto" }, children: [
        /* @__PURE__ */ jsx("div", { style: { fontSize: 11, color: C.mutedFg, textTransform: "uppercase", padding: "4px 8px" }, children: "Bases" }),
        bases.map((b) => /* @__PURE__ */ jsxs("div", { children: [
          /* @__PURE__ */ jsxs(
            "button",
            {
              onClick: () => setBaseId(b.base_id),
              style: {
                width: "100%",
                textAlign: "left",
                padding: "6px 8px",
                borderRadius: 6,
                border: "none",
                cursor: "pointer",
                background: b.base_id === baseId ? C.muted : "transparent",
                color: C.fg,
                fontSize: 13,
                opacity: b.deleted_at ? 0.55 : 1
              },
              title: b.last_error || (b.deleted_at ? "No longer visible to the token" : b.base_id),
              children: [
                /* @__PURE__ */ jsxs("div", { style: { fontWeight: b.base_id === baseId ? 600 : 400 }, children: [
                  b.name,
                  b.last_error ? " \u26A0" : ""
                ] }),
                /* @__PURE__ */ jsxs("div", { style: { fontSize: 11, color: C.mutedFg }, children: [
                  num(b.tables),
                  " tables \xB7 ",
                  num(b.records),
                  " records",
                  b.deleted_at ? " \xB7 gone" : ""
                ] })
              ]
            }
          ),
          b.base_id === baseId && tables.map((tb) => /* @__PURE__ */ jsxs(
            "button",
            {
              onClick: () => {
                setTableId(tb.table_id);
                setOffset(0);
              },
              style: {
                width: "100%",
                textAlign: "left",
                padding: "4px 8px 4px 20px",
                borderRadius: 6,
                border: "none",
                cursor: "pointer",
                fontSize: 12,
                color: tb.table_id === tableId ? C.fg : C.mutedFg,
                background: tb.table_id === tableId ? `hsl(var(--primary) / 0.12)` : "transparent",
                opacity: tb.deleted_at ? 0.55 : 1
              },
              title: tb.last_error || void 0,
              children: [
                tb.name,
                " ",
                /* @__PURE__ */ jsxs("span", { style: { color: C.mutedFg }, children: [
                  "(",
                  num(tb.records),
                  ")"
                ] }),
                tb.last_error ? " \u26A0" : ""
              ]
            },
            tb.table_id
          ))
        ] }, b.base_id))
      ] }),
      /* @__PURE__ */ jsxs("div", { style: { ...panel, display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }, children: [
        /* @__PURE__ */ jsxs("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }, children: [
          /* @__PURE__ */ jsxs("div", { style: { fontSize: 15, fontWeight: 600, marginRight: "auto" }, children: [
            table ? table.name : "Select a table",
            table && /* @__PURE__ */ jsxs("span", { style: { fontWeight: 400, color: C.mutedFg, fontSize: 12 }, children: [
              " \xB7 ",
              num(total),
              " ",
              showDeleted ? "records incl. deleted" : "records"
            ] })
          ] }),
          table && /* @__PURE__ */ jsxs(Fragment, { children: [
            /* @__PURE__ */ jsx(
              "button",
              {
                style: btn,
                disabled: busy === "csv",
                onClick: () => doDownload("csv", `/export/table?${qs({ table_id: table.table_id, format: "csv", include_deleted: showDeleted })}`, `${table.name}.csv`),
                children: busy === "csv" ? "Exporting\u2026" : "Export CSV"
              }
            ),
            /* @__PURE__ */ jsx(
              "button",
              {
                style: btn,
                disabled: busy === "json",
                onClick: () => doDownload("json", `/export/table?${qs({ table_id: table.table_id, format: "json", include_deleted: showDeleted })}`, `${table.name}.json`),
                children: busy === "json" ? "Exporting\u2026" : "Export JSON"
              }
            )
          ] }),
          baseId && /* @__PURE__ */ jsx(
            "button",
            {
              style: btn,
              disabled: busy === "base",
              onClick: () => doDownload("base", `/export/base?${qs({ base_id: baseId })}`, "base.json"),
              children: busy === "base" ? "Exporting\u2026" : "Export whole base (JSON)"
            }
          )
        ] }),
        table && /* @__PURE__ */ jsxs(
          "form",
          {
            onSubmit: (e) => {
              e.preventDefault();
              setOffset(0);
              setQApplied(q.trim());
            },
            style: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" },
            children: [
              /* @__PURE__ */ jsx(
                "input",
                {
                  style: { ...input, flex: "1 1 220px" },
                  placeholder: "Search any field or record ID\u2026",
                  value: q,
                  onChange: (e) => setQ(e.target.value)
                }
              ),
              /* @__PURE__ */ jsx("button", { type: "submit", style: btn, children: "Search" }),
              qApplied && /* @__PURE__ */ jsx("button", { type: "button", style: btn, onClick: () => {
                setQ("");
                setQApplied("");
                setOffset(0);
              }, children: "Clear" }),
              /* @__PURE__ */ jsxs("label", { style: { display: "flex", gap: 6, alignItems: "center", fontSize: 12, color: C.mutedFg }, children: [
                /* @__PURE__ */ jsx("input", { type: "checkbox", checked: showDeleted, onChange: (e) => {
                  setShowDeleted(e.target.checked);
                  setOffset(0);
                } }),
                "Include deleted"
              ] })
            ]
          }
        ),
        table && /* @__PURE__ */ jsx("div", { style: { overflowX: "auto", border: `1px solid ${C.border}`, borderRadius: 8 }, children: /* @__PURE__ */ jsxs("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 12 }, children: [
          /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { style: { background: C.muted }, children: [
            columns.map((f) => /* @__PURE__ */ jsx("th", { style: { textAlign: "left", padding: "8px 10px", fontWeight: 600, whiteSpace: "nowrap", borderBottom: `1px solid ${C.border}` }, children: f.name }, f.id)),
            /* @__PURE__ */ jsx("th", { style: { textAlign: "left", padding: "8px 10px", fontWeight: 600, borderBottom: `1px solid ${C.border}`, whiteSpace: "nowrap" }, children: "Changed" })
          ] }) }),
          /* @__PURE__ */ jsxs("tbody", { children: [
            records.map((r) => /* @__PURE__ */ jsxs(
              "tr",
              {
                onClick: () => setDrawer({ table_id: table.table_id, record_id: r.record_id }),
                style: { cursor: "pointer", borderBottom: `1px solid ${C.border}`, opacity: r.deleted_at ? 0.55 : 1 },
                onMouseEnter: (e) => e.currentTarget.style.background = C.muted,
                onMouseLeave: (e) => e.currentTarget.style.background = "transparent",
                children: [
                  columns.map((f, i) => /* @__PURE__ */ jsxs("td", { style: { padding: "7px 10px", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: i === 0 ? 500 : 400 }, children: [
                    i === 0 && r.deleted_at && /* @__PURE__ */ jsx("span", { style: { ...pill(STATUS.deleted), marginRight: 6 }, children: "deleted" }),
                    cellText(r.fields?.[f.id]) || /* @__PURE__ */ jsx("span", { style: { color: C.mutedFg }, children: i === 0 ? r.record_id : "" })
                  ] }, f.id)),
                  /* @__PURE__ */ jsx("td", { style: { padding: "7px 10px", color: C.mutedFg, whiteSpace: "nowrap" }, title: abs(r.last_changed_at), children: rel(r.last_changed_at) })
                ]
              },
              r.record_id
            )),
            !recLoading && records.length === 0 && /* @__PURE__ */ jsx("tr", { children: /* @__PURE__ */ jsx("td", { colSpan: columns.length + 1, style: { padding: 18, textAlign: "center", color: C.mutedFg }, children: qApplied ? "No records match." : "No records in this table." }) })
          ] })
        ] }) }),
        table && total > PAGE && /* @__PURE__ */ jsxs("div", { style: { display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: C.mutedFg }, children: [
          /* @__PURE__ */ jsx("button", { style: btn, disabled: offset === 0, onClick: () => setOffset(Math.max(0, offset - PAGE)), children: "\u2190 Prev" }),
          /* @__PURE__ */ jsxs("span", { children: [
            num(offset + 1),
            "\u2013",
            num(Math.min(offset + PAGE, total)),
            " of ",
            num(total)
          ] }),
          /* @__PURE__ */ jsx("button", { style: btn, disabled: offset + PAGE >= total, onClick: () => setOffset(offset + PAGE), children: "Next \u2192" })
        ] }),
        table && table.fields.length > columns.length && /* @__PURE__ */ jsxs("div", { style: { fontSize: 11, color: C.mutedFg }, children: [
          "Showing ",
          columns.length,
          " of ",
          table.fields.length,
          " fields. Open a record for all of them."
        ] })
      ] })
    ] }),
    /* @__PURE__ */ jsxs("div", { style: panel, children: [
      /* @__PURE__ */ jsx("div", { style: { fontSize: 15, fontWeight: 600, marginBottom: 8 }, children: "Recent changes" }),
      changes.length === 0 ? /* @__PURE__ */ jsx("div", { style: { color: C.mutedFg, fontSize: 12 }, children: "No changes recorded yet. The first backup of each table is a baseline; later syncs record creates, edits and deletes." }) : /* @__PURE__ */ jsx("div", { style: { display: "flex", flexDirection: "column" }, children: changes.map((c) => /* @__PURE__ */ jsxs(
        "button",
        {
          onClick: () => setDrawer({ table_id: c.table_id, record_id: c.record_id }),
          style: { display: "flex", gap: 10, alignItems: "center", padding: "6px 4px", border: "none", borderBottom: `1px solid ${C.border}`, background: "transparent", color: C.fg, cursor: "pointer", textAlign: "left", fontSize: 12 },
          children: [
            /* @__PURE__ */ jsx("span", { style: { ...pill(STATUS[c.change_type] || "220 9% 46%"), minWidth: 62, textAlign: "center" }, children: c.change_type }),
            /* @__PURE__ */ jsx("span", { style: { fontWeight: 500, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 260 }, children: c.primary_value || c.record_id }),
            /* @__PURE__ */ jsxs("span", { style: { color: C.mutedFg, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }, children: [
              c.base_name,
              " / ",
              c.table_name,
              c.change_type === "updated" && c.changed_field_names?.length ? ` \xB7 ${c.changed_field_names.join(", ")}` : ""
            ] }),
            /* @__PURE__ */ jsx("span", { style: { color: C.mutedFg, whiteSpace: "nowrap" }, title: abs(c.changed_at), children: rel(c.changed_at) })
          ]
        },
        c.id
      )) })
    ] }),
    drawer && /* @__PURE__ */ jsx(RecordDrawer, { detail, onClose: () => setDrawer(null), busy, onDownload: doDownload })
  ] });
}
function RecordDrawer({ detail, onClose, busy, onDownload }) {
  const fields = detail?.table?.fields || [];
  const names = useMemo(() => Object.fromEntries(fields.map((f) => [f.id, f.name])), [fields]);
  const rec = detail?.record;
  return /* @__PURE__ */ jsx("div", { onClick: onClose, style: { position: "fixed", inset: 0, background: "rgb(0 0 0 / 0.35)", zIndex: 50, display: "flex", justifyContent: "flex-end" }, children: /* @__PURE__ */ jsxs(
    "div",
    {
      onClick: (e) => e.stopPropagation(),
      style: { width: "min(640px, 100%)", height: "100%", overflow: "auto", background: C.card, color: C.fg, borderLeft: `1px solid ${C.border}`, padding: 18, display: "flex", flexDirection: "column", gap: 16 },
      children: [
        /* @__PURE__ */ jsxs("div", { style: { display: "flex", alignItems: "center", gap: 8 }, children: [
          /* @__PURE__ */ jsx("div", { style: { fontSize: 16, fontWeight: 600, marginRight: "auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }, children: rec ? cellText(rec.fields?.[detail.table.primary_field_id]) || rec.record_id : "Record" }),
          /* @__PURE__ */ jsx("button", { style: btn, onClick: onClose, children: "Close" })
        ] }),
        !detail && /* @__PURE__ */ jsx("div", { style: { color: C.mutedFg }, children: "Loading\u2026" }),
        detail?.error && /* @__PURE__ */ jsx("div", { style: { color: "hsl(0 72% 51%)" }, children: detail.error }),
        rec && /* @__PURE__ */ jsxs(Fragment, { children: [
          /* @__PURE__ */ jsxs("div", { style: { fontSize: 11, color: C.mutedFg, lineHeight: 1.6 }, children: [
            detail.table.base_name,
            " / ",
            detail.table.name,
            " \xB7 ",
            /* @__PURE__ */ jsx("code", { children: rec.record_id }),
            /* @__PURE__ */ jsx("br", {}),
            "Created ",
            abs(rec.created_time),
            " \xB7 backed up since ",
            abs(rec.first_seen_at),
            rec.deleted_at && /* @__PURE__ */ jsxs(Fragment, { children: [
              /* @__PURE__ */ jsx("br", {}),
              /* @__PURE__ */ jsxs("span", { style: pill(STATUS.deleted), children: [
                "deleted in Airtable ",
                rel(rec.deleted_at)
              ] })
            ] })
          ] }),
          /* @__PURE__ */ jsxs(Section, { title: "Fields", children: [
            fields.map((f) => {
              const v = rec.fields?.[f.id];
              if (v === void 0 || v === null || v === "" || Array.isArray(v) && v.length === 0) return null;
              return /* @__PURE__ */ jsxs("div", { style: { display: "grid", gridTemplateColumns: "150px 1fr", gap: 10, padding: "6px 0", borderBottom: `1px solid ${C.border}` }, children: [
                /* @__PURE__ */ jsx("div", { style: { color: C.mutedFg, fontSize: 12 }, title: `${f.type} \xB7 ${f.id}`, children: f.name }),
                /* @__PURE__ */ jsx("div", { style: { whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 13 }, children: cellText(v) })
              ] }, f.id);
            }),
            Object.keys(rec.fields || {}).filter((k) => !names[k]).map((k) => /* @__PURE__ */ jsxs("div", { style: { display: "grid", gridTemplateColumns: "150px 1fr", gap: 10, padding: "6px 0", borderBottom: `1px solid ${C.border}` }, children: [
              /* @__PURE__ */ jsxs("div", { style: { color: C.mutedFg, fontSize: 12 }, title: "Field no longer in the table schema", children: [
                k,
                " (removed)"
              ] }),
              /* @__PURE__ */ jsx("div", { style: { whiteSpace: "pre-wrap", wordBreak: "break-word" }, children: cellText(rec.fields[k]) })
            ] }, k))
          ] }),
          detail.attachments?.length > 0 && /* @__PURE__ */ jsx(Section, { title: `Attachments (${detail.attachments.length})`, children: detail.attachments.map((a) => /* @__PURE__ */ jsxs("div", { style: { display: "flex", gap: 10, alignItems: "center", padding: "5px 0", borderBottom: `1px solid ${C.border}`, fontSize: 12 }, children: [
            /* @__PURE__ */ jsx("span", { style: { flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, title: a.filename, children: a.filename }),
            /* @__PURE__ */ jsx("span", { style: { color: C.mutedFg }, children: a.size_bytes != null ? bytes(a.size_bytes) : "" }),
            a.status === "stored" ? /* @__PURE__ */ jsx(
              "button",
              {
                style: btn,
                disabled: busy === a.attachment_id,
                onClick: () => onDownload(a.attachment_id, `/attachments/${encodeURIComponent(a.attachment_id)}`, a.filename || a.attachment_id),
                children: busy === a.attachment_id ? "\u2026" : "Download"
              }
            ) : /* @__PURE__ */ jsx("span", { style: pill(a.status === "failed" ? STATUS.deleted : "220 9% 46%"), title: a.error || void 0, children: a.status.replace("_", " ") })
          ] }, a.attachment_id)) }),
          /* @__PURE__ */ jsx(Section, { title: "History", children: (detail.changes || []).length === 0 ? /* @__PURE__ */ jsx("div", { style: { color: C.mutedFg, fontSize: 12 }, children: "No changes since the baseline backup." }) : (detail.changes || []).map((c) => /* @__PURE__ */ jsxs("div", { style: { padding: "6px 0", borderBottom: `1px solid ${C.border}`, fontSize: 12 }, children: [
            /* @__PURE__ */ jsxs("div", { style: { display: "flex", gap: 8, alignItems: "center" }, children: [
              /* @__PURE__ */ jsx("span", { style: pill(STATUS[c.change_type] || "220 9% 46%"), children: c.change_type }),
              /* @__PURE__ */ jsx("span", { style: { color: C.mutedFg }, title: abs(c.changed_at), children: rel(c.changed_at) })
            ] }),
            c.previous_fields && Object.keys(c.previous_fields).length > 0 && /* @__PURE__ */ jsx("div", { style: { marginTop: 4, display: "flex", flexDirection: "column", gap: 2 }, children: Object.entries(c.previous_fields).map(([fid, v]) => /* @__PURE__ */ jsxs("div", { style: { color: C.mutedFg, wordBreak: "break-word" }, children: [
              /* @__PURE__ */ jsx("b", { style: { color: C.fg, fontWeight: 500 }, children: names[fid] || fid }),
              " was: ",
              cellText(v) || /* @__PURE__ */ jsx("i", { children: "empty" })
            ] }, fid)) })
          ] }, c.id)) }),
          detail.comments?.length > 0 && /* @__PURE__ */ jsx(Section, { title: `Comments (${detail.comments.length})`, children: detail.comments.map((c) => /* @__PURE__ */ jsxs("div", { style: { padding: "6px 0", borderBottom: `1px solid ${C.border}`, fontSize: 12, paddingLeft: c.parent_comment_id ? 16 : 0, opacity: c.deleted_at ? 0.55 : 1 }, children: [
            /* @__PURE__ */ jsxs("div", { style: { color: C.mutedFg }, children: [
              /* @__PURE__ */ jsx("b", { style: { color: C.fg, fontWeight: 500 }, children: c.author?.name || c.author?.email || "Someone" }),
              " \xB7 ",
              abs(c.created_time),
              c.deleted_at ? " \xB7 deleted" : ""
            ] }),
            /* @__PURE__ */ jsx("div", { style: { whiteSpace: "pre-wrap", wordBreak: "break-word", marginTop: 2 }, children: c.text })
          ] }, c.comment_id)) })
        ] })
      ]
    }
  ) });
}
function Section({ title, children }) {
  return /* @__PURE__ */ jsxs("div", { children: [
    /* @__PURE__ */ jsx("div", { style: { fontSize: 11, color: C.mutedFg, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }, children: title }),
    children
  ] });
}
export {
  AirtableBackupApp as default
};
