"""protect() and the Antigravity hook, end to end against a real Guardian server.

The server runs the real service code; only Jev's HTTP API is replaced by the
test stand-in in guardian-service/tests/fake_jev.py.
"""

import asyncio
import importlib.util
import io
import json
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from langchain_core.tools import tool

from guardian import GuardianClient, antigravity, is_guardian_refusal, protect

SERVICE_DIR = Path(__file__).resolve().parents[2] / "guardian-service"


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
    monkeypatch.setenv("GUARDIAN_ESCALATION_TIMEOUT", "5")  # a stuck escalation fails fast
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
    url = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("GUARDIAN_URL", url)
    yield url
    server.should_exit = True
    thread.join(5)


ran: list[str] = []


@tool
def read_file(path: str) -> str:
    """Read a file."""
    ran.append(f"read {path}")
    return f"contents of {path}"


@tool
def run_shell(command: str) -> str:
    """Run a shell command."""
    ran.append(f"shell {command}")
    return "ok"


@pytest.fixture(autouse=True)
def reset_ran():
    ran.clear()


def resolve_when_pending(url: str, approve: bool) -> threading.Thread:
    def worker():
        for _ in range(100):
            pending = [d for d in httpx.get(f"{url}/decisions").json() if d["status"] == "pending"]
            if pending:
                httpx.post(f"{url}/{'approve' if approve else 'reject'}/{pending[0]['id']}", json={"by": "test"})
                return
            time.sleep(0.05)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def latest(url: str) -> dict:
    return httpx.get(f"{url}/decisions").json()[0]


def wait_until(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# ── protect() ───────────────────────────────────────────────────────────────


def test_allow_runs_the_tool_and_reports_the_result(guardian_url):
    tools = protect([read_file], agent_name="t", url=guardian_url, task="read things")
    assert tools[0].invoke({"path": "README.md"}) == "contents of README.md"
    assert ran == ["read README.md"]
    d = latest(guardian_url)
    assert d["verdict"] == "ALLOW" and d["context"]["task"] == "read things"
    assert wait_until(lambda: httpx.get(f"{guardian_url}/decisions/{d['id']}").json()["result"])


def test_block_never_runs_the_tool(guardian_url):
    out = protect([run_shell], url=guardian_url)[0].invoke({"command": "rm -rf ./*"})
    assert is_guardian_refusal(out) and out.startswith("GUARDIAN BLOCKED")
    assert ran == []


def test_escalate_waits_then_runs_when_approved(guardian_url):
    tools = protect([run_shell], url=guardian_url)
    approver = resolve_when_pending(guardian_url, approve=True)
    assert tools[0].invoke({"command": "python scripts/migrate_db.py --apply"}) == "ok"
    approver.join(5)
    assert ran == ["shell python scripts/migrate_db.py --apply"]


def test_escalate_rejected_does_not_run(guardian_url):
    tools = protect([run_shell], url=guardian_url)
    rejecter = resolve_when_pending(guardian_url, approve=False)
    out = tools[0].invoke({"command": "python scripts/migrate_db.py --apply"})
    rejecter.join(5)
    assert out.startswith("GUARDIAN REJECTED") and ran == []


def test_async_tools_are_guarded_too(guardian_url):
    tools = protect([read_file, run_shell], url=guardian_url)
    assert asyncio.run(tools[0].ainvoke({"path": "a.txt"})) == "contents of a.txt"
    assert asyncio.run(tools[1].ainvoke({"command": "rm -rf ./*"})).startswith("GUARDIAN BLOCKED")
    assert ran == ["read a.txt"]


def test_reasoning_and_history_are_sent(guardian_url):
    tools = protect([read_file, run_shell], url=guardian_url)
    tools.guardian.set_context(reasoning="look first")
    tools[0].invoke({"path": "a.txt"})
    tools.guardian.set_context(reasoning="now wipe")
    tools[1].invoke({"command": "rm -rf ./*"})
    d = latest(guardian_url)
    assert d["context"]["reasoning"] == "now wipe"
    assert d["context"]["history"][0]["tool"] == "read_file"


def test_unreachable_service_fails_closed_by_default():
    dead = "http://127.0.0.1:9"
    out = protect([read_file], url=dead)[0].invoke({"path": "a"})
    assert out.startswith("GUARDIAN UNAVAILABLE") and ran == []
    client = GuardianClient(url=dead, fail_open=True)
    assert protect([read_file], client=client)[0].invoke({"path": "a"}) == "contents of a"


def test_plain_functions_are_accepted(guardian_url):
    def echo(text: str) -> str:
        """Echo text back."""
        return text

    [guarded] = protect([echo], url=guardian_url)
    assert guarded.name == "echo" and guarded.invoke({"text": "hi"}) == "hi"


# ── Antigravity hook ────────────────────────────────────────────────────────


def hook_payload(tmp_path, tool, args, step=0, transcript=None):
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in (transcript or [])), encoding="utf-8")
    return {
        "toolCall": {"name": tool, "args": args},
        "stepIdx": step,
        "conversationId": "conv-abc",
        "workspacePaths": [str(tmp_path)],
        "transcriptPath": str(path),
        "artifactDirectoryPath": str(tmp_path),
        "modelName": "gemini-test",
    }


