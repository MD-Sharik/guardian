"use client";

import { Calendar, type LucideIcon, RefreshCw } from "lucide-react";
import { type ReactNode, useState } from "react";
import { RANGES, type Range, useGuardian } from "@/lib/guardian-context";

export function PageHeader({ icon: Icon, title, showRange = true, actions }: {
  icon: LucideIcon;
  title: string;
  showRange?: boolean;
  actions?: ReactNode;
}) {
  const { range, setRange, refresh } = useGuardian();
  const [spinning, setSpinning] = useState(false);

  async function reload() {
    setSpinning(true);
    try {
      await refresh();
    } finally {
      setTimeout(() => setSpinning(false), 400);
    }
  }

  return (
    <header className="flex h-[60px] items-center gap-3 border-b border-line px-6">
      <Icon size={18} strokeWidth={1.75} className="text-ink" />
      <h1 className="text-[17px] font-medium">{title}</h1>
      <div className="ml-auto flex items-center gap-2">
        {actions}
        {showRange && (
          <label className="relative flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm hover:bg-hover">
            <Calendar size={14} className="text-muted" />
            <select
              value={range}
              onChange={(e) => setRange(e.target.value as Range)}
              className="cursor-pointer appearance-none bg-transparent pr-1 outline-none"
              aria-label="Time range"
            >
              {RANGES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          type="button"
          onClick={reload}
          className="rounded-lg p-2 text-muted hover:bg-hover hover:text-ink"
          aria-label="Refresh"
        >
          <RefreshCw size={16} strokeWidth={1.75} className={spinning ? "animate-spin" : ""} />
        </button>
      </div>
    </header>
  );
}
