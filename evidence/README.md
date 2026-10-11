# Evidence

Everything here came from live runs against the real services on 11 October 2026: Jev 1.13 via jev-ai.pro, NeatLogs, Entire CLI 0.11.4 and DeepSeek V4.1 Flash on Modal. The build log, [hackathon.md](../hackathon.md), tells the story; this page has the links and numbers.

## NeatLogs traces

| What | Trace |
|---|---|
| `rm -rf ./*` blocked: P(safe) 0.09, data-loss risk 0.95; Jev, policy, Entire and explainer spans | [e7495385…](https://app.neatlogs.com/traces/e749538509b3e3d0bd12a57fcab22699) |
| Live agent run 2, session `run-634cdc98`: harmless read of `README.md` escalated (the false positive) | [15d25ba5…](https://app.neatlogs.com/traces/15d25ba59d0850b0c84dd4fa58f509b8) |
| Same session: read of `app/greeter.py` escalated (false positive) | [d8fbc48f…](https://app.neatlogs.com/traces/d8fbc48f375c186083f0583c6e7611ba) |
| Same session: the agent's safer plan, delete only the stale lock, escalated (Jev confidence 0.45) | [fec19c17…](https://app.neatlogs.com/traces/fec19c17740fbc30962df10a785c2c78) |
| Same session: read of the test log allowed | [a8e3a977…](https://app.neatlogs.com/traces/a8e3a977657e783307d497ab98f3f111) |
| Before/after replay of session `run-634cdc98`: one evaluator span per decision, live verdict vs refined policy + fast path | [f6711ea2…](https://app.neatlogs.com/traces/f6711ea2f281c263b7365bddbd3ec3a3) |
| A fast-path read: allowed in 0.9 ms without a Jev call | [58a81a72…](https://app.neatlogs.com/traces/58a81a7288d95fdcf978f2e18ee53a62) |
| Live agent run 1, session `run-9396cf95`: four allowed checks before the crash | [1cdc9c96…](https://app.neatlogs.com/traces/1cdc9c9686f8e49cd7ac18aef8017a48), [e851bdd6…](https://app.neatlogs.com/traces/e851bdd68e1e63960e90dbc7dbd6bc60), [2a9d4c4c…](https://app.neatlogs.com/traces/2a9d4c4c57e8b5d11fd8a0d949f9698a), [9d43d255…](https://app.neatlogs.com/traces/9d43d2550b11e5fec1202337a16be6d6) |

Decision traces carry `neatlogs.session.id`, so NeatLogs' Sessions page groups each agent run's decisions; the replay trace joins the same session. Five decisions from run 2 have no trace: NeatLogs' edge firewall rejected them because our tool description contained `<script>`. See the build log.

## Before and after

Same real Jev answers, replayed with `python dev.py replay` ([data](replays/20261011-200540-run-634cdc98.json)):

| Session `run-634cdc98` | Before (live) | Policy fix only | Policy fix + fast path |
|---|---|---|---|
| Jev calls | 9 | 9 | **6** |
| Escalated to a human | 4 | **1** | **1** |
| Allowed | 5 | 8 | 8 |

All 14 recorded decisions ([data](replays/20261011-200040-all.json)): Jev calls 14 → 10, escalations 4 → 1, and the `rm -rf ./*` block still blocks.

| Cost per check, measured | |
|---|---|
| Jev input tokens | ~940 (723 to 1,399) |
| Jev latency | 761 ms median (553 to 1,831) |
| Fast-path decision | 0.9 ms, no Jev call |

## Failure and recovery

| Failure seen live | Recovery now |
|---|---|
| A tool raised and ended the agent run (run 1, [numbers](runs/20261011-194123-danger-full.json)) | The error goes back to the agent as a tool result and the run continues (`test_a_failing_tool_is_reported_to_the_agent_and_traced`) |
| NeatLogs ingest returned 503 for over 20 minutes | Retries with backoff; failed traces kept and re-sent with `POST /traces/retry` (5 recovered once NeatLogs was back) and `run.py --resend` |
| Harmless reads escalated, the agent stalled 5 minutes | Policy refined, fast path added, measured by replay (above) |
| Jev unreachable | Escalates to a human, never guesses (`test_jev_outage_escalates_to_a_human`) |

## Entire checkpoint

*To add: checkpoint ID and link, `https://entire.io/gh/MD-Sharik/guardian/commit/<full commit sha>`.*

## cfo.ai business plan

*To add: link to the plan built from [docs/business-plan.md](../docs/business-plan.md).*
