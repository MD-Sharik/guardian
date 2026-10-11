"use client";

import { Hand } from "lucide-react";
import { useState } from "react";
import { DecisionTable } from "@/components/DecisionTable";
import { PageHeader } from "@/components/PageHeader";
import { Card, Empty, SectionLabel } from "@/components/ui";
import { actionSummary, explanationLines, pct, timeAgo } from "@/lib/format";
import { useGuardian } from "@/lib/guardian-context";
import type { Decision } from "@/lib/types";

export default function Approvals() {
  const { decisions, inRange } = useGuardian();
  const pending = decisions.filter((d) => d.status === "pending").reverse();
  const answered = inRange.filter((d) => d.verdict === "ESCALATE" && d.status !== "pending");

  return (
    <>
      <PageHeader icon={Hand} title="approvals" />
      <div className="space-y-10 px-6 py-6">
        <section>
          <SectionLabel>waiting for you · {pending.length}</SectionLabel>
          {pending.length ? (
            <div className="grid gap-4 lg:grid-cols-2">
              {pending.map((d) => (
                <ApprovalCard key={d.id} d={d} />
              ))}
            </div>
          ) : (
            <Empty icon={<Hand size={22} />} title="Nothing needs a decision">
              When Jev isn&apos;t confident about an action, the agent pauses and the action appears here for you to approve
              or reject.
            </Empty>
          )}
        </section>

        {answered.length > 0 && (
          <section>
            <SectionLabel>answered</SectionLabel>
            <DecisionTable decisions={answered} />
          </section>
        )}
      </div>
    </>
  );
}

function ApprovalCard({ d }: { d: Decision }) {
  const { resolve, open, now, health } = useGuardian();
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const why = d.explanation ? explanationLines(d.explanation.text).find((l) => l.label?.startsWith("Why it")) : null;
  const waitedS = now ? Math.max(0, now / 1000 - d.created_at) : 0;
  const timeout = health?.escalation_timeout_s ?? 300;

  async function act(approve: boolean) {
    setBusy(approve ? "approve" : "reject");
    setError(null);
    try {
      await resolve(d.id, approve);
    } catch (e) {
      setError(`Couldn't send your answer: ${(e as Error).message}`);
      setBusy(null);
    }
  }

  return (
    <Card className="row-in overflow-hidden">
      <div className="space-y-3 p-5">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-sm">
            <span className="font-medium">{d.agent_name}</span> <span className="text-muted">wants to run</span>{" "}
            <span className="font-mono text-xs">{d.tool}</span>
          </p>
          <span className="text-xs whitespace-nowrap text-escalate">waiting {timeAgo(d.created_at, now).replace(" ago", "")}</span>
        </div>
        <code className="block rounded-lg border border-line bg-code px-3 py-2 font-mono text-[12.5px] break-all">{actionSummary(d)}</code>
        <dl className="grid grid-cols-3 gap-2 text-xs">
          <Stat label="P(safe)" value={d.jev ? pct(d.jev.signals.p_safe) : "–"} />
          <Stat label="confidence" value={d.confidence.toFixed(2)} />
          <Stat label="session" value={d.session_id ?? "–"} />
        </dl>
        <p className="text-sm text-muted">{d.reasons[0]}</p>
        {why ? <p className="text-sm">{why.body}</p> : d.context.reasoning ? <p className="text-sm text-muted">Agent: “{d.context.reasoning}”</p> : null}
        {error && <p className="text-xs text-block">{error}</p>}
      </div>
      <div className="h-0.5 bg-line">
        <div className="h-full bg-escalate transition-all" style={{ width: `${Math.min(100, (waitedS / timeout) * 100)}%` }} />
      </div>
      <div className="flex items-center gap-2 bg-subtle px-5 py-3">
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => act(true)}
          className="rounded-lg bg-ink px-3.5 py-1.5 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
        >
          {busy === "approve" ? "Approving…" : "Approve and run"}
        </button>
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => act(false)}
          className="rounded-lg border border-line-strong bg-surface px-3.5 py-1.5 text-sm font-medium text-block hover:bg-block-soft disabled:opacity-50"
        >
          {busy === "reject" ? "Rejecting…" : "Reject"}
        </button>
        <button type="button" onClick={() => open(d.id)} className="ml-auto text-sm text-muted hover:text-ink">
          details
        </button>
      </div>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted">{label}</dt>
      <dd className="truncate font-mono">{value}</dd>
    </div>
  );
}
