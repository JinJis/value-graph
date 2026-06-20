"""ValueGraph admin panel.

Django-admin-style CRUD over every service database (control-plane / studio /
datasets) via SQLAlchemy reflection + sqladmin, plus an operations console for the
runtime pieces (data pipeline scheduler, self-test, RAG, MCP/catalog).

One login gates everything (a session cookie + a guard middleware that also wraps
the mounted sqladmin sub-apps).
"""

from __future__ import annotations


import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqladmin import Admin, ModelView
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.automap import automap_base
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from adminpanel.config import DATABASES, settings
from adminpanel.views import HEAD, STYLE, _cell, _esc, render

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


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if request.session.get("authed"):
        return RedirectResponse("/", status_code=302)
    return render("login", err="")


@app.post("/login")
async def login(request: Request, username: str = Form(""), password: str = Form("")):
    if username == settings.adminui_username and password == settings.adminui_password:
        request.session["authed"] = True
        return RedirectResponse("/", status_code=302)
    return HTMLResponse(render("login", err="<div class=e>Invalid credentials.</div>"), status_code=401)


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

    body = render("dashboard", 
        msg=f"<div class=flash>{_esc(msg)}</div>" if msg else "",
        dbcards=dbcards,
        tool_count=_esc(tool_count), rag_backend=_esc(rag_backend),
        sched_state=_esc(sched_state), fact_rows=_esc(fact_rows),
        store_html=store_html, jobs_html=jobs_html, preset_opts=preset_opts,
    )
    return HEAD + refresh + STYLE + body


@app.post("/ops/scheduler/{action}")
async def ops_scheduler(request: Request, action: str):
    async with httpx.AsyncClient() as c:
        await c.post(f"{settings.datasets_url}/admin/scheduler/{action}", timeout=20)
    return RedirectResponse(f"/?msg=scheduler+{action}+requested", status_code=303)


@app.post("/ops/backfill")
async def ops_backfill(request: Request, preset: str = Form(""), market: str = Form("US"),
                       tickers: str = Form(""), precompute: str = Form("")):
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
        # Same trigger, one click: also index visual-evidence pointers (US SEC iXBRL).
        # Independent of the backfill job (it reads filings live), so fire-and-forget here;
        # the datasets endpoint resolves the preset and skips non-US tickers itself.
        ev = ""
        if precompute:
            pc = {"preset": preset} if preset else {"market": market, "tickers": tick}
            pr = await c.post(f"{settings.datasets_url}/admin/precompute-locations", json=pc, timeout=20)
            ev = "+evidence" if pr.status_code == 200 and pr.json().get("started") else "+(evidence+skipped:+US+only)"
    return RedirectResponse(
        f"/?msg=backfill+{'started' if ok else 'failed'}+{label}{ev}+(watch+progress+below)", status_code=303
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
    return HEAD + STYLE + render("search", query=_esc(query), rows=rows)


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


@app.get("/db/{key}/{table}", response_class=HTMLResponse)
async def browse_table(request: Request, key: str, table: str, page: int = 0):
    info = DB_STATUS.get(key)
    meta = (info or {}).get("meta", {})
    if not info or table not in meta:
        return HTMLResponse(HEAD + STYLE + "<h1>unknown table</h1><a href=/>← back</a>", status_code=404)
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

    body = render("browse", 
        title=info["title"], key=_esc(key), table=_esc(table),
        head=head, rows=trs, nav=nav,
    )
    return HEAD + STYLE + body


@app.get("/db/{key}/{table}/row/{offset}", response_class=HTMLResponse)
async def row_detail(request: Request, key: str, table: str, offset: int):
    info = DB_STATUS.get(key)
    meta = (info or {}).get("meta", {})
    if not info or table not in meta:
        return HTMLResponse(HEAD + STYLE + "<h1>unknown table</h1><a href=/>← back</a>", status_code=404)
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
        return HTMLResponse(HEAD + STYLE + "<h1>row not found</h1>"
                            f"<a href='/db/{key}/{table}'>← back</a>", status_code=404)
    back_page = offset // _PAGE_SIZE
    kv = "".join(
        f"<tr><th class=kvk>{_esc(c)}</th><td class=kvv>{_cell(v)}</td></tr>"
        for c, v in zip(cols, row)
    )
    body = render("row", 
        title=info["title"], key=_esc(key), table=_esc(table),
        offset=offset, back_page=back_page, kv=kv,
    )
    return HEAD + STYLE + body


