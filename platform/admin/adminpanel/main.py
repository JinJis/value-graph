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
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.automap import automap_base
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from adminpanel.config import DATABASES, settings

app = FastAPI(title="ValueGraph Admin")

_MODELVIEW_META = type(ModelView)
DB_STATUS: dict[str, dict] = {}  # key -> {title, tables:[...], error, meta:{table->{columns,pk}}}
ENGINES: dict[str, object] = {}  # key -> sqlalchemy Engine (for the read-only browser)


def _mount_database(key: str, title: str, url: str) -> None:
    """Reflect a service DB and register a sqladmin CRUD view per table.

    Also captures real table/column/pk metadata + the live engine so the
    self-contained DB browser (``/db/...``) can page rows without depending on
    sqladmin's (proxy-fragile, absolute-URL) static assets.
    """
    try:
        engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        base = automap_base()
        base.prepare(autoload_with=engine)
    except Exception as e:  # DB missing / unreachable — note it, keep the panel up
        DB_STATUS[key] = {"title": title, "tables": [], "error": str(e)[:200], "meta": {}}
        return

    ENGINES[key] = engine
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

    meta: dict[str, dict] = {}
    for tname, tbl in sorted(base.metadata.tables.items()):
        meta[tname] = {
            "columns": [c.name for c in tbl.columns],
            "pk": [c.name for c in tbl.primary_key.columns],
        }
    DB_STATUS[key] = {"title": title, "tables": tables, "error": None, "meta": meta}


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
        jobs = await _safe_get(c, f"{settings.datasets_url}/admin/jobs")
        universes = await _safe_get(c, f"{settings.datasets_url}/admin/universes")
        raginfo = await _safe_get(c, f"{settings.rag_url}/rag/info")
        catalog = await _safe_get(c, f"{settings.gateway_url}/catalog")

    # database cards — each table links into the self-contained browser (/db/...)
    dbcards = ""
    for key, info in DB_STATUS.items():
        if info["error"]:
            body = f"<div class=err>unavailable: {_esc(info['error'])}</div>"
        else:
            meta = info.get("meta", {})
            counts = _table_counts(key)
            links = " ".join(
                f"<a class=tbl href='/db/{key}/{tname}'>{_esc(tname)} "
                f"<span class=cnt>{_esc(counts.get(tname, '?'))}</span></a>"
                for tname in meta
            ) or "<span class=muted>(no tables)</span>"
            body = f"<div class=tbls>{links}</div><a class=open href='/{key}'>open CRUD editor →</a>"
        dbcards += f"<div class=card><h3>{_esc(info['title'])} <span class=muted>{key}</span></h3>{body}</div>"

    tool_count = catalog.get("count", "?")
    rag_backend = raginfo.get("embedding_backend", raginfo.get("_error", "?"))
    sched_state = sched.get("state", sched.get("_error", "?"))
    fact_rows = stats.get("total_facts", stats.get("_error", "?"))

    # per-market store breakdown + an explicit empty-state warning (the store is
    # empty until someone backfills — make that obvious instead of silent).
    by_market = stats.get("by_market") or []
    if by_market:
        store_rows = "".join(
            f"<tr><td>{_esc(m['market'])}</td><td>{_esc(m['tickers'])}</td><td>{_esc(m['facts'])}</td>"
            f"<td>{_esc(m.get('earliest_report_period'))} → {_esc(m.get('latest_report_period'))}</td></tr>"
            for m in by_market
        )
        store_html = f"<table><tr><th>market</th><th>tickers</th><th>facts</th><th>report-period range</th></tr>{store_rows}</table>"
    else:
        store_html = ("<div class=warn>The ingestion store is <b>empty</b>. Trigger a backfill below "
                      "(or enable the scheduler) — otherwise the screener / historical / 13F-ticker "
                      "endpoints return nothing.</div>")

    # recent ingestion jobs (with live progress) + auto-refresh while one runs
    job_list = jobs.get("jobs") if isinstance(jobs, dict) else None
    running = any(j.get("status") == "running" for j in (job_list or []))
    if job_list:
        def _prog(j):
            tot, dn = j.get("total") or 0, j.get("done") or 0
            return f"{dn}/{tot}" if tot else "—"
        job_rows = "".join(
            f"<tr><td>{_esc(j['id'])}</td><td>{_esc(j['kind'])}</td><td>{_esc(j.get('market'))}</td>"
            f"<td>{_esc(j.get('spec'))}</td><td class={_esc(j['status'])}>{_esc(j['status'])}</td>"
            f"<td>{_esc(_prog(j))}</td><td>{_esc(j.get('rows'))}</td>"
            f"<td>{_esc((j.get('started_at') or '')[:19])}</td>"
            f"<td class=err>{_esc(j.get('error') or '')}</td></tr>"
            for j in job_list
        )
        jobs_html = (f"<table><tr><th>#</th><th>kind</th><th>mkt</th><th>spec</th><th>status</th>"
                     f"<th>progress</th><th>rows</th><th>started</th><th>error</th></tr>{job_rows}</table>")
    else:
        jobs_html = "<p class=muted>No ingestion jobs yet.</p>"

    # universe preset dropdown for the backfill form
    preset_opts = "".join(
        f"<option value='{_esc(u['id'])}'>{_esc(u['label'])} · {_esc(u['market'])}</option>"
        for u in (universes.get("universes") or [])
    ) or "<option value=''>(presets unavailable)</option>"

    # while a backfill runs, refresh every 4s so progress advances on screen
    refresh = "<meta http-equiv=refresh content=4>" if running else ""

    body = _DASH_BODY.format(
        msg=f"<div class=flash>{_esc(msg)}</div>" if msg else "",
        dbcards=dbcards,
        tool_count=_esc(tool_count), rag_backend=_esc(rag_backend),
        sched_state=_esc(sched_state), fact_rows=_esc(fact_rows),
        store_html=store_html, jobs_html=jobs_html, preset_opts=preset_opts,
    )
    return _HEAD + refresh + _STYLE + body


