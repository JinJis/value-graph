"""ValueGraph admin panel.

Django-admin-style CRUD over every service database (control-plane / studio /
datasets) via SQLAlchemy reflection + sqladmin, plus an operations console for the
runtime pieces (data pipeline scheduler, self-test, RAG, MCP/catalog).

One login gates everything (a session cookie + a guard middleware that also wraps
the mounted sqladmin sub-apps).
"""

from __future__ import annotations

import html

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqladmin import Admin, ModelView
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.automap import automap_base
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from adminpanel.config import DATABASES, settings

app = FastAPI(title="ValueGraph Admin")

_MODELVIEW_META = type(ModelView)
DB_STATUS: dict[str, dict] = {}  # key -> {title, tables:[...], error}


def _mount_database(key: str, title: str, url: str) -> None:
    """Reflect a service DB and register a sqladmin CRUD view per table."""
    try:
        engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        base = automap_base()
        base.prepare(autoload_with=engine)
    except Exception as e:  # DB missing / unreachable — note it, keep the panel up
        DB_STATUS[key] = {"title": title, "tables": [], "error": str(e)[:200]}
        return

    admin = Admin(app, engine, base_url=f"/{key}", title=f"VG Admin · {title}")
    tables: list[str] = []
    for cls in sorted(base.classes, key=lambda c: c.__name__):
        cols = [c.name for c in inspect(cls).columns]
        view = _MODELVIEW_META(
            f"{key}_{cls.__name__}", (ModelView,),
            {
                "column_list": cols, "name": cls.__name__, "name_plural": cls.__name__,
                "category": title, "can_create": True, "can_edit": True,
                "can_delete": True, "can_export": True, "page_size": 50,
            },
            model=cls,
        )
        admin.add_view(view)
        tables.append(cls.__name__)
    DB_STATUS[key] = {"title": title, "tables": tables, "error": None}


for _k, _t, _u in DATABASES:
    _mount_database(_k, _t, _u)


# --- auth: one session, one guard over everything (incl. the sqladmin apps) ---
async def _guard(request: Request, call_next):
    p = request.url.path
    if p in ("/login", "/logout", "/healthz") or "/statics/" in p:
        return await call_next(request)
    if not request.session.get("authed"):
        return RedirectResponse("/login", status_code=302)
    return await call_next(request)


app.add_middleware(BaseHTTPMiddleware, dispatch=_guard)            # inner
app.add_middleware(SessionMiddleware, secret_key=settings.adminui_secret)  # outermost


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


_LOGIN_HTML = """<!doctype html><meta charset=utf-8><title>VG Admin · login</title>
<style>body{{background:#0b0e14;color:#e7ecf3;font-family:system-ui;display:flex;height:100vh;
align-items:center;justify-content:center;margin:0}}.c{{background:#141925;border:1px solid #232b3a;
border-radius:16px;padding:32px;width:320px}}h1{{margin:0 0 16px;font-size:18px}}input{{width:100%;
box-sizing:border-box;background:#0b0e14;border:1px solid #232b3a;color:#e7ecf3;padding:10px;
border-radius:10px;margin-bottom:10px}}button{{width:100%;background:#4f8cff;color:#fff;border:0;
padding:11px;border-radius:10px;font-weight:600;cursor:pointer}}.e{{color:#ff6b6b;font-size:13px;margin-bottom:8px}}</style>
<div class=c><h1>ValueGraph Admin</h1>{err}<form method=post action=/login>
<input name=username placeholder=username autofocus>
<input name=password type=password placeholder=password>
<button>Sign in</button></form></div>"""


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if request.session.get("authed"):
        return RedirectResponse("/", status_code=302)
    return _LOGIN_HTML.format(err="")


@app.post("/login")
async def login(request: Request, username: str = Form(""), password: str = Form("")):
    if username == settings.adminui_username and password == settings.adminui_password:
        request.session["authed"] = True
        return RedirectResponse("/", status_code=302)
    return HTMLResponse(_LOGIN_HTML.format(err="<div class=e>Invalid credentials.</div>"), status_code=401)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# --- ops console ----------------------------------------------------------
