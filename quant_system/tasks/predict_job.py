"""可验证走势预测任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.config.prediction_config import DEFAULT_HORIZON
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.factors.technical import compute_technical_factors
from quant_system.pipeline.kline_loader import load_kline_df, load_stock_context
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.pipeline.quality_gate import load_quality_map
from quant_system.prediction.verified import build_verified_prediction
from quant_system.storage.json_store import JsonStore
from quant_system.tasks.backtest_job import run_backtest_job
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def _load_backtest(store: JsonStore, code: str, strategy: str) -> dict | None:
    path = store.backtest_dir() / f"{code}_{strategy}.json"
    if path.exists():
        return store.read(path)
    return None


def _load_factors(store: JsonStore, code: str) -> dict | None:
    path = store.factors_dir() / f"{code}.json"
    if path.exists():
        return store.read(path)
    return None


def run_predict_job(
    codes: list[str] | None = None,
    strategy_name: str = "ma_cross",
    horizon: str = DEFAULT_HORIZON,
    days: int = 750,
    *,
    auto_backtest: bool = True,
    allow_warn_quality: bool = False,
) -> list[dict[str, Any]]:
    """生成可验证走势预测（默认 5d）。"""
    cfg = CrawlerConfig()
    api = AkShareAPI(cfg)
    store = JsonStore(DBConfig())
    quality_map = load_quality_map(store)

    if codes:
        stocks = [{"code": normalize_code(c), "name": ""} for c in codes]
    else:
        stocks = load_watchlist(cfg)

    if not stocks:
        logger.error("未配置自选股")
        return []

    results: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []

    for item in stocks:
        code = normalize_code(item["code"])
        try:
            backtest = _load_backtest(store, code, strategy_name)
            if not backtest and auto_backtest:
                logger.info("预测前自动回测 %s", code)
                run_backtest_job(
                    codes=[code], strategy_name=strategy_name,
                    days=days, allow_warn_quality=allow_warn_quality,
                )
                backtest = _load_backtest(store, code, strategy_name)

            if not backtest:
                logger.warning("预测跳过 %s: 缺少回测证据", code)
                continue

            df, meta = load_kline_df(code, api, cfg, store, prefer_api=True, days=days)
            ctx = load_stock_context(code, store)
            factor_payload = _load_factors(store, code)
            if factor_payload:
                factors = factor_payload.get("factors", {})
                data_version = factor_payload.get("data_version")
            else:
                factor_payload = compute_technical_factors(
                    df, code,
                    trade_date=ctx.get("trade_date"),
                    close_override=ctx.get("close_override"),
                    data_version=meta.get("data_version"),
                )
                factors = factor_payload["factors"]
                data_version = factor_payload.get("data_version")

            quality = quality_map.get(code, {})

            pred = build_verified_prediction(
                code, df, factors,
                backtest=backtest,
                quality=quality,
                horizon=horizon,
                data_version=data_version or meta.get("data_version"),
                trade_date=ctx.get("trade_date"),
                strategy_name=strategy_name,
            )
            store.save_prediction(code, pred)
            index.append({
                "code": code,
                "horizon": horizon,
                "direction": pred["direction"],
                "probability": pred["probability"],
                "confidence": pred["confidence"],
                "expected_return": pred["expected_return"],
            })
            results.append(pred)
            logger.info(
                "预测 %s %s: %s p=%.2f conf=%s",
                code, horizon, pred["direction"], pred["probability"], pred["confidence"],
            )
        except Exception as e:
            logger.error("预测 %s 失败: %s", code, e)

    if index:
        store.save_prediction_index(index, now_str())
    logger.info("predict 完成，共 %s 只", len(results))
    return results
