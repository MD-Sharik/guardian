"use client";

import { actionSummary, clock, timeAgo } from "@/lib/format";
import { useGuardian } from "@/lib/guardian-context";
import type { Decision } from "@/lib/types";
import { ConfidenceBar, StatusNote, VerdictPill } from "./ui";

export function DecisionTable({ decisions, showAgent = true }: { decisions: Decision[]; showAgent?: boolean }) {
  const { open, now, health } = useGuardian();
  const threshold = health?.thresholds.min_confidence;
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-line bg-subtle text-left text-xs text-muted">
            <th className="px-4 py-2.5 font-medium">time</th>
            {showAgent && <th className="px-4 py-2.5 font-medium">agent</th>}
            <th className="px-4 py-2.5 font-medium">tool</th>
            <th className="px-4 py-2.5 font-medium">action</th>
            <th className="px-4 py-2.5 font-medium">verdict</th>
            <th className="px-4 py-2.5 font-medium">confidence</th>
            <th className="px-4 py-2.5 text-right font-medium">jev</th>
          </tr>
        </thead>
        <tbody>
          {decisions.map((d) => (
            <tr
              key={d.id}
              onClick={() => open(d.id)}
              className="row-in cursor-pointer border-b border-line last:border-0 hover:bg-hover"
            >
              <td className="px-4 py-2.5 whitespace-nowrap text-muted" title={clock(d.created_at)}>
                {timeAgo(d.created_at, now) || clock(d.created_at)}
              </td>
              {showAgent && <td className="px-4 py-2.5 whitespace-nowrap">{d.agent_name}</td>}
              <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap">{d.tool}</td>
              <td className="max-w-[340px] px-4 py-2.5">
                <button type="button" className="block w-full truncate text-left font-mono text-xs text-muted" onClick={() => open(d.id)}>
                  {actionSummary(d)}
                </button>
              </td>
              <td className="px-4 py-2.5 whitespace-nowrap">
                <div className="flex items-center gap-2">
                  <VerdictPill verdict={d.verdict} />
                  <StatusNote status={d.status} />
                </div>
              </td>
              <td className="px-4 py-2.5">
                <ConfidenceBar value={d.confidence} threshold={threshold} />
              </td>
              <td className="px-4 py-2.5 text-right font-mono text-xs whitespace-nowrap text-muted tabular-nums">
                {d.jev ? `${Math.round(d.jev.latency_ms)} ms` : d.checked === false ? "fast path" : "down"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
