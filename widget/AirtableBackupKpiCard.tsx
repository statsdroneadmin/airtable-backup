/// <reference path="./nousviz_widget_types.d.ts" />
/**
 * AirtableBackupKpiCard — minimal plugin-shipped React widget.
 *
 * Demonstrates:
 *   - The CustomWidgetProps contract (pluginId, dashboardName, config)
 *   - Reading data via window.NousViz.widgets.apiFetch from a configurable
 *     endpoint, with cancellation on unmount
 *   - Tailwind tokens that match NousViz's design system (bg-card,
 *     border-border, text-foreground, font-display, ...)
 *   - Optional colour variants (green / red / blue / purple / amber / neutral)
 *
 * Dashboard YAML usage:
 *
 *   - id: my_kpi
 *     type: custom
 *     component: AirtableBackupKpiCard
 *     config:
 *       label: "Average score"
 *       endpoint: "/api/plugins/airtable-backup/overview"
 *       value_path: "stats.avg_score"   # dotted path into response JSON
 *       color: blue                      # optional
 *       sublabel: "0–100 scale"          # optional
 *
 * Reference: docs/05-widgets-custom-react.md
 */

import { useEffect, useState } from "react";

type Color = "green" | "red" | "blue" | "purple" | "amber" | "neutral";

const COLOR_CLASSES: Record<Color, string> = {
  green:   "text-green-400",
  red:     "text-red-400",
  blue:    "text-blue-400",
  purple:  "text-purple-400",
  amber:   "text-amber-400",
  neutral: "text-foreground",
};

interface Config {
  label: string;
  endpoint: string;
  value_path?: string;       // default: "value"
  color?: Color;
  sublabel?: string;
}

function readPath(payload: unknown, path: string): number | null {
  if (payload === null || typeof payload !== "object") return null;
  let cursor: unknown = payload;
  for (const key of path.split(".")) {
    if (cursor === null || typeof cursor !== "object") return null;
    cursor = (cursor as Record<string, unknown>)[key];
  }
  if (typeof cursor === "number" && Number.isFinite(cursor)) return cursor;
  if (typeof cursor === "string") {
    const n = Number(cursor);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export default function AirtableBackupKpiCard(props: CustomWidgetProps) {
  const config = props.config as unknown as Config;
  const {
    label,
    endpoint,
    value_path = "value",
    color = "neutral",
    sublabel,
  } = config;

  const [value, setValue] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!endpoint) {
      setLoaded(true);
      return;
    }
    window.NousViz.widgets
      .apiFetch(endpoint)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return;
        setValue(readPath(data, value_path));
        setLoaded(true);
      })
      .catch(() => {
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

  return (
    <div className="bg-card border border-border rounded-lg p-4 flex flex-col gap-1">
      <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className={cn("text-3xl font-display font-semibold tabular-nums", colorClass)}>
        {loaded ? (value === null ? "—" : fmt(value)) : "…"}
      </div>
      {sublabel && (
        <div className="text-xs text-muted-foreground">{sublabel}</div>
      )}
    </div>
  );
}
