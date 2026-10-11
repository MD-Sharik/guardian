"use client";

import { ExternalLink, Plug } from "lucide-react";
import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { Card, ModeBadge, SectionLabel } from "@/components/ui";
import { useGuardian } from "@/lib/guardian-context";
import { agentSources } from "@/lib/setup";
import type { Mode } from "@/lib/types";

interface Item {
  name: string;
  role: string;
  mode: Mode | undefined;
  detail?: string;
  docs: string;
  setup: string;
}

export default function Integrations() {
  const { health, decisions } = useGuardian();
  const sources = agentSources(decisions);
  const host = (url?: string) => url?.replace(/^https?:\/\//, "");

  const services: Item[] = [
    {
      name: "Jev",
      role: "Answers typed safety questions about every action",
      mode: health?.modes.jev,
      detail: health ? `${health.jev_model} via ${host(health.jev_base_url)}` : undefined,
      docs: "https://opencode.ai/docs/zen/",
      setup: "/setup#jev",
    },
    {
      name: "NeatLogs",
      role: "Traces every decision with spans for each step",
      mode: health?.modes.neatlogs,
      detail: health?.modes.neatlogs === "live" ? `project ${health.neatlogs_project}` : undefined,
      docs: "https://docs.neatlogs.com",
      setup: "/setup#neatlogs",
    },
    {
      name: "Entire",
      role: "Supplies the agent's captured session for blocked actions",
      mode: health?.modes.entire,
      detail: health?.modes.entire === "live" ? "entire CLI on PATH" : undefined,
      docs: "https://docs.entire.io",
      setup: "/setup#entire",
    },
    {
      name: "Explainer",
      role: "Writes the plain-English explanation of blocked and escalated actions",
      mode: health?.modes.explainer,
      detail: health?.modes.explainer === "live" ? health.llm_model : undefined,
      docs: "https://modal.com/docs",
      setup: "/setup#explainer",
    },
  ];
  const agents: Item[] = [
    {
      name: "Antigravity",
      role: "PreToolUse / PostToolUse hook in .agents/hooks.json",
      mode: sources.antigravity ? "live" : "off",
      detail: sources.antigravity ? `${sources.antigravity} actions checked` : "no actions seen yet",
      docs: "https://antigravity.google/docs/hooks/",
      setup: "/setup#agent",
    },
    {
      name: "Python SDK and HTTP API",
      role: "protect() for LangChain / LangGraph tools, or POST /evaluate",
      mode: sources.sdk ? "live" : "off",
      detail: sources.sdk ? `${sources.sdk} actions checked` : "no actions seen yet",
      docs: "https://python.langchain.com/docs/concepts/tools/",
      setup: "/setup#agent",
    },
  ];

  return (
    <>
      <PageHeader icon={Plug} title="integrations" showRange={false} />
      <div className="mx-auto max-w-4xl space-y-10 px-6 py-8">
        <section>
          <SectionLabel>services</SectionLabel>
          <Grid items={services} />
        </section>
        <section>
          <SectionLabel>agents</SectionLabel>
          <Grid items={agents} />
        </section>
      </div>
    </>
  );
}

function Grid({ items }: { items: Item[] }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {items.map((item) => (
        <Card key={item.name} className="flex flex-col p-5">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-[15px] font-medium">{item.name}</h3>
            <ModeBadge mode={item.mode} />
          </div>
          <p className="mt-1 text-sm text-muted">{item.role}</p>
          {item.detail && <p className="mt-3 font-mono text-xs">{item.detail}</p>}
          <div className="mt-auto flex items-center gap-4 pt-4 text-sm">
            <Link href={item.setup} className="text-info hover:underline">
              {item.mode === "live" ? "settings" : "set up"}
            </Link>
            <a href={item.docs} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-muted hover:text-ink">
              docs <ExternalLink size={12} />
            </a>
          </div>
        </Card>
      ))}
    </div>
  );
}
