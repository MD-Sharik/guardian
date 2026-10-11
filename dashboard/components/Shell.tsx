"use client";

import {
  Ban,
  Hand,
  House,
  ListChecks,
  Moon,
  Plug,
  Radio,
  Rocket,
  Settings,
  SlidersHorizontal,
  Sun,
  Workflow,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { useGuardian } from "@/lib/guardian-context";
import { setupSteps } from "@/lib/setup";
import { DecisionDrawer } from "./DecisionDrawer";

const NAV = [
  { href: "/", label: "home", icon: House },
  { href: "/decisions", label: "decisions", icon: ListChecks },
  { href: "/approvals", label: "approvals", icon: Hand },
  { href: "/sessions", label: "sessions", icon: Workflow },
  { href: "/policy", label: "policy", icon: SlidersHorizontal },
  { href: "/integrations", label: "integrations", icon: Plug },
];

export function Shell({ children }: { children: ReactNode }) {
  const { selected } = useGuardian();
  return (
    <div className="flex h-full gap-0 p-2">
      <div className="flex min-w-0 flex-1 overflow-hidden rounded-xl border border-line bg-surface">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto">
          <MobileNav />
          {children}
        </main>
      </div>
      <Toasts />
      {selected && <DecisionDrawer d={selected} />}
    </div>
  );
}

function Sidebar() {
  const pathname = usePathname();
  const { health, decisions, connection } = useGuardian();
  const steps = setupSteps(health, decisions);
  const done = steps.filter((s) => s.done).length;
  const pending = decisions.filter((d) => d.status === "pending").length;
  const linkClass = (active: boolean) =>
    `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
      active ? "border border-line-strong bg-surface text-ink shadow-sm" : "border border-transparent text-muted hover:bg-hover hover:text-ink"
    }`;

  return (
    <aside className="hidden w-[248px] shrink-0 flex-col border-r border-line px-4 py-4 md:flex">
      <div className="flex items-center gap-2.5 px-1 pb-4">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-ink text-sm font-semibold text-surface">G</span>
        <span className="text-sm font-semibold">Guardian</span>
        <span
          className={`ml-auto h-2 w-2 rounded-full ${connection === "live" ? "bg-allow" : connection === "connecting" ? "bg-escalate" : "bg-block"}`}
          title={connection === "live" ? "Streaming live" : connection}
        />
      </div>

      <nav className="space-y-1">
        <Link
          href="/setup"
          className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-sm transition-colors ${
            pathname === "/setup"
              ? "border-accent-line bg-accent text-ink"
              : done < steps.length
                ? "border-accent-line bg-accent/70 text-ink hover:bg-accent"
                : "border-transparent text-muted hover:bg-hover hover:text-ink"
          }`}
        >
          <Rocket size={16} strokeWidth={1.75} />
          setup
          <span className="ml-auto rounded-md bg-surface/80 px-1.5 py-0.5 text-xs text-muted tabular-nums">
            {done}/{steps.length}
          </span>
        </Link>
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href} className={linkClass(pathname === href)}>
            <Icon size={16} strokeWidth={1.75} />
            {label}
            {href === "/approvals" && pending > 0 && (
              <span className="ml-auto rounded-full bg-escalate px-1.5 text-xs font-medium text-surface tabular-nums">
                {pending}
              </span>
            )}
          </Link>
        ))}
      </nav>

      <div className="mt-auto space-y-1 pt-4">
        <div className="flex items-center gap-3 px-3 py-2 text-sm text-muted">
          <Radio size={16} strokeWidth={1.75} />
          {connection === "live" ? "streaming" : connection === "connecting" ? "connecting…" : "service offline"}
        </div>
        <div className="flex items-center gap-2 border-t border-line px-1 pt-3">
          <span className="grid h-7 w-7 place-items-center rounded-full bg-hover text-xs font-medium text-muted">L</span>
          <span className="text-sm">local</span>
          <Link href="/integrations" className="ml-auto rounded-md p-1.5 text-muted hover:bg-hover hover:text-ink" aria-label="Integrations">
            <Settings size={16} strokeWidth={1.75} />
          </Link>
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}

/** On small screens the sidebar is hidden; this scrollable bar replaces it. */
function MobileNav() {
  const pathname = usePathname();
  const { decisions } = useGuardian();
  const pending = decisions.filter((d) => d.status === "pending").length;
  return (
    <nav className="flex gap-1 overflow-x-auto border-b border-line px-3 py-2 md:hidden" aria-label="Pages">
      {[{ href: "/setup", label: "setup", icon: Rocket }, ...NAV].map(({ href, label, icon: Icon }) => (
        <Link
          key={href}
          href={href}
          className={`flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm ${
            pathname === href ? "bg-hover text-ink" : "text-muted"
          }`}
        >
          <Icon size={14} strokeWidth={1.75} />
          {label}
          {href === "/approvals" && pending > 0 && (
            <span className="rounded-full bg-escalate px-1.5 text-xs text-surface">{pending}</span>
          )}
        </Link>
      ))}
      <span className="ml-auto flex shrink-0 items-center pl-2">
        <ThemeToggle />
      </span>
    </nav>
  );
}

function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => setDark(document.documentElement.classList.contains("dark")), []);
  function toggle() {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("guardian-theme", next ? "dark" : "light");
    } catch {
      // storage blocked: the toggle still works for this visit
    }
    setDark(next);
  }
  return (
    <button
      type="button"
      onClick={toggle}
      className="rounded-md p-1.5 text-muted hover:bg-hover hover:text-ink"
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {dark ? <Sun size={16} strokeWidth={1.75} /> : <Moon size={16} strokeWidth={1.75} />}
    </button>
  );
}

function Toasts() {
  const { toasts, dismiss, open } = useGuardian();
  return (
    <div
      className="pointer-events-none fixed right-5 bottom-5 z-40 flex w-[min(360px,calc(100vw-2.5rem))] flex-col-reverse gap-2"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`toast-in pointer-events-auto flex gap-3 rounded-xl border bg-surface p-3 shadow-lg ${
            t.tone === "block" ? "border-block/40" : "border-escalate/40"
          }`}
        >
          <span className={`mt-0.5 ${t.tone === "block" ? "text-block" : "text-escalate"}`}>
            {t.tone === "block" ? <Ban size={16} /> : <Hand size={16} />}
          </span>
          <button
            type="button"
            className="min-w-0 flex-1 text-left"
            onClick={() => {
              open(t.decisionId);
              dismiss(t.id);
            }}
          >
            <p className="text-sm font-medium">{t.title}</p>
            <p className="truncate font-mono text-xs text-muted">{t.body}</p>
          </button>
          <button type="button" onClick={() => dismiss(t.id)} className="self-start text-faint hover:text-ink" aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
