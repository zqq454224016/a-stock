"""美国 CPI（月度，BLS 公共 API，无需 token）。"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from typing import Any

SERIES = "CUUR0000SA0"  # CPI-U All items, US city average

def run_us_cpi_job(data_dir: Path) -> dict[str, Any]:
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/" + SERIES + "?startyear=2015&endyear=" + str(datetime.now().year)
    payload: dict[str, Any]
    try:
        req = Request(url, headers={"User-Agent": "a-stock-quant/1.0"})
        with urlopen(req, timeout=20) as r: payload = json.loads(r.read().decode())
        rows = []
        for x in (payload.get("Results", {}).get("series", [{}])[0].get("data", [])):
            rows.append({"year": x.get("year"), "period": x.get("period"), "period_name": x.get("periodName"), "value": float(x.get("value")), "footnotes": x.get("footnotes") or []})
        rows.sort(key=lambda x: (x["year"], x["period"]))
        latest = rows[-1] if rows else None
        prev = rows[-13] if len(rows) >= 13 else None
        yoy = ((latest["value"] / prev["value"] - 1) * 100) if latest and prev and prev["value"] else None
        if yoy is None: signal, impact = "unknown", "缺少同比数据"
        elif yoy >= 3.5: signal, impact = "hot", "通胀偏高：利率维持高位预期，压制高估值成长资产，美元和防御板块相对受益"
        elif yoy <= 2.0: signal, impact = "cool", "通胀偏低：降息预期改善，利好成长、科技和长久期资产"
        else: signal, impact = "stable", "通胀温和：对风险资产影响中性，市场更关注就业和利率路径"
        out = {"dataset": "us_cpi", "series_id": SERIES, "source": "BLS", "updated_at": datetime.now().isoformat(timespec="seconds"), "rows": rows, "latest": latest, "analysis": {"yoy_pct": round(yoy, 3) if yoy is not None else None, "signal": signal, "market_impact": impact, "used_in_stock_score": False}, "limitations": ["月度数据", "发布日期需结合BLS日历，不等同统计月份"]}
    except Exception as exc:
        out = {"dataset": "us_cpi", "series_id": SERIES, "source": "BLS", "updated_at": datetime.now().isoformat(timespec="seconds"), "status": "unavailable", "error": str(exc)[:300], "rows": []}
    path = data_dir / "macro/us_cpi.json"; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
