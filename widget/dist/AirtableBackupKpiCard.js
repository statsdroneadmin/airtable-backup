// AirtableBackupKpiCard.tsx
import { useEffect, useState } from "/api/widget-runtime/react.js";
import { jsx, jsxs } from "/api/widget-runtime/react-jsx-runtime.js";
var COLOR_CLASSES = {
  green: "text-green-400",
  red: "text-red-400",
  blue: "text-blue-400",
  purple: "text-purple-400",
  amber: "text-amber-400",
  neutral: "text-foreground"
};
function readPath(payload, path) {
  if (payload === null || typeof payload !== "object") return null;
  let cursor = payload;
  for (const key of path.split(".")) {
    if (cursor === null || typeof cursor !== "object") return null;
    cursor = cursor[key];
  }
  if (typeof cursor === "number" && Number.isFinite(cursor)) return cursor;
  if (typeof cursor === "string") {
    const n = Number(cursor);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}
function AirtableBackupKpiCard(props) {
  const config = props.config;
  const {
    label,
    endpoint,
    value_path = "value",
    color = "neutral",
    sublabel
  } = config;
  const [value, setValue] = useState(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let cancelled = false;
    if (!endpoint) {
      setLoaded(true);
      return;
    }
    window.NousViz.widgets.apiFetch(endpoint).then((r) => r.ok ? r.json() : null).then((data) => {
      if (cancelled) return;
      setValue(readPath(data, value_path));
      setLoaded(true);
    }).catch(() => {
      if (cancelled) return;
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [endpoint, value_path]);
  const colorClass = COLOR_CLASSES[color] ?? COLOR_CLASSES.neutral;
  const fmt = window.NousViz.widgets.formatNumber;
  const cn = window.NousViz.widgets.cn;
  return /* @__PURE__ */ jsxs("div", { className: "bg-card border border-border rounded-lg p-4 flex flex-col gap-1", children: [
    /* @__PURE__ */ jsx("div", { className: "text-xs font-medium uppercase tracking-wider text-muted-foreground", children: label }),
    /* @__PURE__ */ jsx("div", { className: cn("text-3xl font-display font-semibold tabular-nums", colorClass), children: loaded ? value === null ? "\u2014" : fmt(value) : "\u2026" }),
    sublabel && /* @__PURE__ */ jsx("div", { className: "text-xs text-muted-foreground", children: sublabel })
  ] });
}
export {
  AirtableBackupKpiCard as default
};
