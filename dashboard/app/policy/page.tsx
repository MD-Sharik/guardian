"use client";

import { SlidersHorizontal } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Card, SectionLabel } from "@/components/ui";
import { useGuardian } from "@/lib/guardian-context";

export default function Policy() {
  const { health } = useGuardian();
  const t = health?.thresholds;

  return (
    <>
      <PageHeader icon={SlidersHorizontal} title="policy" showRange={false} />
      <div className="mx-auto max-w-3xl space-y-8 px-6 py-8">
        <div>
          <h2 className="text-xl font-medium">How Jev&apos;s answers become a verdict</h2>
          <p className="mt-1 text-sm text-muted">
            Guardian asks Jev ({health?.jev_model ?? "…"}) typed questions about every action, then applies these rules.
            Every rule that fires is recorded as a reason, and the strictest verdict wins. Change a threshold in{" "}
            <code className="font-mono text-ink">.env</code> and restart Guardian.
          </p>
        </div>

        {t && (
          <>
            <Card className="space-y-6 p-5">
              <Zone
                label="P(safe)"
                hint="Noul · is this action safe to run?"
                env="GUARDIAN_BLOCK_SAFE_BELOW · GUARDIAN_ALLOW_SAFE_ABOVE"
                stops={[
                  { to: t.block_safe_below, color: "bg-block", name: "block" },
                  { to: t.allow_safe_above, color: "bg-escalate", name: "ask" },
                  { to: 1, color: "bg-allow", name: "allow" },
                ]}
                max={1}
              />
              <Zone
                label="Impact"
                hint="Score · 0 negligible … 3 critical, if it's a mistake"
                env="GUARDIAN_SEVERITY_ESCALATE · GUARDIAN_SEVERITY_BLOCK"
                stops={[
                  { to: t.severity_escalate, color: "bg-allow", name: "allow" },
                  { to: t.severity_block, color: "bg-escalate", name: "ask" },
                  { to: 3, color: "bg-block", name: "block" },
                ]}
                max={3}
              />
              <Zone
                label="Confidence"
                hint="The least certain of Jev's answers"
                env="GUARDIAN_MIN_CONFIDENCE"
                stops={[
                  { to: t.min_confidence, color: "bg-escalate", name: "ask" },
                  { to: 1, color: "bg-allow", name: "ok" },
                ]}
                max={1}
              />
            </Card>

            <section>
              <SectionLabel>all rules</SectionLabel>
              <div className="overflow-hidden rounded-xl border border-line">
                <table className="w-full text-sm">
                  <tbody>
                    <Rule verdict="block" when={`P(safe) below ${t.block_safe_below}`} />
                    <Rule verdict="block" when={`impact at or above ${t.severity_block} / 3`} />
                    <Rule verdict="block" when={`Jev picks data loss, exfiltration or system damage with p ≥ ${t.risk_block}`} />
                    <Rule verdict="ask" when={`confidence below ${t.min_confidence}`} />
                    <Rule verdict="ask" when={`P(safe) between ${t.block_safe_below} and ${t.allow_safe_above}`} />
                    <Rule verdict="ask" when={`impact at or above ${t.severity_escalate} / 3`} />
                    <Rule verdict="ask" when={`P(on task) below ${t.on_task_min}`} />
                    <Rule verdict="ask" when={`content being written looks incomplete (P(ok) below ${t.output_ok_min})`} />
                    <Rule verdict="ask" when="Jev picks “unclear effects”" />
                    <Rule verdict="ask" when="Jev can't be reached" />
                    <Rule verdict="allow" when="none of the above" />
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </div>
    </>
  );
}

const RULE_STYLE = {
  block: "bg-block-soft text-block",
  ask: "bg-escalate-soft text-escalate",
  allow: "bg-allow-soft text-allow",
};
const RULE_LABEL = { block: "block", ask: "ask a human", allow: "allow" };

function Rule({ verdict, when }: { verdict: keyof typeof RULE_STYLE; when: string }) {
  return (
    <tr className="border-b border-line last:border-0">
      <td className="w-36 px-4 py-2.5">
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${RULE_STYLE[verdict]}`}>{RULE_LABEL[verdict]}</span>
      </td>
      <td className="px-4 py-2.5">{when}</td>
    </tr>
  );
}

function Zone({
  label,
  hint,
  env,
  stops,
  max,
}: {
  label: string;
  hint: string;
  env: string;
  stops: { to: number; color: string; name: string }[];
  max: number;
}) {
  let from = 0;
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-xs text-muted">{hint}</span>
      </div>
      <div className="flex h-7 overflow-hidden rounded-lg text-[11px] font-medium text-surface">
        {stops.map((s) => {
          const width = ((s.to - from) / max) * 100;
          const start = from;
          from = s.to;
          return (
            <div
              key={s.name + s.to}
              className={`${s.color} flex items-center justify-between px-2`}
              style={{ width: `${width}%` }}
              title={`${start} – ${s.to}`}
            >
              <span>{s.name}</span>
              <span className="opacity-80">{s.to}</span>
            </div>
          );
        })}
      </div>
      <p className="mt-1.5 font-mono text-[11px] text-faint">{env}</p>
    </div>
  );
}