@app.post("/ops/scheduler/{action}")
async def ops_scheduler(request: Request, action: str):
    async with httpx.AsyncClient() as c:
        await c.post(f"{settings.datasets_url}/admin/scheduler/{action}", timeout=20)
    return RedirectResponse(f"/?msg=scheduler+{action}+requested", status_code=303)


@app.post("/ops/backfill")
async def ops_backfill(request: Request, preset: str = Form(""), market: str = Form("US"),
                       tickers: str = Form("")):
    tick = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()] or None
    if preset:
        payload = {"preset": preset, "deep": True}
        label = preset
    else:
        payload = {"market": market, "tickers": tick, "deep": True}
        label = f"{market}+{'+'.join(tick) if tick else '(no+tickers)'}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{settings.datasets_url}/admin/backfill", json=payload, timeout=20)
        ok = r.status_code == 200
    return RedirectResponse(
        f"/?msg=backfill+{'started' if ok else 'failed'}+{label}+(watch+progress+below)", status_code=303
    )


@app.post("/ops/news")
async def ops_news(request: Request, market: str = Form("US"), tickers: str = Form("")):
    tick = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()] or None
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{settings.datasets_url}/admin/news/ingest",
                         json={"market": market, "tickers": tick}, timeout=20)
        ok = r.status_code == 200
    label = f"{market}+{'+'.join(tick) if tick else 'market'}"
    return RedirectResponse(
        f"/?msg=news+ingest+{'started' if ok else 'failed'}+{label}+(watch+progress+below)", status_code=303
    )


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


# --- self-contained DB browser (no sqladmin static deps; relative URLs only) ---
_PAGE_SIZE = 50


def _table_counts(key: str) -> dict[str, int]:
    """Row count per table (best-effort; '?' for any that error)."""
    out: dict[str, int] = {}
    engine = ENGINES.get(key)
    meta = DB_STATUS.get(key, {}).get("meta", {})
    if engine is None:
        return out
    with engine.connect() as conn:
        for tname in meta:
            try:
                out[tname] = conn.execute(text(f'SELECT COUNT(*) FROM "{tname}"')).scalar()
            except Exception:
                out[tname] = "?"
    return out


