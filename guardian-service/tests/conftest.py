import sys
from pathlib import Path

import httpx2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fake_jev  # noqa: E402


def isolate_env(monkeypatch, tmp_path, jev_key="test-key"):
    """Point the service at a throwaway DB and switch off every optional integration,
    even if the developer's .env has real keys."""
    monkeypatch.setenv("JEV_API_KEY", jev_key)
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    monkeypatch.setenv("JEV_BASE_URL", "")
    monkeypatch.setenv("JEV_MODEL", "")
    monkeypatch.setenv("NEATLOGS_API_KEY", "")
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "MODAL_PROXY_TOKEN_ID", "MODAL_PROXY_TOKEN_SECRET"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("ENTIRE_BIN", "entire-not-installed-for-tests")
    monkeypatch.setenv("GUARDIAN_FAST_PATH_TOOLS", "")
    monkeypatch.setenv("GUARDIAN_DB_PATH", str(tmp_path / "test.db"))


def use_fake_jev(monkeypatch, handler=fake_jev.handler):
    from app import guardian
    from app.adapters.jev_client import JevClient

    monkeypatch.setattr(guardian, "JevClient", lambda s: JevClient(s, transport=httpx2.MockTransport(handler)))


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    clients = []

    def make(handler=fake_jev.handler, **env):
        isolate_env(monkeypatch, tmp_path)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        use_fake_jev(monkeypatch, handler)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()
