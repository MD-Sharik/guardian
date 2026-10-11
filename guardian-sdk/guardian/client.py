"""HTTP client for the Guardian service."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("guardian.sdk")

DEFAULT_URL = "http://127.0.0.1:8000"
WAIT_POLL_S = 25
HISTORY_LEN = 10
MAX_ARG_CHARS = 300

# Messages returned to the agent instead of the tool's output. They start with
# a fixed prefix so agents (and is_guardian_refusal) can recognise them.
REFUSAL_PREFIX = "GUARDIAN "


@dataclass
class Verdict:
    """The outcome of one Guardian check, as seen by the agent."""

    allowed: bool
    decision: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    reachable: bool = True  # False when Guardian itself couldn't be reached

    @property
    def status(self) -> str | None:
        return self.decision.get("status")

    @property
    def id(self) -> str | None:
        return self.decision.get("id")


def is_guardian_refusal(text: Any) -> bool:
    return isinstance(text, str) and text.startswith(REFUSAL_PREFIX)


def _refusal(decision: dict[str, Any]) -> str:
    reasons = " ".join(decision.get("reasons") or [])
    status = decision.get("status")
    if status == "blocked":
        return (f"GUARDIAN BLOCKED this action (confidence {decision.get('confidence', 0):.2f}). {reasons} "
                "Do not retry it; choose a narrower, safer approach.")
    if status == "rejected":
        note = f" Reviewer note: {decision['note']}" if decision.get("note") else ""
        return f"GUARDIAN REJECTED: a human reviewer declined this action.{note} Do not retry it."
    if status == "expired":
        return "GUARDIAN EXPIRED: no human approved this action in time, so it was not run."
    if status == "pending":
        return "GUARDIAN ESCALATED this action and no human answered in time, so it was not run."
    return f"GUARDIAN DID NOT ALLOW this action (status {status})."


def _short(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_ARG_CHARS:
        return value[:MAX_ARG_CHARS] + "…"
    return value


class GuardianClient:
    """Asks Guardian before each tool call; waits for a human on ESCALATE.

    on_decision(decision, phase) is called with phase "evaluated" for every
    verdict and "resolved" when a human answers an escalation.
    """

    def __init__(
        self,
        url: str | None = None,
        agent_name: str = "agent",
        session_id: str | None = None,
        task: str | None = None,
        timeout: float = 15.0,
        approval_timeout: float = 600.0,
        fail_open: bool = False,
        on_decision: Callable[[dict[str, Any], str], None] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.url = (url or os.getenv("GUARDIAN_URL") or DEFAULT_URL).rstrip("/")
        self.agent_name = agent_name
        self.session_id = session_id or f"run-{uuid.uuid4().hex[:8]}"
        self.task = task
        self.reasoning: str | None = None
        self.entire_session_id = os.getenv("ENTIRE_SESSION_ID") or None
        self.timeout = timeout
        self.approval_timeout = approval_timeout
        self.fail_open = fail_open
        self.on_decision = on_decision
        self.metadata = metadata or {}
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_LEN)

    def set_context(self, *, task: str | None = None, reasoning: str | None = None) -> None:
        """Tell Guardian what the agent is doing; sent with the next checks."""
        if task is not None:
            self.task = task
        if reasoning is not None:
            self.reasoning = reasoning

    # ── request building ───────────────────────────────────────────────────

    def _payload(self, tool: str, args: dict[str, Any], description: str | None) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "tool": tool,
            "args": json.loads(json.dumps(args, default=str)),
            "tool_description": description,
            "session_id": self.session_id,
            "context": {
                "task": self.task,
                "reasoning": self.reasoning,
                "history": list(self.history),
                "entire_session_id": self.entire_session_id,
                "metadata": self.metadata,
            },
        }

    def _record(self, tool: str, args: dict[str, Any], decision: dict[str, Any]) -> None:
        self.history.append({
            "tool": tool,
            "args": {k: _short(v) for k, v in args.items()},
            "verdict": decision.get("verdict"),
            "status": decision.get("status"),
            "reasoning": self.reasoning,
        })

    def _notify(self, decision: dict[str, Any], phase: str) -> None:
        if self.on_decision:
            self.on_decision(decision, phase)
        else:
            log.info("guardian %s: %s %s", phase, decision.get("verdict"), decision.get("status"))

    def _unavailable(self, exc: Exception) -> Verdict:
        log.warning("Guardian unreachable at %s: %s", self.url, exc)
        if self.fail_open:
            return Verdict(True, {}, "", reachable=False)
        return Verdict(
            False, {}, f"GUARDIAN UNAVAILABLE: could not reach {self.url}, so the action was not run.", reachable=False
        )

    def _finish(self, tool: str, args: dict[str, Any], decision: dict[str, Any]) -> Verdict:
        self._record(tool, args, decision)
        allowed = decision.get("status") in ("allowed", "approved")
        return Verdict(allowed, decision, "" if allowed else _refusal(decision))

    # ── sync API ───────────────────────────────────────────────────────────

    def check(self, tool: str, args: dict[str, Any], description: str | None = None) -> Verdict:
        try:
            with httpx.Client(base_url=self.url, timeout=self.timeout) as http:
                decision = http.post("/evaluate", json=self._payload(tool, args, description)).raise_for_status().json()
                self._notify(decision, "evaluated")
                if decision["status"] == "pending":
                    decision = self._wait(http, decision)
                    self._notify(decision, "resolved")
        except httpx.HTTPError as exc:
            return self._unavailable(exc)
        return self._finish(tool, args, decision)

    def _wait(self, http: httpx.Client, decision: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + self.approval_timeout
        while decision["status"] == "pending" and (left := deadline - time.monotonic()) > 0:
            poll = min(WAIT_POLL_S, left)
            decision = http.get(
                f"/decisions/{decision['id']}/wait", params={"timeout": poll}, timeout=poll + 10
            ).raise_for_status().json()
        return decision

    def handoff(self, decision_id: str | None, to: str) -> None:
        """Tell Guardian a pending escalation is now being decided elsewhere (e.g. the agent's own prompt)."""
        if not decision_id:
            return
        try:
            httpx.post(f"{self.url}/handoff/{decision_id}", json={"by": to}, timeout=self.timeout)
        except httpx.HTTPError as exc:
            log.debug("could not hand off: %s", exc)

    def report(self, decision_id: str | None, ok: bool, output: Any = None, error: str | None = None) -> None:
        if not decision_id:
            return
        try:
            httpx.post(
                f"{self.url}/decisions/{decision_id}/result",
                json={"ok": ok, "output": None if output is None else str(output), "error": error},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:  # reporting is best-effort
            log.debug("could not report result: %s", exc)

    # ── async API ──────────────────────────────────────────────────────────

    async def acheck(self, tool: str, args: dict[str, Any], description: str | None = None) -> Verdict:
        try:
            async with httpx.AsyncClient(base_url=self.url, timeout=self.timeout) as http:
                resp = await http.post("/evaluate", json=self._payload(tool, args, description))
                decision = resp.raise_for_status().json()
                self._notify(decision, "evaluated")
                deadline = time.monotonic() + self.approval_timeout
                waited = False
                while decision["status"] == "pending" and (left := deadline - time.monotonic()) > 0:
                    poll = min(WAIT_POLL_S, left)
                    resp = await http.get(
                        f"/decisions/{decision['id']}/wait", params={"timeout": poll}, timeout=poll + 10
                    )
                    decision, waited = resp.raise_for_status().json(), True
                if waited:
                    self._notify(decision, "resolved")
        except httpx.HTTPError as exc:
            return self._unavailable(exc)
        return self._finish(tool, args, decision)

    async def areport(self, decision_id: str | None, ok: bool, output: Any = None, error: str | None = None) -> None:
        await asyncio.to_thread(self.report, decision_id, ok, output, error)
