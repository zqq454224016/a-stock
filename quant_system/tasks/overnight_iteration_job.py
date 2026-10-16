"""Parallel tournament for T+1 overnight candidates."""
from __future__ import annotations
import gzip, json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.strategy.overnight import SPECS, backtest
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str

def _one(path: Path, cfg: CrawlerConfig) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")); name = payload.get("name") or path.stem
        hp = cfg.data_dir / "history" / f"{path.stem}.json.gz"
        if not hp.exists(): return []
        frame = __import__("pandas").DataFrame(json.load(gzip.open(hp, "rt", encoding="utf-8")))
        if len(frame) < 80 or "ST" in str(name).upper(): return []
        return [{"code": path.stem, "name": name, **backtest(frame, spec)} for spec in SPECS]
    except Exception:
        return []

def run_overnight_iteration(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig(); root = cfg.data_dir / "overnight_iterations"; root.mkdir(parents=True, exist_ok=True)
    paths = [p for p in (cfg.data_dir / "stocks").glob("*.json") if p.stem != "index" and is_research_stock_code(p.stem)]
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(2, cfg.fetch_workers), thread_name_prefix="overnight") as pool:
        for chunk in pool.map(lambda p: _one(p, cfg), paths): rows.extend(chunk)
    summary = {"status": "complete", "updated_at": now_str(), "universe": len(paths), "proxy": True, "strategies": {}}
    for spec in SPECS:
        items = [x for x in rows if x["strategy"] == spec.name and x["trades"]]
        summary["strategies"][spec.name] = {"stocks": len(items), "trades": sum(x["trades"] for x in items), "avg_net_return_pct": round(sum(x["avg_net_return_pct"] for x in items) / len(items), 4) if items else None, "items": items[:200]}
    (root / "latest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
