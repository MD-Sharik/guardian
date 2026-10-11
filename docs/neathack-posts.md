# #neatHack post drafts

Edit freely. Each fits in one post; links go in replies if the platform truncates.

## 1. What we're building

> Building Guardian for #neatHack: a safety layer that checks every AI agent tool call *before* it runs.
>
> It asks Jev (TypeSafe AI's System One) typed questions (is it safe, what's the risk, how bad if wrong) and returns ALLOW, BLOCK or ESCALATE to a human. Every decision is traced to NeatLogs; Entire supplies the agent's session when Guardian steps in.
>
> First live result: `rm -rf ./*` blocked at P(safe) 0.09.
>
> Code: https://github.com/MD-Sharik/guardian

## 2. The bug we found by watching real runs

> #neatHack day log: our agent wasn't the problem, our policy was.
>
> In a live run the agent read README.md while investigating, and Guardian escalated it to a human. Jev said "safe, negligible impact" but "off task". Three harmless reads, a 5-minute stall.
>
> Fix: off-task only matters when the action can change something. Plus a fast path so read-only tools skip the check entirely.

## 3. Before and after, measured

> Measured the fix without spending a single new Jev call: Guardian stores Jev's answers, so `dev.py replay` re-scores real decisions with the new policy.
>
> Same session:
> Jev calls 9 → 6
> Human escalations 4 → 1
> `rm -rf` still blocked
>
> The replay itself is a NeatLogs trace, grouped with the original run. #neatHack

## 4. Reliability, the unglamorous part

> Things that broke in our live runs today, and what Guardian does now:
>
> • A tool crashed and killed the agent → errors go back to the agent, which recovers
> • Trace ingest went down for 20+ minutes → retries, and failed traces re-send later
> • Jev unreachable → escalate to a human, never guess
>
> 84 tests. #neatHack

## 5. Submission (quote the official neatlogs post)

> Team huma1nity: Guardian, a real-time safety layer for AI agents.
>
> Repo: https://github.com/MD-Sharik/guardian
> Demo: <video link>
> Evidence (NeatLogs traces, Entire checkpoint, cfo.ai plan): https://github.com/MD-Sharik/guardian/blob/main/evidence/README.md
>
> #neatHack
