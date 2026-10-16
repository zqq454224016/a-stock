"""自选股分析采集任务。"""

from __future__ import annotations

import gzip
import json
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.tickflow_api import create_market_data_api
from quant_system.factors.signal import compute_primary_signal
from quant_system.factors.technical import compute_technical_factors
from quant_system.pipeline.adjuster import apply_adjustment
from quant_system.pipeline.cleaner import clean_kline_df
from quant_system.pipeline.cross_source import run_cross_source_check
from quant_system.pipeline.kline_loader import make_data_version
from quant_system.pipeline.normalizer import normalize_code, normalize_kline_df, to_symbol
from quant_system.pipeline.kline_merge import merge_spot_into_daily_kline
from quant_system.pipeline.quality_gate import factor_block_reason
from quant_system.pipeline.quality_inspector import inspect_kline_df
from quant_system.pipeline.stock_analyzer import build_stock_analysis
from quant_system.pipeline.validator import validate_kline_df
from quant_system.storage.json_store import JsonStore
from quant_system.tasks.factor_utils import save_composite_factors
from quant_system.tasks.runtime import resolve_stock_items, run_for_items
from quant_system.utils.logger import get_logger
from quant_system.utils.trade_calendar import get_calendar

logger = get_logger(__name__)

def _save_full_history(code: str, df: Any, cfg: CrawlerConfig) -> None:
    """研究历史独立压缩落盘，页面股票 JSON 只保留展示窗口。"""
    path = cfg.data_dir / "history" / f"{code}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    rows = json.loads(df.to_json(orient="records", date_format="iso"))
    with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=5) as stream:
        json.dump(rows, stream, ensure_ascii=False, separators=(",", ":"))
    temporary.replace(path)


def _process_daily_stock(
    item: dict[str, Any],
    api: Any,
    store: JsonStore,
    cfg: CrawlerConfig,
    cal: Any,
    spot_map: dict[str, dict],
    prefetched: dict[str, tuple[Any, str]] | None = None,
) -> dict[str, Any] | None:
    code = normalize_code(item["code"])
    name = item.get("name", "")
    symbol = to_symbol(code)
    try:
        logger.info("采集个股 %s (%s)", code, name or symbol)
        if prefetched is not None:
            if code not in prefetched:
                raise RuntimeError("批量日 K 未返回该标的")
            raw_df, daily_source = prefetched[code]
        else:
            raw_df, daily_source = api.fetch_daily_hist(symbol, adjust="qfq")
        df = normalize_kline_df(raw_df, code, days=cfg.research_hist_days)
        df = clean_kline_df(df)
        df = apply_adjustment(df, adj_type="qfq")

        spot = spot_map.get(code)
        df, merge_meta = merge_spot_into_daily_kline(df, spot, calendar=cal)
        validate_kline_df(df)
        _save_full_history(code, df, cfg)

        cross_meta = run_cross_source_check(api, cfg, symbol, code, df, daily_source)
        quality = inspect_kline_df(code, df, calendar=cal, cross_source=cross_meta)
        data = build_stock_analysis(code, name, df, spot)
        data["daily_kline_source"] = daily_source
        data["kline_source"] = f"{daily_source}+spot" if merge_meta.get("kline_merged") else daily_source
        data.update(merge_meta)
        data["quality"] = {
            k: quality[k] for k in (
                "status", "quality_score", "missing_rate", "duplicate_count",
                "cross_source_diff", "factor_eligible", "issues", "checked_at",
            ) if k in quality
        }
        data["data_version"] = make_data_version(code, df)
        data["source"] = api.source_name
        data["history_rows"] = len(df)
        data["history_artifact"] = f"assets/data/history/{code}.json.gz"
        data["kline"] = data.get("kline", [])[-cfg.stock_hist_days:]

        block = factor_block_reason(quality)
        if block:
            logger.warning("因子跳过 %s: %s", code, block)
            data["factors"] = None
        else:
            close_override = float(spot["close"]) if spot else None
            factor_payload = compute_technical_factors(
                df, code,
                trade_date=data["trade_date"],
                close_override=close_override,
                data_version=data["data_version"],
            )
            composite = save_composite_factors(code, data["trade_date"], factor_payload, store)
            data["factors"] = composite["factors"]
            signal_payload = compute_primary_signal(
                composite["factors"], code, data["trade_date"],
            )
            data["primary_signal"] = signal_payload
            store.save_signal(code, signal_payload)

        store.save_stock_analysis(code, data)
        return {
            "code": code,
            "name": data["name"],
            "trade_date": data["trade_date"],
            "close": data["quote"]["close"],
            "change_pct": data["quote"]["change_pct"],
            "trend": data["analysis"]["trend"],
            "quality_score": quality.get("quality_score"),
            "primary_signal": (data.get("primary_signal") or {}).get("signal"),
            "artifact": f"assets/data/stocks/{code}.json",
        }
    except Exception as e:
        logger.error("个股 %s 失败: %s", code, e)
        return None


def run_daily_stock(
    codes: list[str] | None = None,
    *,
    items: list[dict[str, Any]] | None = None,
    batch_history: bool = False,
) -> list[dict]:
    cfg = CrawlerConfig()
    api = create_market_data_api(cfg)
    store = JsonStore(DBConfig())
    cal = get_calendar()

    full_market_run = items is None and not codes
    if full_market_run:
        from quant_system.tasks.universe_job import load_tickflow_universe, sync_tickflow_universe
        stocks = load_tickflow_universe(cfg) or sync_tickflow_universe(cfg)
    else:
        stocks = items if items is not None else resolve_stock_items(cfg, codes=codes, reason="个股采集", research_only=False)
    if not stocks:
        logger.error("全市场股票池为空，请先同步 TickFlow 股票清单")
        return []

    codes_list = [normalize_code(item["code"]) for item in stocks]
    # 全市场历史回填会以小批次反复调用本函数。若每批都请求一次实时行情，
    # 仅几十只股票就会耗尽 quotes 的分钟额度；历史任务也不应依赖盘中快照。
    # 全市场实时数据由独立的 public_quote_merge 任务批量获取和审计。
    spot_map = {} if batch_history else api.fetch_spot_map(codes=codes_list)
    prefetched = None
    if (full_market_run or batch_history) and hasattr(api, "fetch_daily_hist_batch"):
        logger.info("全市场日 K 使用 TickFlow 批量接口：%s 只", len(codes_list))
        prefetched = api.fetch_daily_hist_batch(codes_list, adjust="qfq")
        logger.info("TickFlow 批量日 K 返回：%s/%s 只", len(prefetched), len(codes_list))

    worker = lambda item: _process_daily_stock(item, api, store, cfg, cal, spot_map, prefetched)
    def save_index(rows: list[dict], timestamp: str) -> None:
        if full_market_run:
            store.save_stock_index(rows, timestamp)
            return
        index_path = cfg.stock_data_dir / "index.json"
        existing: list[dict] = []
        if index_path.exists():
            try:
                existing = store.read(index_path).get("stocks") or []
            except (OSError, ValueError, TypeError):
                existing = []
        by_code = {str(row.get("code")): row for row in existing if row.get("code")}
        by_code.update({str(row.get("code")): row for row in rows if row.get("code")})
        store.save_stock_index(list(by_code.values()), timestamp)

    index = run_for_items(
        cfg=cfg,
        items=stocks,
        worker=worker,
        label="个股采集",
        empty_message="全市场股票池为空，请先同步 TickFlow 股票清单",
        on_success=save_index,
        save_when_empty=False,
    )

    logger.info("个股采集完成，共 %s 只", len(index))
    return index
