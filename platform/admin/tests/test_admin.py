"""Admin panel tests — build throwaway service DBs, drive the panel over HTTP.

The DB urls are set via env BEFORE importing the app (the sqladmin views are
mounted at import from those urls). Ops calls to other services fail gracefully
(no stack needed), so the dashboard still renders.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

_TMP = tempfile.mkdtemp()


def _make_db(path: str, ddl: str) -> None:
    c = sqlite3.connect(path)
    c.executescript(ddl)
    c.commit()
    c.close()


# build 3 service-like DBs with PKs, then point the panel at them
_CP = f"{_TMP}/controlplane.db"
_ST = f"{_TMP}/studio.db"
_DS = f"{_TMP}/datasets.db"
_make_db(_CP, "create table tenants(id text primary key, name text);"
              "insert into tenants values('ten_1','Acme Capital');"
              "create table api_keys(id text primary key, project_id text, prefix text);")
_make_db(_ST, "create table users(email text primary key, tenant_id text, api_key text);"
              "insert into users values('a@b.com','ten_1','vgk_x');"
              "create table agents(id text primary key, user_email text, name text);")
_make_db(_DS, "create table financial_facts(id integer primary key, ticker text, value real);"
              "insert into financial_facts values(1,'AAPL',391000000000.0);")

os.environ["CONTROLPLANE_DB"] = f"sqlite:///{_CP}"
os.environ["STUDIO_DB"] = f"sqlite:///{_ST}"
os.environ["DATASETS_DB"] = f"sqlite:///{_DS}"
os.environ["ADMINUI_USERNAME"] = "admin"
os.environ["ADMINUI_PASSWORD"] = "secret"

from fastapi.testclient import TestClient  # noqa: E402

from adminpanel.main import DB_STATUS, app  # noqa: E402

client = TestClient(app)


def test_reflection_found_every_table():
    assert set(DB_STATUS) == {"controlplane", "studio", "datasets"}
    assert "tenants" in DB_STATUS["controlplane"]["tables"]
    assert "api_keys" in DB_STATUS["controlplane"]["tables"]
    assert "users" in DB_STATUS["studio"]["tables"]
    assert "agents" in DB_STATUS["studio"]["tables"]
    assert "financial_facts" in DB_STATUS["datasets"]["tables"]
    assert all(v["error"] is None for v in DB_STATUS.values())


def test_auth_required_then_login():
    # unauthenticated -> redirected to /login
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login"
    # a sqladmin sub-app is also gated
    assert client.get("/controlplane/tenants/list", follow_redirects=False).status_code == 302
    # bad creds rejected
    assert client.post("/login", data={"username": "admin", "password": "nope"}).status_code == 401
    # good creds -> session
    r = client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/"


def test_browse_real_rows_after_login():
    client.post("/login", data={"username": "admin", "password": "secret"})
    # control-plane tenants table shows the seeded row
    r = client.get("/controlplane/tenants/list")
    assert r.status_code == 200 and "Acme Capital" in r.text
    # studio users table
    r2 = client.get("/studio/users/list")
    assert r2.status_code == 200 and "a@b.com" in r2.text
    # datasets ingestion store
    r3 = client.get("/datasets/financial_facts/list")
    assert r3.status_code == 200 and "AAPL" in r3.text


def test_dashboard_renders_without_services():
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.get("/")
    assert r.status_code == 200
    # lists every DB + every table link, and the ops console sections
    for t in ("tenants", "api_keys", "users", "agents", "financial_facts"):
        assert t in r.text
    assert "Data pipeline" in r.text and "RAG" in r.text and "MCP" in r.text


def test_db_browser_lists_rows_and_relative_urls():
    client.post("/login", data={"username": "admin", "password": "secret"})
    # the self-contained browser pages the real rows (no sqladmin statics)
    r = client.get("/db/controlplane/tenants")
    assert r.status_code == 200 and "Acme Capital" in r.text
    # every internal link is relative (works behind a proxy/tunnel)
    assert "http://localhost" not in r.text
    # rows link into the per-row detail by offset
    assert "/db/controlplane/tenants/row/0" in r.text


def test_db_browser_row_detail():
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.get("/db/studio/users/row/0")
    assert r.status_code == 200
    # vertical key/value view shows the seeded user's fields
    assert "a@b.com" in r.text and "tenant_id" in r.text and "ten_1" in r.text


def test_db_browser_unknown_table_404():
    client.post("/login", data={"username": "admin", "password": "secret"})
    assert client.get("/db/controlplane/nope").status_code == 404
    assert client.get("/db/controlplane/tenants/row/9999").status_code == 404


def test_dashboard_links_into_browser():
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.get("/")
    # dashboard table chips point at the browser, not sqladmin's /list pages
    assert "/db/controlplane/tenants" in r.text
    assert "open CRUD editor" in r.text


def test_healthz_open():
    assert client.get("/healthz").json() == {"status": "ok"}
