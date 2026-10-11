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
import json
import os
import sys
import textwrap
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "guardian-sdk")]

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from agent import LLMPlanner, build_agent  # noqa: E402
from examples import EXAMPLES  # noqa: E402
from guardian import GuardianClient, protect  # noqa: E402
from run_trace import RunTrace, post_trace  # noqa: E402
from sandbox_tools import TOOLS, reset_workspace  # noqa: E402

load_dotenv(HERE.parent / ".env")

if os.name == "nt":
    os.system("")  # enable ANSI colours in the Windows console
sys.stdout.reconfigure(encoding="utf-8")

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
COLORS = {"ALLOW": "\033[32m", "BLOCK": "\033[31m", "ESCALATE": "\033[33m"}
DASHBOARD = os.getenv("GUARDIAN_DASHBOARD_URL", "http://localhost:3000")
RUNS_DIR = HERE.parent / "evidence" / "runs"


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


def run(task: str, title: str, url: str, health: dict, label: str) -> None:
    llm = llm_config()
    reset_workspace()
    session_id = f"run-{uuid.uuid4().hex[:8]}"
    fast_path = health.get("fast_path_tools") or ""
    trace = RunTrace(
        title, task, session_id,
        project=os.getenv("NEATLOGS_PROJECT") or "guardian",
        api_key=os.getenv("NEATLOGS_API_KEY", ""),
        ingest_url=os.getenv("NEATLOGS_INGEST_URL") or "https://ingest.neatlogs.com",
        app_url=os.getenv("NEATLOGS_APP_URL") or "https://app.neatlogs.com",
        metadata={"llm.model": llm["model"], "jev.model": health.get("jev_model"), "guardian.fast_path": fast_path},
    )

    def decided(decision: dict, phase: str) -> None:
        on_decision(decision, phase)
        trace.on_decision(decision, phase)

    tools = protect(TOOLS, agent_name="langgraph-agent", url=url, task=task, session_id=session_id,
                    on_decision=decided)
    guardian: GuardianClient = tools.guardian
    planner = LLMPlanner(tools, guardian, **llm)

    say(f"\n{BOLD}━━ {title} ━━{RESET}")
    say(f"{DIM}task: {task}{RESET}")
    say(f"{DIM}session: {session_id} · fast path: {fast_path or 'off (every tool checked)'}{RESET}")

    agent = build_agent(planner, tools)
    final, error = None, None
    try:
        for update in agent.stream({"messages": [HumanMessage(task)]}, {"recursion_limit": 40, "callbacks": [trace]},
                                   stream_mode="updates"):
            for node in update.values():
                for message in node["messages"]:
                    print_step(message)
                    if isinstance(message, AIMessage) and not message.tool_calls:
                        final = message.text if isinstance(message.text, str) else message.text()
    except Exception as exc:  # still trace the run, so the failure is visible in NeatLogs
        error = f"{type(exc).__name__}: {exc}"
        say(f"\033[31m✗ run failed: {error}{RESET}")

    if health["modes"].get("neatlogs") == "live":
        trace.refresh_decisions(url)  # include each decision's own NeatLogs trace link
    sent = trace.send(final, error)
    report(trace.summary(), sent)
    save_run(label, title, task, session_id, fast_path, trace, sent, final, error)
    if error:
        sys.exit(1)


def report(totals: dict, sent: dict) -> None:
    say(f"\n{BOLD}Run summary{RESET}")
    say(f"LLM calls {totals['llm_calls']} ({totals['llm_prompt_tokens']} in / {totals['llm_completion_tokens']} out "
        f"tokens) · tool calls {totals['tool_calls']}", 2)
    say(f"Guardian decisions {totals['guardian_decisions']}: Jev checks {totals['jev_checks']}, fast path "
        f"{totals['fast_path_allows']} · allowed {totals['allowed']}, blocked {totals['blocked']}, "
        f"escalated {totals['escalated']}", 2)
    say(f"Guardian time {totals['guardian_ms']:.0f} ms (Jev {totals['jev_ms']:.0f} ms, "
        f"{totals['jev_input_tokens']} input tokens) · run {totals['duration_ms'] / 1000:.1f} s", 2)
    if sent.get("mode") == "live":
        say(f"NeatLogs trace: {sent['url']}", 2)
    elif sent.get("mode") == "error":
        say(f"\033[31mNeatLogs trace failed: {sent['error']}{RESET}", 2)


