"""Explainer: turn a decision + Entire session data into plain English.

Calls any OpenAI-compatible `/chat/completions` endpoint. Guardian is set up
for a Modal Shared Endpoint serving deepseek-ai/DeepSeek-V4.1-Flash, which
authenticates with `Authorization: Bearer <MODAL_PROXY_TOKEN_ID>.<MODAL_PROXY_TOKEN_SECRET>`.
"""

from __future__ import annotations

import json
import re

import httpx

from ..config import Settings
from ..models import Decision, Explanation

SYSTEM = """You explain AI-agent safety decisions to engineers watching a live dashboard.

You receive the tool call an agent attempted, the typed verdict from Jev (TypeSafe AI's decision model) \
with Guardian's policy reasons, and the agent's captured session from Entire (its intent, reasoning, \
transcript, files and commit) when available.

Write exactly three lines, each starting with its label:
What it tried: <the action in concrete terms>
Why it did it: <the agent's motive, grounded in the session data; if the session does not show a motive, say so>
Why Guardian {verb}: <the deciding risk, then one safer alternative>

Plain English, no markdown, under 110 words in total."""

VERBS = {"BLOCK": "blocked it", "ESCALATE": "asked a human", "ALLOW": "allowed it"}
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class ExplainerError(Exception):
    pass


def chat_completions_url(base_url: str) -> str:
    """Accept the base (…/v1) or the full …/v1/chat/completions URL."""
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def build_prompt(d: Decision, entire: dict | None) -> str:
    facts: dict = {
        "agent": d.agent_name,
        "attempted_action": {"tool": d.tool, "args": d.args},
        "agent_task": d.context.task,
        "agent_reasoning": d.context.reasoning,
        "guardian_verdict": d.verdict,
        "policy_reasons": d.reasons,
        "entire_session": entire,
    }
    if d.jev:
        s = d.jev.signals
        facts["jev_answers"] = {
            "p_safe": s.p_safe,
            "risk": s.risk,
            "risk_probabilities": s.risk_probabilities,
            "severity_0_to_3": s.severity,
            "confidence": s.confidence,
        }
    else:
        facts["jev_error"] = d.jev_error
    return json.dumps(facts, default=str, ensure_ascii=False, indent=1)[:20000]


async def complete(http: httpx.AsyncClient, settings: Settings, system: str, user: str, max_tokens: int) -> tuple[str, str]:
    """One chat completion. Returns (text, model). Raises ExplainerError."""
    try:
        resp = await http.post(
            chat_completions_url(settings.llm_base_url),
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
                "stream": False,
            },
        )
    except httpx.HTTPError as exc:
        raise ExplainerError(f"could not reach the LLM endpoint: {exc}") from exc
    if resp.status_code >= 400:
        raise ExplainerError(f"LLM endpoint returned {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
        choice = data["choices"][0]
        text = THINK_BLOCK.sub("", choice["message"].get("content") or "").strip()
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ExplainerError(f"unexpected response from the LLM endpoint: {resp.text[:300]}") from exc
    if not text:
        raise ExplainerError(f"the LLM returned no text (finish_reason={choice.get('finish_reason')})")
    return text, data.get("model") or settings.llm_model


class Explainer:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.mode = "live" if settings.llm_base_url and settings.llm_api_key else "off"
        # Generous timeout: a Modal endpoint may need to cold-start. This runs in the background.
        self._http = httpx.AsyncClient(timeout=120.0, transport=transport) if self.mode == "live" else None

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def explain(self, d: Decision, entire: dict | None) -> Explanation:
        """Raises ExplainerError when the LLM can't produce an explanation."""
        assert self._http is not None, "explainer is off"
        system = SYSTEM.format(verb=VERBS[d.verdict])
        text, model = await complete(self._http, self.settings, system, build_prompt(d, entire), max_tokens=2048)
        return Explanation(text=text, model=model)
