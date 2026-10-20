"""四轨策略归并 + 分市场状态证据矩阵。

对每个策略逐笔回放，按“决策当时可知的市场状态”分组，只用开发段（最近60个交易日之前）
判断某策略在某状态下是否有正边；最近60日仅作诊断。输出每个状态下各轨道可用的策略，
供市场状态路由读取。
"""

from __future__ import annotations

import gzip
import json
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.etf_history import (
    ETF_POOL,
    load_etf_history,
    refresh_etf_history,
    cached_inverse_scan,
)
from quant_system.strategy import aggressive_board, overnight, tail_overnight
from quant_system.strategy.defensive_etf import REVERSAL_RULES, reversal_setup
from quant_system.strategy.defensive_etf import SPECS as DEFENSIVE_SPECS
from quant_system.strategy.defensive_etf import trades as defensive_trades
from quant_system.strategy.long_term_quality import attach_point_in_time_quality
from quant_system.strategy.robust_iteration import CANDIDATES, features, trades as robust_trades
from quant_system.strategy.track_catalog import TRACKS, build_catalog
from quant_system.tasks.strategy_job import _read_stock
from quant_system.tasks.tail_overnight_iteration_job import load_history
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str

EVIDENCE_VERSION = "1.0.0"
HOLDOUT_TRADE_DAYS = 60
REGIMES = ("rising", "range", "falling", "extreme_risk")
# 个股约60个策略×4个状态，多重检验下用更严格的 t 值；ETF 策略少、样本少。
GATE = {
    "stock": {"min_trades": 100, "min_periods": 20, "min_t": 3.0},
    "etf": {"min_trades": 15, "min_periods": 10, "min_t": 2.0},
}

_REGIMES: dict[str, str] = {}
_PRIOR: dict[str, str] = {}
_DATA_DIR = ""
_HIST_DAYS = 2500

STRATEGY_NAMES = [entry.name for entry in build_catalog()]
_STRATEGY_INDEX = {name: index for index, name in enumerate(STRATEGY_NAMES)}
REGIME_CODES = REGIMES + ("unknown",)
_REGIME_INDEX = {name: index for index, name in enumerate(REGIME_CODES)}


def _date_int(value: str) -> int:
    return int(value[:10].replace("-", ""))


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def _init(regimes: dict[str, str], prior: dict[str, str], data_dir: str, hist_days: int) -> None:
    global _REGIMES, _PRIOR, _DATA_DIR, _HIST_DAYS
    _REGIMES, _PRIOR, _DATA_DIR, _HIST_DAYS = regimes, prior, data_dir, hist_days


def _rows(strategy: str, dates: list[str], nets: list[float], regimes: list[str]) -> list[tuple]:
    sid = _STRATEGY_INDEX[strategy]
    unknown = _REGIME_INDEX["unknown"]
    return [
        (sid, _date_int(d), float(n), _REGIME_INDEX.get(r, unknown))
        for d, n, r in zip(dates, nets, regimes) if np.isfinite(n)
    ]


def _pack(rows: list[tuple]) -> np.ndarray:
    return np.array(rows, dtype=[("strategy", "i2"), ("date", "i4"), ("net", "f4"), ("regime", "i1")])


def _next_open_trades(frame: pd.DataFrame, mask: pd.Series, hold: int, cost: float) -> tuple[list, list]:
    opens = pd.to_numeric(frame["open"], errors="coerce").to_numpy()
    dates = frame["date"].astype(str).str[:10].to_numpy()
    out_d, out_n = [], []
    for i in np.flatnonzero(mask.fillna(False).to_numpy()):
        if i + 1 + hold >= len(frame) or not (opens[i + 1] > 0):
            continue
        out_d.append(dates[i])
        out_n.append(opens[i + 1 + hold] / opens[i + 1] - 1 - cost)
    return out_d, out_n


def _stock_job(path_str: str) -> np.ndarray:
    return _pack(_stock_rows(path_str))


