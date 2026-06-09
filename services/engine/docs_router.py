"""Human-facing docs surface: a landing page + a database ERD.

FastAPI already serves the OpenAPI schema (``/openapi.json``), Swagger UI (``/docs``) and
ReDoc (``/redoc``). This adds a root landing page that links them together and an ``/erd``
page that renders the Postgres schema + the Neo4j graph model + the Two-Track architecture as
Mermaid diagrams (kept in sync with ``infra/migrations`` and ``db/graph_store.py`` by hand).
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["docs"], include_in_schema=False)


# --- Mermaid sources (hand-maintained against infra/migrations + db/graph_store.py) --------

# Two-Track architecture (CLAUDE.md §1): Studio edits Staging → explicit Publish → Production.
_TWO_TRACK = """
graph LR
  Studio["Studio (Admin)<br/>build · CVE · tickets"]
  Staging["STAGING (mutable)<br/>Postgres + Neo4j builds"]
  Prod["PRODUCTION (read-only)<br/>production_snapshots"]
  Terminal["Terminal (User)<br/>3D canvas"]
  Studio --> Staging
  Staging -- "explicit Publish" --> Prod
  Prod --> Terminal
"""

# Postgres relational schema. ||--o{ = FK (one-to-many); |o--o{ = optional FK;
# ||..o{ = logical link (theme_id uuid, no DB constraint).
_PG_ERD = """
erDiagram
  themes_meta ||--o{ sources : "theme_id"
  themes_meta ||--o{ blueprints : "theme_id"
  themes_meta ||--o{ tickets : "theme_id"
  themes_meta ||--o{ jobs : "theme_id"
  tickets ||--o{ ticket_events : "ticket_id"
  tickets |o--o{ sources : "ticket_id (evidence)"
  themes_meta ||..o{ production_snapshots : "theme_id (no FK)"
  themes_meta ||..o{ feed_items : "theme_id (no FK)"

  users {
    uuid id PK
    text email UK
    text display_name
    timestamptz created_at
  }
  themes_meta {
    uuid id PK
    text name
    text status
    text description
    text_array seed_tickers
    int version
    timestamptz published_at
  }
  sources {
    uuid id PK
    uuid theme_id FK
    uuid ticket_id FK
    text type
    text url
    text storage_key
    text content_type
    text verification_status
    date as_of_date
  }
  blueprints {
    uuid id PK
    uuid theme_id FK
    int version
    jsonb content
    text generated_by
  }
  tickets {
    uuid id PK
    uuid theme_id FK
    text target
    text metric
    text status
    text reason_code
    jsonb current_estimate
    jsonb research_proposal
  }
  ticket_events {
    uuid id PK
    uuid ticket_id FK
    text from_status
    text to_status
    text actor
  }
  jobs {
    uuid id PK
    text type
    text status
    jsonb payload
    uuid theme_id FK
  }
  production_snapshots {
    uuid id PK
    uuid theme_id
    int snapshot_version
    int source_build_version
    text published_by
    jsonb content
  }
  feed_items {
    uuid id PK
    uuid theme_id
    text title
    text url
    text source_type
    jsonb entities
    timestamptz published_at
  }
  disclosure_calendar {
    uuid id PK
    text company_ticker UK
    date next_filing_estimate
    date last_filing_date
    int cadence_days
  }
  company_financials {
    uuid id PK
    text company_ticker UK
    float revenue
    float cogs
    float capex
    float rnd
    float sga
    text currency
    date as_of_date
  }
  prompt_overrides {
    text key PK
    text text
    timestamptz updated_at
  }
"""

# Neo4j graph model (db/graph_store.py): the published supply-chain graph + its provenance.
_NEO4J = """
graph LR
  C1["(:Company)<br/>ticker — unique"]
  C2["(:Company)<br/>ticker"]
  CL["(:Claim)<br/>key, theme_id, build_version,<br/>value, text_span"]
  SRC["(:Source)<br/>id"]
  TB["(:ThemeBuild)<br/>theme_id, version"]
  GE["(:GapEdge)<br/>theme_id, build_version<br/>(drawn gap edges)"]
  C1 -- "SUPPLIES { theme_id, build_version,<br/>trade_value, confidence, ... }" --> C2
  CL -- "SOURCED_FROM" --> SRC
"""


def _page(title: str, intro: str, diagrams: list[tuple[str, str, str]]) -> str:
    sections = "".join(
        f'<h2>{heading}</h2><p class="note">{note}</p>'
        f'<pre class="mermaid">{src}</pre>'
        for heading, note, src in diagrams
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 1100px; margin: 2rem auto;
         padding: 0 1rem; color: #0f172a; }}
  a {{ color: #2563eb; }}
  h1 {{ margin-bottom: .25rem; }}
  .note {{ color: #475569; font-size: 14px; margin: .25rem 0 .75rem; }}
  nav {{ margin: .5rem 0 1.5rem; font-size: 14px; }}
  .mermaid {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
             padding: 12px; overflow-x: auto; }}
</style>
</head><body>
<h1>{title}</h1>
<p class="note">{intro}</p>
<nav>
  <a href="docs">Swagger UI</a> ·
  <a href="redoc">ReDoc</a> ·
  <a href="openapi.json">OpenAPI JSON</a> ·
  <a href="erd">Database ERD</a> ·
  <a href="health">Health</a>
</nav>
{sections}
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({{ startOnLoad: true, securityLevel: 'loose' }});
</script>
</body></html>"""


@router.get("/", response_class=HTMLResponse)
def landing() -> HTMLResponse:
    """Engine landing page: links to the API docs and the database ERD."""
    return HTMLResponse(
        _page(
            "ValueGraph Engine",
            "FastAPI service powering the supply-chain graph. Explore the API and data model:",
            [
                (
                    "Two-Track architecture",
                    "Studio edits Staging; an explicit Publish copies it to read-only "
                    "Production, which the Terminal renders.",
                    _TWO_TRACK,
                )
            ],
        )
    )


@router.get("/erd", response_class=HTMLResponse)
def erd() -> HTMLResponse:
    """Entity-relationship diagrams for the Postgres schema + the Neo4j graph model."""
    return HTMLResponse(
        _page(
            "ValueGraph — Data model (ERD)",
            "The relational store (Postgres) and the published graph store (Neo4j). "
            "Diagrams track infra/migrations and the graph store; financials/calendar are "
            "keyed by ticker (a logical link to the Neo4j :Company nodes, not a Postgres FK).",
            [
                ("Postgres (relational)", "Users, themes, sources, blueprints, tickets, "
                 "jobs, snapshots, feed, calendar, financials, prompt overrides.", _PG_ERD),
                ("Neo4j (published graph)", "Companies + SUPPLIES edges, with Claims "
                 "SOURCED_FROM Sources; versioned per ThemeBuild.", _NEO4J),
                ("Two-Track architecture", "How Staging becomes Production.", _TWO_TRACK),
            ],
        )
    )
