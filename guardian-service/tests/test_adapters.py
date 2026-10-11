"""Each adapter's real code path, run against fake transports / CLI output.

These don't call the sponsor APIs. They check that each adapter sends the
documented request and parses the documented response.
"""

import asyncio
import json
import sys
import httpx
import httpx2
import pytest

from app.adapters.entire_client import EntireClient
from app.adapters.explainer import Explainer, ExplainerError
from app.adapters.jev_client import JevClient, JevUnavailable, build_state, signals_from_answers
from app.adapters.neatlogs_tracer import NeatLogsTracer
from app.config import Settings, Thresholds, llm_api_key
from app.models import Decision, EvaluateRequest, JevResult
from app.policy import decide

REQ = EvaluateRequest(
    agent_name="antigravity",
    tool="run_command",
    args={"CommandLine": "rm -rf ./*"},
    session_id="conv-1",
    context={"task": "Clean up the workspace", "reasoning": "Wipe everything", "entire_session_id": "conv-1"},
)

# Shape from https://docs.typesafe.ai/introduction/quickstart (response body)
JEV_RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "safe": {"type": "noul", "noul": 0.04},
        "on_task": {"type": "noul", "noul": 0.71},
        "risk": {
            "type": "choice",
            "choice": "data_loss",
            "confidence": 0.81,
            "probabilities": {"none": 0.02, "data_loss": 0.85, "exfiltration": 0.01, "system_damage": 0.11, "unclear": 0.01},
        },
        "severity": {
            "type": "score",
            "score": 2.86,
            "confidence": 0.9,
            "legend": {"0": "Negligible", "1": "Minor", "2": "Serious", "3": "Critical"},
            "probabilities": {"0": 0.0, "1": 0.02, "2": 0.1, "3": 0.88},
        },
    },
    "usage": {"input_tokens": 512, "output_tokens": 70},
}


def run(coro):
    return asyncio.run(coro)


def evaluate_with(handler, req=REQ):
    async def go():
        jev = JevClient(Settings(jev_api_key="test-key"), transport=httpx2.MockTransport(handler))
        try:
            return await jev.evaluate(req)
        finally:
            await jev.aclose()

    return run(go())


def test_jev_needs_a_key():
    with pytest.raises(RuntimeError, match="JEV_API_KEY"):
        JevClient(Settings())


def test_jev_request_and_parsing():
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=JEV_RESPONSE, headers={"x-typesafe-request-id": "req_1"})

    result = evaluate_with(handler)
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["auth"] == "Bearer test-key"
    body = seen["body"]
    assert body["model"] == "jev-latest"
    assert body["state"]["proposed_action"] == {"tool": "run_command", "tool_description": "", "arguments": REQ.args}
    assert {k: q["type"] for k, q in body["questions"].items()} == {
        "safe": "noul", "on_task": "noul", "risk": "choice", "severity": "score",
    }
    assert set(body["questions"]["risk"]["criteria"]) == {"none", "data_loss", "exfiltration", "system_damage", "unclear"}
    assert len(body["questions"]["severity"]["criteria"]) == 4

    assert result.model == "jev-1.13.0"
    assert result.input_tokens == 512  # recorded so cost per check can be measured
    s = result.signals
    assert (s.p_safe, s.risk, s.severity) == (0.04, "data_loss", 2.86)
    assert s.severity_probabilities["3"] == 0.88
    assert s.confidence == pytest.approx(0.81)  # min(0.81, 0.9, |2*0.04-1|)
    assert decide(s, Thresholds()).verdict == "BLOCK"


def test_jev_asks_about_output_quality_for_writes():
    seen = {}

    def handler(request):
        seen["questions"] = json.loads(request.content)["questions"]
        answers = dict(JEV_RESPONSE["answers"], output_ok={"type": "noul", "noul": 0.2})
        return httpx2.Response(200, json={**JEV_RESPONSE, "answers": answers})

    req = REQ.model_copy(update={"tool": "write_file", "args": {"path": "a.py", "content": "# TODO"}})
    result = evaluate_with(handler, req)
    assert seen["questions"]["output_ok"]["type"] == "noul"
    assert result.signals.output_ok == 0.2


def test_jev_failure_raises_instead_of_guessing():
    with pytest.raises(JevUnavailable):
        evaluate_with(lambda r: httpx2.Response(401, json={"error": {"message": "invalid api key"}}))