def _cell(v, limit: int = 0) -> str:
    if v is None:
        return "<span class=muted>NULL</span>"
    s = str(v)
    if limit and len(s) > limit:
        s = s[:limit] + "…"
    return _esc(s)


@app.get("/db/{key}/{table}", response_class=HTMLResponse)
async def browse_table(request: Request, key: str, table: str, page: int = 0):
    info = DB_STATUS.get(key)
    meta = (info or {}).get("meta", {})
    if not info or table not in meta:
        return HTMLResponse(_HEAD + _STYLE + "<h1>unknown table</h1><a href=/>← back</a>", status_code=404)
    engine = ENGINES[key]
    cols = meta[table]["columns"]
    pk = meta[table]["pk"]
    order = f'"{pk[0]}"' if pk else f'"{cols[0]}"'
    page = max(page, 0)
    offset = page * _PAGE_SIZE
    with engine.connect() as conn:
        total = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0
        rows = conn.execute(
            text(f'SELECT * FROM "{table}" ORDER BY {order} LIMIT :lim OFFSET :off'),
            {"lim": _PAGE_SIZE, "off": offset},
        ).fetchall()

    head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    trs = ""
    for i, row in enumerate(rows):
        cells = "".join(f"<td>{_cell(v, 90)}</td>" for v in row)
        trs += f"<tr class=rowlink onclick=\"location='/db/{key}/{table}/row/{offset + i}'\">{cells}</tr>"
    if not rows:
        trs = f"<tr><td colspan={len(cols)} class=muted>no rows</td></tr>"

    last = max((total - 1) // _PAGE_SIZE, 0)
    nav = ""
    if page > 0:
        nav += f"<a class=pg href='/db/{key}/{table}?page={page - 1}'>← prev</a>"
    nav += f"<span class=muted>rows {offset + 1 if total else 0}–{min(offset + _PAGE_SIZE, total)} of {total}</span>"
    if page < last:
        nav += f"<a class=pg href='/db/{key}/{table}?page={page + 1}'>next →</a>"

    body = _BROWSE_BODY.format(
        title=info["title"], key=_esc(key), table=_esc(table),
        head=head, rows=trs, nav=nav,
    )
    return _HEAD + _STYLE + body


@app.get("/db/{key}/{table}/row/{offset}", response_class=HTMLResponse)
async def row_detail(request: Request, key: str, table: str, offset: int):
    info = DB_STATUS.get(key)
    meta = (info or {}).get("meta", {})
    if not info or table not in meta:
        return HTMLResponse(_HEAD + _STYLE + "<h1>unknown table</h1><a href=/>← back</a>", status_code=404)
    engine = ENGINES[key]
    cols = meta[table]["columns"]
    pk = meta[table]["pk"]
    order = f'"{pk[0]}"' if pk else f'"{cols[0]}"'
    offset = max(offset, 0)
    with engine.connect() as conn:
        row = conn.execute(
            text(f'SELECT * FROM "{table}" ORDER BY {order} LIMIT 1 OFFSET :off'),
            {"off": offset},
        ).fetchone()
    if row is None:
        return HTMLResponse(_HEAD + _STYLE + "<h1>row not found</h1>"
                            f"<a href='/db/{key}/{table}'>← back</a>", status_code=404)
    back_page = offset // _PAGE_SIZE
    kv = "".join(
        f"<tr><th class=kvk>{_esc(c)}</th><td class=kvv>{_cell(v)}</td></tr>"
        for c, v in zip(cols, row)
    )
    body = _ROW_BODY.format(
        title=info["title"], key=_esc(key), table=_esc(table),
        offset=offset, back_page=back_page, kv=kv,
    )
    return _HEAD + _STYLE + body


_STYLE = """<style>body{background:#0b0e14;color:#e7ecf3;font-family:system-ui;margin:0;padding:24px;max-width:1100px;margin:auto}
a{color:#4f8cff;text-decoration:none}h1{font-size:20px}h2{font-size:15px;color:#93a0b4;margin-top:28px;border-bottom:1px solid #232b3a;padding-bottom:6px}
h3{font-size:14px;margin:0 0 8px}.muted{color:#93a0b4;font-weight:400;font-size:12px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.card{background:#141925;border:1px solid #232b3a;border-radius:12px;padding:14px}.tbls{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.tbl{background:#1b2230;border:1px solid #232b3a;border-radius:8px;padding:4px 8px;font-size:12px}.open{font-size:13px}
.stat{display:inline-block;background:#141925;border:1px solid #232b3a;border-radius:10px;padding:10px 14px;margin:0 8px 8px 0}
.stat b{display:block;font-size:18px}.err{color:#ff6b6b;font-size:12px}.flash{background:#16321f;border:1px solid #2e6b3f;color:#9be8a8;padding:8px 12px;border-radius:8px;margin-bottom:14px}
form.ops{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:6px 0}input,button,textarea{background:#0b0e14;border:1px solid #232b3a;color:#e7ecf3;border-radius:8px;padding:7px 9px}
button{background:#1b2230;cursor:pointer}button.p{background:#4f8cff;color:#fff;border:0}table{width:100%;border-collapse:collapse;font-size:13px}td,th{border-bottom:1px solid #232b3a;padding:6px;text-align:left;vertical-align:top}
.top{display:flex;justify-content:space-between;align-items:center}
.warn{background:#3a2a16;border:1px solid #6b4e2e;color:#e8c79b;padding:10px 12px;border-radius:8px;margin:6px 0}
td.success{color:#9be8a8}td.error{color:#ff8a8a}td.running{color:#e0c060}
.cnt{background:#0b0e14;border:1px solid #232b3a;border-radius:6px;padding:0 5px;margin-left:3px;font-size:11px;color:#93a0b4}
.rowlink{cursor:pointer}.rowlink:hover td{background:#1b2230}
.pg{background:#1b2230;border:1px solid #232b3a;border-radius:8px;padding:5px 10px;margin-right:10px}
.nav{display:flex;gap:12px;align-items:center;margin:14px 0}
.kvk{width:220px;color:#93a0b4;font-weight:500;white-space:nowrap}.kvv{white-space:pre-wrap;word-break:break-word}
.crumb{font-size:13px;margin-bottom:6px}</style>"""

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

<h2>Ingestion store</h2>
{store_html}
<form class=ops method=post action=/ops/backfill>
  <label class=muted>universe</label>
  <select name=preset>{preset_opts}</select>
  <button class=p>Backfill universe</button>
</form>
<form class=ops method=post action=/ops/backfill>
  <label class=muted>or custom</label>
  <select name=market><option>US</option><option>KR</option></select>
  <input name=tickers placeholder="explicit tickers e.g. AAPL MSFT / 005930" size=34>
  <button>Backfill tickers</button>
</form>

<h2>News → RAG index</h2>
<p class=muted>Pull Google News headlines into the RAG index so <code>rag__search</code> returns
recent context. Indexed as a global corpus (visible to every tenant). Shows up in jobs below (kind <b>news</b>).</p>
<form class=ops method=post action=/ops/news>
  <select name=market><option>US</option><option>KR</option></select>
  <input name=tickers placeholder="tickers e.g. AAPL MSFT / 005930 (blank = market news)" size=40>
  <button class=p>Pull news → RAG</button>
</form>

<h2>Recent ingestion jobs</h2>
{jobs_html}

<h2>Data pipeline (scheduler)</h2>
<form class=ops method=post action=/ops/scheduler/run><button class=p>Run scheduled ingestion now</button></form>
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

_BROWSE_BODY = """
<div class=crumb><a href=/>ValueGraph Admin</a> / {title} <span class=muted>({key})</span></div>
<div class=top><h1>{table}</h1><a href='/{key}'>open CRUD editor →</a></div>
<div class=nav>{nav}</div>
<table><tr>{head}</tr>{rows}</table>
<p class=muted>Click any row to see its full detail.</p>"""

_ROW_BODY = """
<div class=crumb><a href=/>ValueGraph Admin</a> / {title} <span class=muted>({key})</span> /
<a href='/db/{key}/{table}'>{table}</a> / row #{offset}</div>
<div class=top><h1>{table} <span class=muted>row #{offset}</span></h1>
<a href='/db/{key}/{table}?page={back_page}'>← back to list</a></div>
<table>{kv}</table>"""
