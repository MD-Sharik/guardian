import type { Decision } from "./types";

export const RISK_WORD: Record<string, string> = {
  none: "No meaningful risk",
  data_loss: "Data loss",
  exfiltration: "Exfiltration",
  system_damage: "System damage",
  unclear: "Unclear effects",
};

export const SEVERITY_WORD = ["Negligible", "Minor", "Serious", "Critical"];

// Argument names that best describe an action, across agents (LangChain tools, Antigravity).
const SUMMARY_KEYS = ["command", "CommandLine", "url", "Url", "path", "AbsolutePath", "TargetFile", "file_path", "query", "Query"];

/** The one argument that best describes an action, for one-line display. */
export function actionSummary(d: Pick<Decision, "tool" | "args">): string {
  const a = d.args as Record<string, unknown>;
  if (d.tool === "http_request" && typeof a.url === "string") {
    return `${String(a.method ?? "GET").toUpperCase()} ${a.url}`;
  }
  for (const key of SUMMARY_KEYS) {
    if (typeof a[key] === "string" && a[key]) return a[key] as string;
  }
  const first = Object.values(a).find((v) => typeof v === "string" && v);
  return typeof first === "string" ? first : JSON.stringify(a);
}

export function timeAgo(ts: number, now: number): string {
  if (!now) return "";
  const s = Math.max(0, Math.round(now / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
}

export function pct(p: number): string {
  return `${Math.round(p * 100)}%`;
}

export function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Explanations come back as "Label: text" lines; split them for layout. */
export function explanationLines(text: string): { label: string | null; body: string }[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const m = line.match(/^([A-Z][A-Za-z ]{2,40}):\s+(.*)$/);
      return m ? { label: m[1], body: m[2] } : { label: null, body: line };
    });
}
