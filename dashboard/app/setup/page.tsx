"use client";

import { Check, ExternalLink, Rocket } from "lucide-react";
import { type ReactNode, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { CodeBlock } from "@/components/ui";
import { API, useGuardian } from "@/lib/guardian-context";
import { type SetupStep, type StepId, agentSources, setupSteps } from "@/lib/setup";

export default function Setup() {
  const { health, decisions } = useGuardian();
  const steps = setupSteps(health, decisions);
  const done = steps.filter((s) => s.done).length;

  return (
    <>
      <PageHeader icon={Rocket} title="setup" showRange={false} />
      <div className="mx-auto max-w-3xl px-6 py-8">
        <div className="mb-8">
          <h2 className="text-xl font-medium">Put Guardian in front of your agent</h2>
          <p className="mt-1 text-sm text-muted">
            {done} of {steps.length} done. Steps tick off on their own as Guardian sees each piece working. After
            editing <code className="font-mono text-ink">.env</code>, restart with{" "}
            <code className="font-mono text-ink">python dev.py</code> and check with{" "}
            <code className="font-mono text-ink">python dev.py doctor</code>.
          </p>
          <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-line">
            <div className="h-full rounded-full bg-allow transition-all" style={{ width: `${(done / steps.length) * 100}%` }} />
          </div>
        </div>

        <ol className="space-y-4">
          {steps.map((step, i) => (
            <Step key={step.id} index={i + 1} step={step}>
              <StepBody id={step.id} />
            </Step>
          ))}
        </ol>
      </div>
    </>
  );
}

function Step({ index, step, children }: { index: number; step: SetupStep; children: ReactNode }) {
  return (
    <li id={step.id} className="scroll-mt-6 rounded-xl border border-line bg-surface">
      <div className="flex items-center gap-3 px-5 py-4">
        <span
          className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-medium ${
            step.done ? "bg-allow text-surface" : "border border-line-strong text-muted"
          }`}
        >
          {step.done ? <Check size={13} strokeWidth={3} /> : index}
        </span>
        <h3 className="text-[15px] font-medium">{step.title}</h3>
        <span className={`ml-auto text-xs ${step.done ? "text-allow" : "text-muted"}`}>{step.done ? "done" : "to do"}</span>
      </div>
      <div className="space-y-3 border-t border-line px-5 py-4 text-sm">{children}</div>
    </li>
  );
}

function StepBody({ id }: { id: StepId }) {
  const { health, decisions } = useGuardian();
  switch (id) {
    case "jev":
      return (
        <>
          <p className="text-muted">
            Jev answers Guardian&apos;s typed questions about every action. Guardian won&apos;t start without it. Use an
            OpenCode key (opencode.ai/console → Keys) or a TypeSafe key.
          </p>
          {health?.modes.jev === "live" && (
            <p className="text-allow">
              Connected: {health.jev_model} via {health.jev_base_url.replace(/^https?:\/\//, "")}
            </p>
          )}
          <CodeBlock label=".env" code={"JEV_API_KEY=<your key>\nJEV_BASE_URL=https://opencode.ai/zen\nJEV_MODEL=jev-1.13-free"} />
        </>
      );
    case "agent":
      return <AgentStep count={decisions.length} sources={agentSources(decisions)} />;
    case "neatlogs":
      return (
        <>
          <p className="text-muted">Every decision becomes a trace with spans for Jev, the policy, Entire and the explainer.</p>
          {health?.modes.neatlogs === "live" && (
            <a
              href={health.neatlogs_app_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-info hover:underline"
            >
              Open project &ldquo;{health.neatlogs_project}&rdquo; in NeatLogs <ExternalLink size={13} />
            </a>
          )}
          <CodeBlock label=".env" code={"NEATLOGS_API_KEY=<your key>\nNEATLOGS_PROJECT=guardian"} />
        </>
      );
    case "explainer":
      return (
        <>
          <p className="text-muted">
            When an action is blocked or escalated, an LLM explains what the agent tried and why, using its Entire session.
            Any OpenAI-compatible endpoint works; this is set up for DeepSeek on Modal.
          </p>
          {health?.modes.explainer === "live" && <p className="text-allow">Connected: {health.llm_model}</p>}
          <CodeBlock
            label=".env"
            code={
              "LLM_BASE_URL=https://<workspace>--<endpoint>.modal.direct/v1\nLLM_MODEL=deepseek-ai/DeepSeek-V4.1-Flash\nMODAL_PROXY_TOKEN_ID=wk-...\nMODAL_PROXY_TOKEN_SECRET=ws-..."
            }
          />
        </>
      );
    case "entire":
      return (
        <>
          <p className="text-muted">
            Entire records your coding agent&apos;s sessions. Guardian reads the session behind each blocked action so the
            explanation reflects what the agent was actually trying to do.
          </p>
          <CodeBlock label="PowerShell" code="irm https://entire.io/install.ps1 | iex" />
          <CodeBlock label="in your agent's project" code="entire enable --agent antigravity" />
        </>
      );
  }
}

const TABS = ["Antigravity", "Python SDK", "HTTP API"] as const;

function AgentStep({ count, sources }: { count: number; sources: { antigravity: number; sdk: number } }) {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Antigravity");
  return (
    <>
      <p className="text-muted">Guardian checks each tool call before it runs. Pick how your agent connects.</p>
      {count > 0 && (
        <p className="text-allow">
          Receiving actions: {sources.antigravity} from Antigravity, {sources.sdk} from SDK or HTTP clients.
        </p>
      )}
      <div className="flex gap-1 rounded-lg border border-line bg-subtle p-1" role="tablist">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`flex-1 rounded-md px-3 py-1.5 text-sm ${tab === t ? "bg-surface shadow-sm" : "text-muted hover:text-ink"}`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Antigravity" && (
        <>
          <p className="text-muted">
            Adds a hook to the project&apos;s <code className="font-mono text-ink">.agents/hooks.json</code>. Every tool call
            Antigravity makes is allowed, denied with a reason, or held for your approval here.
          </p>
          <CodeBlock label="from the Guardian folder" code="python dev.py install-antigravity C:\path\to\your\project" />
          <CodeBlock label="in your project" code="agy" />
          <p className="text-xs text-muted">Antigravity only loads workspace hooks for trusted folders, so trust it when asked.</p>
        </>
      )}

      {tab === "Python SDK" && (
        <>
          <p className="text-muted">Wraps LangChain or LangGraph tools, or plain functions. Blocked calls return a reason instead of running.</p>
          <CodeBlock label="install" code="pip install -e ./guardian-sdk" />
          <CodeBlock
            label="python"
            code={`from guardian import protect

tools = protect(tools, agent_name="my-agent", task="what the agent is doing")
# optional, per step: tools.guardian.set_context(reasoning="why it's about to act")`}
          />
        </>
      )}

      {tab === "HTTP API" && (
        <>
          <p className="text-muted">
            For any language. Run the tool only when <code className="font-mono text-ink">status</code> is{" "}
            <code className="font-mono text-ink">allowed</code>; if it&apos;s <code className="font-mono text-ink">pending</code>,
            long-poll <code className="font-mono text-ink">GET /decisions/&#123;id&#125;/wait</code> until it&apos;s approved or rejected.
          </p>
          <CodeBlock
            label="curl"
            code={`curl -X POST ${API}/evaluate \\
  -H "Content-Type: application/json" \\
  -d '{
    "agent_name": "my-agent",
    "session_id": "run-42",
    "tool": "run_shell",
    "args": {"command": "rm -rf ./build"},
    "context": {"task": "Clean the build output", "reasoning": "Stale artifacts break the tests"}
  }'`}
          />
          <CodeBlock label="response (trimmed)" code={`{"id": "a1b2c3", "verdict": "ESCALATE", "status": "pending", "confidence": 0.31, "reasons": ["…"]}`} />
        </>
      )}
    </>
  );
}
