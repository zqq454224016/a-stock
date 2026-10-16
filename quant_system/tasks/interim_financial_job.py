"""Point-in-time interim-report dataset used by recommendation evidence."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.tushare_api import TushareAPI
from quant_system.utils.time_utils import now_str


def _period(today: date | None = None) -> str:
    current = today or date.today()
    year = current.year if current.month >= 7 else current.year - 1
    return f"{year}0630"


def _iso(value: Any) -> str | None:
    text = str(value or "").replace("-", "")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 and text.isdigit() else None


def _latest_by_symbol(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("ts_code") or "")
        if not symbol:
            continue
        current = result.get(symbol)
        row_date = str(row.get("f_ann_date") or row.get("ann_date") or "")
        current_date = str((current or {}).get("f_ann_date") or (current or {}).get("ann_date") or "")
        if current is None or row_date >= current_date:
            result[symbol] = row
    return result


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


PUBLIC_FIELD_MAP = {
    "每股收益": "eps",
    "营业总收入-营业总收入": "revenue",
    "营业总收入-同比增长": "revenue_yoy_pct",
    "营业总收入-季度环比增长": "revenue_qoq_pct",
    "净利润-净利润": "net_profit",
    "净利润-同比增长": "net_profit_yoy_pct",
    "净利润-季度环比增长": "net_profit_qoq_pct",
    "每股净资产": "book_value_per_share",
    "净资产收益率": "roe_pct",
    "每股经营现金流量": "operating_cashflow_per_share",
    "销售毛利率": "gross_margin_pct",
    "所处行业": "industry",
}
RESEARCH_CODE_PREFIXES = ("000", "001", "002", "003", "600", "601", "603", "605")
FINANCIAL_UNIVERSE_SCOPE = "ordinary_a_share_main_boards_v1"


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_value(value.item())
    return value


def build_public_quarterly_reports(
    rows: list[dict[str, Any]],
    output_dir: Path,
    *,
    period: str,
    as_of: date | None = None,
    write_current: bool = True,
) -> dict[str, Any]:
    """Build PIT-safe quarterly facts; future-dated records stay quarantined."""
    cutoff = as_of or date.today()
    report_period = _iso(period)
    accepted: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    seen: set[str] = set()
    fetched_at = now_str()
    for raw in rows:
        code = str(raw.get("股票代码") or "").zfill(6)
        announced = _iso(raw.get("最新公告日期"))
        if (
            len(code) != 6
            or not code.isdigit()
            or not code.startswith(RESEARCH_CODE_PREFIXES)
            or not announced
        ):
            continue
        metrics = {target: _json_value(raw.get(source)) for source, target in PUBLIC_FIELD_MAP.items()}
        canonical = json.dumps(
            {"code": code, "period": report_period, "announced": announced, "metrics": metrics},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        version_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
        if version_id in seen:
            continue
        seen.add(version_id)
        item = {
            "dataset": "financial.quarterly_summary",
            "schema_version": "1.0.0",
            "source": "eastmoney_public_via_akshare",
            "code": code,
            "name": str(raw.get("股票简称") or code),
            "report_period": report_period,
            "published_at": f"{announced}T00:00:00+08:00",
            "known_at": f"{announced}T23:59:59+08:00",
            "fetched_at": fetched_at,
            "version_id": version_id,
            "metrics": metrics,
        }
        if announced > cutoff.isoformat():
            item["quarantine_reason"] = "published_after_as_of"
            quarantined.append(item)
        else:
            accepted.append(item)

    by_code: dict[str, list[dict[str, Any]]] = {}
    for item in accepted:
        by_code.setdefault(item["code"], []).append(item)
    if write_current:
        for code, versions in by_code.items():
            latest = max(versions, key=lambda row: (row["published_at"], row["version_id"]))
            _write(output_dir / f"{code}.json", {
                **latest,
                "status": "available",
                "versions_in_period": len(versions),
                "limitations": ["季度摘要，不替代完整财务三表", "公告日当日不参与交易信号"],
                "updated_at": fetched_at,
            })

    history_dir = output_dir.parent / "point_in_time_financials/periods"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{period}.json.gz"
    with gzip.open(history_path, "wt", encoding="utf-8") as stream:
        json.dump({
            "period": report_period,
            "as_of": cutoff.isoformat(),
            "universe_scope": FINANCIAL_UNIVERSE_SCOPE,
            "accepted": accepted,
            "quarantined": quarantined,
        }, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    manifest = {
        "dataset": "financial.interim_report",
        "schema_version": "2.0.0",
        "period": report_period,
        "as_of": cutoff.isoformat(),
        "source": "eastmoney_public_via_akshare",
        "universe_scope": FINANCIAL_UNIVERSE_SCOPE,
        "status": "partial" if accepted else "unavailable",
        "count": len(by_code),
        "version_count": len(accepted),
        "quarantined_future_count": len(quarantined),
        "history_artifact": str(history_path.relative_to(output_dir.parent)),
        "source_errors": {},
        "limitations": ["公开季度摘要主干", "最终候选完整三表需另行补充并以巨潮公告核验"],
        "updated_at": fetched_at,
    }
    if write_current:
        _write(output_dir / "index.json", manifest)
        _write(output_dir.parent / "point_in_time_financials/status.json", manifest)
    return manifest


def fetch_public_quarterly(period: str) -> list[dict[str, Any]]:
    import akshare as ak

    return ak.stock_yjbb_em(date=period).to_dict(orient="records")


def _quarter_periods(today: date | None = None, years: int = 5) -> list[str]:
    current = today or date.today()
    start_year = current.year - years
    values = [
        f"{year}{month_day}"
        for year in range(start_year, current.year + 1)
        for month_day in ("0331", "0630", "0930", "1231")
    ]
    return [value for value in values if value <= current.strftime("%Y%m%d")]


def _valid_period_artifact(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 100:
        return False
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
        return payload.get("universe_scope") == FINANCIAL_UNIVERSE_SCOPE
    except (OSError, ValueError, TypeError):
        return False


def build_point_in_time_financial_index(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "point_in_time_financials"
    by_code: dict[str, list[dict[str, Any]]] = {}
    period_count = 0
    for path in sorted((root / "periods").glob("*.json.gz")):
        if not _valid_period_artifact(path):
            continue
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
        period_count += 1
        for item in payload.get("accepted") or []:
            by_code.setdefault(item["code"], []).append(item)
    output = root / "by_code"
    output.mkdir(parents=True, exist_ok=True)
    version_count = 0
    for code, versions in by_code.items():
        versions.sort(key=lambda row: (row["known_at"], row["report_period"], row["version_id"]))
        version_count += len(versions)
        with gzip.open(output / f"{code}.json.gz", "wt", encoding="utf-8") as stream:
            json.dump(versions, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    status = {
        "status": "complete" if period_count >= 20 else "partial",
        "universe_scope": FINANCIAL_UNIVERSE_SCOPE,
        "period_count": period_count,
        "code_count": len(by_code),
        "version_count": version_count,
        "updated_at": now_str(),
    }
    _write(root / "index_status.json", status)
    return status


def load_financial_as_of(data_dir: Path, code: str, as_of: str) -> dict[str, Any] | None:
    path = data_dir / "point_in_time_financials/by_code" / f"{str(code).zfill(6)}.json.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        versions = json.load(stream)
    eligible = [item for item in versions if str(item.get("known_at") or "") <= as_of]
    if not eligible:
        return None
    return max(eligible, key=lambda row: (row["report_period"], row["known_at"], row["version_id"]))


def run_public_financial_backfill(
    cfg: CrawlerConfig | None = None,
    *,
    periods: list[str] | None = None,
) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "point_in_time_financials"
    period_dir = root / "periods"
    requested = periods or _quarter_periods()
    completed: list[str] = []
    errors: dict[str, str] = {}
    for period in requested:
        artifact = period_dir / f"{period}.json.gz"
        if _valid_period_artifact(artifact):
            completed.append(period)
            continue
        try:
            rows = fetch_public_quarterly(period)
            build_public_quarterly_reports(
                rows, cfg.data_dir / "interim_reports",
                period=period, as_of=date.today(), write_current=False,
            )
            completed.append(period)
        except Exception as exc:
            errors[period] = str(exc)[:500]
        _write(root / "backfill_status.json", {
            "status": "running",
            "requested_periods": requested,
            "completed_periods": completed,
            "errors": errors,
            "updated_at": now_str(),
        })
    payload = {
        "status": "complete" if len(completed) == len(requested) else "partial",
        "requested_periods": requested,
        "completed_periods": completed,
        "period_count": len(completed),
        "errors": errors,
        "updated_at": now_str(),
    }
    _write(root / "backfill_status.json", payload)
    if payload["status"] == "complete":
        payload["index"] = build_point_in_time_financial_index(cfg)
        _write(root / "backfill_status.json", payload)
    return payload


def launch_public_financial_backfill(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "point_in_time_financials"
    pid_path = root / "backfill.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            return {"status": "already_running", "pid": pid}
        except (OSError, ValueError):
            pid_path.unlink(missing_ok=True)
    log = (root / "backfill.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    stream = log.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "quant_system.tasks.interim_financial_job", "--backfill"],
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return {"status": "started", "pid": process.pid}


def build_interim_reports(raw: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    datasets = raw.get("datasets") or {}
    mapped = {key: _latest_by_symbol(rows or []) for key, rows in datasets.items()}
    symbols = sorted({symbol for rows in mapped.values() for symbol in rows})
    period = str(raw.get("period") or "")
    for symbol in symbols:
        income = mapped.get("income", {}).get(symbol) or {}
        balance = mapped.get("balance_sheet", {}).get(symbol) or {}
        cashflow = mapped.get("cash_flow", {}).get(symbol) or {}
        indicators = mapped.get("indicators", {}).get(symbol) or {}
        announced = income.get("f_ann_date") or income.get("ann_date") or indicators.get("ann_date")
        code = symbol.split(".", 1)[0]
        payload = {
            "dataset": "financial.interim_report",
            "schema_version": "1.0.0",
            "source": "tushare",
            "symbol": symbol,
            "code": code,
            "report_period": _iso(period),
            "announced_at": _iso(announced),
            "known_at": f"{_iso(announced)}T09:30:00+08:00" if _iso(announced) else None,
            "status": "available",
            "income": income,
            "balance_sheet": balance,
            "cash_flow": cashflow,
            "indicators": indicators,
            "limitations": [key for key in ("income", "balance_sheet", "cash_flow", "indicators") if not mapped.get(key, {}).get(symbol)],
            "updated_at": now_str(),
        }
        _write(output_dir / f"{code}.json", payload)
    status = "available" if symbols else "unavailable"
    manifest = {
        "dataset": "financial.interim_report",
        "schema_version": "1.0.0",
        "period": _iso(period),
        "source": "tushare",
        "status": "partial" if symbols and raw.get("errors") else status,
        "count": len(symbols),
        "source_errors": raw.get("errors") or {},
        "updated_at": now_str(),
    }
    _write(output_dir / "index.json", manifest)
    return manifest


def run_interim_financial_job() -> dict[str, Any]:
    cfg = CrawlerConfig()
    period = _period()
    output_dir = cfg.data_dir / "interim_reports"
    if not cfg.tushare_enabled or not cfg.tushare_token:
        try:
            return build_public_quarterly_reports(
                fetch_public_quarterly(period), output_dir, period=period,
            )
        except Exception as exc:
            error = {
                "status": "failed",
                "source": "eastmoney_public_via_akshare",
                "period": _iso(period),
                "error": str(exc)[:500],
                "updated_at": now_str(),
            }
            _write(cfg.data_dir / "point_in_time_financials/refresh_status.json", error)
            try:
                previous = json.loads((cfg.data_dir / "point_in_time_financials/status.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                previous = {}
            if previous.get("status") in {"partial", "available", "complete"}:
                _write(output_dir / "index.json", previous)
                return {**previous, "refresh_status": "failed_preserved_last_good", "refresh_error": error["error"]}
            return build_interim_reports({
                "period": period,
                "datasets": {},
                "errors": {"eastmoney_public": error["error"]},
            }, output_dir)
    try:
        raw = TushareAPI(cfg).fetch_interim_financial(period)
    except Exception as exc:
        raw = {"period": period, "datasets": {}, "errors": {"tushare": str(exc)}}
    _write(cfg.data_dir / "raw" / "tushare" / "interim_financial" / f"{period}.json", raw)
    return build_interim_reports(raw, output_dir)


if __name__ == "__main__" and "--backfill" in sys.argv:
    try:
        run_public_financial_backfill()
    finally:
        (CrawlerConfig().data_dir / "point_in_time_financials/backfill.pid").unlink(missing_ok=True)