def run_hook(event, payload, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload) if isinstance(payload, dict) else payload))
    with pytest.raises(SystemExit) as exit_info:
        antigravity.main([event])
    assert exit_info.value.code == 0  # a non-zero exit would make Antigravity deny the call
    return json.loads(capsys.readouterr().out)


def test_hook_allows_safe_calls_and_sends_context(guardian_url, tmp_path, monkeypatch, capsys):
    transcript = [
        {"role": "user", "content": [{"type": "text", "text": "Fix the typo in greeter.py"}]},
        {"role": "assistant", "content": "I'll open greeter.py first."},
    ]
    payload = hook_payload(tmp_path, "view_file", {"AbsolutePath": "greeter.py"}, transcript=transcript)
    assert run_hook("pre", payload, monkeypatch, capsys) == {"decision": "allow"}

    d = latest(guardian_url)
    assert d["agent_name"] == "antigravity" and d["session_id"] == "conv-abc"
    assert d["tool"] == "view_file" and d["args"] == {"AbsolutePath": "greeter.py"}
    assert d["context"]["task"] == "Fix the typo in greeter.py"
    assert d["context"]["reasoning"] == "I'll open greeter.py first."
    assert d["context"]["entire_session_id"] == "conv-abc"
    assert d["context"]["metadata"]["workspace"] == str(tmp_path)
    assert d["context"]["metadata"]["model"] == "gemini-test"

    # PostToolUse reports the outcome against the same decision
    assert run_hook("post", payload, monkeypatch, capsys) == {}
    assert wait_until(lambda: httpx.get(f"{guardian_url}/decisions/{d['id']}").json()["result"] is not None)


def test_hook_denies_dangerous_calls_with_a_reason(guardian_url, tmp_path, monkeypatch, capsys):
    out = run_hook("pre", hook_payload(tmp_path, "run_command", {"CommandLine": "rm -rf ./*"}), monkeypatch, capsys)
    assert out["decision"] == "deny" and out["reason"].startswith("GUARDIAN BLOCKED")


def test_hook_waits_for_the_dashboard(guardian_url, tmp_path, monkeypatch, capsys):
    approver = resolve_when_pending(guardian_url, approve=True)
    payload = hook_payload(tmp_path, "run_command", {"CommandLine": "python migrate.py --apply"}, step=4)
    assert run_hook("pre", payload, monkeypatch, capsys) == {"decision": "allow"}
    approver.join(5)
    assert latest(guardian_url)["status"] == "approved"


def test_hook_hands_over_to_antigravity_when_nobody_answers(guardian_url, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(antigravity, "HOOK_WAIT_S", 0.5)
    payload = hook_payload(tmp_path, "run_command", {"CommandLine": "python migrate.py --apply"}, step=5)
    out = run_hook("pre", payload, monkeypatch, capsys)
    assert out["decision"] == "force_ask" and "nobody answered" in out["reason"]
    assert latest(guardian_url)["status"] == "handed_off"


def test_hook_asks_the_human_when_guardian_is_down(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GUARDIAN_URL", "http://127.0.0.1:9")
    out = run_hook("pre", hook_payload(tmp_path, "view_file", {"AbsolutePath": "a"}), monkeypatch, capsys)
    assert out["decision"] == "force_ask" and "unreachable" in out["reason"]


def test_hook_survives_garbage_input(monkeypatch, capsys):
    monkeypatch.setenv("GUARDIAN_URL", "http://127.0.0.1:9")
    assert run_hook("pre", "not json", monkeypatch, capsys)["decision"] == "force_ask"
    assert run_hook("post", "not json", monkeypatch, capsys) == {}


def test_transcript_context_tolerates_unknown_shapes(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join([
        "not json",
        json.dumps({"type": "USER_INPUT", "message": {"text": "Deploy the app"}}),
        json.dumps({"source": "MODEL", "content": [{"text": "Running the deploy script."}]}),
        json.dumps({"type": "TOOL_RESULT", "output": 3}),
    ]), encoding="utf-8")
    assert antigravity.transcript_context(str(path)) == ("Deploy the app", "Running the deploy script.")
    assert antigravity.transcript_context(str(tmp_path / "missing.jsonl")) == (None, None)
    assert antigravity.transcript_context(None) == (None, None)
