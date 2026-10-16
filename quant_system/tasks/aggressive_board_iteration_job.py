"""激进板筛选推荐的并行策略锦标赛（研究轨，不直接改正式推荐）。"""

from __future__ import annotations

import gzip
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.strategy.aggressive_board import SPECS, backtest
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str


def _one(path: Path, cfg: CrawlerConfig) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        name = payload.get("name") or path.stem
        history_path = cfg.data_dir / "history" / f"{path.stem}.json.gz"
        if not history_path.exists():
            return []
        frame = __import__("pandas").DataFrame(
            json.load(gzip.open(history_path, "rt", encoding="utf-8"))
        )
        if len(frame) < 80 or "ST" in str(name).upper():
            return []
        return [{"code": path.stem, "name": name, **backtest(frame, spec)} for spec in SPECS]
    except Exception:
        return []


def run_aggressive_board_iteration(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "aggressive_board_iterations"
    root.mkdir(parents=True, exist_ok=True)
    paths = [
        path for path in (cfg.data_dir / "stocks").glob("*.json")
        if path.stem != "index" and is_research_stock_code(path.stem)
    ]
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(
        max_workers=max(2, cfg.fetch_workers),
        thread_name_prefix="aggressive",
    ) as pool:
        for chunk in pool.map(lambda path: _one(path, cfg), paths):
            rows.extend(chunk)

    summary: dict[str, Any] = {
        "status": "complete",
        "updated_at": now_str(),
        "universe": len(paths),
        "proxy": True,
        "product_alignment": "recommendation.aggressive_filter",
        "note": (
            "并行研究激进板三类代理；正式激进板仍须偏强市+情绪偏热+分时确认，"
            "本结果不自动写入正式推荐。"
        ),
        "strategies": {},
    }
    for spec in SPECS:
        items = [row for row in rows if row["strategy"] == spec.name and row["trades"]]
        avg = (
            round(sum(row["avg_net_return_pct"] for row in items) / len(items), 4)
            if items else None
        )
        hit_vals = [row["hit_rate"] for row in items if row.get("hit_rate") is not None]
        summary["strategies"][spec.name] = {
            "mode": spec.mode,
            "max_hold_days": spec.max_hold_days,
            "stocks": len(items),
            "trades": sum(row["trades"] for row in items),
            "avg_net_return_pct": avg,
            "avg_hit_rate": round(sum(hit_vals) / len(hit_vals), 4) if hit_vals else None,
            "edge_positive": avg is not None and avg > 0,
            "items": items[:200],
        }
    positive = sum(
        1 for payload in summary["strategies"].values() if payload.get("edge_positive")
    )
    summary["positive_edge_count"] = positive
    summary["all_negative"] = bool(summary["strategies"]) and positive == 0
    (root / "latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    result = run_aggressive_board_iteration()
    print(json.dumps({
        "status": result.get("status"),
        "universe": result.get("universe"),
        "all_negative": result.get("all_negative"),
        "strategies": {
            name: {
                k: payload.get(k)
                for k in ("stocks", "trades", "avg_net_return_pct", "avg_hit_rate", "edge_positive")
            }
            for name, payload in (result.get("strategies") or {}).items()
        },
    }, ensure_ascii=False, indent=2))
