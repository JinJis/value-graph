"""Studio API tests — control-plane admin + agent-engine are respx-mocked."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from studioapi import provision
from studioapi.chat import _title, stream_and_persist
from studioapi.config import settings
from studioapi.db import init_db
from studioapi.main import app
from studioapi.models import User

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


# --- title derivation -----------------------------------------------------
def test_title_uses_first_user_message_and_truncates():
    assert _title([{"role": "user", "content": "삼성전자 최근 실적"}]) == "삼성전자 최근 실적"
    # a leading assistant/system turn is skipped in favour of the first user turn
    assert _title([{"role": "assistant", "content": "hi"}, {"role": "user", "content": "AAPL?"}]) == "AAPL?"
    assert _title([{"role": "user", "content": "x" * 200}]) == "x" * 80
    assert _title([]) == "New chat"


# --- auth / deps ----------------------------------------------------------
def test_missing_user_email_is_401(monkeypatch):
    # service token present but no X-User-Email -> unauthenticated
    assert client.get("/conversations", headers={"X-Service-Token": SVC}).status_code == 401


def test_wrong_service_token_is_401():
    assert client.get("/conversations", headers={"X-Service-Token": "nope", "X-User-Email": "a@b.com"}).status_code == 401


# --- provisioning resilience ---------------------------------------------
@respx.mock
async def test_ensure_user_survives_activation_failures(monkeypatch):
    _cfg(monkeypatch)
    respx.post("http://cp.test/admin/tenants").mock(return_value=httpx.Response(200, json={"id": "tenF"}))
    respx.post("http://cp.test/admin/tenants/tenF/projects").mock(return_value=httpx.Response(200, json={"id": "prjF"}))
    respx.post("http://cp.test/admin/projects/prjF/keys").mock(return_value=httpx.Response(200, json={"api_key": "vgk_f"}))
    # every activation fails (e.g. connector missing) — the user is still provisioned
    respx.post("http://cp.test/admin/projects/prjF/activations").mock(return_value=httpx.Response(500, json={"error": "boom"}))
    u = await provision.ensure_user("partial@u.com")
    assert u.api_key == "vgk_f" and u.tenant_id == "tenF"


# --- conversations --------------------------------------------------------
@respx.mock
def test_messages_of_unknown_conversation_is_empty(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    r = client.get("/conversations/cnv_does_not_exist/messages", headers=_hdr("ghost@u.com"))
    assert r.status_code == 200 and r.json()["messages"] == []


@respx.mock
async def test_chat_reuses_existing_conversation(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    sse = (
        'data: {"type":"token","text":"hello there"}\n\n'
        'data: {"type":"done","citations":[],"refused":false}\n\n'
    ).encode()
    respx.post("http://ae.test/agent/chat").mock(return_value=httpx.Response(200, content=sse))

    user = User(email="multi@u.com", tenant_id="t", project_id="p", api_key="vgk_m")
    # first turn -> new conversation
    cid = None
    async for chunk in stream_and_persist(user, None, [{"role": "user", "content": "first"}]):
        if '"type": "conversation"' in chunk:
            import json as _json
            cid = _json.loads(chunk[5:].strip())["id"]
    assert cid
    # second turn on the same id -> no new conversation row, messages accumulate
    async for _ in stream_and_persist(user, cid, [{"role": "user", "content": "second"}]):
        pass

    convs = client.get("/conversations", headers=_hdr("multi@u.com")).json()["conversations"]
    assert len([c for c in convs if c["id"] == cid]) == 1
    msgs = client.get(f"/conversations/{cid}/messages", headers=_hdr("multi@u.com")).json()["messages"]
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert {m["content"] for m in user_msgs} == {"first", "second"}


@respx.mock
def test_conversations_scoped_to_user(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    sse = b'data: {"type":"token","text":"ok"}\n\ndata: {"type":"done","citations":[],"refused":false}\n\n'
    respx.post("http://ae.test/agent/chat").mock(return_value=httpx.Response(200, content=sse))
    for q in ("alpha", "beta"):
        client.post("/chat/stream", json={"messages": [{"role": "user", "content": q}]}, headers=_hdr("owner@u.com"))
    # owner sees both of their conversations...
    owner_titles = {c["title"] for c in client.get("/conversations", headers=_hdr("owner@u.com")).json()["conversations"]}
    assert {"alpha", "beta"} <= owner_titles
    # ...a different user sees none of them
    other_titles = {c["title"] for c in client.get("/conversations", headers=_hdr("other@u.com")).json()["conversations"]}
    assert not ({"alpha", "beta"} & other_titles)