async def _safe_get(client: httpx.AsyncClient, url: str) -> dict:
    try:
        r = await client.get(url, timeout=8)
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_status": r.status_code}
    except Exception as e:
        return {"_error": str(e)[:120]}


def _esc(v) -> str:
    return html.escape(str(v))


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, msg: str = ""):
    async with httpx.AsyncClient() as c:
        sched = await _safe_get(c, f"{settings.datasets_url}/admin/scheduler")
        stats = await _safe_get(c, f"{settings.datasets_url}/admin/store/stats")
        raginfo = await _safe_get(c, f"{settings.rag_url}/rag/info")
        catalog = await _safe_get(c, f"{settings.gateway_url}/catalog")

    # database cards
    dbcards = ""
    for key, info in DB_STATUS.items():
        if info["error"]:
            body = f"<div class=err>unavailable: {_esc(info['error'])}</div>"
        else:
            links = " ".join(
                f"<a class=tbl href='/{key}/{t.lower()}/list'>{_esc(t)}</a>" for t in info["tables"]
            ) or "<span class=muted>(no tables)</span>"
            body = f"<div class=tbls>{links}</div><a class=open href='/{key}'>open admin →</a>"
        dbcards += f"<div class=card><h3>{_esc(info['title'])} <span class=muted>{key}</span></h3>{body}</div>"

    tool_count = catalog.get("count", "?")
    rag_backend = raginfo.get("embedding_backend", raginfo.get("_error", "?"))
    sched_state = sched.get("state", sched.get("_error", "?"))
    fact_rows = stats.get("financial_facts", stats.get("rows", stats.get("_error", "?")))

    body = _DASH_BODY.format(
        msg=f"<div class=flash>{_esc(msg)}</div>" if msg else "",
        dbcards=dbcards,
        tool_count=_esc(tool_count), rag_backend=_esc(rag_backend),
        sched_state=_esc(sched_state), fact_rows=_esc(fact_rows),
    )
    return _HEAD + _STYLE + body


@app.post("/ops/scheduler/{action}")
async def ops_scheduler(request: Request, action: str):
    async with httpx.AsyncClient() as c:
        await c.post(f"{settings.datasets_url}/admin/scheduler/{action}", timeout=20)
    return RedirectResponse(f"/?msg=scheduler+{action}+requested", status_code=303)


@app.post("/ops/selftest")
async def ops_selftest(request: Request):
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{settings.datasets_url}/admin/selftest", timeout=60)
        j = r.json() if r.status_code == 200 else {}
    summary = f"selftest: {j.get('passed', '?')} passed / {j.get('failed', '?')} failed / {j.get('skipped', '?')} skipped"
    return RedirectResponse(f"/?msg={summary.replace(' ', '+')}", status_code=303)


@app.post("/ops/rag/ingest")
async def ops_rag_ingest(request: Request, text: str = Form(...), source: str = Form("admin"),
                         ticker: str = Form(""), url: str = Form("")):
    doc = {"text": text, "source": source}
    if ticker:
        doc["ticker"] = ticker
    if url:
        doc["url"] = url
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{settings.rag_url}/rag/ingest", json={"documents": [doc]}, timeout=30)
        n = (r.json() or {}).get("chunks", "?") if r.status_code == 200 else f"err {r.status_code}"
    return RedirectResponse(f"/?msg=rag+ingested+{n}+chunks", status_code=303)


@app.post("/ops/rag/search", response_class=HTMLResponse)
async def ops_rag_search(request: Request, query: str = Form(...)):
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{settings.rag_url}/rag/search", json={"query": query, "top_k": 5}, timeout=30)
        hits = (r.json() or {}).get("hits", []) if r.status_code == 200 else []
    rows = "".join(
        f"<tr><td>{_esc(round(h.get('score', 0), 3))}</td><td>{_esc((h.get('provenance') or {}).get('source'))}</td>"
        f"<td>{_esc(h.get('text', '')[:200])}</td></tr>" for h in hits
    ) or "<tr><td colspan=3 class=muted>no hits</td></tr>"
    return _HEAD + _STYLE + _SEARCH_BODY.format(query=_esc(query), rows=rows)


