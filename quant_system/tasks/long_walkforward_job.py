"""长线轨道的逐年滚动前推验证。

最近60日诊断窗口装不下持有20–60日的交易，中长线候选在原锦标赛里样本外恒为0笔。
这里按年分折：每折只用该年之前（扣除持有期间隔）的交易挑选候选，再看它在当年的表现；
各年样本外拼接起来就是完整的前推记录。逐笔交易来自 strategy_tracks 证据缓存。
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.strategy.track_catalog import TRACK_LONG, build_catalog
from quant_system.tasks.strategy_track_evidence_job import _cell, run_strategy_track_evidence
from quant_system.utils.time_utils import now_str

WALKFORWARD_VERSION = "1.0.0"
FIRST_TEST_YEAR = 2019
SELECTION = {"min_train_trades": 200, "min_train_t": 2.0}  # 2026-10-20 预登记
GATE = {"min_test_trades": 200, "min_t": 2.0, "min_positive_fold_ratio": 0.6, "min_beat_baseline_ratio": 0.5}
GROUPS = {
    "long_all": {"label": "长线组（20日波段 + 60日中长线）", "min_hold": 11, "baseline": "baseline_long_only"},
    "hold_60": {"label": "60日持有组（原锦标赛无法评估）", "min_hold": 60, "baseline": "baseline_medium"},
}


def _to_int(day: date) -> int:
    return day.year * 10000 + day.month * 100 + day.day


def _purge_cutoff(test_start: date, hold_days: int) -> int:
    # 交易日折算自然日（约 7/5），再多留 10 天缓冲
    return _to_int(test_start - timedelta(days=math.ceil(hold_days * 1.4) + 10))


def _load_rows(cfg: CrawlerConfig) -> pd.DataFrame:
    root = cfg.data_dir / "strategy_tracks"
    names_path, cache = root / "stock_trades_names.json", root / "stock_trades.npy"
    if not cache.exists() or not names_path.exists():
        run_strategy_track_evidence(cfg, refresh_etf=False)
    names = json.loads(names_path.read_text(encoding="utf-8"))
    packed = np.load(cache)
    return pd.DataFrame({
        "strategy": np.asarray(names, dtype=object)[packed["strategy"]],
        "date": packed["date"],
        "net": packed["net"].astype("f8"),
    })


def _summary(rows: pd.DataFrame) -> dict[str, Any]:
    return _cell(rows.net, rows.date, "month") if not rows.empty else {"trades": 0, "periods": 0}


def walkforward(rows: pd.DataFrame, candidates: dict[str, int], baseline: str, last_year: int) -> dict[str, Any]:
    folds = []
    selected_parts = []
    for year in range(FIRST_TEST_YEAR, last_year + 1):
        start, end = date(year, 1, 1), date(year, 12, 31)
        test_mask = (rows.date >= _to_int(start)) & (rows.date <= _to_int(end))
        ranking = []
        for name, hold in candidates.items():
            train = rows[(rows.strategy == name) & (rows.date < _purge_cutoff(start, hold))]
            stats = _summary(train)
            if (stats["trades"] >= SELECTION["min_train_trades"]
                    and (stats.get("avg_net_return_pct") or -1) > 0
                    and stats.get("t_stat", 0) >= SELECTION["min_train_t"]):
                ranking.append((stats["t_stat"], name, stats))
        ranking.sort(reverse=True)
        base_test = _summary(rows[test_mask & (rows.strategy == baseline)])
        fold = {"test_year": year, "train_qualified": [r[1] for r in ranking], "baseline_test": base_test}
        if ranking:
            _, name, train_stats = ranking[0]
            test_rows = rows[test_mask & (rows.strategy == name)]
            test_stats = _summary(test_rows)
            fold.update({"selected": name, "train": train_stats, "test": test_stats})
            fold["beat_baseline"] = (test_stats.get("avg_net_return_pct") or -99) > (base_test.get("avg_net_return_pct") or -99)
            selected_parts.append(test_rows)
        else:
            fold.update({"selected": None, "test": {"trades": 0}, "note": "无候选达标，当年空仓"})
        folds.append(fold)

    traded = [f for f in folds if f["selected"] and f["test"].get("trades")]
    oos = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame(columns=rows.columns)
    aggregate = _summary(oos)
    positive = sum(1 for f in traded if (f["test"].get("avg_net_return_pct") or -1) > 0)
    beat = sum(1 for f in traded if f.get("beat_baseline"))
    checks = {
        "test_trades": aggregate["trades"] >= GATE["min_test_trades"],
        "oos_avg_positive": (aggregate.get("avg_net_return_pct") or -1) > 0,
        "oos_t": aggregate.get("t_stat", 0) >= GATE["min_t"],
        "positive_folds": bool(traded) and positive / len(traded) >= GATE["min_positive_fold_ratio"],
        "beat_baseline": bool(traded) and beat / len(traded) >= GATE["min_beat_baseline_ratio"],
    }
    return {
        "folds": folds,
        "aggregate_oos": aggregate,
        "traded_folds": len(traded),
        "positive_folds": positive,
        "beat_baseline_folds": beat,
        "checks": checks,
        "passed": all(checks.values()),
    }


def run_long_walkforward(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    rows = _load_rows(cfg)
    catalog = [entry for entry in build_catalog() if entry.track == TRACK_LONG and entry.source == "robust"]
    last_year = int(str(rows.date.max())[:4])
    groups = {}
    for key, spec in GROUPS.items():
        candidates = {e.name: e.hold_days for e in catalog if not e.baseline and e.hold_days >= spec["min_hold"]}
        groups[key] = {
            "label": spec["label"], "baseline": spec["baseline"], "candidates": sorted(candidates),
            **walkforward(rows, candidates, spec["baseline"], last_year),
        }
    payload = {
        "status": "complete",
        "walkforward_version": WALKFORWARD_VERSION,
        "updated_at": now_str(),
        "method": {
            "folds": f"按自然年，{FIRST_TEST_YEAR}–{last_year} 逐年做样本外",
            "train": "仅用测试年之前、并扣除持有期间隔的交易",
            "selection": SELECTION,
            "t_stat": "按月聚类",
            "gate": GATE,
            "per_trade_not_portfolio": "逐笔口径，未含同日容量约束",
            "latest_year_partial": f"{last_year} 年只含已完成退出的交易",
        },
        "groups": groups,
    }
    path = cfg.data_dir / "strategy_tracks/long_walkforward.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run_long_walkforward()
    for key, group in result["groups"].items():
        print(f"\n## {group['label']}  passed={group['passed']}  checks={group['checks']}")
        agg = group["aggregate_oos"]
        print(f"   OOS: trades={agg.get('trades')} avg={agg.get('avg_net_return_pct')} hit={agg.get('hit_rate')} "
              f"t={agg.get('t_stat')} months={agg.get('periods')} | positive_folds={group['positive_folds']}/{group['traded_folds']} "
              f"beat_baseline={group['beat_baseline_folds']}/{group['traded_folds']}")
        for fold in group["folds"]:
            test, base = fold["test"], fold["baseline_test"]
            print(f"   {fold['test_year']}: {fold['selected'] or '空仓':32s} "
                  f"train_t={(fold.get('train') or {}).get('t_stat')} test n={test.get('trades')} avg={test.get('avg_net_return_pct')} "
                  f"| baseline avg={base.get('avg_net_return_pct')}")
