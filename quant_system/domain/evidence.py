"""Source and point-in-time metadata shared by research datasets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceMeta:
    dataset: str
    source: str
    fetched_at: datetime
    as_of: str
    published_at: datetime | None = None
    known_at: datetime | None = None
    source_id: str = ""
    schema_version: str = "1.0.0"
    quality_status: str = "valid"

    def __post_init__(self) -> None:
        if not self.dataset or not self.source or not self.as_of:
            raise ValueError("dataset, source and as_of are required")
        if self.known_at and self.published_at and self.known_at < self.published_at:
            raise ValueError("known_at cannot be earlier than published_at")

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        for key in ("fetched_at", "published_at", "known_at"):
            value = values[key]
            values[key] = value.isoformat() if value else None
        return values