def _stock_rows(path_str: str) -> list[tuple]:
    path = Path(path_str)
    out: list[tuple] = []
    try:
        stock, frame = _read_stock(path)
        if "ST" in str(stock.get("name") or "").upper() or len(frame) < 500:
            return out
        prepared = attach_point_in_time_quality(features(frame.tail(_HIST_DAYS)), Path(_DATA_DIR), path.stem)
        date_col = "date" if "date" in prepared.columns else "trade_date"
        signal_dates = prepared[date_col].astype(str).str[:10].to_numpy()
        execution: dict[str, dict[str, Any]] = {}
        execution_path = Path(_DATA_DIR) / "execution_history" / f"{path.stem}.json.gz"
        if execution_path.exists():
            with gzip.open(execution_path, "rt", encoding="utf-8") as stream:
                execution = {str(r.get("date"))[:10]: r for r in json.load(stream) if isinstance(r, dict)}
        for candidate in CANDIDATES:
            result = robust_trades(prepared, candidate, _REGIMES, execution, code=path.stem, prepared=True)
            if result.empty:
                continue
            dates = [signal_dates[i] for i in result["signal_at"].astype(int)]
            out += _rows(candidate.name, dates, result["net_return"].tolist(), [_REGIMES.get(d, "unknown") for d in dates])
    except Exception:
        pass
    try:
        history = load_history(CrawlerConfig(), path.stem)
        if history is None or len(history) < 80:
            return out
        for spec in tail_overnight.SPECS:
            result = tail_overnight.trades(history, spec, path.stem)
            if not result.empty:
                dates = result["date"].tolist()
                out += _rows(spec.name, dates, result["net"].tolist(), [_PRIOR.get(d, "unknown") for d in dates])
        for spec in overnight.SPECS:
            d, n = _next_open_trades(history, overnight.signal_mask(history, spec), 1, 2 * 0.00008 + 2 * 0.001)
            out += _rows(spec.name, d, n, [_REGIMES.get(x, "unknown") for x in d])
        for spec in aggressive_board.SPECS:
            d, n = _next_open_trades(
                history, aggressive_board.signal_mask(history, spec), spec.max_hold_days, 2 * 0.00008 + 2 * 0.001,
            )
            out += _rows(spec.name, d, n, [_REGIMES.get(x, "unknown") for x in d])
    except Exception:
        pass
    return out


def _cell(values: pd.Series, dates: pd.Series | None = None, cluster: str = "week") -> dict[str, Any]:
    """逐笔均值 + 按时间聚类的 t 值。

    同一时段数千只股票同涨同跌，逐笔 t 值会被横截面相关性放大；先求每个时段
    的平均收益，再在时段之间算 t 值。持有≥11日的策略按月聚类。
    """
    n = int(values.size)
    if n == 0:
        return {"trades": 0, "periods": 0}
    if dates is None:
        groups = pd.Series(values.to_numpy())
    else:
        stamp = pd.to_datetime(dates.astype(str), format="%Y%m%d")
        key = stamp.dt.to_period("M" if cluster == "month" else "W").to_numpy()
        groups = pd.Series(values.to_numpy()).groupby(key).mean()
    periods = int(groups.size)
    std = float(groups.std(ddof=1)) if periods > 1 else 0.0
    t_stat = float(groups.mean()) / (std / math.sqrt(periods)) if std > 0 else 0.0
    return {
        "trades": n,
        "periods": periods,
        "avg_net_return_pct": round(float(values.mean()) * 100, 4),
        "median_net_return_pct": round(float(values.median()) * 100, 4),
        "hit_rate": round(float((values > 0).mean()), 4),
        "period_hit_rate": round(float((groups > 0).mean()), 4),
        "t_stat": round(t_stat, 2),
    }


