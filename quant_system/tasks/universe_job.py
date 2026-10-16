"""TickFlow full-market stock universe."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_system.application import UniverseService
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.tickflow_api import TickFlowAPI
from quant_system.infrastructure.storage import JsonUniverseRepository


def universe_path(cfg: CrawlerConfig | None = None) -> Path:
    return (cfg or CrawlerConfig()).data_dir / "universe" / "stocks.json"


def sync_tickflow_universe(cfg: CrawlerConfig | None = None) -> list[dict[str, Any]]:
    cfg = cfg or CrawlerConfig()
    service = UniverseService(TickFlowAPI(cfg), JsonUniverseRepository(universe_path(cfg)))
    return service.refresh()


def load_tickflow_universe(cfg: CrawlerConfig | None = None) -> list[dict[str, Any]]:
    return JsonUniverseRepository(universe_path(cfg)).load()
