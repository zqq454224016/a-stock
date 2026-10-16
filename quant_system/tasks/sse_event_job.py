"""SSE risk-warning announcement index, PDF parser, validator and AI exception queue."""

from __future__ import annotations

import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.tasks.strategy_job import _write
from quant_system.utils.time_utils import now_str

QUERY_URL = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
SSE_ROOT = "https://big5.sse.com.cn/site/cht/www.sse.com.cn"
HEADERS = {
    "Referer": "https://www.sse.com.cn/assortment/stock/list/info/announcement/",
    "User-Agent": "Mozilla/5.0 (compatible; a-stock-research/1.0)",
}
EVENT_TITLE = re.compile(r"(实施|撤销).{0,12}(退市风险警示|其他风险警示|风险警示)")
EXCLUDE_TITLE = re.compile(r"(申请|进展|风险提示|专项说明|问询|回复)")
DATE_PATTERNS = (
    re.compile(r"(?:实施|撤销|变更)?(?:风险警示)?(?:的)?(?:起始日|生效日|变更日期)[：:\s]*(20\d{2})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?"),
    re.compile(r"(?:自|于)?\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日(?:起)?[^。\n]{0,40}(?:实施|撤销|变更)"),
    re.compile(r"(?:实施|撤销|变更)[^。\n]{0,40}(?:日期|起始日)[：:\s]*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
)


def _announcement_params(code: str, begin: str, end: str) -> dict[str, str]:
    return {
        "isPagination": "true", "productId": code, "keyWord": "风险警示",
        "securityType": "0101", "reportType2": "", "reportType": "ALL",
        "beginDate": begin, "endDate": end, "pageHelp.pageSize": "100",
        "pageHelp.pageNo": "1", "pageHelp.beginPage": "1", "pageHelp.cacheSize": "1",
    }


def _extract_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:8])


