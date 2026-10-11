"""Guardian REST + SSE API.

POST /evaluate             action in, decision out
POST /approve/{id}         human approves an ESCALATE
POST /reject/{id}          human rejects an ESCALATE
POST /handoff/{id}         the agent stopped waiting and asked its own human
GET  /decisions            decision history, newest first
GET  /decisions/{id}       one decision
GET  /decisions/{id}/wait  long-poll until an ESCALATE is resolved
POST /decisions/{id}/result   the agent reports what the tool returned
POST /decisions/{id}/explain  generate an explanation on demand
GET  /stream               server-sent events: every decision as it changes
GET  /health               adapter modes (live / off) and thresholds
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config import Settings
from .events import sse
from .guardian import Guardian
from .models import Decision, EvaluateRequest, ResolveRequest, ResultRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

KEEPALIVE_S = 15


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    log = logging.getLogger("guardian")
    try:
        app.state.guardian = Guardian(settings)
    except RuntimeError as exc:  # e.g. JEV_API_KEY missing: nothing to decide with
        log.error("Guardian can't start: %s", exc)
        raise SystemExit(1) from exc
    log.info("adapter modes: %s", app.state.guardian.modes)
    yield
    await app.state.guardian.aclose()


app = FastAPI(title="Guardian", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


def g(request: Request) -> Guardian:
    return request.app.state.guardian


def found(d: Decision | None) -> Decision:
    if d is None:
        raise HTTPException(404, "decision not found")
    return d


@app.get("/health")
def health(request: Request) -> dict:
    guardian = g(request)
    return {
        "status": "ok",
        "modes": guardian.modes,
        "thresholds": asdict(guardian.settings.thresholds),
        "llm_model": guardian.settings.llm_model,
        "jev_model": guardian.settings.jev_model,
        "jev_base_url": guardian.settings.jev_base_url or "https://api.typesafe.ai",
        "neatlogs_project": guardian.settings.neatlogs_project,
        "neatlogs_app_url": guardian.settings.neatlogs_app_url,
        "escalation_timeout_s": guardian.settings.escalation_timeout_s,
    }


@app.post("/evaluate")
async def evaluate(req: EvaluateRequest, request: Request) -> Decision:
    return await g(request).evaluate(req)


@app.get("/decisions")
def list_decisions(request: Request, limit: int = Query(200, ge=1, le=1000)) -> list[Decision]:
    return g(request).store.list(limit)


@app.delete("/decisions")
def clear_decisions(request: Request) -> dict:
    g(request).clear()
    return {"cleared": True}


@app.get("/decisions/{decision_id}")
def get_decision(decision_id: str, request: Request) -> Decision:
    return found(g(request).store.get(decision_id))


@app.get("/decisions/{decision_id}/wait")
async def wait_decision(decision_id: str, request: Request, timeout: float = Query(25, ge=0, le=60)) -> Decision:
    return found(await g(request).wait(decision_id, timeout))


@app.post("/approve/{decision_id}")
def approve(decision_id: str, request: Request, body: ResolveRequest | None = None) -> Decision:
    body = body or ResolveRequest()
    return found(g(request).resolve(decision_id, True, body.by, body.note))


@app.post("/reject/{decision_id}")
def reject(decision_id: str, request: Request, body: ResolveRequest | None = None) -> Decision:
    body = body or ResolveRequest()
    return found(g(request).resolve(decision_id, False, body.by, body.note))


@app.post("/handoff/{decision_id}")
def handoff(decision_id: str, request: Request, body: ResolveRequest | None = None) -> Decision:
    body = body or ResolveRequest(by="agent")
    return found(g(request).handoff(decision_id, body.by))


@app.post("/decisions/{decision_id}/result")
def report_result(decision_id: str, body: ResultRequest, request: Request) -> Decision:
    return found(g(request).report_result(decision_id, body))


@app.post("/decisions/{decision_id}/explain")
async def explain(decision_id: str, request: Request) -> Decision:
    if g(request).explainer.mode == "off":
        raise HTTPException(409, "The explainer is off. Set LLM_BASE_URL and MODAL_PROXY_TOKEN_ID/SECRET (or LLM_API_KEY).")
    return found(await g(request).explain(decision_id))


@app.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    guardian = g(request)

    async def events():
        queue = guardian.broker.subscribe()
        try:
            yield "retry: 2000\n\n"
            yield sse("hello", {"modes": guardian.modes})
            while not await request.is_disconnected():
                try:
                    yield await asyncio.wait_for(queue.get(), KEEPALIVE_S)
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            guardian.broker.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
