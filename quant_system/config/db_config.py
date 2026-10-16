"""Local JSON storage configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class DBConfig:
    # JSON is the only active persistence contract.
    json_data_dir: Path = PROJECT_ROOT / "assets" / "data"
