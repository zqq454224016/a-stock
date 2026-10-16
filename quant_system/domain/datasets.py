"""Dataset catalog. This module intentionally has no I/O dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DataLayer(StrEnum):
    RAW = "raw"
    NORMALIZED = "normalized"
    FEATURE = "feature"
    RESEARCH = "research"
    EVIDENCE = "evidence"


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    name: str
    layer: DataLayer
    primary_key: tuple[str, ...]
    owner: str
    requires_known_at: bool = False
    description: str = ""


DATASET_CATALOG: dict[str, DatasetSpec] = {
    "market.instruments": DatasetSpec(
        "market.instruments", DataLayer.NORMALIZED, ("symbol", "effective_from"), "market-data",
        requires_known_at=True, description="Point-in-time listed instrument universe",
    ),
    "market.daily": DatasetSpec(
        "market.daily", DataLayer.NORMALIZED, ("symbol", "trade_date"), "market-data",
        description="Adjusted and unadjusted daily bars",
    ),
    "market.corporate_actions": DatasetSpec(
        "market.corporate_actions", DataLayer.NORMALIZED, ("symbol", "action_id"), "market-rules",
        requires_known_at=True, description="Dividends, splits and adjustment factors",
    ),
    "market.trading_status": DatasetSpec(
        "market.trading_status", DataLayer.NORMALIZED, ("symbol", "trade_date"), "market-rules",
        requires_known_at=True, description="ST, suspension and price-limit status",
    ),
    "financial.statements": DatasetSpec(
        "financial.statements", DataLayer.NORMALIZED, ("symbol", "period_end", "version"), "fundamentals",
        requires_known_at=True, description="Point-in-time financial statements",
    ),
    "events.announcements": DatasetSpec(
        "events.announcements", DataLayer.NORMALIZED, ("source", "source_id"), "events",
        requires_known_at=True, description="Official company and regulatory announcements",
    ),
    "features.technical": DatasetSpec(
        "features.technical", DataLayer.FEATURE, ("symbol", "trade_date", "feature_version"), "quant-research",
        description="Technical and liquidity features",
    ),
    "research.factor_evaluation": DatasetSpec(
        "research.factor_evaluation", DataLayer.RESEARCH, ("run_id", "factor"), "quant-research",
        description="Out-of-sample factor evaluation",
    ),
    "evidence.stock": DatasetSpec(
        "evidence.stock", DataLayer.EVIDENCE, ("evidence_id",), "ai-research",
        requires_known_at=True, description="Frozen evidence package consumed by AI",
    ),
}


def dataset_spec(name: str) -> DatasetSpec:
    try:
        return DATASET_CATALOG[name]
    except KeyError as exc:
        raise ValueError(f"Unknown dataset: {name}") from exc
