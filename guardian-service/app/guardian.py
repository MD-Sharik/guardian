"""Guardian core: evaluate an action, store it, stream it, enrich it.

evaluate()  Jev typed questions -> policy verdict -> stored + streamed.
            Returns as soon as the verdict exists, so the agent never waits
            on tracing or explanations. If Jev can't be reached, the action
            is escalated to a human rather than guessed at.
_enrich()   In the background: for BLOCK / ESCALATE, pull the Entire
            session and generate an explanation (each only if configured);
            then send the NeatLogs trace.
resolve()   A human approves or rejects an ESCALATE from the dashboard.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable

from .adapters.entire_client import EntireClient
from .adapters.explainer import Explainer, ExplainerError
from .adapters.jev_client import JevClient, JevUnavailable
from .adapters.neatlogs_tracer import NeatLogsTracer
from .config import Settings
from .db import DecisionStore
from .events import EventBroker
from .models import Decision, EvaluateRequest, ResultRequest, Status, ToolResult
from .policy import PolicyResult, decide

log = logging.getLogger("guardian")

INITIAL_STATUS: dict[str, Status] = {"ALLOW": "allowed", "BLOCK": "blocked", "ESCALATE": "pending"}
MAX_OUTPUT_CHARS = 4000
HISTORY_LEN = 5
HISTORY_ARG_CHARS = 300


class Guardian:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = DecisionStore(settings.db_path)
        self.broker = EventBroker()
        self.jev = JevClient(settings)
        self.tracer = NeatLogsTracer(settings)
        self.entire = EntireClient(settings)
        self.explainer = Explainer(settings)
        self._fast_path = re.compile(settings.fast_path_tools) if settings.fast_path_tools else None
        self._resolved: dict[str, asyncio.Event] = {}
        self._tasks: set[asyncio.Task] = set()

    @property
    def modes(self) -> dict[str, str]:
        return {
            "jev": self.jev.mode,
            "neatlogs": self.tracer.mode,
            "entire": self.entire.mode,
            "explainer": self.explainer.mode,
        }

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(self.jev.aclose(), self.tracer.aclose(), self.explainer.aclose())
        self.store.close()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _update(self, decision_id: str, change: Callable[[Decision], None]) -> Decision | None:
        """Read-modify-write on the stored copy (no awaits, so atomic on the loop)."""
        d = self.store.get(decision_id)
        if d is None:
            return None
        change(d)
        self.store.save(d)
        self.broker.publish("decision", d.model_dump(mode="json"))
        return d

    # ── evaluate ────────────────────────────────────────────────────────────

    def _session_history(self, session_id: str) -> list[dict]:
        """Recent steps of this session, oldest first, for clients that don't keep their own."""
        steps = [d for d in self.store.list(500) if d.session_id == session_id][:HISTORY_LEN]
        return [
            {
                "tool": d.tool,
                "args": {k: v[:HISTORY_ARG_CHARS] if isinstance(v, str) else v for k, v in d.args.items()},
                "verdict": d.verdict,
                "status": d.status,
                "reasoning": d.context.reasoning,
            }
            for d in reversed(steps)
        ]

    async def evaluate(self, req: EvaluateRequest) -> Decision:
        start = time.perf_counter()
        if not req.context.history and req.session_id:
            req.context.history = self._session_history(req.session_id)
        jev, jev_error, checked = None, None, True
        if self._fast_path and self._fast_path.fullmatch(req.tool):
            # Read-only tool: allowed without spending a Jev call. Still recorded, streamed and traced.
            checked = False
            policy = PolicyResult("ALLOW", 1.0, ["Read-only tool: allowed by the fast path without a Jev check."])
        else:
            try:
                jev = await self.jev.evaluate(req)
                policy = decide(jev.signals, self.settings.thresholds)
            except JevUnavailable as exc:
                jev_error = str(exc)
                policy = PolicyResult("ESCALATE", 0.0, [f"Jev could not be reached ({exc}), so a human must decide."])
        d = Decision(
            agent_name=req.agent_name,
            session_id=req.session_id,
            tool=req.tool,
            args=req.args,
            context=req.context,
            verdict=policy.verdict,
            status=INITIAL_STATUS[policy.verdict],
            confidence=policy.confidence,
            reasons=policy.reasons,
            jev=jev,
            jev_error=jev_error,
            checked=checked,
            latency_ms=(time.perf_counter() - start) * 1000,
            explanation_pending=policy.verdict != "ALLOW" and self.explainer.mode == "live",
        )
        self.store.save(d)
        self.broker.publish("decision", d.model_dump(mode="json"))
        log.info("%s %s %s (confidence %.2f)", d.verdict, d.tool, d.args, d.confidence)

        if d.verdict == "ESCALATE":
            self._resolved[d.id] = asyncio.Event()
            self._spawn(self._expire_later(d.id))
        self._spawn(self._enrich(d.id))
        return d

    async def _enrich(self, decision_id: str) -> None:
        try:
            d = self.store.get(decision_id)
            if d and d.verdict != "ALLOW":
                await self._explain(d)
            d = self.store.get(decision_id)
            if d and self.tracer.mode == "live":
                trace = await self.tracer.record(d)
                self._update(decision_id, lambda x: setattr(x, "trace", trace))
        except Exception:  # background work must never take the service down
            log.exception("enrichment failed for %s", decision_id)

    async def _explain(self, d: Decision) -> Decision | None:
        entire = await self.entire.session_context(d)
        explanation, error = None, None
        if self.explainer.mode == "live":
            try:
                explanation = await self.explainer.explain(d, entire)
            except ExplainerError as exc:
                error = str(exc)

        def apply(x: Decision) -> None:
            x.entire = entire
            x.explanation = explanation
            x.explanation_error = error
            x.explanation_pending = False

        return self._update(d.id, apply)

    async def explain(self, decision_id: str) -> Decision | None:
        d = self.store.get(decision_id)
        if d is None:
            return None
        self._update(decision_id, lambda x: setattr(x, "explanation_pending", True))
        return await self._explain(d)

    # ── escalation ──────────────────────────────────────────────────────────

    def resolve(self, decision_id: str, approve: bool, by: str, note: str | None) -> Decision | None:
        return self._settle(decision_id, "approved" if approve else "rejected", by, note)

    def handoff(self, decision_id: str, by: str) -> Decision | None:
        """The agent stopped waiting and asked its own human (e.g. Antigravity's approval prompt)."""
        return self._settle(decision_id, "handed_off", by, None)

    def _settle(self, decision_id: str, status: Status, by: str, note: str | None) -> Decision | None:
        d = self.store.get(decision_id)
        if d is None or d.status != "pending":
            return d

        def apply(x: Decision) -> None:
            x.status = status
            x.resolved_by, x.resolved_at, x.note = by, time.time(), note

        d = self._update(decision_id, apply)
        if event := self._resolved.pop(decision_id, None):
            event.set()
        return d

    async def wait(self, decision_id: str, timeout: float) -> Decision | None:
        d = self.store.get(decision_id)
        if d is None or d.is_resolved:
            return d
        # setdefault: a pending decision from before a restart has no event yet
        event = self._resolved.setdefault(decision_id, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            pass
        return self.store.get(decision_id)

    async def _expire_later(self, decision_id: str) -> None:
        await asyncio.sleep(self.settings.escalation_timeout_s)
        d = self.store.get(decision_id)
        if d and d.status == "pending":
            def apply(x: Decision) -> None:
                x.status = "expired"
                x.resolved_by, x.resolved_at = "timeout", time.time()

            self._update(decision_id, apply)
            if event := self._resolved.pop(decision_id, None):
                event.set()

    # ── tool outcome ────────────────────────────────────────────────────────

    def report_result(self, decision_id: str, req: ResultRequest) -> Decision | None:
        result = ToolResult(
            ok=req.ok,
            output=(req.output or "")[:MAX_OUTPUT_CHARS] or None,
            error=(req.error or "")[:MAX_OUTPUT_CHARS] or None,
        )
        return self._update(decision_id, lambda x: setattr(x, "result", result))

    async def retry_traces(self) -> dict[str, int]:
        """Re-send the traces NeatLogs didn't accept (e.g. during an ingest outage)."""
        failed = [d for d in self.store.list(1000) if d.trace and d.trace.mode == "error"]
        sent = 0
        for d in failed:
            trace = await self.tracer.record(d)  # rebuilt from the decision as it is now
            self._update(d.id, lambda x, t=trace: setattr(x, "trace", t))
            sent += trace is not None and trace.mode == "live"
        return {"failed_before": len(failed), "sent": sent, "still_failing": len(failed) - sent}

    def clear(self) -> None:
        self.store.clear()
        self.broker.publish("reset", {})
