"""回测任务。"""

from __future__ import annotations

from typing import Any

from quant_system.backtest.engine import run_backtest
from quant_system.config.backtest_config import BacktestConfig
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.pipeline.kline_loader import load_kline_df
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.pipeline.quality_gate import is_backtest_eligible, load_quality_map
from quant_system.pipeline.quality_inspector import inspect_kline_df
from quant_system.storage.json_store import JsonStore
from quant_system.strategy.ma_cross import MACrossStrategy
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str
from quant_system.utils.trade_calendar import get_calendar

logger = get_logger(__name__)

STRATEGIES = {
    "ma_cross": MACrossStrategy,
}


def run_backtest_job(
    codes: list[str] | None = None,
    strategy_name: str = "ma_cross",
    days: int = 750,
    *,
    allow_warn_quality: bool = False,
    initial_cash: float = 100_000.0,
) -> list[dict[str, Any]]:
    """对自选股运行单策略日线回测。"""
    cfg = CrawlerConfig()
    api = AkShareAPI(cfg)
    store = JsonStore(DBConfig())
    bt_cfg = BacktestConfig(initial_cash=initial_cash, strategy_name=strategy_name)
    quality_map = load_quality_map(store)
    cal = get_calendar()

    strat_cls = STRATEGIES.get(strategy_name)
    if not strat_cls:
        raise ValueError(f"未知策略: {strategy_name}，可选: {list(STRATEGIES)}")

    if codes:
        stocks = [{"code": normalize_code(c), "name": ""} for c in codes]
    else:
        stocks = load_watchlist(cfg)

    if not stocks:
        logger.error("未配置自选股")
        return []

    strategy = strat_cls()
    results: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []

    for item in stocks:
        code = normalize_code(item["code"])
        try:
            df, meta = load_kline_df(
                code, api, cfg, store, prefer_api=True, days=days,
            )
            if len(df) < 60:
                logger.warning("回测跳过 %s: K 线不足 %s 根", code, len(df))
                continue

            quality = quality_map.get(code) or inspect_kline_df(code, df, calendar=cal)
            if not is_backtest_eligible(quality, allow_warn=allow_warn_quality):
                logger.warning(
                    "回测跳过 %s: quality_score=%s（需 >=90 或 --allow-warn）",
                    code, quality.get("quality_score"),
                )
                continue

            result = run_backtest(
                df, strategy, bt_cfg,
                code=code,
                data_version=meta.get("data_version"),
                quality_score=quality.get("quality_score"),
            )
            store.save_backtest(code, strategy_name, result)
            m = result["metrics"]
            index.append({
                "code": code,
                "strategy": strategy_name,
                "annual_return_pct": m.get("annual_return_pct"),
                "max_drawdown_pct": m.get("max_drawdown_pct"),
                "sharpe_ratio": m.get("sharpe_ratio"),
                "win_rate_pct": m.get("win_rate_pct"),
            })
            results.append(result)
            logger.info(
                "回测 %s [%s]: 年化=%s%% 回撤=%s%% 夏普=%s",
                code, strategy_name,
                m.get("annual_return_pct"), m.get("max_drawdown_pct"), m.get("sharpe_ratio"),
            )
        except Exception as e:
            logger.error("回测 %s 失败: %s", code, e)

    if index:
        store.save_backtest_index(index, now_str())
    logger.info("backtest 完成，共 %s 只", len(results))
    return results