_STYLE = """<style>body{background:#0b0e14;color:#e7ecf3;font-family:system-ui;margin:0;padding:24px;max-width:1100px;margin:auto}
a{color:#4f8cff;text-decoration:none}h1{font-size:20px}h2{font-size:15px;color:#93a0b4;margin-top:28px;border-bottom:1px solid #232b3a;padding-bottom:6px}
h3{font-size:14px;margin:0 0 8px}.muted{color:#93a0b4;font-weight:400;font-size:12px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.card{background:#141925;border:1px solid #232b3a;border-radius:12px;padding:14px}.tbls{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.tbl{background:#1b2230;border:1px solid #232b3a;border-radius:8px;padding:4px 8px;font-size:12px}.open{font-size:13px}
.stat{display:inline-block;background:#141925;border:1px solid #232b3a;border-radius:10px;padding:10px 14px;margin:0 8px 8px 0}
.stat b{display:block;font-size:18px}.err{color:#ff6b6b;font-size:12px}.flash{background:#16321f;border:1px solid #2e6b3f;color:#9be8a8;padding:8px 12px;border-radius:8px;margin-bottom:14px}
form.ops{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:6px 0}input,button,textarea{background:#0b0e14;border:1px solid #232b3a;color:#e7ecf3;border-radius:8px;padding:7px 9px}
button{background:#1b2230;cursor:pointer}button.p{background:#4f8cff;color:#fff;border:0}table{width:100%;border-collapse:collapse;font-size:13px}td,th{border-bottom:1px solid #232b3a;padding:6px;text-align:left;vertical-align:top}
.top{display:flex;justify-content:space-between;align-items:center}</style>"""

_HEAD = "<!doctype html><meta charset=utf-8><title>ValueGraph Admin</title>"

_DASH_BODY = """
<div class=top><h1>ValueGraph Admin</h1><a href=/logout>logout</a></div>{msg}
<h2>Live status</h2>
<div class=stat><span class=muted>catalog tools</span><b>{tool_count}</b></div>
<div class=stat><span class=muted>RAG embedder</span><b>{rag_backend}</b></div>
<div class=stat><span class=muted>scheduler</span><b>{sched_state}</b></div>
<div class=stat><span class=muted>store rows</span><b>{fact_rows}</b></div>

<h2>Databases — browse &amp; edit every table</h2>
<div class=grid>{dbcards}</div>

<h2>Data pipeline</h2>
<form class=ops method=post action=/ops/scheduler/run><button class=p>Run ingestion now</button></form>
<form class=ops method=post action=/ops/scheduler/pause><button>Pause</button></form>
<form class=ops method=post action=/ops/scheduler/resume><button>Resume</button></form>
<form class=ops method=post action=/ops/selftest><button>Run self-test</button></form>

<h2>RAG</h2>
<form class=ops method=post action=/ops/rag/ingest>
  <input name=text placeholder="document text" size=44 required>
  <input name=source placeholder=source value=admin size=10>
  <input name=ticker placeholder=ticker size=8>
  <input name=url placeholder=url size=16>
  <button class=p>Ingest</button></form>
<form class=ops method=post action=/ops/rag/search>
  <input name=query placeholder="semantic query" size=44 required><button>Search</button></form>

<h2>MCP &amp; catalog</h2>
<p class=muted>The MCP server exposes one tool per catalog resource; the gateway reports
<b>{tool_count}</b> connector resources. Browse them in the data-plane admin or via <code>/catalog</code>.</p>
"""

_SEARCH_BODY = """
<div class=top><h1>RAG search</h1><a href=/>← back</a></div>
<p class=muted>query: <b>{query}</b></p>
<table><tr><th>score</th><th>source</th><th>text</th></tr>{rows}</table>"""
