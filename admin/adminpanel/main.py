"""ValueGraph admin — operations console.

A left-nav mission-control over the whole platform, organized by operator
job-to-be-done (Overview · Catalog · Pipelines · Data · Users · DB browser):

* **Catalog** — what the service offers, live from the manifest: every data
  source/connector, each resource → REST path → MCP tool, RAG + agent backends.
* **Pipelines** — every ingest/precompute job as a live progress card + controls.
* **Data / Users** — ingestion-store + RAG health; tenants/projects/keys/activations.
* **DB browser** — our own styled CRUD over every reflected service table (no
  sqladmin → no unstyled raw-HTML fallback).

One session login gates everything (a guard middleware).
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import MetaData, Table, and_, create_engine, text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from adminpanel.config import DATABASES, settings
from adminpanel.views import _cell, _esc, badge, login_page, page, progress, sdot

app = FastAPI(title="ValueGraph Admin")

DB_STATUS: dict[str, dict] = {}   # key -> {title, tables:[...], error, meta:{table->{columns,pk}}}
ENGINES: dict[str, object] = {}   # key -> sqlalchemy Engine
TABLES: dict[str, dict] = {}      # key -> {table_name -> sqlalchemy Table} (for typed CRUD)


def _mount_database(key: str, title: str, url: str) -> None:
    """Reflect a service DB: capture table/column/pk metadata + Table objects (typed
    CRUD) + the live engine, so the styled DB browser pages and edits rows directly."""
    try:
        engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        md = MetaData()
        md.reflect(bind=engine)
    except Exception as e:  # DB missing / unreachable — note it, keep the panel up
        DB_STATUS[key] = {"title": title, "tables": [], "error": str(e)[:200], "meta": {}}
        return

    ENGINES[key] = engine
    TABLES[key] = dict(md.tables)
    meta: dict[str, dict] = {}
    for tname, tbl in sorted(md.tables.items()):
        meta[tname] = {"columns": [c.name for c in tbl.columns],
                       "pk": [c.name for c in tbl.primary_key.columns]}
    DB_STATUS[key] = {"title": title, "tables": sorted(meta), "error": None, "meta": meta}


for _k, _t, _u in DATABASES:
    _mount_database(_k, _t, _u)


# --- auth -----------------------------------------------------------------
async def _guard(request: Request, call_next):
    p = request.url.path
    if p in ("/login", "/logout", "/healthz"):
        return await call_next(request)
    if not request.session.get("authed"):
        return RedirectResponse("/login", status_code=302)
    return await call_next(request)


app.add_middleware(BaseHTTPMiddleware, dispatch=_guard)
app.add_middleware(SessionMiddleware, secret_key=settings.adminui_secret)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if request.session.get("authed"):
        return RedirectResponse("/", status_code=302)
    return HTMLResponse(login_page())


@app.post("/login")
async def login(request: Request, username: str = Form(""), password: str = Form("")):
    if username == settings.adminui_username and password == settings.adminui_password:
        request.session["authed"] = True
        return RedirectResponse("/", status_code=302)
    return HTMLResponse(login_page("<div class=e>Invalid credentials.</div>"), status_code=401)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# --- shared data fetch ----------------------------------------------------
async def _safe_get(client: httpx.AsyncClient, url: str) -> dict:
    try:
        r = await client.get(url, timeout=8)
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_status": r.status_code}
    except Exception as e:
        return {"_error": str(e)[:120]}


def _ok(d: dict) -> bool:
    return isinstance(d, dict) and "_error" not in d and "_status" not in d


def _flash(msg: str) -> str:
    return f"<div class=flash>{_esc(msg)}</div>" if msg else ""


def _table_counts(key: str) -> dict[str, int]:
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


def _tile(k, v, ic, href, small=False) -> str:
    inner = f"<div class='k'>{ic} {_esc(k)}</div><div class='v {'sm' if small else ''}'>{_esc(v)}</div>"
    return f"<a class=tile href='{href}' style='display:block'>{inner}</a>"


# --- Overview -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def overview(request: Request, msg: str = ""):
    async with httpx.AsyncClient() as c:
        sched = await _safe_get(c, f"{settings.datasets_url}/admin/scheduler")
        stats = await _safe_get(c, f"{settings.datasets_url}/admin/store/stats")
        jobs = await _safe_get(c, f"{settings.datasets_url}/admin/jobs")
        raginfo = await _safe_get(c, f"{settings.rag_url}/rag/info")
        catalog = await _safe_get(c, f"{settings.gateway_url}/catalog")
        agentinfo = await _safe_get(c, f"{settings.agent_engine_url}/agent/info")

    conns = catalog.get("connectors") or []
    tool_count = sum(len(cn.get("resources") or []) for cn in conns) if conns else catalog.get("count", "?")
    job_list = jobs.get("jobs") if isinstance(jobs, dict) else []
    running = [j for j in (job_list or []) if j.get("status") == "running"]
    errored = [j for j in (job_list or []) if j.get("status") == "error"][:5]

    tiles = "".join([
        _tile("data sources", len(conns) if conns else "?", "◈", "/catalog"),
        _tile("catalog tools", tool_count, "⚙", "/catalog"),
        _tile("RAG embedder", raginfo.get("embedding_backend", "—"), "▤", "/data", small=True),
        _tile("scheduler", sched.get("state", "—"), "⏣", "/pipelines", small=True),
        _tile("store facts", stats.get("total_facts", "—"), "▦", "/data"),
        _tile("jobs running", len(running), "●", "/pipelines"),
    ])

    checks = [
        ("Gateway / catalog", _ok(catalog)),
        ("Data plane (datasets)", _ok(stats) or _ok(sched)),
        ("RAG", _ok(raginfo)),
        ("Agent engine", _ok(agentinfo)),
        ("Scheduler", _ok(sched) and sched.get("state") in ("running", "paused", "idle")),
    ]
    health = "".join(
        f"<div class=card><h3>{sdot('ok' if up else 'err')} {_esc(name)}</h3>"
        f"<div class=sub>{'reachable' if up else 'unreachable / down'}</div></div>"
        for name, up in checks
    )
    for key, info in DB_STATUS.items():
        up = info["error"] is None
        health += (f"<div class=card><h3>{sdot('ok' if up else 'err')} DB · {_esc(info['title'])}</h3>"
                   f"<div class=sub>{len(info.get('meta', {}))} tables · {_esc(info['error']) if not up else 'reflected'}</div></div>")

    err_html = ""
    if errored:
        rows = "".join(f"<tr><td>{_esc(j['id'])}</td><td>{_esc(j.get('kind'))}</td>"
                       f"<td class=err>{_cell(j.get('error'), 120)}</td></tr>" for j in errored)
        err_html = ("<h2>Recent errors</h2><div class=tablewrap><table><thead><tr><th>#</th><th>kind</th>"
                    f"<th>error</th></tr></thead><tbody>{rows}</tbody></table></div>")

    body = (
        _flash(msg)
        + "<h2>At a glance</h2><div class=tiles>" + tiles + "</div>"
        + "<h2>Subsystem health</h2><div class=grid>" + health + "</div>"
        + err_html
        + "<h2>Jump to</h2><div>"
        + "".join(f"<span class=pill><a href='{h}'>{_esc(l)}</a></span>"
                  for h, l in [("/catalog", "Catalog →"), ("/pipelines", "Pipelines →"),
                               ("/data", "Data →"), ("/users", "Users →"), ("/db", "DB browser →")])
        + "</div>"
    )
    return HTMLResponse(page("/", "Overview", body, refresh=bool(running)))


# --- Catalog --------------------------------------------------------------
@app.get("/catalog", response_class=HTMLResponse)
async def catalog_view(request: Request):
    async with httpx.AsyncClient() as c:
        catalog = await _safe_get(c, f"{settings.gateway_url}/catalog")
        raginfo = await _safe_get(c, f"{settings.rag_url}/rag/info")
        agentinfo = await _safe_get(c, f"{settings.agent_engine_url}/agent/info")

    conns = catalog.get("connectors") or []
    tool_count = sum(len(cn.get("resources") or []) for cn in conns)

    cards = ""
    for cn in conns:
        cid = cn.get("id", "?")
        lic = cn.get("license") or {}
        up = cn.get("upstream") or {}
        meta_badges = " ".join(
            [badge(m) for m in (cn.get("markets") or [])]
            + [badge("key required", "warn") if up.get("requires_key") else badge("keyless", "ok"),
               badge("redistributable", "ok") if lic.get("redistribution") else badge("restricted", "err")]
        )
        rrows = ""
        for r in (cn.get("resources") or []):
            prov = (r.get("provenance") or {}).get("source") or "—"
            tool = f"{cid}__{r.get('name')}"
            rrows += (f"<tr><td><code>{_esc(tool)}</code></td>"
                      f"<td>{badge(_esc(r.get('method', 'GET')))} <code>{_esc(r.get('path'))}</code></td>"
                      f"<td>{_esc(', '.join(r.get('markets') or cn.get('markets') or []))}</td>"
                      f"<td class=muted>{_esc(prov)}</td></tr>")
        cards += (
            f"<div class=card><h3>{_esc(cn.get('name'))} <span class=muted>{_esc(cid)}</span></h3>"
            f"<div class=sub>{_esc(cn.get('description') or '')}</div>"
            f"<div style='margin-bottom:10px'>{meta_badges}</div>"
            f"<div class=tablewrap><table><thead><tr><th>MCP tool</th><th>REST</th><th>markets</th><th>source</th></tr></thead>"
            f"<tbody>{rrows or '<tr><td colspan=4 class=muted>no resources</td></tr>'}</tbody></table></div></div>"
        )

    rag_card = (
        "<div class=card><h3>◩ RAG</h3><div class=sub>provenance-first retrieval</div>"
        + "".join(f"<div><span class=muted>{_esc(k)}:</span> <code>{_esc(raginfo.get(k, '—'))}</code></div>"
                  for k in ("embedding_backend", "embedding_model", "reranker_backend", "vector_store"))
        + ("<div class=warn>RAG unreachable</div>" if not _ok(raginfo) else "")
        + "</div>"
    )
    agent_card = (
        "<div class=card><h3>✦ Agent engine</h3><div class=sub>planner + tool loop</div>"
        + "".join(f"<div><span class=muted>{_esc(k)}:</span> <code>{_esc(agentinfo.get(k, '—'))}</code></div>"
                  for k in ("llm_backend", "model"))
        + ("<div class=warn>Agent engine unreachable</div>" if not _ok(agentinfo) else "")
        + "</div>"
    )

    summary = "".join([
        _tile("connectors", len(conns), "◈", "/catalog"),
        _tile("MCP tools", tool_count, "⚙", "/catalog"),
        _tile("RAG embedder", raginfo.get("embedding_backend", "—"), "▤", "/data", small=True),
        _tile("agent model", agentinfo.get("model", "—"), "✦", "/catalog", small=True),
    ])

    err = "<div class=warn>Gateway/catalog unreachable — start the stack to see live connectors.</div>" if not conns else ""
    body = ("<p class=hint>Live from the connector manifest (<code>/catalog</code>), <code>/rag/info</code> and "
            "<code>/agent/info</code> — every data source, its REST routes &amp; the MCP tool each exposes "
            "(<code>{connector}__{resource}</code>). Never hand-maintained.</p>"
            + "<div class=tiles>" + summary + "</div>" + err
            + "<h2>Retrieval &amp; agent</h2><div class=grid>" + rag_card + agent_card + "</div>"
            + "<h2>Data sources / connectors</h2><div class=grid>" + cards + "</div>")
    return HTMLResponse(page("/catalog", "Catalog", body))


# --- Pipelines ------------------------------------------------------------
@app.get("/pipelines", response_class=HTMLResponse)
async def pipelines(request: Request, msg: str = ""):
    async with httpx.AsyncClient() as c:
        sched = await _safe_get(c, f"{settings.datasets_url}/admin/scheduler")
        jobs = await _safe_get(c, f"{settings.datasets_url}/admin/jobs")
        universes = await _safe_get(c, f"{settings.datasets_url}/admin/universes")

    job_list = jobs.get("jobs") if isinstance(jobs, dict) else []
    running = any(j.get("status") == "running" for j in (job_list or []))
    sstate = sched.get("state", sched.get("_error", "?"))
    sbadge = badge(sstate, "run" if sstate == "running" else ("warn" if sstate == "paused" else ""))

    if job_list:
        rows = ""
        for j in job_list:
            st = j.get("status")
            kind = {"success": "ok", "error": "err", "running": "run"}.get(st, "")
            tot, dn = j.get("total") or 0, j.get("done") or 0
            ptxt = f"{dn}/{tot}" if tot else "—"
            rows += (
                f"<tr><td>{_esc(j['id'])}</td><td>{badge(_esc(j.get('kind')))}</td>"
                f"<td>{_esc(j.get('market') or '')}</td><td class=wrap>{_cell(j.get('spec'), 40)}</td>"
                f"<td>{badge(_esc(st), kind)}</td>"
                f"<td><div style='display:flex;align-items:center;gap:8px'>{progress(dn, tot, kind)}<span class=muted>{_esc(ptxt)}</span></div></td>"
                f"<td>{_esc(j.get('rows') if j.get('rows') is not None else '')}</td>"
                f"<td class=muted>{_esc((j.get('started_at') or '')[:19])}</td>"
                f"<td class=err>{_cell(j.get('error') or '', 60)}</td></tr>"
            )
        jobs_html = ("<div class=tablewrap><table><thead><tr><th>#</th><th>kind</th><th>mkt</th><th>spec</th>"
                     "<th>status</th><th>progress</th><th>rows</th><th>started</th><th>error</th></tr></thead>"
                     f"<tbody>{rows}</tbody></table></div>")
    else:
        jobs_html = "<div class=empty>No ingestion jobs yet — trigger one below.</div>"

    preset_opts = "".join(
        f"<option value='{_esc(u['id'])}'>{_esc(u['label'])} · {_esc(u['market'])}</option>"
        for u in (universes.get("universes") or [])
    ) or "<option value=''>(presets unavailable)</option>"

    triggers = f"""
