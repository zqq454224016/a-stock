"""尾盘进、次日出：全市场并行回测、预登记门禁与前向影子评估。"""

from __future__ import annotations

import gzip
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.strategy.robust_iteration import TRANSACTION_FEE_RATE, slippage_rate
from quant_system.strategy.tail_overnight import (
    DAILY_TOP_K,
    GATE,
    HOLDOUT_TRADE_DAYS,
    LIMIT_MOVE,
    SPECS,
    STAMP_TAX_RATE,
    TAIL_SOURCE_ID,
    gate,
    summarize,
    trades,
)
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str

RESEARCH_VERSION = "1.0.0"
FORWARD_MIN_DAYS = 20
FORWARD_MIN_TRADES = 30


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


def load_history(cfg: CrawlerConfig, code: str) -> pd.DataFrame | None:
    path = cfg.data_dir / "history" / f"{code}.json.gz"
    if not path.exists():
        return None
    try:
        frame = pd.DataFrame(json.load(gzip.open(path, "rt", encoding="utf-8")))
    except (OSError, ValueError):
        return None
    if frame.empty or "close" not in frame:
        return None
    frame["date"] = frame["date"].astype(str).str[:10]
    return frame.sort_values("date").reset_index(drop=True)


def _universe(cfg: CrawlerConfig) -> list[tuple[str, str]]:
    rows = []
    for path in (cfg.data_dir / "stocks").glob("*.json"):
        if path.stem == "index" or not is_research_stock_code(path.stem):
            continue
        try:
            name = json.loads(path.read_text(encoding="utf-8")).get("name") or path.stem
        except (OSError, ValueError):
            continue
        if "ST" in str(name).upper():
            continue
        rows.append((path.stem, str(name)))
    return sorted(rows)


