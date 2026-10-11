"""One NeatLogs trace per agent run: every LLM call (with tokens), every tool
call, and Guardian's verdict on it.

A LangChain callback handler collects spans while the LangGraph agent runs, and
`send()` posts them through NeatLogs' dependency-free HTTP ingest
(POST {ingest}/v1/trace, https://docs.neatlogs.com/sdk/http-injection). The
neatlogs SDK needs Python < 3.14, and this repo also runs on 3.14.

The run trace and Guardian's per-decision traces share `neatlogs.session.id`,
so NeatLogs groups them into one session.

  agent.run <title>              WORKFLOW  task in, final answer out, run totals
    ├─ llm                       LLM       messages in, reply out, tokens
    ├─ <tool>                    TOOL      args in, output (or Guardian's refusal) out
    │    └─ guardian.check       GUARDRAIL verdict and P(safe); absent on the fast path
    └─ ...
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from langchain_core.callbacks import BaseCallbackHandler

PASSED = {"allowed", "approved"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _drop_nulls(value: Any) -> Any:
    """NeatLogs ingest rejects null fields with a 400; omit them."""
    if isinstance(value, dict):
        return {k: _drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_nulls(v) for v in value if v is not None]
    return value


def _message(m: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.type, "content": m.content}
    if getattr(m, "tool_calls", None):
        out["tool_calls"] = [{"name": c["name"], "args": c["args"]} for c in m.tool_calls]
    return out


def guardrail_span(d: dict[str, Any]) -> dict[str, Any] | None:
    """Guardian's verdict on one tool call. None on the fast path, where Jev wasn't asked."""
    if d.get("checked") is False:
        return None
    jev = d.get("jev") or {}
    signals = jev.get("signals") or {}
    return {
        "name": "guardian.check",
        "kind": "GUARDRAIL",
        "input": _json({"tool": d.get("tool"), "args": d.get("args")}),
        "output": _json({"verdict": d.get("verdict"), "status": d.get("status"), "reasons": d.get("reasons")}),
        "passed": d.get("status") in PASSED,
        "score": signals.get("p_safe"),
        "duration_ms": d.get("latency_ms"),
        "metadata": {
            "guardian.decision_id": d.get("id"),
            "guardian.verdict": d.get("verdict"),
            "guardian.status": d.get("status"),
            "guardian.trace_url": (d.get("trace") or {}).get("url"),
            "jev.model": jev.get("model"),
            "jev.latency_ms": jev.get("latency_ms"),
            "jev.input_tokens": jev.get("input_tokens"),
            "jev.error": d.get("jev_error"),
        },
    }


def post_trace(
    payload: dict[str, Any],
    *,
    api_key: str,
    ingest_url: str = "https://ingest.neatlogs.com",
    app_url: str = "https://app.neatlogs.com",
    transport: httpx.BaseTransport | None = None,
    attempts: int = 3,
    backoff_s: float = 1.0,
) -> dict[str, Any]:
    """POST one trace, retrying 5xx responses and network errors (a 4xx means the payload is wrong)."""
    error = ""
    with httpx.Client(timeout=15, transport=transport) as http:
        for attempt in range(attempts):
            try:
                resp = http.post(f"{ingest_url.rstrip('/')}/v1/trace", headers={"x-api-key": api_key}, json=payload)
                resp.raise_for_status()
                trace_id = resp.json().get("trace_id")
                return {"mode": "live", "trace_id": trace_id,
                        "url": f"{app_url.rstrip('/')}/traces/{trace_id}" if trace_id else app_url}
            except httpx.HTTPStatusError as exc:
                error = f"NeatLogs ingest returned {exc.response.status_code}: {exc.response.text[:200]}"
                if exc.response.status_code < 500:
                    break
            except (httpx.HTTPError, ValueError) as exc:
                error = f"NeatLogs ingest failed: {exc}"
            if attempt < attempts - 1:
                time.sleep(backoff_s * 2**attempt)
    return {"mode": "error", "error": error}


class RunTrace(BaseCallbackHandler):
    """Pass as a LangGraph callback; give `on_decision` to protect() as well."""

    def __init__(
        self,
        name: str,
        task: str,
        session_id: str,
        *,
        project: str,
        api_key: str = "",
        ingest_url: str = "https://ingest.neatlogs.com",
        app_url: str = "https://app.neatlogs.com",
        metadata: dict[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.name, self.task, self.session_id = name, task, session_id
        self.project, self.api_key = project, api_key
        self.ingest_url, self.app_url = ingest_url.rstrip("/"), app_url.rstrip("/")
        self.metadata = metadata or {}
        self.spans: list[dict[str, Any]] = []
        self.decisions: dict[str, dict[str, Any]] = {}  # Guardian decisions by id, in arrival order
        self._open: dict[UUID, tuple[dict[str, Any], float]] = {}
        self._inner: set[UUID] = set()
        self._claimed: dict[str, dict[str, Any]] = {}  # decision id -> the tool span it belongs to
        self._lock = threading.Lock()
        self._transport = transport
        self._start, self._t0 = _now(), time.perf_counter()

    # --- LangChain callbacks -------------------------------------------------

    def on_chat_model_start(self, serialized, messages, *, run_id, invocation_params=None, **kwargs):
        model = (invocation_params or {}).get("model") or (invocation_params or {}).get("model_name")
        span = {"name": "llm", "kind": "LLM", "model": model, "start": _now(),
                "input": _json([_message(m) for m in messages[0]])}
        with self._lock:
            self._open[run_id] = (span, time.perf_counter())

    def on_llm_end(self, response, *, run_id, **kwargs):
        with self._lock:
            span, t0 = self._open.pop(run_id, (None, 0.0))
        if span is None:
            return
        gen = response.generations[0][0]
        message = getattr(gen, "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        calls = [{"name": c["name"], "args": c["args"]} for c in getattr(message, "tool_calls", None) or []]
        span.update(
            output=_json({"text": gen.text, "tool_calls": calls}) if calls else gen.text,
            tokens={"prompt": usage.get("input_tokens"), "completion": usage.get("output_tokens"),
                    "total": usage.get("total_tokens")},
            duration_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
        span["model"] = span.get("model") or (response.llm_output or {}).get("model_name")
        self._close(span)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._fail(run_id, error)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, inputs=None, **kwargs):
        with self._lock:
            if parent_run_id in self._open or parent_run_id in self._inner:
                # protect() runs the original tool inside the guarded one; that's the same call.
                self._inner.add(run_id)
                return
            name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
            span = {"name": name, "kind": "TOOL", "tool_name": name, "start": _now(),
                    "input": _json(inputs if inputs is not None else input_str), "_args": inputs}
            self._open[run_id] = (span, time.perf_counter())

    def on_tool_end(self, output, *, run_id, **kwargs):
        with self._lock:
            if run_id in self._inner:
                self._inner.discard(run_id)
                return
            span, t0 = self._open.pop(run_id, (None, 0.0))
        if span is None:
            return
        span["output"] = str(getattr(output, "content", output))
        span["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        self._claim(span)
        self._close(span)

    def on_tool_error(self, error, *, run_id, **kwargs):
        with self._lock:
            if run_id in self._inner:
                self._inner.discard(run_id)
                return
        self._fail(run_id, error, claim=True)

    # --- Guardian ------------------------------------------------------------

    def on_decision(self, decision: dict[str, Any], phase: str) -> None:
        """protect()'s on_decision hook: called on evaluation and again when a human resolves it."""
        if decision.get("id"):
            with self._lock:
                self.decisions[decision["id"]] = decision

    def _claim(self, span: dict[str, Any]) -> None:
        """Pair a finished tool span with the Guardian decision made for it (same tool, same args)."""
        with self._lock:
            free = [d for i, d in self.decisions.items() if i not in self._claimed and d.get("tool") == span["tool_name"]]
            match = next((d for d in free if d.get("args") == span.get("_args")), free[0] if free else None)
            if match:
                self._claimed[match["id"]] = span

    # --- assembling and sending ----------------------------------------------

    def _close(self, span: dict[str, Any]) -> None:
        with self._lock:
            self.spans.append(span)

    def _fail(self, run_id: UUID, error: BaseException, claim: bool = False) -> None:
        with self._lock:
            span, t0 = self._open.pop(run_id, (None, 0.0))
        if span is not None:
            span.update(status="ERROR", error=f"{type(error).__name__}: {error}",
                        duration_ms=round((time.perf_counter() - t0) * 1000, 2))
            if claim:
                self._claim(span)
            self._close(span)

    def summary(self) -> dict[str, Any]:
        llm = [s for s in self.spans if s["kind"] == "LLM"]
        decisions = list(self.decisions.values())
        checked = [d for d in decisions if d.get("checked") is not False]
        jev = [d["jev"] for d in checked if d.get("jev")]
        verdicts = [d.get("verdict") for d in decisions]
        return {
            "duration_ms": round((time.perf_counter() - self._t0) * 1000, 2),
            "llm_calls": len(llm),
            "llm_prompt_tokens": sum((s.get("tokens") or {}).get("prompt") or 0 for s in llm),
            "llm_completion_tokens": sum((s.get("tokens") or {}).get("completion") or 0 for s in llm),
            "tool_calls": sum(1 for s in self.spans if s["kind"] == "TOOL"),
            "guardian_decisions": len(decisions),
            "jev_checks": len(checked),
            "fast_path_allows": len(decisions) - len(checked),
            "jev_input_tokens": sum(j.get("input_tokens") or 0 for j in jev),
            "jev_ms": round(sum(j.get("latency_ms") or 0 for j in jev), 2),
            "guardian_ms": round(sum(d.get("latency_ms") or 0 for d in decisions), 2),
            "allowed": verdicts.count("ALLOW"),
            "blocked": verdicts.count("BLOCK"),
            "escalated": verdicts.count("ESCALATE"),
        }

    def payload(self, output: str | None = None, error: str | None = None) -> dict[str, Any]:
        decision_for = {id(span): self.decisions[i] for i, span in self._claimed.items()}
        children = []
        for span in sorted(self.spans, key=lambda s: s["start"]):
            node = {k: v for k, v in span.items() if not k.startswith("_")}
            decision = decision_for.get(id(span))
            if decision:
                node["metadata"] = {"guardian.verdict": decision.get("verdict"),
                                    "guardian.checked": decision.get("checked", True)}
                guard = guardrail_span(decision)
                if guard:
                    node["children"] = [{**guard, "start": span["start"]}]
            children.append(node)
        totals = self.summary()
        return _drop_nulls({
            "name": f"agent.run {self.name}",
            "project": self.project,
            "input": self.task,
            "output": output,
            "start": self._start,
            "duration_ms": totals["duration_ms"],
            "status": "ERROR" if error else "OK",
            "error": error,
            "attributes": {"neatlogs.session.id": self.session_id, "neatlogs.workflow.name": "langgraph-agent"},
            "metadata": {**self.metadata, **{f"run.{k}": v for k, v in totals.items()}},
            "children": children,
        })

    def send(self, output: str | None = None, error: str | None = None) -> dict[str, Any]:
        """Post the trace. Returns {"mode", "trace_id", "url", "error"}; mode "off" without a key."""
        if not self.api_key:
            return {"mode": "off"}
        return post_trace(self.payload(output, error), api_key=self.api_key, ingest_url=self.ingest_url,
                          app_url=self.app_url, transport=self._transport)

    def refresh_decisions(self, guardian_url: str, wait_s: float = 30.0) -> None:
        """Re-read each decision from Guardian so its own NeatLogs trace link is included.
        Guardian traces a decision in the background, after Entire and the explainer,
        so call this only when Guardian's NeatLogs integration is live."""
        deadline = time.monotonic() + wait_s
        with httpx.Client(timeout=5) as http:
            for decision_id in list(self.decisions):
                while True:
                    try:
                        d = http.get(f"{guardian_url}/decisions/{decision_id}").raise_for_status().json()
                    except httpx.HTTPError:
                        break
                    with self._lock:
                        self.decisions[decision_id] = d
                    if d.get("trace") or time.monotonic() > deadline:
                        break
                    time.sleep(1)
