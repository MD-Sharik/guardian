"use client";

import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { actionSummary } from "./format";
import type { Decision, Health } from "./types";

export const API = process.env.NEXT_PUBLIC_GUARDIAN_URL ?? "http://127.0.0.1:8000";

export type Connection = "connecting" | "live" | "offline";
export type Range = "1h" | "24h" | "7d" | "all";

export const RANGES: { value: Range; label: string; ms: number }[] = [
  { value: "1h", label: "Last hour", ms: 3_600_000 },
  { value: "24h", label: "Last 24 hours", ms: 86_400_000 },
  { value: "7d", label: "Last 7 days", ms: 604_800_000 },
  { value: "all", label: "All time", ms: Infinity },
];

export interface Toast {
  id: string;
  decisionId: string;
  tone: "block" | "escalate";
  title: string;
  body: string;
}

interface GuardianState {
  decisions: Decision[]; // newest first
  inRange: Decision[];
  byId: Record<string, Decision>;
  health: Health | null;
  connection: Connection;
  now: number; // ms; 0 until mounted (so nothing time-based is baked into the prerender)
  range: Range;
  setRange: (range: Range) => void;
  selected: Decision | null;
  open: (id: string) => void;
  close: () => void;
  resolve: (id: string, approve: boolean) => Promise<void>;
  explain: (id: string) => Promise<void>;
  clear: () => Promise<void>;
  refresh: () => Promise<void>;
  toasts: Toast[];
  dismiss: (id: string) => void;
}

const Ctx = createContext<GuardianState | null>(null);

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, { headers: { "content-type": "application/json" }, ...init });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export function GuardianProvider({ children }: { children: ReactNode }) {
  const [byId, setById] = useState<Record<string, Decision>>({});
  const [health, setHealth] = useState<Health | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [now, setNow] = useState(0);
  const [range, setRange] = useState<Range>("7d");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seen = useRef(new Set<string>());

  const refresh = useCallback(async () => {
    const [h, list] = await Promise.all([call<Health>("/health"), call<Decision[]>("/decisions?limit=1000")]);
    setHealth(h);
    list.forEach((d) => seen.current.add(d.id));
    setById(Object.fromEntries(list.map((d) => [d.id, d])));
  }, []);

  const dismiss = useCallback((id: string) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const close = useCallback(() => setSelectedId(null), []);

  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    refresh().catch(() => setConnection("offline"));
    const es = new EventSource(`${API}/stream`);
    es.onopen = () => {
      setConnection("live");
      refresh().catch(() => setConnection("offline")); // fill anything missed while disconnected
    };
    es.onerror = () => setConnection(es.readyState === EventSource.CLOSED ? "offline" : "connecting");
    es.addEventListener("decision", (event) => {
      const d = JSON.parse((event as MessageEvent).data) as Decision;
      if (!seen.current.has(d.id)) {
        seen.current.add(d.id);
        if (d.verdict !== "ALLOW") {
          const toast: Toast = {
            id: `${d.id}-${Date.now()}`,
            decisionId: d.id,
            tone: d.verdict === "BLOCK" ? "block" : "escalate",
            title: d.verdict === "BLOCK" ? `Blocked ${d.tool}` : `${d.agent_name} is waiting for your approval`,
            body: actionSummary(d),
          };
          setToasts((t) => [toast, ...t].slice(0, 4));
          setTimeout(() => setToasts((t) => t.filter((x) => x.id !== toast.id)), 8000);
        }
      }
      setById((prev) => ({ ...prev, [d.id]: d }));
    });
    es.addEventListener("reset", () => {
      seen.current.clear();
      setById({});
    });
    return () => es.close();
  }, [refresh]);

  const resolve = useCallback(async (id: string, approve: boolean) => {
    const d = await call<Decision>(`/${approve ? "approve" : "reject"}/${id}`, {
      method: "POST",
      body: JSON.stringify({ by: "dashboard" }),
    });
    setById((prev) => ({ ...prev, [d.id]: d }));
  }, []);

  const explain = useCallback(async (id: string) => {
    setById((prev) => (prev[id] ? { ...prev, [id]: { ...prev[id], explanation_pending: true } } : prev));
    const d = await call<Decision>(`/decisions/${id}/explain`, { method: "POST" });
    setById((prev) => ({ ...prev, [d.id]: d }));
  }, []);

  const clear = useCallback(async () => {
    await call("/decisions", { method: "DELETE" });
  }, []);

  const decisions = useMemo(() => Object.values(byId).sort((a, b) => b.created_at - a.created_at), [byId]);
  const inRange = useMemo(() => {
    const ms = RANGES.find((r) => r.value === range)!.ms;
    if (!now || ms === Infinity) return decisions;
    return decisions.filter((d) => d.created_at * 1000 >= now - ms);
  }, [decisions, range, now]);

  const value: GuardianState = {
    decisions,
    inRange,
    byId,
    health,
    connection,
    now,
    range,
    setRange,
    selected: selectedId ? (byId[selectedId] ?? null) : null,
    open: setSelectedId,
    close,
    resolve,
    explain,
    clear,
    refresh,
    toasts,
    dismiss,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useGuardian(): GuardianState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useGuardian must be used inside <GuardianProvider>");
  return ctx;
}
