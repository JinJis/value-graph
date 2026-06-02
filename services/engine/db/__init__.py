"""Database access + migrations for the ValueGraph Engine.

Postgres (relational: users/themes/tickets/jobs/disclosure calendar) and Neo4j
(the knowledge graph). Migrations are raw SQL/Cypher files under infra/migrations/,
applied once each by a lightweight runner that tracks versions.
"""
