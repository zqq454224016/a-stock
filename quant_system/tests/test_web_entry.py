import json
from types import SimpleNamespace

from quant_system.web import server
from quant_system.web.server import ASSET_DIR, DiagnosisHandler


def test_internal_diagnosis_page_exists():
    content = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
    assert "AI 诊股" in content
    assert "/api/diagnose" in content
    assert "/api/recommend" in content
    assert "生成 AI 股票研究候选" in content
    assert "获取 TickFlow 全市场股票清单" in content
    assert "后台同步全市场历史数据" in content
    assert "同步市场制度基础数据" in content
    assert "Tushare Pro Token" in content
    assert "/api/config" in content
    assert "/api/dashboard" in content
    assert "/api/strategy" in content
    assert "趋势策略总览" in content
    assert "多周期推荐" in content
    assert "今日涨跌分析" in content
    assert "自动策略迭代" in content
    assert DiagnosisHandler.server_version == "AStockDiagnosis/1.0"


def test_dashboard_compacts_strategy_and_recommendations(monkeypatch, tmp_path):
    def write(rel, payload):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    write("strategy/index.json", {"count": 2, "items": [
        {"code": "600001", "name": "甲", "trend_stage": "rising", "trend_score": 88, "confidence": "high"},
        {"code": "600002", "name": "乙", "trend_stage": "falling", "trend_score": 20, "confidence": "high"},
    ]})
    write("strategy_backtest/status.json", {"status": "complete", "total": 2, "validated": 2})
    write("recommendations/summary.json", {"periods": {"short": {
        "label": "短线", "recommendations": [{"code": "600001", "score": 80}],
        "evaluated": [{"raw": "must not leak"}],
    }}})
    write("today_change/summary.json", {
        "trade_date": "2026-07-23", "sample_count": 2,
        "market_state": "分化", "breadth": {"advances": 1, "declines": 1},
    })
    write("iteration/status.json", {
        "policy_version": "1.0.0", "phase": "data_foundation",
        "strategy_status": "research_only", "failed_gates": ["history_length"],
        "gates": [{"name": "history_length", "actual": 250, "required": 1250, "passed": False}],
    })
    monkeypatch.setattr(server, "CrawlerConfig", lambda: SimpleNamespace(data_dir=tmp_path))

    payload = server._dashboard_payload(limit=1)

    assert payload["strategy"]["stage_counts"] == {"rising": 1, "falling": 1}
    assert payload["strategy"]["top"][0]["code"] == "600001"
    assert payload["validation"]["status"] == "complete"
    assert payload["today_change"]["market_state"] == "分化"
    assert payload["iteration"]["strategy_status"] == "research_only"
    assert "evaluated" not in payload["periods"]["short"]
