"""产出短线 / 长线分轨策略分析报告。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.strategy.horizon_analysis import build_horizon_analysis
from quant_system.utils.time_utils import now_str


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_horizon_strategy_analysis(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "horizon_analysis"
    strategy = _read(cfg.data_dir / "strategy_iterations/latest.json")
    if not strategy:
        payload = {
            "status": "missing_strategy_iteration",
            "updated_at": now_str(),
            "summary": "缺少 strategy_iterations/latest.json，无法分轨分析",
        }
        _write(root / "latest.json", payload)
        return payload

    overnight = _read(cfg.data_dir / "overnight_iterations/latest.json")
    aggressive = _read(cfg.data_dir / "aggressive_board_iterations/latest.json")
    recommendation = _read(cfg.data_dir / "recommendations/summary.json")
    payload = build_horizon_analysis(
        strategy_iteration=strategy,
        overnight_iteration=overnight,
        aggressive_board_iteration=aggressive,
        recommendation=recommendation,
    )
    _write(root / "latest.json", payload)
    _write(root / "short.json", payload["tracks"]["short"])
    _write(root / "long.json", payload["tracks"]["long"])
    _write(root / "swing.json", payload["tracks"]["swing"])
    stamp = now_str().replace(" ", "T").replace(":", "")
    _write(root / "history" / f"{stamp}.json", payload)
    return payload


if __name__ == "__main__":
    result = run_horizon_strategy_analysis()
    print(json.dumps({
        "status": result.get("status"),
        "short_verdict": ((result.get("tracks") or {}).get("short") or {}).get("analysis", {}).get("verdict"),
        "long_verdict": ((result.get("tracks") or {}).get("long") or {}).get("analysis", {}).get("verdict"),
        "comparison": result.get("comparison"),
    }, ensure_ascii=False, indent=2))