def save_run(label, title, task, session_id, fast_path, trace, sent, final, error) -> None:
    """Keep each run's numbers and links as evidence (evidence/runs/*.json)."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}.json"
    decisions = [{"id": d.get("id"), "tool": d.get("tool"), "args": d.get("args"), "verdict": d.get("verdict"),
                  "status": d.get("status"), "checked": d.get("checked", True),
                  "p_safe": ((d.get("jev") or {}).get("signals") or {}).get("p_safe"),
                  "jev_ms": (d.get("jev") or {}).get("latency_ms"), "guardian_ms": d.get("latency_ms"),
                  "trace_url": (d.get("trace") or {}).get("url")} for d in trace.decisions.values()]
    record = {
        "title": title, "task": task, "session_id": session_id, "fast_path_tools": fast_path,
        "totals": trace.summary(), "neatlogs": sent, "final_answer": final, "error": error, "decisions": decisions,
    }
    if sent.get("mode") == "error":
        record["neatlogs_payload"] = trace.payload(final, error)  # for `run.py --resend`
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    say(f"{DIM}saved {path.relative_to(HERE.parent)}{RESET}", 2)


def resend_failed_runs(url: str) -> None:
    """Send run traces NeatLogs didn't accept, adding Guardian's own trace links where they now exist."""
    pending = [p for p in sorted(RUNS_DIR.glob("*.json"))
               if "neatlogs_payload" in json.loads(p.read_text(encoding="utf-8"))]
    if not pending:
        say("No failed run traces to resend.")
    for path in pending:
        record = json.loads(path.read_text(encoding="utf-8"))
        links = {}
        for d in record["decisions"]:
            try:
                trace = httpx.get(f"{url}/decisions/{d['id']}", timeout=5).raise_for_status().json().get("trace") or {}
            except httpx.HTTPError:
                trace = {}
            if trace.get("mode") == "live":
                d["trace_url"] = links[d["id"]] = trace.get("url")
        for tool in record["neatlogs_payload"].get("children", []):
            for guard in tool.get("children", []):
                meta = guard.get("metadata", {})
                if meta.get("guardian.decision_id") in links:
                    meta["guardian.trace_url"] = links[meta["guardian.decision_id"]]
        sent = post_trace(record["neatlogs_payload"], api_key=os.getenv("NEATLOGS_API_KEY", ""),
                          ingest_url=os.getenv("NEATLOGS_INGEST_URL") or "https://ingest.neatlogs.com",
                          app_url=os.getenv("NEATLOGS_APP_URL") or "https://app.neatlogs.com")
        record["neatlogs"] = sent
        if sent["mode"] == "live":
            del record["neatlogs_payload"]
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        say(f"{path.name}: {sent.get('url') or sent.get('error')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LangGraph example agent behind Guardian.")
    parser.add_argument("example", nargs="?", choices=list(EXAMPLES), help="a built-in example task")
    parser.add_argument("--task", help="your own task instead of an example")
    parser.add_argument("--url", default=os.getenv("GUARDIAN_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--resend", action="store_true", help="resend run traces NeatLogs didn't accept")
    args = parser.parse_args()
    if args.resend:
        return resend_failed_runs(args.url)
    if not (args.example or args.task):
        parser.error(f"pick an example ({', '.join(EXAMPLES)}) or pass --task")
    llm_config()  # fail early with a clear message

    health = check_service(args.url)
    modes = " · ".join(f"{k} {v}" for k, v in health["modes"].items())
    say(f"{DIM}Guardian at {args.url} ({modes}){RESET}")
    label = (args.example or "task") + ("-fast" if health.get("fast_path_tools") else "-full")
    if args.task:
        run(args.task, "Your task", args.url, health, label)
    else:
        run(EXAMPLES[args.example], f"Example: {args.example}", args.url, health, label)


if __name__ == "__main__":
    main()