<h2>Triggers</h2>
<div class=grid>
  <div class=card><h3>Backfill — universe</h3><div class=sub>ingestion store + optional evidence PDFs</div>
    <form class=ops method=post action=/ops/backfill>
      <select name=preset>{preset_opts}</select>
      <label class=muted><input type=checkbox name=precompute value=1> 📷 evidence</label>
      <button class=p>Backfill</button>
    </form></div>
  <div class=card><h3>Backfill — explicit tickers</h3><div class=sub>comma/space separated</div>
    <form class=ops method=post action=/ops/backfill>
      <select name=market><option>US</option><option>KR</option></select>
      <input name=tickers placeholder="AAPL MSFT / 005930" size=22>
      <label class=muted><input type=checkbox name=precompute value=1> 📷 evidence</label>
      <button class=p>Backfill</button>
    </form></div>
  <div class=card><h3>News → RAG</h3><div class=sub>headlines into the corpus (kind <code>news</code>)</div>
    <form class=ops method=post action=/ops/news>
      <select name=market><option>US</option><option>KR</option></select>
      <input name=tickers placeholder="tickers (blank = market)" size=22>
      <button class=p>Pull news</button>
    </form></div>
  <div class=card><h3>Scheduler &amp; self-test</h3><div class=sub>state: {sbadge}</div>
    <form class=ops method=post action=/ops/scheduler/run><button class=p>Run now</button></form>
    <form class=ops method=post action=/ops/scheduler/pause><button>Pause</button></form>
    <form class=ops method=post action=/ops/scheduler/resume><button>Resume</button></form>
    <form class=ops method=post action=/ops/selftest><button>Run self-test</button></form>
  </div>
  <div class=card><h3>RAG ingest</h3><div class=sub>add a document to the corpus</div>
    <form class=ops method=post action=/ops/rag/ingest>
      <input name=text placeholder="document text" size=22 required>
      <input name=source placeholder=source value=admin size=10>
      <button class=p>Ingest</button></form></div>
  <div class=card><h3>RAG search</h3><div class=sub>semantic probe</div>
    <form class=ops method=post action=/ops/rag/search>
      <input name=query placeholder="semantic query" size=22 required><button class=p>Search</button></form></div>
