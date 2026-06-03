"""[M4-PERSIST-01] Versioned theme-build persistence: Protocol + in-memory + Neo4j.

A :class:`~services.engine.db.artifacts.ThemeBuild` is stored per theme as an
incrementing build version, so a theme's full CVE-derived state is reconstructable
from the DB and prior builds remain retrievable. This is the Staging graph; the
explicit Staging->Production publish is M4-PUB-04.

Neo4j layout:
- ``(:Company {ticker})`` MERGE'd by ticker (shared across builds).
- ``(:ThemeBuild {theme_id, version, created_at})`` identifies a build.
- ``(:Company)-[:SUPPLIES {theme_id, build_version, ...}]->(:Company)`` per edge.
- ``(:Claim {key, theme_id, build_version, ...})-[:SOURCED_FROM]->(:Source {id})``.
- ``(:GapEdge {theme_id, build_version, ...})`` for drawn (non-publishable) gaps.

Re-saving a version replaces that version's edges/claims/gaps (idempotent).
"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol

from neo4j import Driver

from services.engine.db.artifacts import GapEdge, ThemeBuild, edge_source_refs


def claim_key(claim: dict[str, Any]) -> str:
    """Deterministic node key for a Claim (the schema has no id; identity = content)."""
    raw = "|".join(
        str(claim.get(field, ""))
        for field in ("source_id", "relation", "subject", "object", "text_span")
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class GraphStore(Protocol):
    def next_version(self, theme_id: str) -> int: ...

    def save_build(self, build: ThemeBuild) -> ThemeBuild: ...

    def load_build(self, theme_id: str, version: int) -> ThemeBuild | None: ...

    def load_latest(self, theme_id: str) -> ThemeBuild | None: ...

    def list_versions(self, theme_id: str) -> list[int]: ...


class InMemoryGraphStore:
    """Faithful in-memory mirror of the Neo4j semantics (used by unit tests)."""

    def __init__(self) -> None:
        self._builds: dict[str, dict[int, ThemeBuild]] = {}

    def next_version(self, theme_id: str) -> int:
        return max(self._builds.get(theme_id, {}), default=0) + 1

    def save_build(self, build: ThemeBuild) -> ThemeBuild:
        stored = build.model_copy(deep=True)
        self._builds.setdefault(build.theme_id, {})[build.version] = stored
        return stored

    def load_build(self, theme_id: str, version: int) -> ThemeBuild | None:
        found = self._builds.get(theme_id, {}).get(version)
        return found.model_copy(deep=True) if found is not None else None

    def load_latest(self, theme_id: str) -> ThemeBuild | None:
        versions = self._builds.get(theme_id, {})
        if not versions:
            return None
        return self.load_build(theme_id, max(versions))

    def list_versions(self, theme_id: str) -> list[int]:
        return sorted(self._builds.get(theme_id, {}))


class Neo4jGraphStore:
    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def next_version(self, theme_id: str) -> int:
        with self._driver.session() as session:
            record = session.run(
                "MATCH (b:ThemeBuild {theme_id: $theme_id}) "
                "RETURN coalesce(max(b.version), 0) + 1 AS v",
                theme_id=theme_id,
            ).single()
            return int(record["v"]) if record else 1

    def save_build(self, build: ThemeBuild) -> ThemeBuild:
        with self._driver.session() as session:
            session.execute_write(self._write_build, build)
        return build

    @staticmethod
    def _write_build(tx: Any, build: ThemeBuild) -> None:
        tid, ver = build.theme_id, build.version
        # Replace any prior copy of this version (idempotent re-save).
        tx.run(
            "MATCH (b:ThemeBuild {theme_id: $tid, version: $ver}) DETACH DELETE b",
            tid=tid, ver=ver,
        )
        tx.run(
            "MATCH (c:Claim {theme_id: $tid, build_version: $ver}) DETACH DELETE c",
            tid=tid, ver=ver,
        )
        tx.run(
            "MATCH (g:GapEdge {theme_id: $tid, build_version: $ver}) DETACH DELETE g",
            tid=tid, ver=ver,
        )
        tx.run(
            "MATCH (:Company)-[r:SUPPLIES {theme_id: $tid, build_version: $ver}]->(:Company) "
            "DELETE r",
            tid=tid, ver=ver,
        )

        tx.run(
            "CREATE (:ThemeBuild {theme_id: $tid, version: $ver, created_at: $created})",
            tid=tid, ver=ver, created=build.created_at.isoformat(),
        )
        tx.run(
            "UNWIND $companies AS co MERGE (c:Company {ticker: co.ticker}) SET c += co",
            companies=build.companies,
        )
        tx.run("UNWIND $sources AS s MERGE (n:Source {id: s.id}) SET n += s.props", sources=[
            {"id": sid, "props": props} for sid, props in build.sources.items()
        ])
        tx.run(
            "UNWIND $edges AS e "
            "MATCH (a:Company {ticker: e.supplier}), (b:Company {ticker: e.customer}) "
            "CREATE (a)-[r:SUPPLIES]->(b) SET r = e, r.theme_id = $tid, r.build_version = $ver",
            edges=build.edges, tid=tid, ver=ver,
        )
        tx.run(
            "UNWIND $claims AS cl "
            "CREATE (c:Claim) SET c = cl.props, c.key = cl.key, "
            "c.theme_id = $tid, c.build_version = $ver "
            "WITH c, cl MATCH (s:Source {id: cl.props.source_id}) "
            "MERGE (c)-[:SOURCED_FROM]->(s)",
            claims=[{"key": claim_key(c), "props": c} for c in build.claims],
            tid=tid, ver=ver,
        )
        tx.run(
            "UNWIND $gaps AS g "
            "CREATE (:GapEdge {theme_id: $tid, build_version: $ver, supplier: g.supplier, "
            "customer: g.customer, confidence: g.confidence, freshness: g.freshness, "
            "reason: g.reason})",
            gaps=[g.model_dump() for g in build.gap_edges], tid=tid, ver=ver,
        )

    def load_build(self, theme_id: str, version: int) -> ThemeBuild | None:
        with self._driver.session() as session:
            return session.execute_read(self._read_build, theme_id, version)

    @staticmethod
    def _read_build(tx: Any, theme_id: str, version: int) -> ThemeBuild | None:
        head = tx.run(
            "MATCH (b:ThemeBuild {theme_id: $tid, version: $ver}) RETURN b.created_at AS created",
            tid=theme_id, ver=version,
        ).single()
        if head is None:
            return None

        edges = [
            _strip(dict(record["r"]), ("theme_id", "build_version"))
            for record in tx.run(
                "MATCH (:Company)-[r:SUPPLIES {theme_id: $tid, build_version: $ver}]->(:Company) "
                "RETURN r ORDER BY r.supplier, r.customer",
                tid=theme_id, ver=version,
            )
        ]
        tickers = sorted({t for e in edges for t in (e["supplier"], e["customer"])})
        companies = [
            dict(record["c"])
            for record in tx.run(
                "MATCH (c:Company) WHERE c.ticker IN $tickers RETURN c ORDER BY c.ticker",
                tickers=tickers,
            )
        ]
        claim_rows = [
            _strip(dict(record["c"]), ("theme_id", "build_version", "key"))
            for record in tx.run(
                "MATCH (c:Claim {theme_id: $tid, build_version: $ver}) "
                "RETURN c ORDER BY c.source_id, c.subject, c.object",
                tid=theme_id, ver=version,
            )
        ]
        source_ids = sorted({c["source_id"] for c in claim_rows})
        sources = {
            record["id"]: _strip(dict(record["s"]), ("id",))
            for record in tx.run(
                "MATCH (s:Source) WHERE s.id IN $ids RETURN s.id AS id, s AS s",
                ids=source_ids,
            )
        }
        gaps = [
            GapEdge(
                supplier=record["g"]["supplier"],
                customer=record["g"]["customer"],
                confidence=record["g"]["confidence"],
                freshness=record["g"]["freshness"],
                reason=record["g"]["reason"],
            )
            for record in tx.run(
                "MATCH (g:GapEdge {theme_id: $tid, build_version: $ver}) "
                "RETURN g ORDER BY g.supplier, g.customer",
                tid=theme_id, ver=version,
            )
        ]
        # Reconstruct per-edge Source refs from the persisted claim->Source chain,
        # restricted to the admitted (publishable) edges.
        admitted_keys = {f"{e['supplier']}->{e['customer']}" for e in edges}
        edge_sources = {
            k: v
            for k, v in edge_source_refs(claim_rows, sources).items()
            if k in admitted_keys
        }
        return ThemeBuild(
            theme_id=theme_id,
            version=version,
            created_at=head["created"],
            companies=companies,
            edges=edges,
            claims=claim_rows,
            sources=sources,
            gap_edges=gaps,
            edge_sources=edge_sources,
        )

    def load_latest(self, theme_id: str) -> ThemeBuild | None:
        versions = self.list_versions(theme_id)
        return self.load_build(theme_id, versions[-1]) if versions else None

    def list_versions(self, theme_id: str) -> list[int]:
        with self._driver.session() as session:
            return [
                int(record["v"])
                for record in session.run(
                    "MATCH (b:ThemeBuild {theme_id: $tid}) RETURN b.version AS v ORDER BY v",
                    tid=theme_id,
                )
            ]


def _strip(props: dict[str, Any], drop: tuple[str, ...]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if k not in drop}
