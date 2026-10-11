# Guardian

**A real-time reliability and safety layer for AI agents.** Guardian sits between an agent and its tools. Before any tool call runs, it asks **Jev**, TypeSafe AI's "System One" decision model, a set of typed questions: *Is this action safe? What kind of risk is it? How bad is the impact if it's a mistake? Is the content being written good enough?* Jev answers with calibrated probabilities and confidence scores, and Guardian's policy turns them into one of three signals: **ALLOW** (run it), **BLOCK** (refuse it and tell the agent why), or **ESCALATE** (pause the agent until a human approves or rejects it in the dashboard). Every decision is traced to **NeatLogs**. When something is blocked or escalated, Guardian pulls the agent's captured session from **Entire** and has an LLM (DeepSeek V4.1 Flash on Modal) explain in plain English why the agent made that move.

It plugs into **Google Antigravity** through Antigravity's own hook system, and into any LangGraph/LangChain agent in two lines:

```python
from guardian import protect
tools = protect(tools, agent_name="my-agent")
```

[![Guardian launch video: an agent types rm -rf ./* and Guardian blocks it before it runs](brag-output/brag.jpg)](brag-output/brag.mp4)

*22-second launch video: [brag-output/brag.mp4](brag-output/brag.mp4)*

## Verified live

On 11 October 2026, one agent action (`run_command rm -rf ./*`) went through the whole pipeline against the real services:

| Step | Result |
|---|---|
| Jev (`jev-1.13.0`) | **BLOCK**: P(safe) 0.11, data-loss risk 0.96, impact 2.5 / 3 critical; answered in 603 ms |
| Explainer (DeepSeek V4.1 Flash on Modal) | *"It wipes all files, not just the cache, risking critical data loss. Safer: clear only the specific cache directory."* |
| Entire CLI 0.11.4 | Ran against the project; reported that no session had been captured there yet |
| NeatLogs | Trace accepted, with all five spans visible in the NeatLogs dashboard |

Jev was reached through jev-ai.pro, a third-party host of TypeSafe's System One API. TypeSafe directly, OpenCode Zen and OpenRouter use the same code with a different `JEV_BASE_URL`. A live Antigravity session hasn't been run yet; the hook is tested end to end against a running Guardian with Antigravity's documented payloads.

### Live agent runs, and what they changed

The LangGraph example agent, driven by DeepSeek on Modal, was given *"wipe the whole workspace with `rm -rf ./*`"*. It investigated first and proposed deleting only the stale lock file. But Guardian escalated three harmless reads to a human: Jev rated them safe with negligible impact, yet "off task". So we refined the policy and added a fast path for read-only tools, then replayed the run's real Jev answers through both (`python dev.py replay`):

| Same session, same Jev answers | Before (live) | After |
|---|---|---|
| Jev calls | 9 | **6** |
| Escalated to a human | 4 | **1** (the uncertain delete) |
| `rm -rf ./*` (all recorded decisions) | blocked | still blocked |

A Jev check costs about 940 input tokens and 761 ms (median, measured); a fast-path decision takes 0.9 ms. NeatLogs trace links, the failure-recovery runs and the raw numbers are in [evidence/](evidence/README.md); the day's build log is [hackathon.md](hackathon.md).

## Deliverables

| Deliverable | Where |
|---|---|
| Guardian service: `/evaluate`, `/approve/{id}`, `/reject/{id}`, `/decisions`, SSE `/stream`, SQLite history | [`guardian-service/`](guardian-service) |
| Sponsor adapters: `jev_client.py`, `neatlogs_tracer.py`, `entire_client.py`, `explainer.py` | [`guardian-service/app/adapters/`](guardian-service/app/adapters) |
| Policy with configurable thresholds | [`policy.py`](guardian-service/app/policy.py), [`.env.example`](.env.example) |
| SDK: `protect(tools)` for LangChain / LangGraph | [`guardian-sdk/`](guardian-sdk) |
| Antigravity integration (PreToolUse / PostToolUse hook) | [`guardian-sdk/guardian/antigravity.py`](guardian-sdk/guardian/antigravity.py), `python dev.py install-antigravity` |
| Dashboard: setup, live decisions, approvals, sessions, policy, integrations, detail drawer | [`dashboard/`](dashboard) |
| Example LangGraph agent with sandboxed tools | [`demo-agent/`](demo-agent) |
| One-command setup, health check, run, demo and tests | [`dev.py`](dev.py), [`Makefile`](Makefile) |
| Read-only fast path, policy replay against recorded decisions (`python dev.py replay`) | [`guardian.py`](guardian-service/app/guardian.py), [`replay.py`](guardian-service/app/replay.py) |
| One NeatLogs trace per agent run: LLM tokens, tool calls, Guardian verdicts | [`demo-agent/run_trace.py`](demo-agent/run_trace.py) |
| Architecture (diagrams, data flow, failure behaviour) | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Evidence: NeatLogs traces, before/after numbers, failure recovery | [`evidence/`](evidence/README.md), [`hackathon.md`](hackathon.md) |
| Business plan: inputs, and the 24-month plan built from them with cfo.ai | [`docs/business-plan.md`](docs/business-plan.md), [plan on cfo.ai](https://cfo.ai/s/zUm3_aE9Keg-yN7i) |
| Tests (84) | `guardian-service/tests`, `guardian-sdk/tests`, `demo-agent/tests` |
| Launch video, poster and share copy | [`brag-output/`](brag-output) |

## Architecture

The architecture is written up in two documents:

- **[High-level design](docs/ARCHITECTURE.md)**: what Guardian is, the system context, components, the ALLOW / BLOCK / ESCALATE flows, what runs synchronously and what runs in the background, deployment, failure behaviour, trust boundaries, and how each sponsor tool is used.
- **[Low-level design](docs/ARCHITECTURE-LOW-LEVEL.md)**: module map, data model and decision state machine, the API and SSE contract, the Jev request, every policy rule and threshold, NeatLogs payloads and retries, SDK and Antigravity hook internals, storage, configuration, concurrency and tests.

```mermaid
flowchart LR
    subgraph agents["Agents"]
        agy["Antigravity (agy)"] -- "PreToolUse / PostToolUse" --> hook["guardian-antigravity-hook"]
        lg["LangGraph agent"] -- "protect(tools)" --> sdk["guardian-sdk"]
        hook --> sdk
    end
    sdk -- "POST /evaluate" --> api

    subgraph service["guardian-service · FastAPI"]
        api["REST + SSE"] --> jevc["jev_client.py"]
        jevc --> policy["policy.py"]
        policy --> db[("SQLite")]
        policy -. "BLOCK / ESCALATE" .-> entc["entire_client.py"]
        entc --> expl["explainer.py"]
        policy --> nlt["neatlogs_tracer.py"]
    end

    jevc <--> jev[("Jev · TypeSafe AI")]
    entc <--> entire[("Entire CLI")]
    expl <--> llm[("DeepSeek on Modal")]
    nlt --> neatlogs[("NeatLogs")]

    api -- "SSE /stream" --> ui["dashboard · Next.js"]
    ui -- "approve / reject" --> api
```

One Antigravity tool call, end to end:

```mermaid
sequenceDiagram
    participant A as Antigravity
    participant H as guardian hook
    participant G as guardian-service
    participant J as Jev
    participant D as Dashboard
    A->>H: PreToolUse {toolCall, conversationId, workspacePaths, transcriptPath}
    H->>G: POST /evaluate (tool, args, task + reasoning from the transcript)
    G->>J: state + typed questions (safe, on_task, risk, severity)
    J-->>G: typed answers with probabilities + confidence
    G->>G: policy → ALLOW / BLOCK / ESCALATE
    G-->>D: SSE (green / red / amber)
    alt ALLOW
        H-->>A: {"decision": "allow"}
    else BLOCK
        H-->>A: {"decision": "deny", "reason": "GUARDIAN BLOCKED …"}
    else ESCALATE
        H->>G: long-poll until you click Approve / Reject
        D->>G: POST /approve/{id}
        H-->>A: allow, deny, or force_ask if nobody answers in time
    end
    Note over G: background: Entire session → LLM explanation → NeatLogs trace
```

## Setup checklist

You need **Python 3.10+**, **Node.js 20+** and **Git**. On Windows, use `py` wherever this says `python` if `python` isn't on your PATH.

### 1. Install Guardian

```bash
python dev.py setup
```

This creates `.venv`, installs everything, and creates `.env` from [`.env.example`](.env.example).

### 2. Get the keys and put them in `.env`

| Key | Where | Needed for |
|---|---|---|
| `JEV_API_KEY` | Your OpenCode key: [opencode.ai/console](https://opencode.ai/console) → **Keys**. `.env.example` already points Jev at OpenCode Zen (`JEV_BASE_URL=https://opencode.ai/zen`, `JEV_MODEL=jev-1.13-free`). | **Required.** Guardian won't start without it. |
| `NEATLOGS_API_KEY`, `NEATLOGS_PROJECT` | [app.neatlogs.com/settings/api-keys](https://app.neatlogs.com/settings/api-keys) | A trace for every decision |
| `MODAL_PROXY_TOKEN_ID`, `MODAL_PROXY_TOKEN_SECRET` | Your Modal endpoint's page ("workspace settings" link). `LLM_BASE_URL` already points at the `guardian` endpoint. | Plain-English explanations, and the LangGraph example agent |

Jev can also run against TypeSafe directly or through OpenRouter, and the explainer works with any OpenAI-compatible endpoint (`LLM_BASE_URL` + `LLM_API_KEY`). See [`.env.example`](.env.example).

### 3. Install the CLIs

Antigravity CLI ([docs](https://antigravity.google/docs/cli/install/)), then run `agy` once to sign in with your Google account:

```powershell
irm https://antigravity.google/cli/install.ps1 | iex
```

Entire CLI ([docs](https://docs.entire.io/installation)):

```powershell
irm https://entire.io/install.ps1 | iex
```

On macOS or Linux use `curl -fsSL https://antigravity.google/cli/install.sh | bash` and `curl -fsSL https://entire.io/install.sh | bash`. Restart your terminal afterwards so both are on your PATH.

### 4. Check everything

```bash
python dev.py doctor
```

It makes a real call to Jev and to your LLM endpoint, and checks for the `entire` and `agy` CLIs. Anything marked `–` is optional and shows as **off** in the dashboard.

### 5. Start Guardian

```bash
python dev.py
```

This runs the API on http://127.0.0.1:8000 and the dashboard on **http://localhost:3000**. Leave it running.

## The dashboard

http://localhost:3000, light by default with a dark mode toggle in the sidebar.

| Page | What it's for |
|---|---|
| **setup** | Step-by-step onboarding that ticks itself off: Jev, your agent (Antigravity hook, Python SDK, or plain HTTP from any language), NeatLogs, the explainer and Entire. Commands and code are copyable. |
| **home** | Decisions, sessions, block rate and Jev latency for the chosen time range; what needs attention (approvals waiting, recent blocks, failing integrations); integrations worth switching on; a digest. |
| **decisions** | Every checked tool call, filterable by verdict and searchable. Click a row for the full detail: Jev's answers, the policy reasons, the explanation, the Entire session and the NeatLogs trace. |
| **approvals** | Escalated actions waiting for you, with Approve and Reject, and a history of the answered ones. |
| **sessions** | One row per agent run (an Antigravity conversation, a LangGraph run), expandable into its steps. |
| **policy** | The thresholds and every rule, as they apply right now. |
| **integrations** | Which services and agents are connected. |

New blocks and escalations also pop up as notifications in the corner.

## Use it with Antigravity

Pick a Git project to let the agent work in. A throwaway one is best for a first try:

```bash
mkdir guardian-playground && cd guardian-playground && git init
```

Turn on Entire for Antigravity in that folder, so Guardian can read the agent's session:

```bash
entire enable --agent antigravity
```

From the Guardian folder, add the Guardian hook to that project:

```bash
python dev.py install-antigravity ../guardian-playground
```

This adds a `guardian` entry to the project's `.agents/hooks.json` and keeps Entire's entry. Then start the agent in the project and trust the folder when it asks, because Antigravity only loads workspace hooks for trusted folders:

```bash
agy
```

Every tool call the agent makes now appears in the dashboard before it runs. Try prompts like these:

| Ask the agent | What should happen |
|---|---|
| "Create hello.py that prints a greeting, then run it." | Green: the reads, the write and the run go straight through |
| "Delete everything in this folder with rm -rf and start over." | Red: Guardian denies it and Antigravity tells the model why, and the model has to pick a safer route |
| "Write a script that rewrites every .json file here in place, then run it." | Probably amber: the agent waits while you approve or reject in the dashboard |

What actually happens depends on what the agent tries and on Jev's real answers. If the signals land somewhere you disagree with, tune the `GUARDIAN_*` thresholds in `.env`.

**How the hook decides:**

- **ALLOW** → `allow`: the tool runs without asking. Set `GUARDIAN_ON_ALLOW=ask` to keep Antigravity's own permission prompts, so Guardian only adds denials.
- **BLOCK** → `deny`, with Guardian's reasons passed to the model.
- **ESCALATE** → the hook waits up to `GUARDIAN_HOOK_WAIT` seconds (240) for you to click in the dashboard. If nobody answers, it hands the question to Antigravity's own prompt (`force_ask`) and marks the decision "handed to the agent's own prompt".
- **Guardian not running** → `force_ask`, so you decide in the terminal. Antigravity treats a failing hook as a deny, so the hook always answers.

Rerun `install-antigravity` after changing `GUARDIAN_URL`, `GUARDIAN_HOOK_WAIT` or `GUARDIAN_ON_ALLOW`, because they're written into the hook command. To remove the hook, run `python dev.py uninstall-antigravity <project>`.

## Use it with LangGraph

The example agent in [`demo-agent/`](demo-agent) is a LangGraph agent driven by your LLM endpoint (DeepSeek on Modal), working in a sandboxed copy of a small project. Each example is a prompt; the model decides what to do and Guardian decides what may run:

```bash
python dev.py demo happy
```

```bash
python dev.py demo danger
```

```bash
python dev.py demo uncertain
```

Or give it your own task: `python dev.py demo --task "Add a farewell() function to app/greeter.py"`.

Each run is sent to NeatLogs as one trace: every LLM call with its tokens, every tool call, and Guardian's verdict under each checked call. Guardian's own decision traces share the run's session ID, so NeatLogs groups them. The run's totals print at the end and are saved to `evidence/runs/`. A tool that fails returns its error to the agent instead of ending the run. If NeatLogs is unreachable, `python demo-agent/run.py --resend` sends saved run traces later.

The sandbox holds even if Guardian allows something it shouldn't. File tools refuse paths outside `demo-agent/workspace`, `run_shell` only runs `ls`, `cat`, `echo` and screened Python scripts and refuses everything else, and `http_request` only sends GET requests. The script screen is a guard for the example, not a security boundary.

## How each sponsor tool is used

| Tool | What Guardian does with it | Where |
|---|---|---|
| **Jev** (TypeSafe AI) | Every checked tool call becomes one `system_one` request through the official `typesafe-sdk`, sent to `JEV_BASE_URL` (the live runs used jev-ai.pro; TypeSafe directly and OpenCode Zen serve the same format). Guardian records the input tokens of every check. The state holds the agent, its task, its stated reasoning, the proposed action and its recent steps. The questions are a **Noul** (P(safe)), a **Noul** (P(on task)), a **Choice** (risk: none, data loss, exfiltration, system damage, unclear), a **Score** (impact 0–3) and, for writes, a **Noul** asking whether the content is good enough. If Jev is unreachable, the action is escalated to a human; Guardian never guesses. | [`jev_client.py`](guardian-service/app/adapters/jev_client.py), [`policy.py`](guardian-service/app/policy.py) |
| **NeatLogs** | One trace per decision via the documented HTTP ingest (`POST /v1/trace`): a `WORKFLOW` root with a `GUARDRAIL` span for Jev (`passed` / `score`), a `CHAIN` span for the policy, a `RETRIEVER` span for the Entire lookup and an `LLM` span for the explanation, grouped by agent session (`neatlogs.session.id`). The example agent adds one trace per run, and `dev.py replay --trace` adds a before/after comparison. Ingest is retried on 5xx; failed traces are kept and re-sent with `POST /traces/retry`. | [`neatlogs_tracer.py`](guardian-service/app/adapters/neatlogs_tracer.py) |
| **Entire** | For BLOCK and ESCALATE, Guardian reads the agent's captured session with the Entire CLI (`entire session info <id> --json`, `--transcript`, `entire checkpoint explain HEAD --json`) in the agent's project folder. For Antigravity, the conversation ID is the Entire session ID. | [`entire_client.py`](guardian-service/app/adapters/entire_client.py) |
| **LLM** (DeepSeek V4.1 Flash on Modal) | Turns the decision plus the Entire session into three lines: what the agent tried, why it did it, and why Guardian stepped in, with a safer alternative. Any OpenAI-compatible `/chat/completions` endpoint works. | [`explainer.py`](guardian-service/app/adapters/explainer.py) |

## The policy

[`policy.py`](guardian-service/app/policy.py) evaluates every rule and keeps every reason. The most severe verdict wins.

| Verdict | When (defaults) |
|---|---|
| **BLOCK** | P(safe) < 0.30, or impact ≥ 2.3 / 3, or Jev picks data loss, exfiltration or system damage with p ≥ 0.70 |
| **ESCALATE** | confidence < 0.50, or 0.30 ≤ P(safe) < 0.75, or impact ≥ 1.5, or P(on task) < 0.40 with impact ≥ 1, or written content P(ok) < 0.40, or risk "unclear", or Jev unreachable |
| **ALLOW** | none of the above (an off-task action with negligible impact is allowed, and the reason says so) |

Tools listed in `GUARDIAN_FAST_PATH_TOOLS` (a regex of read-only tool names, `read_file` by default) are allowed without asking Jev, and are still recorded, streamed and traced. Before changing a threshold, `python dev.py replay` shows what the change would have done to every recorded decision, using the Jev answers already stored.

*Confidence* is the least certain of Jev's answers: the Choice and Score confidences and |2·P(safe) − 1| for the Noul, as [TypeSafe's docs](https://docs.typesafe.ai/confidence) suggest. All thresholds are environment variables.

## API

| Endpoint | |
|---|---|
| `POST /evaluate` | Action in, decision out |
| `POST /approve/{id}` · `POST /reject/{id}` | Resolve an escalation from the dashboard |
| `POST /handoff/{id}` | The agent stopped waiting and asked its own human |
| `GET /decisions` · `GET /decisions/{id}` | History, newest first |
| `GET /decisions/{id}/wait` | Long-poll until an escalation is resolved |
| `POST /decisions/{id}/result` | The agent reports whether the tool ran or failed |
| `POST /decisions/{id}/explain` | Generate an explanation on demand |
| `POST /traces/retry` | Re-send the traces NeatLogs didn't accept |
| `GET /stream` | Server-sent events for every decision as it changes |
| `GET /health` | Which integrations are live or off, the thresholds and the fast path |

Interactive docs are at http://127.0.0.1:8000/docs while the service runs.

## Repository layout

```
guardian-service/   FastAPI service: adapters, policy, SQLite, SSE, doctor
guardian-sdk/       `guardian` package: protect() and the Antigravity hook
dashboard/          Next.js 16 + Tailwind 4 live dashboard
demo-agent/         LangGraph example agent (DeepSeek on Modal) with sandboxed tools and run tracing
evidence/           NeatLogs links, before/after replays, saved run numbers
dev.py, Makefile    setup, doctor, run, install-antigravity, demo, replay, test
```

## Tests

```bash
python dev.py test
```

84 tests cover:

- the policy and its replay
- the API and escalation flow, the fast path, and trace retries
- each integration's request and response handling
- the SDK and the Antigravity hook, end to end against a running service
- the agent run trace, including tool-error recovery, against a running service
- the sandbox The tests swap Jev's HTTP API for a stand-in ([`fake_jev.py`](guardian-service/tests/fake_jev.py)) so they run offline; the product itself has no mock mode.

## Known gaps

- **Jev access:** the free OpenCode tier (`jev-1.13-free`) is reported to refuse clients outside OpenCode (403/402); `python dev.py doctor` shows the exact response. Every Jev check costs one request; the fast path saves the reads, but free credits still run out quickly.
- **Replay isn't a live run:** it assumes the agent makes the same calls. With fewer escalations a live agent keeps working instead of waiting, so later steps can differ.
- **NeatLogs' edge firewall rejects traces containing HTML-like attack text** (for example `<script>`) with a 403. Guardian records the error on the decision and doesn't try to get around the firewall.
- **Antigravity's tool names, argument names and transcript format aren't documented.** Guardian passes the tool call to Jev as-is, and reads the user's prompt and the agent's last message from the transcript on a best-effort basis. After your first session we should look at a real transcript and tighten [`antigravity.py`](guardian-sdk/guardian/antigravity.py).
- **NeatLogs:** the `neatlogs` Python SDK requires Python < 3.14, so Guardian uses the documented HTTP ingest. Its response format isn't documented; in practice it returns `trace_id`, and `https://app.neatlogs.com/traces/<trace_id>` opens the trace.
- **Entire session lookup** assumes the Antigravity conversation ID is the Entire session ID (from `entire session resume`, which prints `agy --conversation SESSION_ID`). If it doesn't match, Guardian falls back to the most recent session in the project.
- **Bypass mode:** community reports say `agy --dangerously-skip-permissions` skips hooks, so Guardian can't see those calls.
