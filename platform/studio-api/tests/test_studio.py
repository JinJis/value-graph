"""Studio API tests — control-plane admin + agent-engine are respx-mocked."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from studioapi import provision
from studioapi.config import settings
from studioapi.db import init_db
from studioapi.main import app

client = TestClient(app)
SVC = "dev-service-token"


def setup_module(_module):
    init_db()


def _cfg(monkeypatch):
    monkeypatch.setattr(settings, "control_plane_url", "http://cp.test")
    monkeypatch.setattr(settings, "agent_engine_url", "http://ae.test")


def _mock_control_plane():
    respx.post("http://cp.test/admin/tenants").mock(return_value=httpx.Response(200, json={"id": "ten1"}))
    respx.post("http://cp.test/admin/tenants/ten1/projects").mock(return_value=httpx.Response(200, json={"id": "prj1"}))
    respx.post("http://cp.test/admin/projects/prj1/keys").mock(return_value=httpx.Response(200, json={"api_key": "vgk_demo"}))
    respx.post("http://cp.test/admin/projects/prj1/activations").mock(return_value=httpx.Response(200, json={}))


def _hdr(email: str) -> dict:
    return {"X-Service-Token": SVC, "X-User-Email": email}


def test_service_token_required():
    assert client.post("/users/ensure", headers={"X-User-Email": "x@y.com"}).status_code == 401
    assert client.post("/users/ensure", headers={"X-Service-Token": SVC}).status_code == 401  # no user


@respx.mock
async def test_ensure_user_provisions_once(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    u = await provision.ensure_user("new@u.com")
    assert u.tenant_id == "ten1" and u.project_id == "prj1" and u.api_key == "vgk_demo"
    # second call returns cached (no new tenant call needed)
    u2 = await provision.ensure_user("new@u.com")
    assert u2.api_key == "vgk_demo"


@respx.mock
def test_users_ensure_endpoint(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    r = client.post("/users/ensure", headers=_hdr("e1@u.com"))
    assert r.status_code == 200 and r.json()["tenant_id"] == "ten1"
    assert "api_key" not in r.json()  # key never leaves the server


@respx.mock
def test_chat_stream_proxies_and_persists(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    sse = (
        'data: {"type":"tool","name":"yahoo__prices","args":{}}\n\n'
        'data: {"type":"token","text":"AAPL closed at 185."}\n\n'
        'data: {"type":"citation","tool":"yahoo__prices","source":"Yahoo Finance"}\n\n'
        'data: {"type":"done","citations":[{"tool":"yahoo__prices","source":"Yahoo Finance"}],"refused":false}\n\n'
    ).encode()
    respx.post("http://ae.test/agent/chat").mock(return_value=httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"}))

    email = "chat@u.com"
    r = client.post("/chat/stream", json={"messages": [{"role": "user", "content": "AAPL price?"}]}, headers=_hdr(email))
    assert r.status_code == 200
    assert "yahoo__prices" in r.text and "conversation" in r.text  # tool event + final conversation event

    convs = client.get("/conversations", headers=_hdr(email)).json()["conversations"]
    assert convs
    cid = convs[0]["id"]
    msgs = client.get(f"/conversations/{cid}/messages", headers=_hdr(email)).json()["messages"]
    roles = [m["role"] for m in msgs]
    assert "user" in roles and "assistant" in roles
    asst = next(m for m in msgs if m["role"] == "assistant")
    assert "AAPL" in asst["content"] and asst["citations"]
