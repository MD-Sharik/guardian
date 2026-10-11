# Guardian — brag plan

**What it is:** a safety layer that checks every action an AI coding agent wants to take, before it runs.
**Who it's for:** developers letting agents like Antigravity or a LangGraph agent loose on real projects.
**What sets it apart:** Jev answers typed safety questions with calibrated probabilities in well under a second; when it isn't sure, the agent pauses and a human decides; then it explains *why* the agent did it, from the agent's own session, and traces every step.
**Most impressive true claim:** an agent ran `rm -rf ./*`; Jev rated it P(safe) 0.11, data-loss risk 96%, critical impact, and Guardian denied it before it ran (Jev answered in 603 ms in the NeatLogs trace).
**Visual hook:** a dark agent terminal typing `rm -rf ./*`, then a red BLOCKED stamp before it executes.
**Real UI to show:** the agent terminal + hook, Jev's answers (dashboard drawer), the approval card (Approve and run), the plain-English explanation (real DeepSeek output), the NeatLogs span tree (real trace).
**Tone:** `default` — punchy, clean. Danger in the dark, calm in Guardian's light UI.
**Share caption:** My AI agent tried to `rm -rf` my project. Guardian stopped it in 0.6 s and told me why.

## Identity

From `dashboard/app/globals.css`: ink #18181b · page #f4f4f5 · surface #ffffff · line #e7e7ea · muted #6b6b76 · allow #15803d on #ecfdf3 · block #dc2626 on #fef2f2 · escalate #b45309 on #fffbeb · info #2563eb. Fonts: Geist, Geist Mono. Logo: black rounded square with a white "G".

## Storyboard (22 s, 1920×1080, 30 fps)

| # | Time | Scene | On screen | Readable line |
|---|---|---|---|---|
| 1 | 0.0–4.2 | Hook | Dark agent terminal. Prompt "clean up the workspace" → agent types "Fastest fix: wipe everything and start clean." → tool call `run_command rm -rf ./*` → red **GUARDIAN BLOCKED** slams in: "denied before it ran · P(safe) 0.11" | "Your AI agent just typed this." → "Guardian stopped it before it ran." |
| 2 | 4.2–7.0 | Reveal | Dip to light. G logo scales in, "Guardian" wordmark | "Checks every AI agent action before it runs." |
| 3 | 7.0–11.6 | Typed answers | Action card `rm -rf ./*`; three questions appear one by one with answers filling: P(safe) 11% · Data loss 96% · Impact critical → **blocked** pill + 603 ms | "Jev answers typed safety questions in 0.6 s." |
| 4 | 11.6–15.6 | Ask a human | Approval card "antigravity wants to run `python scripts/migrate_db.py --apply`", cursor glides to **Approve and run**, click, card settles to "approved" | "Not sure? It pauses and asks you first." |
| 5 | 15.6–19.2 | Explain + trace | "In plain English" card (real DeepSeek lines) + NeatLogs span tree building span by span | "Then it explains why, and traces every step." |
| 6 | 19.2–22.0 | Outro | `tools = protect(tools)` · Antigravity · LangGraph · HTTP; wordmark | "Guardian. A safety layer for AI agents." |

Durations: 4.2 + 2.8 + 4.6 + 4.0 + 3.6 + 2.8 = 22.0 s.

## Sound

120 BPM, A minor. Tense pulse + soft typing ticks under the hook; one low impact on BLOCKED; music opens up on the reveal (kick, hats, bass Am–F–C–G, soft pad); soft ticks for each answer row, a click and a small chime on Approve, airy whooshes on cuts — all in key, mixed under the music. Fade out on the outro.
