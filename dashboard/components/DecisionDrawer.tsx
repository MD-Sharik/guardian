"use client";

import { ExternalLink, Sparkles, X } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { RISK_WORD, SEVERITY_WORD, clock, explanationLines, pct } from "@/lib/format";
import { useGuardian } from "@/lib/guardian-context";
import type { Decision, Mode, Thresholds, TraceSpan } from "@/lib/types";
import { ModeBadge, StatusNote, VerdictPill } from "./ui";

export function DecisionDrawer({ d }: { d: Decision }) {
  const { close, health, resolve, explain } = useGuardian();
  const closeRef = useRef<HTMLButtonElement>(null);
  const t = health?.thresholds;

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  return (
    <div className="fixed inset-0 z-30 flex justify-end">
      <button type="button" aria-label="Close details" onClick={close} className="absolute inset-0 bg-black/20 dark:bg-black/50" />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        className="relative flex h-full w-full max-w-[620px] flex-col border-l border-line bg-surface shadow-2xl"
      >
        <header className="flex items-start gap-3 border-b border-line px-6 py-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <VerdictPill verdict={d.verdict} />
              <StatusNote status={d.status} />
            </div>
            <h2 id="drawer-title" className="mt-2 font-mono text-[15px] font-medium">
              {d.tool}
            </h2>
            <p className="mt-0.5 text-xs text-muted">
              {clock(d.created_at)} · {d.agent_name} · {d.session_id ?? "no session"} · decided in {Math.round(d.latency_ms)} ms
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={close}
            className="rounded-md p-1.5 text-muted hover:bg-hover hover:text-ink"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex-1 space-y-7 overflow-y-auto px-6 py-5">
          <pre className="overflow-x-auto rounded-lg border border-line bg-code px-4 py-3 font-mono text-[12.5px] leading-relaxed">
            {JSON.stringify(d.args, null, 2)}
          </pre>

          <Explanation d={d} explainer={health?.modes.explainer} onExplain={explain} />
          {t && <JevAnswers d={d} t={t} />}

          <Section title="Policy">
            <ul className="space-y-1.5">
              {d.reasons.map((r) => (
                <li key={r} className="flex gap-2 text-sm">
                  <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted" />
                  {r}
                </li>
              ))}
            </ul>
            {d.resolved_by && d.status !== "pending" && (
              <p className="mt-3 text-xs text-muted">
                {d.status.replace("_", " ")} by {d.resolved_by}
                {d.resolved_at ? ` at ${clock(d.resolved_at)}` : ""}
              </p>
            )}
          </Section>

          {d.verdict !== "ALLOW" && <EntireSession entire={d.entire} mode={health?.modes.entire} />}
          <Trace d={d} mode={health?.modes.neatlogs} />

          {d.result && (
            <Section title="Tool result" aside={d.result.ok ? "ran" : "failed"}>
              <pre className="max-h-56 overflow-auto rounded-lg border border-line bg-code px-4 py-3 font-mono text-xs whitespace-pre-wrap text-muted">
                {d.result.ok ? d.result.output || "(no output reported)" : d.result.error}
              </pre>
            </Section>
          )}
        </div>

        {d.status === "pending" && <ResolveBar d={d} onResolve={resolve} />}
      </aside>
    </div>
  );
}

