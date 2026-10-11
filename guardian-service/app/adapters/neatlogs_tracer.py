"""NeatLogs adapter: one trace per Guardian decision.

Uses NeatLogs' dependency-free HTTP ingest (`POST {ingest}/v1/trace`), which
takes one nested JSON trace whose root is the WORKFLOW span; NeatLogs
generates the IDs. Contract:
https://github.com/neatlogs/skills/blob/main/skills/neatlogs-ingest/references/http-ingest.md

Why not the `neatlogs` Python SDK? It requires Python < 3.14, and this
service also runs on 3.14. The ingest endpoint is the documented fallback.

Trace shape:
  guardian.evaluate <tool>        WORKFLOW  action in, decision out
    ├─ jev.system_one             GUARDRAIL Jev state, typed answers, passed/score
    ├─ guardian.policy            CHAIN     signals -> verdict + reasons
    ├─ entire.session_context     RETRIEVER Entire session data (BLOCK/ESCALATE)
    └─ guardian.explainer         LLM       plain-English explanation
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from ..config import Settings
from ..models import Decision, TraceRef

log = logging.getLogger("guardian.neatlogs")


def _json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _drop_nulls(value: Any) -> Any:
    """NeatLogs ingest rejects null fields (400 "expected string, received null"); omit them."""
    if isinstance(value, dict):
        return {k: _drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_nulls(v) for v in value if v is not None]
    return value


def _jev_span(d: Decision) -> dict[str, Any] | None:
    if not d.checked:
        return None  # fast path: Jev wasn't asked
    if d.jev is None:
        return {"name": "jev.system_one", "kind": "GUARDRAIL", "status": "error", "error": d.jev_error}
    s = d.jev.signals
    return {
        "name": "jev.system_one",
        "kind": "GUARDRAIL",
        "model": d.jev.model,
        "input": _json(d.jev.state),
        "output": _json(d.jev.answers),
        "duration_ms": round(d.jev.latency_ms, 2),
        "status": "ok",
        # NeatLogs shows Passed / Blocked from these convenience fields.
        "passed": d.verdict == "ALLOW",
        "score": s.p_safe,
        "metadata": {"jev.confidence": s.confidence, "jev.risk": s.risk, "jev.input_tokens": d.jev.input_tokens},
    }


def build_payload(d: Decision, project: str) -> dict[str, Any]:
    action = {"agent": d.agent_name, "tool": d.tool, "args": d.args}
    verdict = {"verdict": d.verdict, "status": d.status, "confidence": d.confidence, "reasons": d.reasons}
    jev_span = _jev_span(d)
    children: list[dict[str, Any]] = [
        *([jev_span] if jev_span else []),
        {
            "name": "guardian.policy",
            "kind": "CHAIN",
            "input": _json(
                d.jev.signals.model_dump() if d.jev
                else {"jev_error": d.jev_error} if d.checked
                else {"fast_path": d.tool}
            ),
            "output": _json(verdict),
            "duration_ms": 0.1,
        },
    ]
    if d.entire:
        # "No session found" is a normal outcome (e.g. a repo without commits), not a
        # pipeline failure, so it goes in the output instead of failing the whole trace.
        children.append({
            "name": "entire.session_context",
            "kind": "RETRIEVER",
            "query": f"{d.tool} {_json(d.args)}",
            "documents": [] if d.entire.get("error") else [
                {"id": d.entire.get("session_id") or "entire-session", "content": _json(d.entire)[:8000]}
            ],
            "output": d.entire.get("error") or "session found",
            "status": "ok",
        })
    if d.explanation or d.explanation_error:
        children.append({
            "name": "guardian.explainer",
            "kind": "LLM",
            "model": d.explanation.model if d.explanation else None,
            "input": f"Explain why {d.agent_name} attempted {d.tool} and why Guardian returned {d.verdict}.",
            "output": d.explanation.text if d.explanation else None,
            "status": "error" if d.explanation_error else "ok",
            "error": d.explanation_error,
        })
    return _drop_nulls({
        "name": f"guardian.evaluate {d.tool}",
        "project": project,
        "input": _json(action),
        "output": _json(verdict),
        "duration_ms": round(d.latency_ms, 2),
        "status": "ok",
        # Groups every decision of one agent session (and the agent's own run trace) in NeatLogs.
        "attributes": {"neatlogs.session.id": d.session_id} if d.session_id else None,
        "metadata": {
            "guardian.decision_id": d.id,
            "guardian.verdict": d.verdict,
            "guardian.agent": d.agent_name,
            "guardian.session_id": d.session_id,
            "guardian.checked": d.checked,
            **{f"guardian.{k}": v for k, v in d.context.metadata.items() if isinstance(v, (str, int, float))},
        },
        "children": children,
    })


def _find_trace_id(body: Any) -> str | None:
    # The ingest response isn't documented; in practice it carries `trace_id`.
    # Read the likely ID fields defensively and fall back to the project view.
    if isinstance(body, dict):
        for key in ("trace_id", "traceId", "id"):
            if isinstance(body.get(key), str):
                return body[key]
        for nested in ("data", "trace"):
            if isinstance(body.get(nested), dict):
                return _find_trace_id(body[nested])
    return None


class NeatLogsTracer:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        attempts: int = 3,
        backoff_s: float = 1.0,
    ):
        self.settings = settings
        self.mode = "live" if settings.neatlogs_api_key else "off"
        self.attempts, self.backoff_s = attempts, backoff_s
        self._http = httpx.AsyncClient(timeout=10.0, transport=transport) if self.mode == "live" else None

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def record(self, d: Decision) -> TraceRef | None:
        if self._http is None:
            return None
        payload = build_payload(d, self.settings.neatlogs_project)
        error = ""
        for attempt in range(self.attempts):
            try:
                resp = await self._http.post(
                    f"{self.settings.neatlogs_ingest_url}/v1/trace",
                    headers={"x-api-key": self.settings.neatlogs_api_key},
                    json=payload,
                )
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                error = f"NeatLogs ingest returned {exc.response.status_code}: {exc.response.text[:300]}"
                if exc.response.status_code < 500:
                    break  # the payload is wrong; resending won't help
            except httpx.HTTPError as exc:
                error = f"NeatLogs ingest failed: {exc}"
            if attempt < self.attempts - 1:
                await asyncio.sleep(self.backoff_s * 2**attempt)
        else:
            resp = None
        if resp is None or resp.is_error:
            # Kept with the decision, so POST /traces/retry can send it once NeatLogs is back.
            log.warning("%s", error)
            return TraceRef(mode="error", payload=payload, error=error)
        try:
            trace_id = _find_trace_id(resp.json())
        except ValueError:
            trace_id = None
        # TODO(neatlogs): confirm the dashboard's per-trace URL format.
        app = self.settings.neatlogs_app_url
        url = f"{app}/traces/{trace_id}" if trace_id else app
        return TraceRef(mode="live", trace_id=trace_id, url=url, payload=payload)
