"""API and storage models."""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

Verdict = Literal["ALLOW", "BLOCK", "ESCALATE"]
Status = Literal["allowed", "blocked", "pending", "approved", "rejected", "expired", "handed_off"]
AdapterMode = Literal["live", "off", "error"]  # configured / not configured / failed


class ActionContext(BaseModel):
    """What the agent was doing when it asked to act. Sent by guardian-sdk."""

    task: str | None = None
    reasoning: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    entire_session_id: str | None = None
    # Integration-specific details, e.g. {"source": "antigravity", "workspace": ..., "model": ..., "step": ...}
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluateRequest(BaseModel):
    agent_name: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    tool_description: str | None = None
    session_id: str | None = None
    context: ActionContext = Field(default_factory=ActionContext)


class JevSignals(BaseModel):
    """Jev's typed answers, flattened into the numbers the policy reads."""

    p_safe: float
    p_on_task: float
    risk: str
    risk_probabilities: dict[str, float]
    risk_confidence: float
    severity: float  # 0 (negligible) .. 3 (critical), probability-weighted
    severity_confidence: float
    severity_probabilities: dict[str, float]
    output_ok: float | None = None  # only asked when the action writes content
    confidence: float  # aggregate: the least certain of the answers above


class JevResult(BaseModel):
    model: str
    latency_ms: float
    signals: JevSignals
    answers: dict[str, Any]  # raw typed answers as returned by Jev
    state: dict[str, Any]  # the state Jev was asked about


class Explanation(BaseModel):
    text: str
    model: str
    generated_at: float = Field(default_factory=time.time)


class TraceRef(BaseModel):
    mode: AdapterMode
    trace_id: str | None = None
    url: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ToolResult(BaseModel):
    ok: bool
    output: str | None = None
    error: str | None = None
    reported_at: float = Field(default_factory=time.time)


class Decision(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = Field(default_factory=time.time)
    agent_name: str
    session_id: str | None = None
    tool: str
    args: dict[str, Any]
    context: ActionContext
    verdict: Verdict
    status: Status
    confidence: float
    reasons: list[str]
    jev: JevResult | None  # None when Jev could not be reached; see jev_error
    jev_error: str | None = None
    latency_ms: float
    explanation: Explanation | None = None
    explanation_pending: bool = False
    explanation_error: str | None = None
    entire: dict[str, Any] | None = None
    trace: TraceRef | None = None
    result: ToolResult | None = None
    resolved_by: str | None = None
    resolved_at: float | None = None
    note: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.status != "pending"

    @property
    def may_execute(self) -> bool:
        return self.status in ("allowed", "approved")


class ResolveRequest(BaseModel):
    by: str = "dashboard"
    note: str | None = None


class ResultRequest(BaseModel):
    ok: bool
    output: str | None = None
    error: str | None = None