</div>"""

    body = (_flash(msg)
            + "<p class=hint>Everything that ingests or precomputes, in one place — each job shows live "
              "progress and the page auto-refreshes while a job runs.</p>"
            + f"<h2>Jobs {'· ⟳ live' if running else ''}</h2>" + jobs_html
            + triggers)
    return HTMLResponse(page("/pipelines", "Pipelines", body, refresh=running))


# --- Data -----------------------------------------------------------------
@app.get("/data", response_class=HTMLResponse)
async def data_view(request: Request):
    async with httpx.AsyncClient() as c:
        stats = await _safe_get(c, f"{settings.datasets_url}/admin/store/stats")
        raginfo = await _safe_get(c, f"{settings.rag_url}/rag/info")

    by_market = stats.get("by_market") or []
    if by_market:
        rows = "".join(
            f"<tr><td>{badge(_esc(m['market']))}</td><td>{_esc(m['tickers'])}</td><td>{_esc(m['facts'])}</td>"
            f"<td class=muted>{_esc(m.get('earliest_report_period'))} → {_esc(m.get('latest_report_period'))}</td></tr>"
            for m in by_market)
        store_html = ("<div class=tablewrap><table><thead><tr><th>market</th><th>tickers</th><th>facts</th>"
                      f"<th>report-period range</th></tr></thead><tbody>{rows}</tbody></table></div>")
    else:
        store_html = ("<div class=warn>The ingestion store is <b>empty</b>. Run a backfill in "
                      "<a href=/pipelines>Pipelines</a> — otherwise screener / historical / 13F-ticker "
                      "endpoints return nothing.</div>")

    counts = {k: _table_counts(k) for k in DB_STATUS}
    db_rows = ""
    for key, info in DB_STATUS.items():
        for tname in info.get("meta", {}):
            db_rows += (f"<tr><td>{_esc(info['title'])}</td><td><a href='/db/{key}/{tname}'><code>{_esc(tname)}</code></a></td>"
                        f"<td>{_esc(counts[key].get(tname, '?'))}</td></tr>")

    rag_html = "".join(f"<span class=pill>{_esc(k)}: <code>{_esc(raginfo.get(k, '—'))}</code></span>"
                       for k in ("embedding_backend", "reranker_backend", "vector_store"))

    body = ("<h2>Ingestion store</h2>" + store_html
            + "<h2>RAG corpus backends</h2><div>" + (rag_html or "<span class=warn>RAG unreachable</span>") + "</div>"
            + "<h2>Stored rows by table</h2><div class=tablewrap><table><thead><tr><th>database</th><th>table</th>"
              "<th>rows</th></tr></thead><tbody>" + (db_rows or "<tr><td colspan=3 class=muted>no databases</td></tr>")
            + "</tbody></table></div>")
    return HTMLResponse(page("/data", "Data", body))


# --- Users / tenants ------------------------------------------------------
def _query(key: str, sql: str, params: dict | None = None) -> list:
    engine = ENGINES.get(key)
    if engine is None:
        return []
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params or {}).fetchall()
    except Exception:
        return []


def _has(key: str, table: str) -> bool:
    return table in DB_STATUS.get(key, {}).get("meta", {})


def _simple_table(key: str, table: str, cols: list[str], limit: int = 50) -> str:
    if not _has(key, table):
        return f"<div class=empty>No <code>{_esc(table)}</code> table.</div>"
    have = [c for c in cols if c in DB_STATUS[key]["meta"][table]["columns"]] or DB_STATUS[key]["meta"][table]["columns"][:6]
    sel = ", ".join(f'"{c}"' for c in have)
    rows = _query(key, f'SELECT {sel} FROM "{table}" LIMIT {limit}')
    head = "".join(f"<th>{_esc(c)}</th>" for c in have)
    trs = "".join("<tr>" + "".join(f"<td class=wrap>{_cell(v, 60)}</td>" for v in r) + "</tr>" for r in rows)
    link = f"<a href='/db/{key}/{table}'>open in DB browser →</a>"
    return (f"<div class=tablewrap><table><thead><tr>{head}</tr></thead>"
            f"<tbody>{trs or f'<tr><td colspan={len(have)} class=muted>no rows</td></tr>'}</tbody></table></div>"
            f"<div class=hint>{link}</div>")


@app.get("/users", response_class=HTMLResponse)
async def users_view(request: Request):
    cp_up = DB_STATUS.get("controlplane", {}).get("error") is None
    if not cp_up:
        body = "<div class=warn>Control-plane DB not mounted/reflected — tenant &amp; entitlement views unavailable.</div>"
        return HTMLResponse(page("/users", "Users", body))

    body = (
        "<p class=hint>Who can use what, and what they used — from the control-plane "
        "(tenants → projects → API keys → activations → usage) and studio users.</p>"
        + "<h2>Tenants</h2>" + _simple_table("controlplane", "tenants", ["id", "name", "created_at"])
        + "<h2>Projects</h2>" + _simple_table("controlplane", "projects", ["id", "tenant_id", "name", "created_at"])
        + "<h2>API keys</h2>" + _simple_table("controlplane", "api_keys", ["id", "project_id", "prefix", "created_at"])
        + "<h2>Activations (entitlements)</h2>" + _simple_table("controlplane", "activations", ["id", "project_id", "connector_id", "created_at"])
        + "<h2>Recent usage</h2>" + _simple_table("controlplane", "usage_events", ["id", "project_id", "tool", "ts"], limit=30)
        + "<h2>Studio users</h2>" + _simple_table("studio", "users", ["email", "tenant_id", "project_id"])
    )
    return HTMLResponse(page("/users", "Users", body))


# --- ops actions (POST → redirect to /pipelines) --------------------------
@app.post("/ops/scheduler/{action}")
async def ops_scheduler(request: Request, action: str):
    async with httpx.AsyncClient() as c:
        await c.post(f"{settings.datasets_url}/admin/scheduler/{action}", timeout=20)
    return RedirectResponse(f"/pipelines?msg=scheduler+{action}+requested", status_code=303)


@app.post("/ops/backfill")
async def ops_backfill(request: Request, preset: str = Form(""), market: str = Form("US"),
                       tickers: str = Form(""), precompute: str = Form("")):
    tick = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()] or None
    if preset:
        payload, label = {"preset": preset, "deep": True}, preset
    else:
        payload, label = {"market": market, "tickers": tick, "deep": True}, f"{market}+{'+'.join(tick) if tick else '(no+tickers)'}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{settings.datasets_url}/admin/backfill", json=payload, timeout=20)
        ok = r.status_code == 200
        ev = ""
        if precompute:
            pc = {"preset": preset} if preset else {"market": market, "tickers": tick}
            pr = await c.post(f"{settings.datasets_url}/admin/evidence-docs", json=pc, timeout=20)
            ev = "+evidence" if pr.status_code == 200 and pr.json().get("started") else "+(evidence+failed)"
    return RedirectResponse(f"/pipelines?msg=backfill+{'started' if ok else 'failed'}+{label}{ev}", status_code=303)


@app.post("/ops/news")
async def ops_news(request: Request, market: str = Form("US"), tickers: str = Form("")):
    tick = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()] or None
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{settings.datasets_url}/admin/news/ingest", json={"market": market, "tickers": tick}, timeout=20)
        ok = r.status_code == 200
    label = f"{market}+{'+'.join(tick) if tick else 'market'}"
    return RedirectResponse(f"/pipelines?msg=news+ingest+{'started' if ok else 'failed'}+{label}", status_code=303)


@app.post("/ops/selftest")
async def ops_selftest(request: Request):
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{settings.datasets_url}/admin/selftest", timeout=60)
        j = r.json() if r.status_code == 200 else {}
    summary = f"selftest: {j.get('passed', '?')} passed / {j.get('failed', '?')} failed / {j.get('skipped', '?')} skipped"
    return RedirectResponse(f"/pipelines?msg={summary.replace(' ', '+')}", status_code=303)


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
    return RedirectResponse(f"/pipelines?msg=rag+ingested+{n}+chunks", status_code=303)


@app.post("/ops/rag/search", response_class=HTMLResponse)
async def ops_rag_search(request: Request, query: str = Form(...)):
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{settings.rag_url}/rag/search", json={"query": query, "top_k": 5}, timeout=30)
        hits = (r.json() or {}).get("hits", []) if r.status_code == 200 else []
    rows = "".join(
        f"<tr><td>{_esc(round(h.get('score', 0), 3))}</td><td>{_esc((h.get('provenance') or {}).get('source'))}</td>"
        f"<td class=wrap>{_cell(h.get('text', ''), 200)}</td></tr>" for h in hits
    ) or "<tr><td colspan=3 class=muted>no hits</td></tr>"
    body = (f"<div class=crumb><a href=/pipelines>← Pipelines</a></div><h2>RAG search · “{_esc(query)}”</h2>"
            f"<div class=tablewrap><table><thead><tr><th>score</th><th>source</th><th>text</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>")
    return HTMLResponse(page("/pipelines", "RAG search", body))


# --- DB browser (styled CRUD; no sqladmin) --------------------------------
_PAGE = 50


@app.get("/db", response_class=HTMLResponse)
async def db_index(request: Request):
    cards = ""
    for key, info in DB_STATUS.items():
        if info["error"]:
            cards += (f"<div class=card><h3>{_esc(info['title'])} <span class=muted>{key}</span></h3>"
                      f"<div class=err>unavailable: {_esc(info['error'])}</div></div>")
            continue
        counts = _table_counts(key)
        chips = "".join(
            f"<span class=pill><a href='/db/{key}/{t}'>{_esc(t)}</a><span class=cnt>{_esc(counts.get(t, '?'))}</span></span>"
            for t in info["meta"]) or "<span class=muted>(no tables)</span>"
        cards += f"<div class=card><h3>{_esc(info['title'])} <span class=muted>{key}</span></h3>{chips}</div>"
    body = ("<p class=hint>Every reflected service table — view, edit, create, delete in the panel theme.</p>"
            "<div class=grid>" + cards + "</div>")
    return HTMLResponse(page("/db", "DB browser", body))


def _check(key: str, table: str):
    info = DB_STATUS.get(key)
    meta = (info or {}).get("meta", {})
    if not info or table not in meta:
        return None, None
    return info, meta[table]


def _crumb(key, table, extra="") -> str:
    info = DB_STATUS.get(key, {})
    return (f"<div class=crumb><a href=/db>DB browser</a> / {_esc(info.get('title', key))} "
            f"<span class=muted>({_esc(key)})</span> / <a href='/db/{key}/{table}'>{_esc(table)}</a>{extra}</div>")


@app.get("/db/{key}/{table}", response_class=HTMLResponse)
async def browse_table(request: Request, key: str, table: str, page_: int = 0):
    info, m = _check(key, table)
    if not info:
        return HTMLResponse(page("/db", "not found", "<div class=warn>unknown table</div>"), status_code=404)
    cols, pk = m["columns"], m["pk"]
    engine = ENGINES[key]
    order = f'"{pk[0]}"' if pk else f'"{cols[0]}"'
    p = max(page_, 0)
    offset = p * _PAGE
    with engine.connect() as conn:
        total = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0
        rows = conn.execute(text(f'SELECT * FROM "{table}" ORDER BY {order} LIMIT :l OFFSET :o'),
                            {"l": _PAGE, "o": offset}).fetchall()
    head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    trs = ""
    for i, row in enumerate(rows):
        cells = "".join(f"<td class=wrap>{_cell(v, 80)}</td>" for v in row)
        trs += f"<tr class=rowlink onclick=\"location='/db/{key}/{table}/row/{offset + i}'\">{cells}</tr>"
    if not rows:
        trs = f"<tr><td colspan={len(cols)} class=muted>no rows</td></tr>"

    last = max((total - 1) // _PAGE, 0)
    nav = ""
    if p > 0:
        nav += f"<a class=pg href='/db/{key}/{table}?page_={p - 1}'>← prev</a>"
    nav += f"<span class=muted>rows {offset + 1 if total else 0}–{min(offset + _PAGE, total)} of {total}</span>"
    if p < last:
        nav += f"<a class=pg href='/db/{key}/{table}?page_={p + 1}'>next →</a>"
    new_btn = (f"<a class='btn p' href='/db/{key}/{table}/new'>+ new row</a>" if pk
               else "<span class=muted>read-only (no PK)</span>")

    body = (_crumb(key, table)
            + "<div class=top style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px'>"
              f"<div class=pgbar>{nav}</div>{new_btn}</div>"
            + f"<div class=tablewrap><table><thead><tr>{head}</tr></thead><tbody>{trs}</tbody></table></div>"
            + "<p class=hint>Click a row to view / edit.</p>")
    return HTMLResponse(page("/db", f"{table}", body))


def _row_at(key: str, table: str, offset: int):
    info, m = _check(key, table)
    if not info:
        return None, None
    cols, pk = m["columns"], m["pk"]
    engine = ENGINES[key]
    order = f'"{pk[0]}"' if pk else f'"{cols[0]}"'
    with engine.connect() as conn:
        row = conn.execute(text(f'SELECT * FROM "{table}" ORDER BY {order} LIMIT 1 OFFSET :o'),
                           {"o": max(offset, 0)}).fetchone()
    return (dict(zip(cols, row)) if row is not None else None), m


@app.get("/db/{key}/{table}/row/{offset}", response_class=HTMLResponse)
async def row_detail(request: Request, key: str, table: str, offset: int):
    rec, m = _row_at(key, table, offset)
    if rec is None:
        return HTMLResponse(page("/db", "not found", "<div class=warn>row not found</div>"), status_code=404)
    kv = "".join(f"<tr><th class=kvk>{_esc(c)}</th><td class=kvv>{_cell(v)}</td></tr>" for c, v in rec.items())
    back_page = offset // _PAGE
    actions = ""
    if m["pk"]:
        actions = (f"<a class='btn p' href='/db/{key}/{table}/row/{offset}/edit'>✎ edit</a>"
                   f"<form method=post action='/db/{key}/{table}/row/{offset}/delete' "
                   "onsubmit=\"return confirm('Delete this row? This cannot be undone.')\" style='display:inline'>"
                   "<button class=danger>🗑 delete</button></form>")
    body = (_crumb(key, table, f" / row #{offset}")
            + "<div class=top style='margin-bottom:12px'>"
              f"<a class=pg href='/db/{key}/{table}?page_={back_page}'>← back to list</a></div>"
            + f"<div class=tablewrap><table><tbody>{kv}</tbody></table></div>"
            + f"<div class=actions>{actions}</div>")
    return HTMLResponse(page("/db", f"{table} · row", body))


def _coerce(col, raw: str):
    if raw == "":
        return None
    try:
        pyt = col.type.python_type
    except Exception:
        return raw
    try:
        if pyt is bool:
            return raw.strip().lower() in ("1", "true", "yes", "on")
        if pyt is int:
            return int(raw)
        if pyt is float:
            return float(raw)
    except (ValueError, TypeError):
        return raw
    return raw


def _form_fields(tbl: Table, rec: dict | None) -> str:
    out = ""
    for col in tbl.columns:
        val = "" if rec is None or rec.get(col.name) is None else rec.get(col.name)
        tname = type(col.type).__name__
        out += (f"<label class=fld><span class=nm>{_esc(col.name)} "
                f"<code>{_esc(tname)}{' · PK' if col.primary_key else ''}</code></span>"
                f"<input name='f_{_esc(col.name)}' value='{_esc(val)}'></label>")
    return out


@app.get("/db/{key}/{table}/row/{offset}/edit", response_class=HTMLResponse)
async def edit_form(request: Request, key: str, table: str, offset: int):
    rec, m = _row_at(key, table, offset)
    if rec is None or not m["pk"]:
        return HTMLResponse(page("/db", "not editable",
                                 "<div class=warn>row not found or table has no primary key</div>"), status_code=404)
    tbl = TABLES[key][table]
    body = (_crumb(key, table, f" / row #{offset} / edit")
            + f"<h2>Edit row</h2><form method=post action='/db/{key}/{table}/row/{offset}/edit'>"
            + _form_fields(tbl, rec)
            + f"<div class=actions><button class=p>Save</button>"
              f"<a class=pg href='/db/{key}/{table}/row/{offset}'>cancel</a></div></form>")
    return HTMLResponse(page("/db", f"{table} · edit", body))


@app.post("/db/{key}/{table}/row/{offset}/edit")
async def edit_save(request: Request, key: str, table: str, offset: int):
    rec, m = _row_at(key, table, offset)
    if rec is None or not m["pk"]:
        return HTMLResponse(page("/db", "not editable", "<div class=warn>row gone</div>"), status_code=404)
    tbl = TABLES[key][table]
    form = await request.form()
    vals = {c.name: _coerce(c, form.get(f"f_{c.name}", "")) for c in tbl.columns}
    where = [tbl.c[pk] == rec[pk] for pk in m["pk"]]
    try:
        with ENGINES[key].begin() as conn:
            conn.execute(tbl.update().where(and_(*where)).values(**vals))
    except Exception as e:
        body = (_crumb(key, table) + f"<div class=warn>update failed: {_esc(str(e)[:200])}</div>"
                f"<a class=pg href='/db/{key}/{table}/row/{offset}/edit'>← back</a>")
        return HTMLResponse(page("/db", "error", body), status_code=400)
    return RedirectResponse(f"/db/{key}/{table}/row/{offset}", status_code=303)


@app.post("/db/{key}/{table}/row/{offset}/delete")
async def delete_row(request: Request, key: str, table: str, offset: int):
    rec, m = _row_at(key, table, offset)
    if rec is None or not m["pk"]:
        return HTMLResponse(page("/db", "not deletable", "<div class=warn>row gone</div>"), status_code=404)
    tbl = TABLES[key][table]
    where = [tbl.c[pk] == rec[pk] for pk in m["pk"]]
    with ENGINES[key].begin() as conn:
        conn.execute(tbl.delete().where(and_(*where)))
    return RedirectResponse(f"/db/{key}/{table}?msg=deleted", status_code=303)


@app.get("/db/{key}/{table}/new", response_class=HTMLResponse)
async def new_form(request: Request, key: str, table: str):
    info, m = _check(key, table)
    if not info or not m["pk"]:
        return HTMLResponse(page("/db", "not creatable",
                                 "<div class=warn>unknown table / no primary key</div>"), status_code=404)
    tbl = TABLES[key][table]
    body = (_crumb(key, table, " / new")
            + "<h2>New row</h2><p class=hint>Leave a field blank to use its default / autoincrement.</p>"
            + f"<form method=post action='/db/{key}/{table}/new'>" + _form_fields(tbl, None)
            + f"<div class=actions><button class=p>Create</button>"
              f"<a class=pg href='/db/{key}/{table}'>cancel</a></div></form>")
    return HTMLResponse(page("/db", f"{table} · new", body))


@app.post("/db/{key}/{table}/new")
async def new_save(request: Request, key: str, table: str):
    info, m = _check(key, table)
    if not info or not m["pk"]:
        return HTMLResponse(page("/db", "not creatable", "<div class=warn>unknown table</div>"), status_code=404)
    tbl = TABLES[key][table]
    form = await request.form()
    vals = {}
    for c in tbl.columns:
        raw = form.get(f"f_{c.name}", "")
        if raw != "":
            vals[c.name] = _coerce(c, raw)
    try:
        with ENGINES[key].begin() as conn:
            conn.execute(tbl.insert().values(**vals))
    except Exception as e:
        body = (_crumb(key, table) + f"<div class=warn>insert failed: {_esc(str(e)[:200])}</div>"
                f"<a class=pg href='/db/{key}/{table}/new'>← back</a>")
        return HTMLResponse(page("/db", "error", body), status_code=400)
    return RedirectResponse(f"/db/{key}/{table}?msg=created", status_code=303)
