"""Full-market universe use case independent of TickFlow and JSON paths."""

from __future__ import annotations

from typing import Any

from quant_system.application.ports import InstrumentProvider, UniverseRepository


class UniverseService:
    def __init__(self, provider: InstrumentProvider, repository: UniverseRepository):
        self.provider = provider
        self.repository = repository

    def refresh(self) -> list[dict[str, Any]]:
        rows = self.provider.fetch_instruments()
        if not rows:
            raise RuntimeError(f"{self.provider.name} returned an empty universe")
        self.repository.save(rows, source=self.provider.name)
        return rows

    def load(self) -> list[dict[str, Any]]:
        return self.repository.load()