def make_decision(**overrides) -> Decision:
    jev = JevResult(
        model="jev-1.13.0", latency_ms=42.0, signals=signals_from_answers(JEV_RESPONSE["answers"]),
        answers=JEV_RESPONSE["answers"], state=build_state(REQ),
    )
    fields = dict(
        agent_name=REQ.agent_name, session_id=REQ.session_id, tool=REQ.tool, args=REQ.args,
        context=REQ.context, verdict="BLOCK", status="blocked", confidence=0.8,
        reasons=["Jev rates this action unsafe."], jev=jev, latency_ms=50.0,
    )
    return Decision(**{**fields, **overrides})


def has_null(value) -> bool:
    if isinstance(value, dict):
        return any(has_null(v) for v in value.values())
    if isinstance(value, list):
        return any(has_null(v) for v in value)
    return value is None


def test_neatlogs_is_off_without_a_key():
    tracer = NeatLogsTracer(Settings())
    assert tracer.mode == "off" and run(tracer.record(make_decision())) is None


def test_neatlogs_ingest():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"trace_id": "tr_123"})

    tracer = NeatLogsTracer(Settings(neatlogs_api_key="nl-key", neatlogs_project="guardian"),
                            transport=httpx.MockTransport(handler))
    d = make_decision(context=REQ.context.model_copy(update={"metadata": {"source": "antigravity", "step": 3}}))
    ref = run(tracer.record(d))

    assert seen["url"] == "https://ingest.neatlogs.com/v1/trace"
    assert seen["key"] == "nl-key"
    body = seen["body"]
    assert body["project"] == "guardian"
    assert body["metadata"]["guardian.source"] == "antigravity"
    assert body["children"][0]["kind"] == "GUARDRAIL"
    assert body["children"][0]["passed"] is False
    assert body["attributes"]["neatlogs.session.id"] == d.session_id
    assert "trace_id" not in body  # NeatLogs generates IDs
    assert not has_null(body)  # ingest rejects null fields with a 400
    assert ref.mode == "live" and ref.trace_id == "tr_123"
    assert ref.url == "https://app.neatlogs.com/traces/tr_123"


def test_neatlogs_traces_a_jev_outage_too():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    tracer = NeatLogsTracer(Settings(neatlogs_api_key="k"), transport=httpx.MockTransport(handler))
    run(tracer.record(make_decision(jev=None, jev_error="503", verdict="ESCALATE", status="pending",
                                    explanation_error="LLM endpoint returned 500")))
    assert not has_null(seen["body"])
    assert seen["body"]["children"][0] == {"name": "jev.system_one", "kind": "GUARDRAIL", "status": "error", "error": "503"}


def test_neatlogs_fast_path_trace_has_no_jev_span():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    tracer = NeatLogsTracer(Settings(neatlogs_api_key="k"), transport=httpx.MockTransport(handler))
    run(tracer.record(make_decision(jev=None, checked=False, verdict="ALLOW", status="allowed")))
    body = seen["body"]
    assert [c["name"] for c in body["children"]] == ["guardian.policy"]
    assert body["metadata"]["guardian.checked"] is False
    assert not has_null(body)


def test_neatlogs_failure_is_reported():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401)

    tracer = NeatLogsTracer(Settings(neatlogs_api_key="k"), transport=httpx.MockTransport(handler), backoff_s=0)
    ref = run(tracer.record(make_decision()))
    assert ref.mode == "error" and "401" in ref.error and ref.payload["children"]
    assert len(calls) == 1  # a rejected payload isn't resent


def test_neatlogs_outage_is_retried():
    replies = iter([httpx.Response(503, text="Service Temporarily Unavailable"), httpx.Response(200, json={"trace_id": "t"})])
    tracer = NeatLogsTracer(Settings(neatlogs_api_key="k"), transport=httpx.MockTransport(lambda r: next(replies)),
                            backoff_s=0)
    ref = run(tracer.record(make_decision()))
    assert ref.mode == "live" and ref.trace_id == "t"


def entire_with(monkeypatch, outputs):
    seen = []

    async def fake_run(self, repo, *args, timeout=15.0):
        seen.append((str(repo), args))
        return outputs.get(args)

    monkeypatch.setattr(EntireClient, "_run", fake_run)
    return EntireClient(Settings(entire_bin=sys.executable)), seen


def test_entire_is_off_without_the_cli():
    client = EntireClient(Settings(entire_bin="entire-not-installed"))
    assert client.mode == "off" and run(client.session_context(make_decision())) is None


