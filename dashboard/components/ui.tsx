"use client";

import { Check, Copy } from "lucide-react";
import { type ReactNode, useState } from "react";
import type { Mode, Status, Verdict } from "@/lib/types";

const VERDICT_STYLE: Record<Verdict, string> = {
  ALLOW: "bg-allow-soft text-allow",
  BLOCK: "bg-block-soft text-block",
  ESCALATE: "bg-escalate-soft text-escalate",
};
const VERDICT_LABEL: Record<Verdict, string> = { ALLOW: "allowed", BLOCK: "blocked", ESCALATE: "escalated" };

export function VerdictPill({ verdict }: { verdict: Verdict }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${VERDICT_STYLE[verdict]}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {VERDICT_LABEL[verdict]}
    </span>
  );
}

const STATUS_STYLE: Partial<Record<Status, string>> = {
  pending: "text-escalate",
  approved: "text-allow",
  rejected: "text-block",
  expired: "text-muted",
  handed_off: "text-muted",
};
const STATUS_LABEL: Partial<Record<Status, string>> = {
  pending: "waiting for you",
  approved: "approved",
  rejected: "rejected",
  expired: "expired",
  handed_off: "handed to agent",
};

/** Only escalations have an interesting status beyond their verdict. */
export function StatusNote({ status }: { status: Status }) {
  const label = STATUS_LABEL[status];
  if (!label) return null;
  return <span className={`text-xs ${STATUS_STYLE[status]}`}>{label}</span>;
}

export function ModeBadge({ mode }: { mode: Mode | undefined }) {
  const style =
    mode === "live" ? "bg-allow-soft text-allow" : mode === "error" ? "bg-block-soft text-block" : "bg-hover text-muted";
  const label = mode === "live" ? "connected" : mode === "error" ? "failing" : "off";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${style}`}>{mode ? label : "…"}</span>;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-line bg-surface ${className}`}>{children}</div>;
}

export function SectionLabel({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="text-xs font-medium tracking-[0.08em] text-muted uppercase">{children}</h2>
      {aside}
    </div>
  );
}

export function CodeBlock({ code, label }: { code: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked: the text is still selectable
    }
  }
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-code">
      {label && (
        <div className="flex items-center justify-between border-b border-line px-3 py-1.5 text-xs text-muted">
          {label}
        </div>
      )}
      <div className="relative">
        <pre className="overflow-x-auto px-3 py-2.5 pr-20 font-mono text-[12.5px] leading-relaxed text-ink">{code}</pre>
        <button
          type="button"
          onClick={copy}
          className="absolute top-2 right-2 inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 text-xs text-muted hover:text-ink"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line-strong px-6 py-14 text-center">
      <div className="mb-3 text-faint">{icon}</div>
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function ConfidenceBar({ value, threshold }: { value: number; threshold?: number }) {
  const color = threshold !== undefined && value < threshold ? "bg-escalate" : "bg-ink/70";
  return (
    <div className="flex items-center gap-2" title={`Jev confidence ${value.toFixed(2)}`}>
      <div className="relative h-1 w-14 overflow-hidden rounded-full bg-line">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.max(4, value * 100)}%` }} />
      </div>
      <span className="w-7 font-mono text-xs text-muted tabular-nums">{value.toFixed(2)}</span>
    </div>
  );
}
