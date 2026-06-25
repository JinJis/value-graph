-- Extra databases for the SQLAlchemy services (the `rag` DB is created via POSTGRES_DB).
-- Runs ONCE, on a fresh pg_data volume (docker-entrypoint-initdb.d), as the POSTGRES_USER (rag),
-- which therefore owns them. To (re)create on an existing volume: `docker compose down -v`.
CREATE DATABASE datasets;
CREATE DATABASE controlplane;
CREATE DATABASE studio;