def _one(cfg: CrawlerConfig, code: str) -> pd.DataFrame:
    frame = load_history(cfg, code)
    if frame is None or len(frame) < 80:
        return pd.DataFrame()
    parts = [trades(frame, spec, code) for spec in SPECS]
    parts = [part for part in parts if not part.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _regime_by_prior_day(cfg: CrawlerConfig) -> tuple[list[str], dict[str, str]]:
    items = (_read(cfg.data_dir / "market_regime/five_year.json").get("items") or [])
    items = sorted((row for row in items if row.get("date")), key=lambda row: row["date"])
    dates = [str(row["date"]) for row in items]
    prior: dict[str, str] = {}
    for index in range(1, len(items)):
        # 尾盘决策时只确定知道前一交易日的市场状态。
        prior[dates[index]] = str(items[index - 1].get("regime") or "unknown")
    return dates, prior


def _forward_shadow(cfg: CrawlerConfig, root: Path) -> dict[str, dict[str, Any]]:
    """读取不可覆盖的尾盘账本，用已落地的次日K线计算实盘口径收益。"""
    ledger_dir = root / "shadow"
    stats: dict[str, list[float]] = {}
    days: dict[str, set[str]] = {}
    pending = 0
    cache: dict[str, pd.DataFrame | None] = {}
    for path in sorted(ledger_dir.glob("*.json")):
        ledger = _read(path)
        trade_date = str(ledger.get("trade_date") or path.stem)
        for pick in ledger.get("picks") or []:
            code = str(pick.get("code") or "")
            if code not in cache:
                cache[code] = load_history(cfg, code)
            frame = cache[code]
            if frame is None:
                pending += 1
                continue
            index = frame.index[frame["date"] == trade_date]
            if len(index) == 0 or index[0] + 1 >= len(frame):
                pending += 1
                continue
            today, nxt = frame.iloc[index[0]], frame.iloc[index[0] + 1]
            # 实际成交在收盘集合竞价，用落地后的收盘价而不是决策时的盘中价。
            entry = float(today.close)
            exit_price = float(nxt.open if pick.get("exit") == "next_open" else nxt.close)
            if float(nxt.open) / float(today.close) - 1 <= -LIMIT_MOVE:
                exit_price = min(float(nxt.open), float(nxt.close))
            slip = slippage_rate(float(today.get("amount") or 0))
            net = exit_price * (1 - slip) / (entry * (1 + slip)) - 1 - 2 * TRANSACTION_FEE_RATE - STAMP_TAX_RATE
            spec = str(pick.get("spec"))
            stats.setdefault(spec, []).append(net)
            days.setdefault(spec, set()).add(trade_date)
    result: dict[str, dict[str, Any]] = {}
    for spec, values in stats.items():
        series = pd.Series(values)
        result[spec] = {
            "days": len(days[spec]),
            "trades": int(series.size),
            "hit_rate": round(float((series > 0).mean()), 4),
            "avg_net_return_pct": round(float(series.mean() * 100), 4),
        }
    result["_pending_picks"] = {"count": pending}
    return result


def _status(spec_name: str, diag: dict[str, Any], forward: dict[str, Any], approved: set[str]) -> str:
    fwd = forward.get(spec_name) or {}
    forward_ok = (
        fwd.get("days", 0) >= FORWARD_MIN_DAYS
        and fwd.get("trades", 0) >= FORWARD_MIN_TRADES
        and (fwd.get("avg_net_return_pct") or -99) > 0
        and (fwd.get("hit_rate") or 0) >= 0.5
    )
    if diag.get("diagnostic_passed") and forward_ok:
        return "formal" if spec_name in approved else "forward_passed_await_manual"
    if diag.get("diagnostic_passed"):
        return "research_candidate"
    return "observation_only"


def run_tail_overnight_iteration(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "tail_overnight"
    universe = _universe(cfg)
    with ThreadPoolExecutor(max_workers=max(2, cfg.fetch_workers), thread_name_prefix="tail") as pool:
        frames = [frame for frame in pool.map(lambda item: _one(cfg, item[0]), universe) if not frame.empty]
    all_trades = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["date", "code", "spec", "net", "score", "limit_down_exit"]
    )

    calendar, prior_regime = _regime_by_prior_day(cfg)
    if not calendar:
        calendar = sorted(all_trades["date"].unique().tolist())
    holdout_start = calendar[-HOLDOUT_TRADE_DAYS] if len(calendar) > HOLDOUT_TRADE_DAYS else calendar[0]
    dev_dates = [d for d in calendar if d < holdout_start]
    dev_mid = dev_dates[len(dev_dates) // 2] if dev_dates else holdout_start
    all_trades["regime_prior"] = all_trades["date"].map(prior_regime).fillna("unknown")

    forward = _forward_shadow(cfg, root)
    approved = set((_read(root / "approval.json").get("approved_specs") or []))
    specs_out: dict[str, Any] = {}
    for spec in SPECS:
        rows = all_trades[all_trades.spec == spec.name]
        dev1 = rows[rows.date < dev_mid]
        dev2 = rows[(rows.date >= dev_mid) & (rows.date < holdout_start)]
        hold = rows[rows.date >= holdout_start]
        segments = [summarize(dev1), summarize(dev2)]
        holdout = summarize(hold)
        diag = gate(segments, holdout)
        by_regime = {
            regime: summarize(part)
            for regime, part in hold.groupby("regime_prior")
        }
        specs_out[spec.name] = {
            "label": spec.label,
            "mode": spec.mode,
            "exit": spec.exit,
            "development": segments,
            "holdout": holdout,
            "holdout_by_prior_regime": by_regime,
            "gate": diag,
            "forward_shadow": forward.get(spec.name) or {"days": 0, "trades": 0},
            "status": _status(spec.name, diag, forward, approved),
        }

    def dev_strength(name: str) -> float:
        return sum(
            float((seg.get("portfolio") or {}).get("total_return_pct") or -99)
            for seg in specs_out[name]["development"]
        )

    dev_ok = [name for name, item in specs_out.items() if item["gate"]["dev_passed"]]
    selected = max(dev_ok, key=dev_strength) if dev_ok else None
    payload = {
        "status": "complete",
        "research_version": RESEARCH_VERSION,
        "source_id": TAIL_SOURCE_ID,
        "updated_at": now_str(),
        "universe": len(universe),
        "trade_count": int(len(all_trades)),
        "method": {
            "entry": "T日收盘集合竞价（收盘价）",
            "exit": "T+1 开盘或收盘（按策略）",
            "costs": {
                "commission_one_way": TRANSACTION_FEE_RATE,
                "stamp_tax_sell": STAMP_TAX_RATE,
                "slippage": "按T日成交额分档，买卖各一次",
            },
            "excluded": ["收盘涨停/一字板（买不进）", "ST", "创业板/科创板/北交所", "次日停牌"],
            "limit_down_exit": "次日开盘跌停视为卖不出，按开盘与收盘中更差价成交",
            "portfolio": f"每日按分数取前{DAILY_TOP_K}只等权，资金不足部分闲置",
            "segments": {"development_split": dev_mid, "holdout_start": holdout_start,
                         "holdout_trade_days": HOLDOUT_TRADE_DAYS},
            "selection": "只用开发段挑选；最近60日只做诊断，不参与选择",
            "regime": "按前一交易日市场状态分组，仅诊断",
            "gate": GATE,
            "promotion": (
                f"诊断过线 → 研究候选；前向影子≥{FORWARD_MIN_DAYS}个交易日且≥{FORWARD_MIN_TRADES}笔、"
                "均收益>0、命中率≥50% → 待人工确认；approval.json 列入后才算正式推荐"
            ),
        },
        "selected_by_development": selected,
        "specs": specs_out,
        "forward_shadow_pending": (forward.get("_pending_picks") or {}).get("count", 0),
        "limitations": [
            "日线代理：信号用收盘价判断，实盘需在14:50前后用近似收盘价决策",
            "收盘集合竞价成交价与成交量无法从日线完全还原",
            "前复权价格；除权当日的实盘价格与复权价有差异",
        ],
    }
    _write(root / "latest.json", payload)
    return payload


if __name__ == "__main__":
    result = run_tail_overnight_iteration()
    print(json.dumps({
        "trade_count": result.get("trade_count"),
        "selected_by_development": result.get("selected_by_development"),
        "specs": {
            name: {
                "status": item["status"],
                "dev": [(seg.get("trades"), seg.get("avg_net_return_pct"),
                         (seg.get("portfolio") or {}).get("total_return_pct")) for seg in item["development"]],
                "holdout": (item["holdout"].get("trades"), item["holdout"].get("hit_rate"),
                            item["holdout"].get("avg_net_return_pct"),
                            (item["holdout"].get("portfolio") or {}).get("total_return_pct"),
                            (item["holdout"].get("portfolio") or {}).get("max_drawdown_pct")),
                "failed": item["gate"]["failed"],
            }
            for name, item in (result.get("specs") or {}).items()
        },
    }, ensure_ascii=False, indent=1))
