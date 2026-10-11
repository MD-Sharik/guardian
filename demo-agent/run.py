"""Run the LangGraph example agent with every tool call guarded by Guardian.

    python demo-agent/run.py happy        # fix a typo and run the script
    python demo-agent/run.py danger       # the user asks for `rm -rf ./*`
    python demo-agent/run.py uncertain    # a data migration with --apply
    python demo-agent/run.py --task "Add a farewell() function to app/greeter.py"

An LLM planner decides what to do (the OpenAI-compatible endpoint in
LLM_BASE_URL, e.g. DeepSeek on Modal), and Jev decides whether each step may run.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "guardian-sdk")]

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from agent import LLMPlanner, build_agent  # noqa: E402
from examples import EXAMPLES  # noqa: E402
from guardian import GuardianClient, protect  # noqa: E402
from sandbox_tools import TOOLS, reset_workspace  # noqa: E402

load_dotenv(HERE.parent / ".env")

if os.name == "nt":
    os.system("")  # enable ANSI colours in the Windows console
sys.stdout.reconfigure(encoding="utf-8")

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
COLORS = {"ALLOW": "\033[32m", "BLOCK": "\033[31m", "ESCALATE": "\033[33m"}
DASHBOARD = os.getenv("GUARDIAN_DASHBOARD_URL", "http://localhost:3000")


def say(text: str = "", indent: int = 0) -> None:
    print(textwrap.indent(text, " " * indent), flush=True)


def on_decision(decision: dict, phase: str) -> None:
    verdict, status = decision.get("verdict", "?"), decision.get("status", "?")
    color = COLORS.get(verdict, "")
    if phase == "evaluated":
        jev = decision.get("jev") or {}
        source = f"{jev.get('model')} · {jev.get('latency_ms', 0):.0f} ms" if jev else "Jev unreachable"
        say(f"{color}{BOLD}■ {verdict}{RESET} {DIM}confidence {decision.get('confidence', 0):.2f} · {source}{RESET}", 4)
        for reason in decision.get("reasons", [])[:2]:
            say(f"{DIM}{reason}{RESET}", 6)
        if status == "pending":
            say(f"\033[33m⏳ Waiting for a human. Approve or reject it in the dashboard: {DASHBOARD}{RESET}", 4)
    else:
        mark = "✓ approved" if status == "approved" else f"✗ {status}"
        say(f"{color}{BOLD}{mark}{RESET} {DIM}by {decision.get('resolved_by')}{RESET}", 4)


def check_service(url: str) -> dict:
    try:
        return httpx.get(f"{url}/health", timeout=3).raise_for_status().json()
    except httpx.HTTPError:
        say(f"\033[31mGuardian service is not reachable at {url}.{RESET}")
        say("Start it first:  python dev.py")
        sys.exit(1)


def print_step(message) -> None:
    if isinstance(message, AIMessage):
        text = message.text if isinstance(message.text, str) else message.text()
        if message.tool_calls:
            if text:
                say(f"\n{BOLD}🤖 {text}{RESET}")
            for call in message.tool_calls:
                args = ", ".join(f"{k}={_short(v)!r}" for k, v in call["args"].items())
                say(f"→ {call['name']}({args})", 2)
        else:
            say(f"\n{BOLD}🏁 {text}{RESET}")
    elif isinstance(message, ToolMessage):
        say(f"{DIM}↳ {_short(str(message.content), 160)}{RESET}", 4)


def _short(value, limit: int = 60):
    if isinstance(value, str):
        flat = value.replace("\n", "⏎ ")
        return flat if len(flat) <= limit else flat[:limit] + "…"
    return value


def llm_config() -> dict[str, str]:
    token_id, secret = os.getenv("MODAL_PROXY_TOKEN_ID", ""), os.getenv("MODAL_PROXY_TOKEN_SECRET", "")
    api_key = os.getenv("LLM_API_KEY") or (f"{token_id}.{secret}" if token_id and secret else "")
    base_url = os.getenv("LLM_BASE_URL", "")
    if not (base_url and api_key):
        sys.exit("The example agent needs an LLM: set LLM_BASE_URL and MODAL_PROXY_TOKEN_ID/SECRET "
                 "(or LLM_API_KEY) in .env")
    return {"base_url": base_url, "api_key": api_key,
            "model": os.getenv("LLM_MODEL") or "deepseek-ai/DeepSeek-V4.1-Flash"}


def run(task: str, title: str, url: str) -> None:
    llm = llm_config()
    reset_workspace()
    tools = protect(TOOLS, agent_name="langgraph-agent", url=url, task=task, on_decision=on_decision)
    guardian: GuardianClient = tools.guardian
    planner = LLMPlanner(tools, guardian, **llm)

    say(f"\n{BOLD}━━ {title} ━━{RESET}")
    say(f"{DIM}task: {task}{RESET}")
    say(f"{DIM}session: {guardian.session_id}{RESET}")

    agent = build_agent(planner, tools)
    for update in agent.stream({"messages": [HumanMessage(task)]}, {"recursion_limit": 40}, stream_mode="updates"):
        for node in update.values():
            for message in node["messages"]:
                print_step(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LangGraph example agent behind Guardian.")
    parser.add_argument("example", nargs="?", choices=list(EXAMPLES), help="a built-in example task")
    parser.add_argument("--task", help="your own task instead of an example")
    parser.add_argument("--url", default=os.getenv("GUARDIAN_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args()
    if not (args.example or args.task):
        parser.error(f"pick an example ({', '.join(EXAMPLES)}) or pass --task")
    llm_config()  # fail early with a clear message

    health = check_service(args.url)
    modes = " · ".join(f"{k} {v}" for k, v in health["modes"].items())
    say(f"{DIM}Guardian at {args.url} ({modes}){RESET}")
    if args.task:
        run(args.task, "Your task", args.url)
    else:
        run(EXAMPLES[args.example], f"Example: {args.example}", args.url)


if __name__ == "__main__":
    main()
