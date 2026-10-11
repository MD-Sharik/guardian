"""A small LangGraph coding/ops agent: an LLM plans a step, a tool runs, repeat.

Tools run through LangGraph's ToolNode, so whatever `protect()` returns is
exactly what executes: every call is checked by Guardian first. A tool that
raises becomes an error result the agent can read and recover from, instead
of ending the run.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from guardian import GuardianClient


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def build_agent(planner, tools: list[Any]):
    graph = StateGraph(AgentState)
    graph.add_node("agent", planner)
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


LLM_SYSTEM = (
    "You are a coding and ops agent working in a small project workspace. Use the tools to complete the "
    "task. Before each tool call, say in one sentence what you are about to do and why. Tool results that "
    "start with 'GUARDIAN' come from a safety layer: never retry a refused action, find a safer approach."
)


class LLMPlanner:
    """An OpenAI-compatible chat model (e.g. DeepSeek on Modal) bound to the protected tools."""

    def __init__(self, tools: list[Any], guardian: GuardianClient, *, base_url: str, api_key: str, model: str):
        base_url = base_url.rstrip("/").removesuffix("/chat/completions")
        self.llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, max_tokens=4096, temperature=0.2)
        self.llm = self.llm.bind_tools(tools)
        self.guardian = guardian

    def __call__(self, state: AgentState) -> dict:
        reply = self.llm.invoke([SystemMessage(LLM_SYSTEM), *state["messages"]])
        text = reply.text if isinstance(reply.text, str) else reply.text()
        if text:
            self.guardian.set_context(reasoning=text)
        return {"messages": [reply]}
