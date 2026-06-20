"""Auto-selecting US macro provider: FRED first (when keyed), DBnomics fallback.

FRED is bot-walled from datacenter IPs, so a cloud deployment with a valid
``FRED_API_KEY`` still fails. This provider tries FRED only when a key is set and
transparently falls back to the keyless, cloud-safe DBnomics (BIS) backend on any
upstream failure (the bot-wall, a network error, or no data). With no FRED key it
goes straight to DBnomics — so US macro works out of the box, keyless, in the cloud.
"""

from __future__ import annotations

from datetime import date

from app.config import settings
from app.errors import APIError
from app.models.generated import InterestRate
from app.providers.us.dbnomics import DBnomicsProvider
from app.providers.us.fred import FredProvider


class AutoMacroProvider:
    def __init__(self) -> None:
        self._fred = FredProvider()
        self._dbnomics = DBnomicsProvider()

    def banks(self) -> list[dict]:
        return self._dbnomics.banks()

    async def interest_rates(
        self, bank: str, start: date | None, end: date | None
    ) -> list[InterestRate]:
        if settings.fred_api_key:
            try:
                return await self._fred.interest_rates(bank, start, end)
            except APIError:
                pass  # bot-wall / upstream / no-data → keyless fallback
        return await self._dbnomics.interest_rates(bank, start, end)

    async def snapshot(self, bank: str) -> list[InterestRate]:
        if settings.fred_api_key:
            try:
                return await self._fred.snapshot(bank)
            except APIError:
                pass
        return await self._dbnomics.snapshot(bank)
