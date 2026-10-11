"use client";

import { ArrowRight, Ban, CircleCheck, Hand, House, Plug, ScrollText, Sparkles, TriangleAlert, Workflow } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { SectionLabel, VerdictPill } from "@/components/ui";
import { actionSummary, median, timeAgo } from "@/lib/format";
import { RANGES, useGuardian } from "@/lib/guardian-context";
import { agentSources } from "@/lib/setup";
import type { Decision } from "@/lib/types";

export default function Home() {
  const { inRange, decisions, health, range } = useGuardian();
  const rangeLabel = RANGES.find((r) => r.value === range)!.label.toLowerCase();
  const sessions = new Set(inRange.map((d) => d.session_id ?? d.id)).size;
  const blocked = inRange.filter((d) => d.verdict === "BLOCK").length;
  const latencies = inRange.flatMap((d) => (d.jev ? [d.jev.latency_ms] : []));

  return (
    <>
      <PageHeader icon={House} title="home" />
      <section className="grid grid-cols-2 border-b border-line bg-subtle lg:grid-cols-4">
        <Stat label="decisions" value={inRange.length} />
        <Stat label="sessions" value={sessions} />
        <Stat label="blocked" value={inRange.length ? `${Math.round((blocked / inRange.length) * 100)}%` : "0%"} />
        <Stat label="jev p50" value={latencies.length ? `${Math.round(median(latencies))} ms` : "–"} />
      </section>

      <div className="grid gap-10 px-6 py-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
        <div className="min-w-0 space-y-9">
          <NeedsAttention />
          <WorthSwitchingOn />
        </div>
        <Digest decisions={inRange} rangeLabel={rangeLabel} empty={decisions.length === 0} jevModel={health?.jev_model} />
      </div>
    </>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="px-6 py-6">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-2xl font-medium tabular-nums">{value}</p>
    </div>
  );
}

function NeedsAttention() {
  const { decisions, inRange, now, open, resolve } = useGuardian();
  const pending = decisions.filter((d) => d.status === "pending").reverse();
  const blocks = inRange.filter((d) => d.verdict === "BLOCK").slice(0, 5);
  const jevDown = inRange.filter((d) => !d.jev && d.checked !== false).length;
  const traceErrors = inRange.filter((d) => d.trace?.mode === "error").length;
  const items = pending.length + blocks.length + (jevDown ? 1 : 0) + (traceErrors ? 1 : 0);

  return (
    <section>
      <SectionLabel>needs attention</SectionLabel>
      {items === 0 ? (
        <p className="flex items-center gap-2.5 text-sm">
          <CircleCheck size={17} className="text-allow" />
          <span className="font-medium">all clear for now</span>
          <span className="text-muted">· No blocked or escalated actions are waiting for review.</span>
        </p>
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line">
          {pending.map((d) => (
            <PendingRow key={d.id} d={d} now={now} onOpen={open} onResolve={resolve} />
          ))}
          {blocks.map((d) => (
            <Row key={d.id} icon={<Ban size={16} className="text-block" />} onClick={() => open(d.id)}>
              <span>
                Blocked <code className="font-mono text-xs">{actionSummary(d)}</code>
              </span>
              <span className="text-muted">
                {" "}
                · {d.agent_name} · {timeAgo(d.created_at, now)}
              </span>
            </Row>
          ))}
          {jevDown > 0 && (
            <Row icon={<TriangleAlert size={16} className="text-escalate" />} href="/integrations">
              Jev couldn&apos;t be reached {jevDown} {jevDown === 1 ? "time" : "times"}
              <span className="text-muted"> · those actions went to a human</span>
            </Row>
          )}
          {traceErrors > 0 && (
            <Row icon={<TriangleAlert size={16} className="text-escalate" />} href="/integrations">
              NeatLogs rejected {traceErrors} {traceErrors === 1 ? "trace" : "traces"}
              <span className="text-muted"> · check the key and project</span>
            </Row>
          )}
        </ul>
      )}
    </section>
  );
}

function Row({ icon, children, onClick, href }: { icon: ReactNode; children: ReactNode; onClick?: () => void; href?: string }) {
  const body = (
    <>
      <span className="mt-0.5">{icon}</span>
      <span className="min-w-0 flex-1 truncate text-sm">{children}</span>
      <ArrowRight size={14} className="text-faint" />
    </>
  );
  const cls = "flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-hover";
  return (
    <li>
      {href ? (
        <Link href={href} className={cls}>
          {body}
        </Link>
      ) : (
        <button type="button" onClick={onClick} className={cls}>
          {body}
        </button>
      )}
    </li>
  );
}