function ResolveBar({ d, onResolve }: { d: Decision; onResolve: (id: string, approve: boolean) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const act = async (approve: boolean) => {
    setBusy(true);
    try {
      await onResolve(d.id, approve);
    } finally {
      setBusy(false);
    }
  };
  return (
    <footer className="flex gap-2 border-t border-line bg-subtle px-6 py-4">
      <button
        type="button"
        disabled={busy}
        onClick={() => act(true)}
        className="flex-1 rounded-lg bg-ink px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
      >
        Approve and run
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => act(false)}
        className="flex-1 rounded-lg border border-line-strong px-4 py-2 text-sm font-medium text-block hover:bg-block-soft disabled:opacity-50"
      >
        Reject
      </button>
    </footer>
  );
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-xs font-medium tracking-[0.08em] text-muted uppercase">{title}</h3>
        {aside && <span className="text-xs text-muted">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

function Explanation({
  d,
  explainer,
  onExplain,
}: {
  d: Decision;
  explainer: Mode | undefined;
  onExplain: (id: string) => Promise<void>;
}) {
  return (
    <Section title="In plain English" aside={d.explanation?.model}>
      {d.explanation ? (
        <div className="space-y-3 rounded-lg border border-line bg-subtle p-4">
          {explanationLines(d.explanation.text).map((line, i) => (
            <div key={i}>
              {line.label && <p className="text-xs font-medium text-muted">{line.label}</p>}
              <p className="text-sm leading-relaxed">{line.body}</p>
            </div>
          ))}
        </div>
      ) : explainer === "off" ? (
        <p className="text-sm text-muted">
          Explanations are off. Set <code className="font-mono text-ink">LLM_BASE_URL</code> and your Modal proxy token in
          .env, then restart Guardian.
        </p>
      ) : d.explanation_error ? (
        <p className="text-sm text-block">Couldn&apos;t generate an explanation: {d.explanation_error}</p>
      ) : d.explanation_pending ? (
        <div className="space-y-2" aria-live="polite">
          <p className="text-sm text-muted">Reading the agent&apos;s session and writing an explanation…</p>
          <div className="shimmer h-3 w-11/12 rounded" />
          <div className="shimmer h-3 w-4/5 rounded" />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => onExplain(d.id)}
          className="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-hover"
        >
          <Sparkles size={14} /> Explain this decision
        </button>
      )}
    </Section>
  );
}

function JevAnswers({ d, t }: { d: Decision; t: Thresholds }) {
  if (d.checked === false) {
    return (
      <Section title="Jev's answers" aside="not asked">
        <p className="text-sm text-muted">
          {d.tool} is on the read-only fast path, so Guardian allowed it without spending a Jev check.
        </p>
      </Section>
    );
  }
  if (!d.jev) {
    return (
      <Section title="Jev's answers" aside="unreachable">
        <p className="text-sm text-escalate">Jev couldn&apos;t be reached, so Guardian asked a human instead of guessing.</p>
        <p className="mt-2 font-mono text-xs break-all text-muted">{d.jev_error}</p>
      </Section>
    );
  }
  const s = d.jev.signals;
  const risks = Object.entries(s.risk_probabilities).sort((a, b) => b[1] - a[1]);
  return (
    <Section title="Jev's answers" aside={`${d.jev.model} · ${Math.round(d.jev.latency_ms)} ms`}>
      <div className="grid grid-cols-3 gap-3">
        <Gauge label="P(safe)" value={s.p_safe} display={pct(s.p_safe)} tone={s.p_safe < t.block_safe_below ? "block" : s.p_safe < t.allow_safe_above ? "escalate" : "allow"} />
        <Gauge label="On task" value={s.p_on_task} display={pct(s.p_on_task)} tone={s.p_on_task < t.on_task_min ? "escalate" : "allow"} />
        <Gauge label="Confidence" value={s.confidence} display={s.confidence.toFixed(2)} tone={s.confidence < t.min_confidence ? "escalate" : "allow"} />
      </div>

      <p className="mt-5 mb-2 text-xs text-muted">Main risk · confidence {s.risk_confidence.toFixed(2)}</p>
      <div className="space-y-1.5">
        {risks.map(([name, p]) => (
          <div key={name} className="grid grid-cols-[9rem_1fr_3rem] items-center gap-3 text-sm">
            <span className={name === s.risk ? "font-medium" : "text-muted"}>{RISK_WORD[name] ?? name}</span>
            <div className="h-1.5 overflow-hidden rounded-full bg-line">
              <div
                className={`h-full rounded-full ${name === "none" ? "bg-allow" : name === "unclear" ? "bg-escalate" : "bg-block"} ${name === s.risk ? "" : "opacity-40"}`}
                style={{ width: `${p * 100}%` }}
              />
            </div>
            <span className="text-right font-mono text-xs text-muted tabular-nums">{pct(p)}</span>
          </div>
        ))}
      </div>

      <p className="mt-5 mb-2 text-xs text-muted">
        Impact if it&apos;s a mistake · {s.severity.toFixed(2)} / 3 · confidence {s.severity_confidence.toFixed(2)}
      </p>
      <div className="grid grid-cols-4 gap-1.5">
        {SEVERITY_WORD.map((word, i) => {
          const p = s.severity_probabilities[String(i)] ?? 0;
          const color = i >= t.severity_block ? "bg-block" : i >= t.severity_escalate ? "bg-escalate" : "bg-allow";
          return (
            <div key={word} className="rounded-lg border border-line px-2 pt-2 pb-1.5">
              <div className="flex h-9 items-end">
                <div className={`w-full rounded-sm ${color}`} style={{ height: `${Math.max(4, p * 100)}%`, opacity: 0.3 + p * 0.7 }} />
              </div>
              <p className="mt-1.5 text-xs text-muted">{word}</p>
              <p className="font-mono text-[10px] text-faint">{pct(p)}</p>
            </div>
          );
        })}
      </div>

      {s.output_ok !== null && (
        <p className="mt-4 text-sm text-muted">
          Content looks complete and correct:{" "}
          <span className={`font-mono ${s.output_ok < t.output_ok_min ? "text-escalate" : "text-ink"}`}>{pct(s.output_ok)}</span>
        </p>
      )}
    </Section>
  );
}

const TONE_TEXT = { allow: "text-allow", escalate: "text-escalate", block: "text-block" };
const TONE_BAR = { allow: "bg-allow", escalate: "bg-escalate", block: "bg-block" };

function Gauge({ label, value, display, tone }: { label: string; value: number; display: string; tone: "allow" | "escalate" | "block" }) {
  return (
    <div className="rounded-lg border border-line px-3 py-2.5">
      <p className="text-xs text-muted">{label}</p>
      <p className={`font-mono text-xl tabular-nums ${TONE_TEXT[tone]}`}>{display}</p>
      <div className="mt-1.5 h-0.5 rounded-full bg-line">
        <div className={`h-full rounded-full ${TONE_BAR[tone]}`} style={{ width: `${value * 100}%` }} />
      </div>
    </div>
  );
}

function EntireSession({ entire, mode }: { entire: Record<string, unknown> | null; mode: Mode | undefined }) {
  if (mode !== "live" || !entire) {
    return (
      <Section title="Entire session" aside={<ModeBadge mode={mode} />}>
        <p className="text-sm text-muted">
          {mode === "off" ? (
            <>
              The Entire CLI isn&apos;t installed, so the agent&apos;s session can&apos;t be read. See{" "}
              <a className="text-info hover:underline" href="https://docs.entire.io/installation" target="_blank" rel="noreferrer">
                docs.entire.io
              </a>
              .
            </>
          ) : (
            "Reading the agent's session from Entire…"
          )}
        </p>
      </Section>
    );
  }
  const facts: [string, unknown][] = [
    ["Session", entire.session_id],
    ["Repository", entire.repo],
  ];
  const excerpt = (entire.transcript_excerpt as string[] | undefined) ?? [];
  return (
    <Section title="Entire session" aside={<ModeBadge mode={entire.error ? "error" : "live"} />}>
      {typeof entire.error === "string" ? (
        <p className="text-sm text-escalate">{entire.error}</p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-3 text-xs">
            {facts
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k} className="min-w-0">
                  <dt className="text-muted">{k}</dt>
                  <dd className="truncate font-mono">{String(v)}</dd>
                </div>
              ))}
          </dl>
          {typeof entire.summary === "string" && <p className="mt-3 text-sm whitespace-pre-wrap">{entire.summary}</p>}
          {excerpt.length > 0 && (
            <pre className="mt-3 max-h-48 overflow-auto rounded-lg border border-line bg-code px-3 py-2 font-mono text-[11px] whitespace-pre-wrap text-muted">
              {excerpt.join("\n")}
            </pre>
          )}
        </>
      )}
    </Section>
  );
}

