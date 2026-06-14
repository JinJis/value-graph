"""Studio API tests — control-plane admin + agent-engine are respx-mocked."""

from __future__ import annotations

import json

import httpx
import respx
from fastapi.testclient import TestClient

from studioapi import provision
from studioapi.agents import agent_to_spec, seed_templates
from studioapi.chat import _title, stream_and_persist
from studioapi.config import settings
from studioapi.db import init_db
from studioapi.main import app
from studioapi.models import Agent, User
from studioapi.prompts import seed_community_prompts

client = TestClient(app)
SVC = "dev-service-token"


def setup_module(_module):
    init_db()
    seed_templates()
    seed_community_prompts()


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


# --- F1: agents -----------------------------------------------------------
def test_agent_to_spec_maps_fields():
    a = Agent(name="X", model="gemini", system_prompt="Be terse.", data_sources='["yahoo","rag"]')
    spec = agent_to_spec(a)
    assert spec == {"system": "Be terse.", "allowed_tools": ["yahoo", "rag"], "backend": "gemini"}


@respx.mock
def test_agents_list_includes_templates(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    agents = client.get("/agents", headers=_hdr("ab@u.com")).json()["agents"]
    ids = {a["id"] for a in agents}
    assert {"tpl_research", "tpl_filings", "tpl_market", "tpl_macro"} <= ids
    tpl = next(a for a in agents if a["id"] == "tpl_research")
    assert tpl["is_template"] and tpl["editable"] is False and tpl["data_sources"]


@respx.mock
def test_agent_create_get_update_delete(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    email = "builder@u.com"
    created = client.post("/agents", headers=_hdr(email), json={
        "name": "My Filings Bot", "description": "filings only", "model": "stub",
        "system_prompt": "Cite filings.", "data_sources": ["sec_edgar", "rag"],
    }).json()
    aid = created["id"]
    assert created["editable"] and created["data_sources"] == ["sec_edgar", "rag"]
    # it appears in the list alongside templates
    assert aid in {a["id"] for a in client.get("/agents", headers=_hdr(email)).json()["agents"]}
    # update
    upd = client.patch(f"/agents/{aid}", headers=_hdr(email), json={"data_sources": ["sec_edgar"], "model": "gemini"})
    assert upd.json()["data_sources"] == ["sec_edgar"] and upd.json()["model"] == "gemini"
    # delete
    assert client.delete(f"/agents/{aid}", headers=_hdr(email)).status_code == 200
    assert client.get(f"/agents/{aid}", headers=_hdr(email)).status_code == 404


@respx.mock
def test_agent_invalid_model_rejected(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    r = client.post("/agents", headers=_hdr("v@u.com"), json={"name": "bad", "model": "gpt-9"})
    assert r.status_code == 422


@respx.mock
def test_template_not_editable_or_deletable(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    h = _hdr("t@u.com")
    assert client.patch("/agents/tpl_research", headers=h, json={"name": "hijack"}).status_code == 404
    assert client.delete("/agents/tpl_research", headers=h).status_code == 404
    # but it can be read (to clone)
    assert client.get("/agents/tpl_research", headers=h).status_code == 200


@respx.mock
def test_agents_are_user_scoped(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    a = client.post("/agents", headers=_hdr("alice@u.com"), json={"name": "Alice bot"}).json()
    # bob cannot see or fetch alice's private agent
    bob_ids = {x["id"] for x in client.get("/agents", headers=_hdr("bob@u.com")).json()["agents"]}
    assert a["id"] not in bob_ids
    assert client.get(f"/agents/{a['id']}", headers=_hdr("bob@u.com")).status_code == 404


@respx.mock
def test_connectors_proxy(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    respx.get("http://cp.test/catalog").mock(return_value=httpx.Response(200, json={"connectors": [
        {"id": "yahoo", "name": "Yahoo Finance", "description": "prices"},
        {"id": "sec_edgar", "name": "SEC EDGAR", "description": "filings"},
    ]}))
    cons = client.get("/connectors", headers=_hdr("c@u.com")).json()["connectors"]
    assert {c["id"] for c in cons} == {"yahoo", "sec_edgar"}


@respx.mock
def test_chat_with_agent_sends_spec_and_records_agent(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    captured = {}

    def _capture(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=b'data: {"type":"token","text":"ok"}\n\ndata: {"type":"done","citations":[],"refused":false}\n\n')

    respx.post("http://ae.test/agent/chat").mock(side_effect=_capture)

    email = "agentchat@u.com"
    r = client.post("/chat/stream", headers=_hdr(email),
                    json={"messages": [{"role": "user", "content": "AAPL filings?"}], "agent_id": "tpl_filings"})
    assert r.status_code == 200
    spec = captured["body"]["spec"]
    assert spec["backend"] == "stub" and "sec_edgar" in spec["allowed_tools"]
    # the conversation remembers which agent drove it
    conv = client.get("/conversations", headers=_hdr(email)).json()["conversations"][0]
    assert conv["agent_id"] == "tpl_filings"


# --- F2: prompt library ---------------------------------------------------
@respx.mock
def test_community_prompts_seeded(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    cat = client.get("/prompts/community", headers=_hdr("p1@u.com")).json()["prompts"]
    ids = {p["id"] for p in cat}
    assert {"cpr_earnings", "cpr_macro_rates"} <= ids
    one = next(p for p in cat if p["id"] == "cpr_earnings")
    assert one["community"] and one["editable"] is False and one["body"]


@respx.mock
def test_prompt_create_list_update_delete(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    email = "p2@u.com"
    created = client.post("/prompts", headers=_hdr(email), json={
        "title": "내 요약 프롬프트", "body": "{TICKER} 실적 요약해줘", "category": "리서치",
    }).json()
    pid = created["id"]
    assert created["editable"] and created["community"] is False
    # personal library lists it; community catalog does not
    assert pid in {p["id"] for p in client.get("/prompts", headers=_hdr(email)).json()["prompts"]}
    assert pid not in {p["id"] for p in client.get("/prompts/community", headers=_hdr(email)).json()["prompts"]}
    # update + delete
    upd = client.patch(f"/prompts/{pid}", headers=_hdr(email), json={"title": "수정됨"})
    assert upd.json()["title"] == "수정됨"
    assert client.delete(f"/prompts/{pid}", headers=_hdr(email)).status_code == 200
    assert client.get(f"/prompts/{pid}", headers=_hdr(email)).status_code == 404


@respx.mock
def test_import_community_prompt_is_editable_copy_and_idempotent(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    email = "p3@u.com"
    imp = client.post("/prompts/cpr_earnings/import", headers=_hdr(email)).json()
    assert imp["editable"] and imp["source_id"] == "cpr_earnings" and imp["id"] != "cpr_earnings"
    assert imp["body"]  # copied content
    # it now lives in the personal library
    mine = {p["id"] for p in client.get("/prompts", headers=_hdr(email)).json()["prompts"]}
    assert imp["id"] in mine
    # importing again returns the same copy (no duplicates)
    again = client.post("/prompts/cpr_earnings/import", headers=_hdr(email)).json()
    assert again["id"] == imp["id"]


@respx.mock
def test_community_prompt_not_editable(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    h = _hdr("p4@u.com")
    assert client.patch("/prompts/cpr_earnings", headers=h, json={"title": "x"}).status_code == 404
    assert client.delete("/prompts/cpr_earnings", headers=h).status_code == 404
    # importing a non-community (or unknown) id 404s
    assert client.post("/prompts/prm_nope/import", headers=h).status_code == 404


@respx.mock
def test_prompts_are_user_scoped(monkeypatch):
    _cfg(monkeypatch)
    _mock_control_plane()
    p = client.post("/prompts", headers=_hdr("ann@u.com"), json={"title": "Ann", "body": "x"}).json()
    bob_ids = {x["id"] for x in client.get("/prompts", headers=_hdr("bob2@u.com")).json()["prompts"]}
    assert p["id"] not in bob_ids
    assert client.get(f"/prompts/{p['id']}", headers=_hdr("bob2@u.com")).status_code == 404
