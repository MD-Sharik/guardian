"""Antigravity hook: send every tool call the Antigravity agent makes through Guardian.

Antigravity runs this for its PreToolUse and PostToolUse events, configured in
<project>/.agents/hooks.json (`python dev.py install-antigravity <project>`
writes it). Contract: https://antigravity.google/docs/hooks/

  PreToolUse   stdin: {toolCall: {name, args}, stepIdx, conversationId,
                       workspacePaths, transcriptPath, modelName, ...}
               stdout: {"decision": allow|deny|ask|force_ask, "reason": ...}
  PostToolUse  stdin: same, plus `error` when the tool failed; stdout: {}

Guardian verdict -> Antigravity decision:
  ALLOW                    "allow" (or "ask" with --on-allow ask, which keeps
                           Antigravity's own permission prompts)
  BLOCK, or a human rejects "deny", with Guardian's reason for the model
  ESCALATE                 waits up to --wait seconds for an answer in the
                           dashboard, then hands over to Antigravity's prompt
                           ("force_ask") so a human still decides
  Guardian unreachable     "force_ask"

Usage: guardian-antigravity-hook pre|post [--url URL] [--wait SECONDS] [--on-allow allow|ask]
Antigravity runs hooks with its own environment, so `dev.py install-antigravity`
writes these flags into the hook command. GUARDIAN_URL, GUARDIAN_HOOK_WAIT and
GUARDIAN_ON_ALLOW are the fallbacks.

Antigravity treats a crashing hook, a non-zero exit or a missing decision as a
deny, so this always prints exactly one JSON object and exits 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from .client import GuardianClient

HOOK_WAIT_S = float(os.getenv("GUARDIAN_HOOK_WAIT", "240"))  # keep below the hook's timeout in hooks.json
ON_ALLOW = os.getenv("GUARDIAN_ON_ALLOW", "allow")
STATE_DIR = Path(tempfile.gettempdir()) / "guardian-antigravity"
TRANSCRIPT_TAIL = 400
TEXT_CHARS = 1500

USER_ROLES = ("user", "human")
AGENT_ROLES = ("assistant", "model", "agent", "planner", "gemini")
ROLE_KEYS = ("role", "type", "source", "author", "sender", "kind")
TEXT_KEYS = ("text", "content", "prompt", "message")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="guardian-antigravity-hook", add_help=False)
    parser.add_argument("event", nargs="?", default="pre", choices=["pre", "post"])
    parser.add_argument("--url")
    parser.add_argument("--wait", type=float)
    parser.add_argument("--on-allow", choices=["allow", "ask"])
    try:
        opts, _ = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:  # bad flags must not crash the hook either
        opts = argparse.Namespace(event="pre", url=None, wait=None, on_allow=None)
    event = opts.event
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    try:
        if event == "pre":
            out = pre_tool_use(payload, url=opts.url, wait=opts.wait, on_allow=opts.on_allow)
        else:
            out = post_tool_use(payload, url=opts.url)
    except Exception as exc:  # never crash: Antigravity would deny the call
        out = {"decision": "force_ask", "reason": f"Guardian hook error ({exc}); please decide."} if event == "pre" else {}
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()
    sys.exit(0)


def pre_tool_use(
    payload: dict[str, Any], url: str | None = None, wait: float | None = None, on_allow: str | None = None
) -> dict[str, Any]:
    wait = HOOK_WAIT_S if wait is None else wait
    on_allow = on_allow or ON_ALLOW
    call = payload.get("toolCall") or {}
    tool = call.get("name") or "unknown_tool"
    args = call.get("args") if isinstance(call.get("args"), dict) else {"args": call.get("args")}
    conversation = payload.get("conversationId")
    workspace = next(iter(payload.get("workspacePaths") or []), None)
    task, reasoning = transcript_context(payload.get("transcriptPath"))

    client = GuardianClient(
        url=url,
        agent_name="antigravity",
        session_id=conversation,
        task=task,
        approval_timeout=wait,
        metadata={
            "source": "antigravity",
            "workspace": workspace,
            "model": payload.get("modelName"),
            "step": payload.get("stepIdx"),
            "transcript_path": payload.get("transcriptPath"),
        },
    )
    client.reasoning = reasoning
    client.entire_session_id = conversation  # Entire records Antigravity sessions under the conversation ID

    verdict = client.check(tool, args)
    if not verdict.reachable:
        return {"decision": "force_ask", "reason": f"Guardian is unreachable at {client.url}; please decide."}
    if verdict.allowed:
        _remember(conversation, payload.get("stepIdx"), verdict.id)
        return {"decision": on_allow if on_allow in ("allow", "ask") else "allow"}
    if verdict.status == "pending":
        client.handoff(verdict.id, to="antigravity prompt")
        _remember(conversation, payload.get("stepIdx"), verdict.id)  # PostToolUse reports if it ran
        reasons = " ".join(verdict.decision.get("reasons") or [])
        return {
            "decision": "force_ask",
            "reason": f"Guardian escalated this and nobody answered in the dashboard within {wait:.0f}s. "
                      f"{reasons}",
        }
    return {"decision": "deny", "reason": verdict.message}


def post_tool_use(payload: dict[str, Any], url: str | None = None) -> dict[str, Any]:
    decision_id = _recall(payload.get("conversationId"), payload.get("stepIdx"))
    if decision_id:
        error = payload.get("error") or None
        GuardianClient(url=url, timeout=5).report(decision_id, ok=not error, error=error)
    return {}


# ── decision id hand-off between PreToolUse and PostToolUse ──────────────────


def _state_file(conversation: Any, step: Any) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{conversation}-{step}")
    return STATE_DIR / f"{safe}.id"


def _remember(conversation: Any, step: Any, decision_id: str | None) -> None:
    if decision_id and conversation is not None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _state_file(conversation, step).write_text(decision_id, encoding="utf-8")


def _recall(conversation: Any, step: Any) -> str | None:
    path = _state_file(conversation, step)
    try:
        decision_id = path.read_text(encoding="utf-8").strip()
        path.unlink()
        return decision_id
    except OSError:
        return None


# ── transcript: what the user asked and what the agent last said ────────────


def transcript_context(path: str | None) -> tuple[str | None, str | None]:
    """Best effort: the latest user prompt and the latest agent text.

    Antigravity's JSONL transcript format isn't documented, so this looks for
    common role/text shapes and returns (None, None) when it finds nothing.
    """
    if not path:
        return None, None
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-TRANSCRIPT_TAIL:]
    except OSError:
        return None, None
    task = reasoning = None
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        role, text = _role(entry), _text(entry)
        if not text:
            continue
        if role == "user":
            task = text
        elif role == "agent":
            reasoning = text
    return _clip(task), _clip(reasoning)


def _role(entry: Any, depth: int = 0) -> str | None:
    if not isinstance(entry, dict) or depth > 2:
        return None
    for key in ROLE_KEYS:
        value = str(entry.get(key, "")).lower()
        if any(r in value for r in USER_ROLES):
            return "user"
        if any(r in value for r in AGENT_ROLES):
            return "agent"
    for value in entry.values():
        if found := _role(value, depth + 1):
            return found
    return None


def _text(entry: Any, depth: int = 0) -> str | None:
    if depth > 3:
        return None
    if isinstance(entry, str):
        return entry.strip() or None
    if isinstance(entry, list):
        parts = [t for t in (_text(e, depth + 1) for e in entry) if t]
        return "\n".join(parts) or None
    if isinstance(entry, dict):
        for key in TEXT_KEYS:
            if key in entry and (found := _text(entry[key], depth + 1)):
                return found
    return None


def _clip(text: str | None) -> str | None:
    return text if text is None or len(text) <= TEXT_CHARS else text[-TEXT_CHARS:]


if __name__ == "__main__":
    main()
