"use client";

import { ChevronDown, ChevronRight, Workflow } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Empty, VerdictPill } from "@/components/ui";
import { actionSummary, clock, timeAgo } from "@/lib/format";
import { useGuardian } from "@/lib/guardian-context";
import type { Decision } from "@/lib/types";

interface Session {
  id: string;
  agent: string;
  source: string;
  task: string | null;
  steps: Decision[]; // oldest first
  last: number;
}

function groupSessions(decisions: Decision[]): Session[] {
  const map = new Map<string, Session>();
  for (const d of decisions) {
    const id = d.session_id ?? `single-${d.id}`;
    const s = map.get(id) ?? {
      id,
      agent: d.agent_name,
      source: String(d.context.metadata?.source ?? "sdk"),
      task: null,
      steps: [],
      last: 0,
    };
    s.steps.push(d);
    s.task = s.task ?? d.context.task;
    s.last = Math.max(s.last, d.created_at);
    map.set(id, s);
  }
  for (const s of map.values()) s.steps.sort((a, b) => a.created_at - b.created_at);
  return [...map.values()].sort((a, b) => b.last - a.last);
}

export default function Sessions() {
  const { inRange, now, open } = useGuardian();
  const sessions = useMemo(() => groupSessions(inRange), [inRange]);
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <>
      <PageHeader icon={Workflow} title="sessions" />
      <div className="px-6 py-6">
        {sessions.length === 0 ? (
          <Empty icon={<Workflow size={22} />} title="No sessions in this range">
            A session is one agent run, such as one Antigravity conversation. Its steps appear here as Guardian checks them.
          </Empty>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-line bg-subtle text-left text-xs text-muted">
                  <th className="w-8 px-3 py-2.5" />
                  <th className="px-3 py-2.5 font-medium">agent</th>
                  <th className="px-3 py-2.5 font-medium">task</th>
                  <th className="px-3 py-2.5 font-medium">steps</th>
                  <th className="px-3 py-2.5 font-medium">blocked</th>
                  <th className="px-3 py-2.5 font-medium">escalated</th>
                  <th className="px-3 py-2.5 text-right font-medium">last activity</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => {
                  const isOpen = expanded === s.id;
                  const blocked = s.steps.filter((d) => d.verdict === "BLOCK").length;
                  const escalated = s.steps.filter((d) => d.verdict === "ESCALATE").length;
                  return (
                    <Fragment key={s.id}>
                      <tr
                        onClick={() => setExpanded(isOpen ? null : s.id)}
                        className="cursor-pointer border-b border-line last:border-0 hover:bg-hover"
                        aria-expanded={isOpen}
                      >
                        <td className="px-3 py-3 text-muted">{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                        <td className="px-3 py-3 whitespace-nowrap">
                          <p>{s.agent}</p>
                          <p className="font-mono text-[11px] text-faint">{s.id.length > 22 ? `${s.id.slice(0, 22)}…` : s.id}</p>
                        </td>
                        <td className="max-w-[360px] px-3 py-3">
                          <p className="truncate text-muted">{s.task ?? "–"}</p>
                        </td>
                        <td className="px-3 py-3 tabular-nums">{s.steps.length}</td>
                        <td className={`px-3 py-3 tabular-nums ${blocked ? "text-block" : "text-faint"}`}>{blocked}</td>
                        <td className={`px-3 py-3 tabular-nums ${escalated ? "text-escalate" : "text-faint"}`}>{escalated}</td>
                        <td className="px-3 py-3 text-right whitespace-nowrap text-muted">{timeAgo(s.last, now) || clock(s.last)}</td>
                      </tr>
                      {isOpen && (
                        <tr className="border-b border-line bg-subtle last:border-0">
                          <td />
                          <td colSpan={6} className="px-3 py-3">
                            <ol className="space-y-1 border-l border-line-strong pl-4">
                              {s.steps.map((d) => (
                                <li key={d.id}>
                                  <button
                                    type="button"
                                    onClick={() => open(d.id)}
                                    className="flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left hover:bg-hover"
                                  >
                                    <span className="w-16 font-mono text-[11px] text-faint">{clock(d.created_at)}</span>
                                    <VerdictPill verdict={d.verdict} />
                                    <span className="font-mono text-xs">{d.tool}</span>
                                    <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted">{actionSummary(d)}</span>
                                  </button>
                                </li>
                              ))}
                            </ol>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