function PendingRow({
  d,
  now,
  onOpen,
  onResolve,
}: {
  d: Decision;
  now: number;
  onOpen: (id: string) => void;
  onResolve: (id: string, approve: boolean) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const act = async (approve: boolean) => {
    setBusy(true);
    try {
      await onResolve(d.id, approve);
    } catch {
      setBusy(false);
    }
  };
  return (
    <li className="flex items-center gap-3 bg-escalate-soft/50 px-4 py-3">
      <Hand size={16} className="shrink-0 text-escalate" />
      <button type="button" onClick={() => onOpen(d.id)} className="min-w-0 flex-1 truncate text-left text-sm">
        <span className="font-medium">{d.agent_name}</span> wants to run{" "}
        <code className="font-mono text-xs">{actionSummary(d)}</code>
        <span className="text-muted"> · waiting {timeAgo(d.created_at, now).replace(" ago", "")}</span>
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => act(true)}
        className="rounded-md bg-ink px-2.5 py-1 text-xs font-medium text-surface hover:opacity-90 disabled:opacity-50"
      >
        Approve
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => act(false)}
        className="rounded-md border border-line-strong bg-surface px-2.5 py-1 text-xs font-medium text-block hover:bg-block-soft disabled:opacity-50"
      >
        Reject
      </button>
    </li>
  );
}

function WorthSwitchingOn() {
  const { health, decisions } = useGuardian();
  const cards: { icon: ReactNode; title: string; action: string; href: string }[] = [];
  if (agentSources(decisions).antigravity === 0)
    cards.push({ icon: <Workflow size={16} />, title: "guard Antigravity", action: "connect", href: "/setup#agent" });
  if (health?.modes.neatlogs === "off")
    cards.push({ icon: <ScrollText size={16} />, title: "trace every decision", action: "connect NeatLogs", href: "/setup#neatlogs" });
  if (health?.modes.explainer === "off")
    cards.push({ icon: <Sparkles size={16} />, title: "explain blocked actions", action: "connect an LLM", href: "/setup#explainer" });
  if (health?.modes.entire === "off")
    cards.push({ icon: <Plug size={16} />, title: "read agent sessions", action: "install Entire", href: "/setup#entire" });
  if (!cards.length) return null;
  return (
    <section>
      <SectionLabel>worth switching on</SectionLabel>
      <div className="grid gap-3 sm:grid-cols-2">
        {cards.map((c) => (
          <Link key={c.title} href={c.href} className="rounded-xl border border-line px-4 py-4 hover:bg-hover">
            <span className="text-muted">{c.icon}</span>
            <p className="mt-3 text-sm font-medium">{c.title}</p>
            <p className="text-xs text-info">{c.action}</p>
          </Link>
        ))}
      </div>
    </section>
  );
}

function Digest({ decisions, rangeLabel, empty, jevModel }: { decisions: Decision[]; rangeLabel: string; empty: boolean; jevModel?: string }) {
  const { open, now } = useGuardian();
  const count = (v: Decision["verdict"]) => decisions.filter((d) => d.verdict === v).length;
  const topTool = mostCommon(decisions.map((d) => d.tool));
  const topBlocked = mostCommon(decisions.filter((d) => d.verdict === "BLOCK").map((d) => d.tool));
  return (
    <section className="min-w-0">
      <div className="mb-3 flex items-baseline gap-3">
        <h2 className="text-[15px] font-medium">Digest</h2>
        <span className="text-xs text-info">{rangeLabel}</span>
      </div>
      {decisions.length === 0 ? (
        <p className="text-sm text-muted">
          {empty ? (
            <>
              No agent actions yet.{" "}
              <Link href="/setup" className="text-info hover:underline">
                Connect an agent
              </Link>{" "}
              to see them here before they run.
            </>
          ) : (
            `No agent actions arrived in the ${rangeLabel}.`
          )}
        </p>
      ) : (
        <>
          <p className="text-sm leading-relaxed text-muted">
            <span className="text-ink">{decisions.length} actions</span> were checked by {jevModel ?? "Jev"}:{" "}
            {count("ALLOW")} allowed, {count("BLOCK")} blocked and {count("ESCALATE")} sent to a human.
            {topTool && ` The most-used tool was ${topTool}.`}
            {topBlocked && ` Most blocks came from ${topBlocked}.`}
          </p>
          <ul className="mt-5 space-y-1">
            {decisions.slice(0, 8).map((d) => (
              <li key={d.id}>
                <button
                  type="button"
                  onClick={() => open(d.id)}
                  className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-hover"
                >
                  <VerdictPill verdict={d.verdict} />
                  <span className="min-w-0 flex-1 truncate font-mono text-xs">{actionSummary(d)}</span>
                  <span className="text-xs whitespace-nowrap text-faint">{timeAgo(d.created_at, now)}</span>
                </button>
              </li>
            ))}
          </ul>
          <Link href="/decisions" className="mt-2 inline-flex items-center gap-1 px-2 text-xs text-info hover:underline">
            all decisions <ArrowRight size={12} />
          </Link>
        </>
      )}
    </section>
  );
}

function mostCommon(values: string[]): string | null {
  const counts = new Map<string, number>();
  for (const v of values) counts.set(v, (counts.get(v) ?? 0) + 1);
  let best: string | null = null;
  for (const [v, n] of counts) if (!best || n > counts.get(best)!) best = v;
  return best;
}
