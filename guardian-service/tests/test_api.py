import pytest

import fake_jev


def evaluate(client, tool, session="s1", **args):
    resp = client.post("/evaluate", json={
        "agent_name": "test-agent",
        "tool": tool,
        "args": args,
        "session_id": session,
        "context": {"task": "Fix the greeting", "reasoning": "Testing"},
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_health_reports_what_is_configured(client):
    body = client.get("/health").json()
    assert body["modes"] == {"jev": "live", "neatlogs": "off", "entire": "off", "explainer": "off"}


def test_allow(client):
    d = evaluate(client, "read_file", path="README.md")
    assert d["verdict"] == "ALLOW" and d["status"] == "allowed"
    assert d["jev"]["model"] == "jev-test" and d["jev_error"] is None
    assert d["trace"] is None and d["explanation"] is None  # NeatLogs and the explainer are off
    after = client.post(f"/decisions/{d['id']}/result", json={"ok": True, "output": "hello"}).json()
    assert after["result"]["output"] == "hello"


def test_block(client):
    d = evaluate(client, "run_shell", command="rm -rf ./*")
    assert d["verdict"] == "BLOCK" and d["status"] == "blocked"
    assert d["explanation_pending"] is False  # explainer off: nothing to wait for
    assert any("unsafe" in r for r in d["reasons"])


def test_escalate_approve(client):
    d = evaluate(client, "run_shell", command="python scripts/migrate_db.py --apply")
    assert d["verdict"] == "ESCALATE" and d["status"] == "pending"
    assert client.get(f"/decisions/{d['id']}/wait", params={"timeout": 0.2}).json()["status"] == "pending"

    approved = client.post(f"/approve/{d['id']}", json={"by": "tester"}).json()
    assert approved["status"] == "approved" and approved["resolved_by"] == "tester"
    assert client.get(f"/decisions/{d['id']}/wait").json()["status"] == "approved"
    assert client.post(f"/reject/{d['id']}").json()["status"] == "approved"  # resolving twice is a no-op


def test_escalate_reject_and_handoff(client):
    d = evaluate(client, "run_shell", command="python scripts/migrate_db.py --apply")
    assert client.post(f"/reject/{d['id']}").json()["status"] == "rejected"

    d = evaluate(client, "run_shell", command="python scripts/migrate_db.py --apply")
    handed = client.post(f"/handoff/{d['id']}", json={"by": "antigravity prompt"}).json()
    assert handed["status"] == "handed_off" and handed["resolved_by"] == "antigravity prompt"


def test_jev_outage_escalates_to_a_human(make_client):
    client = make_client(fake_jev.down)
    d = evaluate(client, "read_file", path="README.md")
    assert d["verdict"] == "ESCALATE" and d["status"] == "pending"
    assert d["jev"] is None and d["jev_error"]
    assert "human must decide" in d["reasons"][0]


def test_history_is_filled_in_from_the_session(client):
    evaluate(client, "read_file", session="run-9", path="a.txt")
    evaluate(client, "read_file", session="other", path="unrelated.txt")
    resp = client.post("/evaluate", json={"agent_name": "hook", "tool": "read_file", "args": {"path": "b.txt"},
                                          "session_id": "run-9"})
    history = resp.json()["context"]["history"]
    assert [h["args"]["path"] for h in history] == ["a.txt"]
    assert resp.json()["jev"]["state"]["recent_steps"][0]["tool"] == "read_file"


def test_explain_needs_the_explainer(client):
    d = evaluate(client, "run_shell", command="rm -rf ./*")
    assert client.post(f"/decisions/{d['id']}/explain").status_code == 409


def test_history_newest_first_and_clear(client):
    first = evaluate(client, "read_file", path="a.txt")
    second = evaluate(client, "read_file", path="b.txt")
    assert [d["id"] for d in client.get("/decisions").json()][:2] == [second["id"], first["id"]]
    client.delete("/decisions")
    assert client.get("/decisions").json() == []


def test_service_refuses_to_start_without_a_jev_key(tmp_path, monkeypatch):
    from app.config import Settings
    from app.guardian import Guardian
    from conftest import isolate_env

    isolate_env(monkeypatch, tmp_path, jev_key="")
    with pytest.raises(RuntimeError, match="JEV_API_KEY"):
        Guardian(Settings.from_env())