function Trace({ d, mode }: { d: Decision; mode: Mode | undefined }) {
  if (!d.trace) {
    return (
      <Section title="NeatLogs trace" aside={<ModeBadge mode={mode} />}>
        <p className="text-sm text-muted">
          {mode === "off" ? (
            <>
              Tracing is off. Add <code className="font-mono text-ink">NEATLOGS_API_KEY</code> to .env.
            </>
          ) : (
            "Sending trace…"
          )}
        </p>
      </Section>
    );
  }
  return (
    <Section title="NeatLogs trace" aside={<ModeBadge mode={d.trace.mode} />}>
      {d.trace.url ? (
        <a
          href={d.trace.url}
          target="_blank"
          rel="noreferrer"
          className="mb-3 inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-hover"
        >
          Open in NeatLogs <ExternalLink size={13} />
        </a>
      ) : (
        <p className="mb-3 text-sm text-block">NeatLogs rejected the trace: {d.trace.error}</p>
      )}
      <SpanTree span={d.trace.payload} depth={0} />
    </Section>
  );
}

function SpanTree({ span, depth }: { span: TraceSpan; depth: number }) {
  return (
    <div className={depth ? "ml-4 border-l border-line pl-3" : ""}>
      <div className="flex items-baseline gap-2 py-0.5 text-xs">
        <span className="rounded bg-hover px-1.5 font-mono text-[10px] text-muted">{span.kind ?? "WORKFLOW"}</span>
        <span className="font-mono">{span.name}</span>
        {span.duration_ms !== undefined && <span className="text-faint">{span.duration_ms} ms</span>}
      </div>
      {span.children?.map((child) => (
        <SpanTree key={child.name} span={child} depth={depth + 1} />
      ))}
    </div>
  );
}