def _evaluate(rows: pd.DataFrame, catalog: dict[str, Any], calendar: list[str]) -> dict[str, Any]:
    cal = [_date_int(d) for d in calendar]
    holdout_index = len(cal) - HOLDOUT_TRADE_DAYS
    holdout_start = cal[holdout_index]
    # 2018-11 之前没有市场状态，不进入证据。
    rows = rows[rows.date >= cal[0]]
    results: dict[str, Any] = {}
    for name, part in rows.groupby("strategy", observed=True):
        entry = catalog.get(name)
        if entry is None:
            continue
        gate_cfg = GATE["etf" if entry.source == "defensive" else "stock"]
        purge_index = max(1, holdout_index - entry.hold_days - 1)
        dev = part[part.date < cal[purge_index]]
        dev_mid = cal[purge_index // 2]
        hold = part[part.date >= holdout_start]
        cluster = "month" if entry.hold_days >= 11 else "week"

        def cell(frame: pd.DataFrame) -> dict[str, Any]:
            return _cell(frame.net, frame.date, cluster)

        by_regime = {}
        for regime in REGIMES:
            in_regime = dev[dev.decision_regime == regime]
            early = cell(in_regime[in_regime.date < dev_mid])
            late = cell(in_regime[in_regime.date >= dev_mid])
            stats = cell(in_regime)
            passed = bool(
                stats["trades"] >= gate_cfg["min_trades"]
                and stats["periods"] >= gate_cfg["min_periods"]
                and stats.get("t_stat", 0) >= gate_cfg["min_t"]
                and (early.get("avg_net_return_pct") or -1) > 0
                and (late.get("avg_net_return_pct") or -1) > 0
            )
            hcell = cell(hold[hold.decision_regime == regime])
            by_regime[regime] = {
                "development": stats, "development_early": early, "development_late": late,
                "holdout": hcell, "evidence_passed": passed,
                "holdout_contradicts": bool(
                    passed and hcell["trades"] >= 20 and (hcell.get("avg_net_return_pct") or 0) < 0
                ),
            }
        results[name] = {
            "track": entry.track, "family": entry.family, "source": entry.source,
            "hold_days": entry.hold_days, "baseline": entry.baseline, "t_cluster": cluster,
            "all_development": cell(dev), "holdout": cell(hold), "by_regime": by_regime,
        }
    return results


def _families(strategies: dict[str, Any]) -> dict[str, Any]:
    """同族去重：保留开发段最强成员，其余标记为可合并/淘汰。"""
    families: dict[str, list[str]] = {}
    for name, item in strategies.items():
        families.setdefault(item["family"], []).append(name)
    report = {}
    for family, members in families.items():
        def strength(name: str) -> float:
            cell = strategies[name]["all_development"]
            return float(cell.get("t_stat") or -99)
        ranked = sorted(members, key=strength, reverse=True)
        any_edge = [m for m in members if any(c["evidence_passed"] for c in strategies[m]["by_regime"].values())]
        is_baseline = all(strategies[m]["baseline"] for m in members)
        report[family] = {
            "track": strategies[ranked[0]]["track"],
            "members": ranked,
            "keep": ranked[0],
            "merge_into_keep": ranked[1:],
            "has_regime_edge": any_edge,
            "action": "baseline" if is_baseline else "keep" if any_edge else "retire_or_research_only",
        }
    return report


def run_strategy_track_evidence(
    cfg: CrawlerConfig | None = None, *, refresh_etf: bool = True, reuse_stock_trades: bool = False,
) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "strategy_tracks"
    items = sorted(
        (r for r in (_read(cfg.data_dir / "market_regime/five_year.json").get("items") or []) if r.get("date")),
        key=lambda r: r["date"],
    )
    calendar = [str(r["date"]) for r in items]
    regimes = {str(r["date"]): str(r.get("regime") or "unknown") for r in items}
    prior = {calendar[i]: regimes[calendar[i - 1]] for i in range(1, len(calendar))}

    def retry(fn, attempts: int = 3) -> dict[str, Any]:
        last = ""
        for attempt in range(attempts):
            try:
                return fn()
            except Exception as exc:  # 公开接口偶发断连
                last = str(exc)[-200:]
                time.sleep(3 * (attempt + 1))
        return {"error": last}

    etf_refresh = retry(lambda: refresh_etf_history(cfg.data_dir)) if refresh_etf else {}
    inverse_scan = cached_inverse_scan(cfg.data_dir, refresh=refresh_etf)

    cache = root / "stock_trades.npy"
    cache_names = root / "stock_trades_names.json"
    paths = [
        str(p) for p in sorted((cfg.data_dir / "stocks").glob("*.json"))
        if p.stem != "index" and is_research_stock_code(p.stem)
    ]
    chunks: list[np.ndarray] = []
    names_match = cache_names.exists() and json.loads(cache_names.read_text(encoding="utf-8")) == STRATEGY_NAMES
    if reuse_stock_trades and cache.exists() and names_match:
        chunks.append(np.load(cache))
    else:
        workers = max(2, min(8, (os.cpu_count() or 4) - 1))
        with ProcessPoolExecutor(
            max_workers=workers, initializer=_init,
            initargs=(regimes, prior, str(cfg.data_dir), cfg.research_hist_days),
        ) as pool:
            for chunk in pool.map(_stock_job, paths, chunksize=16):
                if chunk.size:
                    chunks.append(chunk)
        if chunks:
            root.mkdir(parents=True, exist_ok=True)
            np.save(cache, np.concatenate(chunks))
            cache_names.write_text(json.dumps(STRATEGY_NAMES, ensure_ascii=False), encoding="utf-8")

    etfs = {code: load_etf_history(cfg.data_dir, code) for code in ETF_POOL}
    etf_rows: list[tuple] = []
    for spec in DEFENSIVE_SPECS:
        result = defensive_trades(spec, etfs, items)
        if not result.empty:
            etf_rows += _rows(spec.name, result["date"].tolist(), result["net"].tolist(),
                              result["decision_regime"].tolist())
    if etf_rows:
        chunks.append(_pack(etf_rows))

    packed = np.concatenate(chunks) if chunks else _pack([])
    rows = pd.DataFrame({
        "strategy": pd.Categorical.from_codes(packed["strategy"], STRATEGY_NAMES),
        "date": packed["date"],
        "net": packed["net"].astype("f8"),
        "decision_regime": pd.Categorical.from_codes(packed["regime"], REGIME_CODES),
    })
    catalog = {entry.name: entry for entry in build_catalog()}
    strategies = _evaluate(rows, catalog, calendar)

    current_regime = regimes.get(calendar[-1], "unknown") if calendar else "unknown"
    decision_regime = current_regime  # 今日收盘后决策下一交易日：用今日状态
    by_track: dict[str, Any] = {}
    for track in TRACKS:
        members = {n: s for n, s in strategies.items() if s["track"] == track}
        regime_view = {}
        for regime in REGIMES:
            eligible = sorted(
                (
                    {"strategy": n, **s["by_regime"][regime]["development"],
                     "holdout": s["by_regime"][regime]["holdout"],
                     "holdout_contradicts": s["by_regime"][regime]["holdout_contradicts"]}
                    for n, s in members.items()
                    if s["by_regime"][regime]["evidence_passed"] and not s["baseline"]
                ),
                key=lambda r: r.get("t_stat", 0), reverse=True,
            )
            regime_view[regime] = {"eligible": eligible[:8], "active": bool(eligible)}
        by_track[track] = {**TRACKS[track], "strategy_count": len(members), "by_regime": regime_view}

    current = {
        track: {
            "active": view["by_regime"].get(decision_regime, {}).get("active", False),
            "top": (view["by_regime"].get(decision_regime, {}).get("eligible") or [None])[0],
        }
        for track, view in by_track.items()
    }
    reversal_setups = {}
    for code in sorted({spec.instrument for spec in DEFENSIVE_SPECS if spec.kind == "reversal"}):
        frame = etfs.get(code)
        if frame is None or len(frame) < 20 or not items:
            continue
        work = frame.copy()
        work["ma20"] = work.close.rolling(20).mean()
        last = work.iloc[-1]
        window = [row for row in items if row["date"] <= last["date"]][-3:]
        reversal_setups[code] = {"date": last["date"], **reversal_setup(last, window)}
    payload = {
        "status": "complete",
        "evidence_version": EVIDENCE_VERSION,
        "updated_at": now_str(),
        "trade_rows": int(len(rows)),
        "calendar": {"first": calendar[0] if calendar else None, "last": calendar[-1] if calendar else None,
                     "holdout_start": calendar[-HOLDOUT_TRADE_DAYS] if len(calendar) > HOLDOUT_TRADE_DAYS else None},
        "method": {
            "regime_source": "market_regime/five_year.json（全市场广度与20日收益）",
            "decision_regime": "次日开盘入场用信号日状态；尾盘入场用前一日状态；超跌反转尾盘用当日数据决策",
            "selection": "只用开发段；开发段前后两半都须为正；最近60日只诊断",
            "gate": GATE,
            "multiple_testing": "个股策略约60个×4状态，t≥3 抑制偶然通过",
            "per_trade_not_portfolio": "证据是逐笔均值，不含同日容量约束；正式晋级仍须组合级门禁",
        },
        "regime_counts": {r: sum(1 for v in regimes.values() if v == r) for r in REGIMES},
        "current": {
            "regime": current_regime, "date": calendar[-1] if calendar else None, "tracks": current,
            "reversal_setups": reversal_setups, "reversal_rules": REVERSAL_RULES,
        },
        "tracks": by_track,
        "families": _families(strategies),
        "strategies": strategies,
        "etf": {
            "refresh": etf_refresh,
            "inverse_scan": {
                "etf_count": inverse_scan.get("etf_count"),
                "inverse_or_leveraged": inverse_scan.get("inverse_or_leveraged"),
                "error": inverse_scan.get("error"),
                "source": inverse_scan.get("source"),
                "scanned_at": inverse_scan.get("scanned_at"),
                "conclusion": (
                    "场内无反向/杠杆ETF，下跌市只能空仓或切换防守资产"
                    if inverse_scan.get("etf_count") and not inverse_scan.get("inverse_or_leveraged") else None
                ),
            },
        },
    }
    _write(root / "latest.json", payload)
    return payload


if __name__ == "__main__":
    import sys

    result = run_strategy_track_evidence(reuse_stock_trades="--reuse" in sys.argv)
    print(json.dumps({
        "trade_rows": result["trade_rows"],
        "current": result["current"],
        "inverse": result["etf"]["inverse_scan"],
        "active_by_regime": {
            track: {r: [e["strategy"] for e in v["eligible"]] for r, v in item["by_regime"].items()}
            for track, item in result["tracks"].items()
        },
    }, ensure_ascii=False, indent=1, default=str))
