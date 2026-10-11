"use client";

import { ListChecks, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { DecisionTable } from "@/components/DecisionTable";
import { PageHeader } from "@/components/PageHeader";
import { Empty } from "@/components/ui";
import { actionSummary } from "@/lib/format";
import { useGuardian } from "@/lib/guardian-context";
import type { Verdict } from "@/lib/types";

const FILTERS: { value: Verdict | "ALL"; label: string }[] = [
  { value: "ALL", label: "all" },
  { value: "ALLOW", label: "allowed" },
  { value: "BLOCK", label: "blocked" },
  { value: "ESCALATE", label: "escalated" },
];

export default function Decisions() {
  const { inRange, decisions, clear } = useGuardian();
  const [filter, setFilter] = useState<Verdict | "ALL">("ALL");
  const [query, setQuery] = useState("");

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return inRange.filter(
      (d) =>
        (filter === "ALL" || d.verdict === filter) &&
        (!q || [d.tool, d.agent_name, actionSummary(d), d.session_id ?? ""].some((s) => s.toLowerCase().includes(q))),
    );
  }, [inRange, filter, query]);

  const clearButton = decisions.length > 0 && (
    <button
      type="button"
      onClick={() => {
        if (window.confirm("Delete the whole decision history? This can't be undone.")) clear();
      }}
      className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-muted hover:bg-hover hover:text-block"
    >
      <Trash2 size={14} /> clear history
    </button>
  );

  return (
    <>
      <PageHeader icon={ListChecks} title="decisions" actions={clearButton} />
      <div className="space-y-4 px-6 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex gap-1 rounded-lg border border-line bg-subtle p-1">
            {FILTERS.map((f) => {
              const n = f.value === "ALL" ? inRange.length : inRange.filter((d) => d.verdict === f.value).length;
              return (
                <button
                  key={f.value}
                  type="button"
                  onClick={() => setFilter(f.value)}
                  className={`rounded-md px-3 py-1 text-sm ${filter === f.value ? "bg-surface shadow-sm" : "text-muted hover:text-ink"}`}
                >
                  {f.label} <span className="text-faint tabular-nums">{n}</span>
                </button>
              );
            })}
          </div>
          <label className="flex min-w-[260px] flex-1 items-center gap-2 rounded-lg border border-line px-3 py-1.5 sm:max-w-sm">
            <Search size={14} className="text-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search tool, agent, command, session"
              className="w-full bg-transparent text-sm outline-none placeholder:text-faint"
            />
          </label>
        </div>

        {shown.length ? (
          <DecisionTable decisions={shown} />
        ) : (
          <Empty icon={<ListChecks size={22} />} title={inRange.length ? "Nothing matches" : "No decisions in this range"}>
            {inRange.length
              ? "Try another filter or search."
              : "Every tool call your agents make shows up here before it runs."}
          </Empty>
        )}
      </div>
    </>
  );
}
