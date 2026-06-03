"""[M4-DQ-05] Read-only data-quality endpoint (computed from the Production snapshot)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from services.engine.db.config import DbSettings
from services.engine.publish.publish import PostgresProductionStore, ProductionStore
from services.engine.publish.quality import QualityReport, compute_quality

router = APIRouter(tags=["publish"])


def get_production_store() -> ProductionStore:
    return PostgresProductionStore(DbSettings.from_env())


ProductionStoreDep = Annotated[ProductionStore, Depends(get_production_store)]


@router.get("/themes/{theme_id}/quality", response_model=QualityReport)
def theme_quality(theme_id: str, store: ProductionStoreDep) -> QualityReport:
    """The verified/derived/estimated/gap mix of a theme's currently published graph."""
    snapshot = store.current(theme_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no published snapshot for theme")
    return compute_quality(snapshot)
