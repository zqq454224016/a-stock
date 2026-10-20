"""回测「尾盘板块T+1观察」规则，输出与尾盘进次日出相同口径的诊断。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.strategy import tail_sector
from quant_system.strategy.tail_overnight import HOLDOUT_TRADE_DAYS, gate, summarize
from quant_system.tasks.tail_overnight_iteration_job import _universe, _write, load_history
from quant_system.utils.time_utils import now_str


def run_tail_sector_backtest(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    context = tail_sector.load_context(cfg.data_dir)
    board, industries, bench = context["board"], context["industries"], context["bench"]

    def one(item: tuple[str, str]) -> pd.DataFrame:
        code = item[0]
        frame = load_history(cfg, code)
        if frame is None or len(frame) < 40 or code not in industries:
            return pd.DataFrame()
        return tail_sector.trades(frame, code, industries[code], board, bench)

    with ThreadPoolExecutor(max_workers=max(2, cfg.fetch_workers)) as pool:
        frames = [f for f in pool.map(one, _universe(cfg)) if not f.empty]
    rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["date", "code", "spec", "net", "score", "limit_down_exit", "sector"])
    calendar = sorted(board)
    holdout_start = calendar[-HOLDOUT_TRADE_DAYS]
    dev_dates = [d for d in calendar if d < holdout_start]
    dev_mid = dev_dates[len(dev_dates) // 2]
    specs = {}
    for name, _ in tail_sector.EXITS:
        part = rows[rows.spec == name]
        segments = [summarize(part[part.date < dev_mid]),
                    summarize(part[(part.date >= dev_mid) & (part.date < holdout_start)])]
        holdout = summarize(part[part.date >= holdout_start])
        specs[name] = {"development": segments, "holdout": holdout, "gate": gate(segments, holdout)}
    payload = {
        "status": "complete",
        "updated_at": now_str(),
        "rule_source": "recommendation/builder.py::_tail_sector_filter（原样复现，未调参）",
        "rule": {
            "sector": f"所属行业进入当日涨幅前{tail_sector.SECTOR_TOP_N}且为正（builder 仅比较领涨/领跌各5个行业）",
            "stock_change_pct": [0.5, 8.0],
            "trend": "收盘>MA20 且 MA5≥MA20",
            "relative_strength": "个股涨幅 - 沪深300ETF涨幅 ≥ 0",
            "excluded": "收盘涨停、一字板、次日停牌",
        },
        "period": {"first": calendar[0], "last": calendar[-1], "holdout_start": holdout_start},
        "trade_count": int(len(rows) // max(1, len(tail_sector.EXITS))),
        "specs": specs,
    }
    _write(cfg.data_dir / "tail_overnight/tail_sector_backtest.json", payload)
    return payload


if __name__ == "__main__":
    result = run_tail_sector_backtest()
    print(json.dumps({
        "period": result["period"], "signals": result["trade_count"],
        "specs": {
            name: {
                "dev": [(s["trades"], s["hit_rate"], s["avg_net_return_pct"], (s.get("portfolio") or {}).get("total_return_pct"))
                        for s in item["development"]],
                "holdout": (item["holdout"]["trades"], item["holdout"]["hit_rate"], item["holdout"]["avg_net_return_pct"],
                            (item["holdout"].get("portfolio") or {}).get("total_return_pct")),
                "failed": item["gate"]["failed"],
            } for name, item in result["specs"].items()
        },
    }, ensure_ascii=False, indent=1))