def test_entire_reads_the_antigravity_session_in_its_workspace(monkeypatch, tmp_path):
    client, seen = entire_with(monkeypatch, {
        ("session", "info", "conv-1", "--json"): json.dumps({"session_id": "conv-1", "agent": "antigravity"}),
        ("checkpoint", "explain", "HEAD", "--json", "--no-pager"): json.dumps({"checkpoint_id": "01KV"}),
        ("checkpoint", "explain", "HEAD", "--short", "--no-pager"): "Agent cleaned stale caches.",
        ("session", "info", "conv-1", "--transcript"): "\n".join([
            '{"role":"user","text":"clean up"}',
            '{"role":"assistant","text":"I will run rm -rf ./* to start fresh"}',
            '{"role":"assistant","text":"unrelated line"}',
        ]),
    })
    ctx = REQ.context.model_copy(update={"metadata": {"workspace": str(tmp_path)}})
    result = run(client.session_context(make_decision(context=ctx)))

    assert {repo for repo, _ in seen} == {str(tmp_path)}
    assert result["source"] == "entire-cli" and result["session_id"] == "conv-1"
    assert result["session"]["agent"] == "antigravity"
    assert result["summary"] == "Agent cleaned stale caches."
    assert result["transcript_excerpt"] == ['{"role":"assistant","text":"I will run rm -rf ./* to start fresh"}']


def test_entire_falls_back_to_the_current_session(monkeypatch, tmp_path):
    client, _ = entire_with(monkeypatch, {
        ("session", "current", "--json"): json.dumps({"session_id": "latest"}),
    })
    ctx = REQ.context.model_copy(update={"entire_session_id": None, "metadata": {"workspace": str(tmp_path)}})
    result = run(client.session_context(make_decision(context=ctx)))
    assert result["session_id"] == "latest" and "error" not in result


def test_entire_reports_missing_data_instead_of_inventing_it(monkeypatch, tmp_path):
    client, _ = entire_with(monkeypatch, {})
    no_repo = run(client.session_context(make_decision()))
    assert "No repository" in no_repo["error"]

    ctx = REQ.context.model_copy(update={"metadata": {"workspace": str(tmp_path)}})
    empty = run(client.session_context(make_decision(context=ctx)))
    assert "returned no session" in empty["error"]


MODAL = Settings(
    llm_base_url="https://md-sharik--ep-guardian-server.us-west.modal.direct/v1",
    llm_api_key="wk-id.ws-secret",
)


def completion(content, finish_reason="stop"):
    """OpenAI-compatible /chat/completions response body."""
    return {
        "id": "cmpl-1",
        "model": "deepseek-ai/DeepSeek-V4.1-Flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}],
    }


def explain_with(handler, settings=MODAL):
    async def go():
        explainer = Explainer(settings, transport=httpx.MockTransport(handler))
        try:
            return await explainer.explain(make_decision(), {"intent": "Clean up"})
        finally:
            await explainer.aclose()

    return run(go())


def test_modal_token_becomes_the_bearer_key(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("MODAL_PROXY_TOKEN_ID", "wk-abc")
    monkeypatch.setenv("MODAL_PROXY_TOKEN_SECRET", "ws-xyz")
    assert llm_api_key() == "wk-abc.ws-xyz"  # Modal: `Authorization: Bearer <id>.<secret>`
    monkeypatch.setenv("LLM_API_KEY", "sk-other")
    assert llm_api_key() == "sk-other"


def test_explainer_is_off_without_an_endpoint():
    assert Explainer(Settings()).mode == "off"
    assert Explainer(Settings(llm_base_url="https://x/v1")).mode == "off"


def test_explainer_calls_the_openai_compatible_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        text = "<think>scratch</think>What it tried: wipe.\nWhy it did it: stale cache.\nWhy Guardian blocked it: data loss."
        return httpx.Response(200, json=completion(text))

    result = explain_with(handler)
    assert seen["url"] == "https://md-sharik--ep-guardian-server.us-west.modal.direct/v1/chat/completions"
    assert seen["auth"] == "Bearer wk-id.ws-secret"
    assert seen["body"]["model"] == "deepseek-ai/DeepSeek-V4.1-Flash"
    assert seen["body"]["stream"] is False
    assert seen["body"]["messages"][0]["role"] == "system"
    assert '"intent": "Clean up"' in seen["body"]["messages"][1]["content"]
    assert result.text.startswith("What it tried")  # <think> block stripped
    assert result.model == "deepseek-ai/DeepSeek-V4.1-Flash"


def test_explainer_accepts_the_full_completions_url():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=completion("What it tried: x."))

    explain_with(handler, Settings(llm_base_url="https://host/v1/chat/completions", llm_api_key="k"))
    assert seen["url"] == "https://host/v1/chat/completions"


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (httpx.Response(401, text="invalid proxy token"), "401: invalid proxy token"),
        (httpx.Response(200, json=completion("", finish_reason="length")), "finish_reason=length"),
        (httpx.Response(200, text="not json"), "unexpected response"),
    ],
)
def test_explainer_errors_are_reported(response, match):
    with pytest.raises(ExplainerError, match=match):
        explain_with(lambda request: response)
