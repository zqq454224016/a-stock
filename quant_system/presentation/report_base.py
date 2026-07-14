"""Shared helpers for static report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "assets" / "data"
REPORTS_DIR = ROOT / "reports"
COMMON_CSS_LINKS = (
    '<link rel="stylesheet" href="../../css/common.css">',
    '<link rel="stylesheet" href="../../css/report.css">',
)


def data_path(*parts: str) -> Path:
    return DATA_DIR.joinpath(*parts)


def report_path(*parts: str) -> Path:
    return REPORTS_DIR.joinpath(*parts)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_data_json(rel: str, default: Any = None) -> Any:
    return read_json(DATA_DIR / rel, default)


def read_json_map(folder: Path, *, exclude_index: bool = True) -> dict[str, dict[str, Any]]:
    if not folder.exists():
        return {}
    return {
        path.stem: read_json(path, {})
        for path in sorted(folder.glob("*.json"))
        if not exclude_index or path.stem != "index"
    }


def safe_json_script(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def write_html(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def read_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def css_links(indent: str = "  ") -> str:
    return "\n".join(f"{indent}{link}" for link in COMMON_CSS_LINKS)
