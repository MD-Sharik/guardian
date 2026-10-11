"""The NeatLogs run trace, end to end: a real Guardian server (Jev replaced by the
test stand-in), the real protect() and LangGraph agent, and a scripted chat model."""

import importlib.util
import json
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

HERE = Path(__file__).resolve().parents[1]
SERVICE_DIR = HERE.parent / "guardian-service"
sys.path[:0] = [str(HERE), str(HERE.parent / "guardian-sdk")]

import sandbox_tools as sb  # noqa: E402
from agent import build_agent  # noqa: E402
from guardian import protect  # noqa: E402
from run_trace import RunTrace, post_trace  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def guardian_url(tmp_path, monkeypatch):
    import uvicorn

    monkeypatch.syspath_prepend(str(SERVICE_DIR))
    service_tests = _load("service_conftest", SERVICE_DIR / "tests" / "conftest.py")
    service_tests.isolate_env(monkeypatch, tmp_path)
    monkeypatch.setenv("GUARDIAN_FAST_PATH_TOOLS", "read_file")
    service_tests.use_fake_jev(monkeypatch)
    from app.main import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "WORKSPACE", tmp_path / "workspace")
    sb.reset_workspace()


def reply(tokens_in, tokens_out, text="", **call):
    calls = [{"name": call["tool"], "args": call["args"], "id": f"call_{tokens_in}"}] if call else []
    return AIMessage(content=text, tool_calls=calls, usage_metadata={
        "input_tokens": tokens_in, "output_tokens": tokens_out, "total_tokens": tokens_in + tokens_out})


def test_one_trace_per_run_with_tokens_tools_and_verdicts(guardian_url):
    model = GenericFakeChatModel(messages=iter([
        reply(100, 20, "Reading the script first.", tool="read_file", args={"path": "app/greeter.py"}),
        reply(150, 25, "Wiping the workspace.", tool="run_shell", args={"command": "rm -rf ./*"}),
        reply(200, 30, "Guardian refused the wipe, so I left the workspace as it was."),
    ]))
    sent = {}

    def neatlogs(request):
        sent["body"] = json.loads(request.content)
        sent["key"] = request.headers["x-api-key"]
        return httpx.Response(200, json={"success": True, "trace_id": "tr_run", "spans": 7})

    trace = RunTrace("test", "Clean up", "run-test1", project="guardian", api_key="nl-key",
                     metadata={"llm.model": "fake"}, transport=httpx.MockTransport(neatlogs))
    tools = protect(sb.TOOLS, agent_name="test-agent", url=guardian_url, session_id="run-test1",
                    on_decision=trace.on_decision)
    agent = build_agent(lambda state: {"messages": [model.invoke(state["messages"])]}, tools)
    agent.invoke({"messages": [HumanMessage("Clean up")]}, {"callbacks": [trace]})

    ref = trace.send("Guardian refused the wipe.")
    assert ref == {"mode": "live", "trace_id": "tr_run", "url": "https://app.neatlogs.com/traces/tr_run"}
    body = sent["body"]
    assert sent["key"] == "nl-key" and body["project"] == "guardian"
    assert body["name"] == "agent.run test"
    assert body["attributes"]["neatlogs.session.id"] == "run-test1"  # groups with Guardian's decision traces
    assert "null" not in json.dumps(body)  # NeatLogs rejects null fields

    kinds = [(c["kind"], c["name"]) for c in body["children"]]
    # One span per tool call: protect() running the original tool inside is not a second call.
    assert kinds == [("LLM", "llm"), ("TOOL", "read_file"), ("LLM", "llm"), ("TOOL", "run_shell"), ("LLM", "llm")]
    llm = body["children"][0]
    assert llm["tokens"] == {"prompt": 100, "completion": 20, "total": 120}

    read, shell = body["children"][1], body["children"][3]
    assert read["metadata"] == {"guardian.verdict": "ALLOW", "guardian.checked": False}
    assert "children" not in read  # fast path: Jev wasn't asked
    assert "Helo" in read["output"]
    assert shell["output"].startswith("GUARDIAN")
    guard = shell["children"][0]
    assert guard["kind"] == "GUARDRAIL" and guard["passed"] is False and guard["score"] == 0.03
    assert guard["metadata"]["guardian.verdict"] == "BLOCK" and guard["metadata"]["jev.model"] == "jev-test"

    totals = trace.summary()
    assert {k: totals[k] for k in ("llm_calls", "llm_prompt_tokens", "llm_completion_tokens", "tool_calls",
                                   "guardian_decisions", "jev_checks", "fast_path_allows", "allowed", "blocked")} == {
        "llm_calls": 3, "llm_prompt_tokens": 450, "llm_completion_tokens": 75, "tool_calls": 2,
        "guardian_decisions": 2, "jev_checks": 1, "fast_path_allows": 1, "allowed": 1, "blocked": 1,
    }
    assert body["metadata"]["run.jev_checks"] == 1 and body["metadata"]["llm.model"] == "fake"


def test_a_failing_tool_is_reported_to_the_agent_and_traced(guardian_url):
    model = GenericFakeChatModel(messages=iter([
        reply(100, 20, tool="read_file", args={"path": "missing.txt"}),
        reply(120, 20, "That file doesn't exist; nothing to do."),
    ]))
    trace = RunTrace("t", "task", "run-test2", project="guardian")
    tools = protect(sb.TOOLS, agent_name="test-agent", url=guardian_url, session_id="run-test2",
                    on_decision=trace.on_decision)
    agent = build_agent(lambda state: {"messages": [model.invoke(state["messages"])]}, tools)
    result = agent.invoke({"messages": [HumanMessage("Read missing.txt")]}, {"callbacks": [trace]})

    error_result = result["messages"][2]
    assert error_result.status == "error" and "FileNotFoundError" in error_result.content
    assert result["messages"][-1].content == "That file doesn't exist; nothing to do."  # the run carried on
    tool = trace.payload()["children"][1]
    assert tool["status"] == "ERROR" and tool["error"].startswith("FileNotFoundError")
    assert tool["metadata"]["guardian.verdict"] == "ALLOW"


def test_ingest_outage_is_retried():
    replies = iter([httpx.Response(503), httpx.Response(200, json={"trace_id": "t"})])
    ref = post_trace({"name": "x"}, api_key="k", transport=httpx.MockTransport(lambda r: next(replies)), backoff_s=0)
    assert ref == {"mode": "live", "trace_id": "t", "url": "https://app.neatlogs.com/traces/t"}


def test_trace_is_off_without_a_key():
    assert RunTrace("t", "task", "s", project="p").send() == {"mode": "off"}


def test_ingest_failure_is_reported_not_raised():
    trace = RunTrace("t", "task", "s", project="p", api_key="k",
                     transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad trace")))
    ref = trace.send()
    assert ref["mode"] == "error" and "bad trace" in ref["error"]
