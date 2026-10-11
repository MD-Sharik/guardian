"""protect(): wrap LangChain / LangGraph tools so Guardian checks every call."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .client import GuardianClient


class ProtectedTools(list):
    """A plain list of tools, plus the GuardianClient that guards them."""

    guardian: GuardianClient


def protect(
    tools: Iterable[Any],
    agent_name: str = "agent",
    *,
    client: GuardianClient | None = None,
    **client_options: Any,
) -> ProtectedTools:
    """Return guarded copies of `tools`.

        from guardian import protect
        tools = protect(tools, agent_name="demo-agent")

    Each call goes to Guardian's /evaluate first. ALLOW runs the tool; BLOCK
    returns a refusal message to the agent instead; ESCALATE waits for a human
    to approve or reject it in the dashboard. Accepts LangChain BaseTools or
    plain functions. Extra keyword arguments go to GuardianClient (url, task,
    session_id, on_decision, fail_open, ...).
    """
    client = client or GuardianClient(agent_name=agent_name, **client_options)
    guarded = ProtectedTools(_wrap(tool, client) for tool in tools)
    guarded.guardian = client
    return guarded


def _wrap(tool: Any, client: GuardianClient) -> Any:
    try:
        from langchain_core.tools import BaseTool, StructuredTool
        from langchain_core.tools import tool as as_tool
    except ImportError as exc:  # pragma: no cover
        raise ImportError("protect() needs langchain-core: pip install 'guardian-sdk[langchain]'") from exc

    if not isinstance(tool, BaseTool):
        tool = as_tool(tool)
    original = tool

    def run(**kwargs: Any) -> Any:
        verdict = client.check(original.name, kwargs, original.description)
        if not verdict.allowed:
            return verdict.message
        return _run_and_report(lambda: original.invoke(kwargs), verdict.id, client)

    async def arun(**kwargs: Any) -> Any:
        verdict = await client.acheck(original.name, kwargs, original.description)
        if not verdict.allowed:
            return verdict.message
        try:
            output = await original.ainvoke(kwargs)
        except Exception as exc:
            await client.areport(verdict.id, ok=False, error=str(exc))
            raise
        await client.areport(verdict.id, ok=True, output=output)
        return output

    return StructuredTool.from_function(
        func=run,
        coroutine=arun,
        name=original.name,
        description=original.description,
        args_schema=original.args_schema,
        return_direct=original.return_direct,
    )


def _run_and_report(call: Callable[[], Any], decision_id: str | None, client: GuardianClient) -> Any:
    try:
        output = call()
    except Exception as exc:
        client.report(decision_id, ok=False, error=str(exc))
        raise
    client.report(decision_id, ok=True, output=output)
    return output
