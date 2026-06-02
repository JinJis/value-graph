"""Object storage for uploaded artifacts (filings/reports/PDFs).

A small ``Storage`` protocol with a local-filesystem backend for dev; the same
interface swaps to S3/MinIO in production without touching call sites.
"""

from services.engine.storage.base import Storage
from services.engine.storage.local import LocalStorage, local_storage_from_env

__all__ = ["Storage", "LocalStorage", "local_storage_from_env"]
