"""Public industry membership and daily-index history with resumable local cache."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from quant_system.analysis.sector_rotation import build_sector_rotation
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str
from quant_system.utils.trade_calendar import get_calendar

SECTOR_DATA_VERSION = "1.0.0"
THS_INDUSTRY_MAPPING_URL = "https://shy313.com/api/plugins/market_flow/exports/ths-industries"


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    return frame.to_dict(orient="records")


def _pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _number(value: Any) -> float | None:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _target_history_end() -> str:
    """Skip cached industry history only when it already covers the latest session."""
    try:
        return get_calendar().latest_completed_trade_day()
    except Exception:  # noqa: BLE001
        return date.today().isoformat()


def _history_rows(frame: Any) -> list[dict[str, Any]]:
    output = []
    for row in _records(frame):
        trade_date = _pick(row, "日期", "date", "交易日")
        close = _number(_pick(row, "收盘", "收盘价", "close"))
        if trade_date is None or close is None:
            continue
        output.append({
            "date": str(trade_date)[:10],
            "open": _number(_pick(row, "开盘", "开盘价", "open")),
            "high": _number(_pick(row, "最高", "最高价", "high")),
            "low": _number(_pick(row, "最低", "最低价", "low")),
            "close": close,
            "change_pct": _number(_pick(row, "涨跌幅", "change_pct")),
            "volume": _number(_pick(row, "成交量", "volume")),
            "amount": _number(_pick(row, "成交额", "amount")),
        })
    return sorted(output, key=lambda row: row["date"])


def _public_industry_mapping() -> list[dict[str, Any]]:
    request = urllib.request.Request(
        THS_INDUSTRY_MAPPING_URL,
        headers={"User-Agent": "a-stock-quant-system/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("public industry mapping is not a list")
    return [row for row in payload if isinstance(row, dict)]


def run_sector_data_job(
    cfg: CrawlerConfig | None = None,
    *,
    ak_module: Any = None,
    years: int = 5,
) -> dict[str, Any]:
    """Fetch all Eastmoney industries, membership and five-year daily history.

    Each board is persisted immediately, so a failed round resumes without
    spending requests on completed boards.
    """
    cfg = cfg or CrawlerConfig()
    if ak_module is None:
        import akshare as ak_module

    root = cfg.data_dir / "sector_data"
    membership_dir = root / "membership"
    history_dir = root / "history"
    board_source = "eastmoney"
    try:
        board_rows = _records(ak_module.stock_board_industry_name_em())
    except Exception:  # noqa: BLE001
        board_source = "tonghuashun"
        try:
            board_rows = _records(ak_module.stock_board_industry_name_ths())
        except Exception:  # noqa: BLE001
            # 两个远端板块目录均不可用时，不能直接退出；使用本地缓存继续
            # 计算，并将来源标记为 cache，避免旧数据被误认为实时数据。
            board_source = "cache"
            board_rows = []
            for cached_path in sorted((cfg.data_dir / "sector_data" / "membership").glob("*.json")):
                name = cached_path.stem
                board_rows.append({"板块名称": name, "板块代码": "cache", "涨跌幅": None})
    boards = []
    for row in board_rows:
        name = str(_pick(row, "板块名称", "行业", "板块", "name") or "").strip()
        if name:
            boards.append({
                "name": name,
                "code": str(_pick(row, "板块代码", "代码", "code") or ""),
                "change_pct": _number(_pick(row, "涨跌幅")),
            })

    end = date.today()
    start = end - timedelta(days=max(1, years) * 366)
    target_end = _target_history_end()
    stock_sectors: dict[str, list[str]] = {}
    completed_membership = completed_history = 0
    failures: list[dict[str, str]] = []
    public_rows: list[dict[str, Any]] = []
    try:
        public_rows = _public_industry_mapping()
    except Exception as exc:  # noqa: BLE001
        failures.append({"industry": "*", "stage": "public_mapping", "error": str(exc)[-240:]})
    public_members: dict[str, list[dict[str, str]]] = {}
    for row in public_rows:
        code = str(row.get("symbol") or "").split(".", 1)[0].zfill(6)
        if not is_research_stock_code(code):
            continue
        labels = [str(value).strip() for value in (row.get("industries") or []) if str(value).strip()]
        for label in labels:
            public_members.setdefault(label, []).append({"code": code, "name": str(row.get("name") or "")})
        if labels:
            stock_sectors[code] = labels

    for board in boards:
        name = board["name"]
        safe_name = name.replace("/", "_")
        membership_path = membership_dir / f"{safe_name}.json"
        history_path = history_dir / f"{safe_name}.json"
        try:
            if membership_path.exists():
                membership = json.loads(membership_path.read_text(encoding="utf-8"))
            elif name in public_members:
                membership = {"industry": name, "members": public_members[name], "updated_at": now_str()}
                _write(membership_path, membership)
            else:
                members = []
                for row in _records(ak_module.stock_board_industry_cons_em(symbol=name)):
                    code = str(_pick(row, "代码", "股票代码") or "").zfill(6)
                    if is_research_stock_code(code):
                        members.append({
                            "code": code,
                            "name": str(_pick(row, "名称", "股票名称") or ""),
                        })
                membership = {"industry": name, "members": members, "updated_at": now_str()}
                _write(membership_path, membership)
            completed_membership += 1
            for member in membership.get("members") or []:
                stock_sectors.setdefault(str(member["code"]), []).append(name)
        except Exception as exc:  # noqa: BLE001
            failures.append({"industry": name, "stage": "membership", "error": str(exc)[-240:]})

        try:
            cached = {}
            if history_path.exists():
                cached = json.loads(history_path.read_text(encoding="utf-8"))
            cached_rows = cached.get("rows") or []
            cached_start = str(cached_rows[0].get("date") or "") if cached_rows else ""
            cached_end = str(cached_rows[-1].get("date") or "") if cached_rows else ""
            if cached_start <= start.isoformat() and cached_end >= target_end:
                completed_history += 1
                continue
            if board_source == "tonghuashun":
                frame = ak_module.stock_board_industry_index_ths(
                    symbol=name,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                )
            else:
                frame = ak_module.stock_board_industry_hist_em(
                    symbol=name,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    period="日k",
                    adjust="",
                )
            rows = _history_rows(frame)
            if not rows:
                raise ValueError("empty industry history")
            _write(history_path, {
                "industry": name,
                "version": SECTOR_DATA_VERSION,
                "start_date": rows[0]["date"],
                "end_date": rows[-1]["date"],
                "rows": rows,
                "updated_at": now_str(),
            })
            completed_history += 1
        except Exception as exc:  # noqa: BLE001
            failures.append({"industry": name, "stage": "history", "error": str(exc)[-240:]})

    mapping = {
        code: {"primary_industry": names[0], "industries": sorted(set(names))}
        for code, names in sorted(stock_sectors.items())
    }
    _write(root / "stock_industry_map.json", {
        "version": SECTOR_DATA_VERSION,
        "updated_at": now_str(),
        "source": "eastmoney_public_via_akshare",
        "stock_count": len(mapping),
        "stocks": mapping,
    })
    rotation: dict[str, Any] = {}
    try:
        rotation = build_sector_rotation(cfg.data_dir)
    except Exception as exc:  # noqa: BLE001
        failures.append({"industry": "*", "stage": "rotation", "error": str(exc)[-240:]})
    status = {
        "version": SECTOR_DATA_VERSION,
        "updated_at": now_str(),
        "status": "complete" if boards and not failures else "partial",
        "board_count": len(boards),
        "membership_completed": completed_membership,
        "history_completed": completed_history,
        "stock_mapping_count": len(mapping),
        "history_years": years,
        "board_source": board_source,
        "mapping_source": "tickflow_reference_public_ths_export" if public_rows else "board_constituent_api",
        "latest_trade_date": str(rotation.get("trade_date") or ""),
        "attempted_trade_date": target_end,
        "rotation_count": int(rotation.get("count") or 0),
        "failures": failures[:100],
        "scoring_policy": "data_only_until_out_of_sample_sector_factor_validation_passes",
    }
    _write(root / "status.json", status)
    return status


def launch_sector_data_job(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "sector_data"
    pid_path = root / "worker.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            return {"status": "already_running", "pid": pid}
        except (OSError, ValueError):
            pid_path.unlink(missing_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    log = (root / "worker.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "quant_system.tasks.sector_data_job"],
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return {"status": "started", "pid": process.pid}


if __name__ == "__main__":
    run_sector_data_job()
