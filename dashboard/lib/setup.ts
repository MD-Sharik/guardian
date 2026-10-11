import type { Decision, Health } from "./types";

export type StepId = "jev" | "agent" | "neatlogs" | "explainer" | "entire";

export interface SetupStep {
  id: StepId;
  title: string;
  done: boolean;
}

/** The onboarding checklist, ticked off from what the service reports and what it has seen. */
export function setupSteps(health: Health | null, decisions: Decision[]): SetupStep[] {
  const live = (key: keyof Health["modes"]) => health?.modes[key] === "live";
  return [
    { id: "jev", title: "Connect Jev", done: live("jev") },
    { id: "agent", title: "Connect your agent", done: decisions.length > 0 },
    { id: "neatlogs", title: "Trace decisions to NeatLogs", done: live("neatlogs") },
    { id: "explainer", title: "Explain blocked actions", done: live("explainer") },
    { id: "entire", title: "Read agent sessions from Entire", done: live("entire") },
  ];
}

export function agentSources(decisions: Decision[]): { antigravity: number; sdk: number } {
  let antigravity = 0;
  for (const d of decisions) if (d.context.metadata?.source === "antigravity") antigravity++;
  return { antigravity, sdk: decisions.length - antigravity };
}
