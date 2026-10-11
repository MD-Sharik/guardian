# Business plan inputs (for cfo.ai)

What to enter into cfo.ai to build Guardian's plan: pricing, costs, revenue and runway. Each number is marked:

- **measured:** from our live runs
- **assumption:** a starting guess to replace or test
- **fill in:** only you know it, or it depends on a provider's price list

## The product in one paragraph

Guardian checks every action an AI agent takes before it runs, and blocks, escalates or allows it. It's for teams that let coding and ops agents run commands, edit files and call APIs: platform teams, agencies and startups using Antigravity, LangGraph or similar. It replaces two bad options: letting agents run unchecked, or approving every step by hand. What a customer pays for is fewer incidents and fewer interruptions.

## Pricing (assumption: a starting proposal to test)

| Plan | Price | Includes |
|---|---|---|
| Open source | $0 | Self-hosted, bring your own Jev, NeatLogs and LLM keys |
| Team (cloud) | $49 / workspace / month | 20,000 checks, dashboard, approvals, 30-day history |
| Usage beyond the plan | $1.50 / 1,000 checks | |
| Enterprise | Custom | SSO, audit export, on-prem, SLA |

How checks add up (**measured**): one short agent task made 9 tool calls. With the fast path, 6 of them needed a Jev check. A developer running agents most of the day might reach roughly 50 tasks a day, about 300 checks a day or ~6,600 per working month (**assumption**). So one Team plan covers about three active developers.

## Cost per check

| Cost driver | Volume per check | Price | Source |
|---|---|---|---|
| Jev System One input tokens | **~940 tokens** (723 to 1,399) | *fill in: Jev price per 1M input tokens* | measured |
| Jev output tokens | n/a | currently free of charge | TypeSafe API schema |
| Explainer (DeepSeek V4.1 Flash on Modal), only on BLOCK/ESCALATE | 1 in 9 checks after the policy fix (4 in 9 before) | *fill in: Modal GPU cost per explanation* | measured rate; tokens per explanation not yet measured |
| NeatLogs trace | 1 per check | *fill in: NeatLogs plan* | |
| Entire session read | only on BLOCK/ESCALATE, local CLI | $0 | |
| Hosting (FastAPI + database) | shared | *fill in: ~$20 to $50 / month for a small instance* | assumption |

Formula for cfo.ai:

```
cost per check = 940 × (Jev $ per 1M input tokens) / 1,000,000
               + escalation rate × (explainer $ per call)
               + (NeatLogs $ per trace)
```

The fast path is a direct cost lever: on the measured session it removed 3 of 9 Jev calls (33%) at no loss of protection.

## Revenue model inputs

| Input | Value |
|---|---|
| Launch month | *fill in* |
| New Team workspaces per month | *assumption: 5 in month 1, growing 20% a month* |
| Average checks per workspace | *assumption: 25,000 a month* (above plan, so some usage revenue) |
| Monthly churn | *assumption: 4%* |
| Open-source to paid conversion | *assumption: 2% of active self-hosters* |

## Company inputs

| Input | Value |
|---|---|
| Team | *fill in: people, salaries or stipends* |
| Cash on hand | *fill in* |
| Other monthly costs (tools, domains, legal) | *fill in* |
| Funding planned | *fill in* |

## Risks to state in the plan

- **Model access:** the product depends on Jev. Mitigation: the Jev endpoint is configurable (TypeSafe directly, or other hosts of the same API); escalate-on-outage means safety doesn't depend on availability.
- **Agent platforms ship their own guardrails.** Mitigation: Guardian works across agents (Antigravity, LangGraph, any tool-calling agent) and adds calibrated checks, human approvals and traces in one place.
- **Cost per check grows with agent usage.** Mitigation: the fast path for read-only tools, measured by replaying real traffic before changing the policy.
