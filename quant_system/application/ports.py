"""Ports implemented by infrastructure adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class InstrumentProvider(Protocol):
    name: str

    def fetch_instruments(self) -> list[dict[str, Any]]: ...


class UniverseRepository(Protocol):
    def save(self, rows: list[dict[str, Any]], *, source: str) -> Path: ...
    def load(self) -> list[dict[str, Any]]: ...