def _effective_date(text: str, announcement_date: str | None = None) -> str | None:
    compact = text.replace("\u3000", " ")
    candidates: set[date] = set()
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(compact):
            try:
                candidates.add(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
            except ValueError:
                continue
    if not candidates:
        return None
    if announcement_date:
        try:
            announced = datetime.strptime(str(announcement_date)[:10], "%Y-%m-%d").date()
            near = sorted(value for value in candidates if announced <= value <= announced + timedelta(days=10))
            if near:
                return near[0].isoformat()
        except ValueError:
            pass
    return sorted(candidates)[-1].isoformat()


def _event_state(title: str) -> str | None:
    if any(word in title for word in ("申请", "进展", "可能", "叠加", "暂不")):
        return None
    if "撤销" in title and "风险警示" in title and "继续实施" not in title and "继续被实施" not in title:
        return "st_end"
    if "实施" in title and "风险警示" in title and "继续" not in title and "撤销" not in title and "停牌" in title:
        return "st_start"
    return None


def run_sse_event_job(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "market_events/sse"
    status_path = root / "status.json"
    if status_path.exists():
        try:
            previous = json.loads(status_path.read_text(encoding="utf-8"))
            if previous.get("status") == "complete" and str(previous.get("updated_at") or "").startswith(date.today().isoformat()):
                return {**previous, "status": "up_to_date"}
        except (OSError, ValueError):
            pass
    universe = json.loads((cfg.data_dir / "universe/stocks.json").read_text(encoding="utf-8"))
    codes = [
        str(row.get("code") or "") for row in universe.get("stocks") or universe.get("items") or []
        if str(row.get("code") or "").startswith(("600", "601", "603", "605"))
    ]
    begin, end = (date.today() - timedelta(days=365 * 5)).isoformat(), date.today().isoformat()
    raw_index = root / "index_raw"
    pending = [code for code in codes if not (raw_index / f"{code}.json").exists()]
    _write(status_path, {"status": "indexing", "updated_at": now_str(), "total": len(codes), "completed": len(codes) - len(pending)})

    def fetch(code: str) -> tuple[str, dict[str, Any]]:
        response = requests.get(QUERY_URL, params=_announcement_params(code, begin, end), headers=HEADERS, timeout=20)
        response.raise_for_status()
        return code, response.json()

    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="sse-index") as pool:
        futures = {pool.submit(fetch, code): code for code in pending}
        for completed, future in enumerate(as_completed(futures), 1):
            code = futures[future]
            try:
                _, payload = future.result()
                _write(raw_index / f"{code}.json", payload)
            except Exception as exc:  # noqa: BLE001
                errors[code] = str(exc)[-300:]
            if completed % 100 == 0:
                _write(root / "status.json", {
                    "status": "indexing", "updated_at": now_str(), "total": len(codes),
                    "completed": len(codes) - len(pending) + completed, "errors": len(errors),
                })
            time.sleep(.01)

    selected: list[dict[str, Any]] = []
    for path in sorted(raw_index.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("result") or []:
            title = str(row.get("TITLE") or "")
            if EVENT_TITLE.search(title) and not EXCLUDE_TITLE.search(title) and _event_state(title):
                selected.append({
                    "code": str(row.get("SECURITY_CODE") or path.stem),
                    "security_name": row.get("SECURITY_NAME"), "announcement_date": row.get("SSEDATE"),
                    "title": title, "pdf_url": SSE_ROOT + str(row.get("URL") or ""),
                })

    events: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    pdf_root = root / "pdf"
    for number, item in enumerate(selected, 1):
        filename = Path(item["pdf_url"]).name or f"{item['code']}_{number}.pdf"
        pdf_path = pdf_root / filename
        try:
            if not pdf_path.exists() or not pdf_path.read_bytes().startswith(b"%PDF-"):
                response = requests.get(item["pdf_url"], headers=HEADERS, timeout=30)
                response.raise_for_status()
                if not response.content.startswith(b"%PDF-"):
                    raise ValueError(f"non_pdf_response:{response.headers.get('content-type')}")
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = pdf_path.with_suffix(".tmp")
                temporary.write_bytes(response.content)
                temporary.replace(pdf_path)
            text = _extract_text(pdf_path.read_bytes())
            effective = _effective_date(text, item["announcement_date"])
            state = _event_state(item["title"])
            event = {
                **item, "date": effective, "event_type": "st_status_change",
                "state": state, "source": "sse_official_announcement_pdf",
                "confidence": "high" if effective and state else "low",
                "known_at": item["announcement_date"], "pdf_path": str(pdf_path.relative_to(cfg.data_dir)),
            }
            if effective and state and effective >= str(item["announcement_date"])[:10]:
                events.append(event)
            else:
                exceptions.append({**event, "exception_reason": "effective_date_or_state_unresolved"})
        except Exception as exc:  # noqa: BLE001
            exceptions.append({**item, "exception_reason": str(exc)[-300:]})
        if number % 50 == 0:
            _write(root / "status.json", {"status": "parsing_pdfs", "updated_at": now_str(), "selected": len(selected), "completed": number})

    events.sort(key=lambda item: (item["code"], item["date"]))
    payload = {
        "status": "complete" if not errors else "partial", "updated_at": now_str(),
        "source": "sse_official_announcements", "codes": len(codes),
        "indexed": len(codes) - len(errors), "selected_announcements": len(selected),
        "validated_events": len(events), "ai_exception_count": len(exceptions),
        "events": events, "errors": dict(list(errors.items())[:20]),
    }
    _write(root / "events.json", payload)
    _write(root / "ai_exceptions.json", {
        "updated_at": now_str(), "scope": "extract_effective_date_and_before_after_name_only",
        "count": len(exceptions), "items": exceptions,
    })
    _write(status_path, {key: payload[key] for key in payload if key != "events"})
    return payload


if __name__ == "__main__":
    run_sse_event_job()
