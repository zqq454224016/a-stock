"""Agent 单元测试（P4-1）。"""

import json
from pathlib import Path

from quant_system.agent.context import StockContext
from quant_system.agent.orchestrator import build_agent_report
from quant_system.agent.policy import validate_agent_output
from quant_system.agent.predict_review import review_prediction
from quant_system.agent.schemas import build_evidence_package
from quant_system.agent.stock_explainer import explain_stock_selection
from quant_system.agent.strategy_diagnosis import diagnose_strategy
from quant_system.config.db_config import DBConfig
from quant_system.storage.json_store import JsonStore


def _write(store: JsonStore, rel: str, data: dict) -> None:
    path = store.config.json_data_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_stock_explainer_positive(tmp_path: Path):
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    code = "600378"
    _write(store, f"stocks/{code}.json", {
        "code": code, "name": "昊华科技", "trade_date": "2026-07-06",
        "analysis": {"trend": "偏多"},
    })
    _write(store, f"factors/{code}.json", {
        "factors": {"multi_factor_score": 72, "technical_score": 87, "sentiment_score": 60},
    })
    _write(store, f"signals/{code}.json", {
        "signal": "bullish", "drivers": ["above_ma20"], "limitations": [],
    })
    ctx = StockContext(code, store)
    out = explain_stock_selection(ctx)
    assert out["verdict"] == "positive"
    assert out["composite_score"] == 72


def test_stock_explainer_tolerates_string_scores(tmp_path: Path):
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    code = "600378"
    _write(store, f"stocks/{code}.json", {"code": code, "name": "昊华科技"})
    _write(store, f"factors/{code}.json", {
        "factors": {
            "multi_factor_score": "72",
            "technical_score": "87",
            "fundamental_detail": {"pe_ttm": "n/a"},
        },
    })
    ctx = StockContext(code, store)
    out = explain_stock_selection(ctx)
    assert out["verdict"] == "positive"
    assert out["composite_score"] == 72.0


def test_strategy_diagnosis_weak(tmp_path: Path):
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    code = "600378"
    _write(store, f"backtest/{code}_ma_cross.json", {
        "strategy": "ma_cross",
        "metrics": {
            "win_rate_pct": 22.0,
            "sharpe_ratio": 0.1,
            "max_drawdown_pct": -50.0,
            "closed_trades": 10,
        },
        "attribution": {"worst_trade": {"pnl": -8000, "reason": "MA死叉"}},
    })
    ctx = StockContext(code, store)
    out = diagnose_strategy(ctx)
    assert out["verdict"] == "weak"
    assert len(out["findings"]) >= 2


def test_predict_review_divergent(tmp_path: Path):
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    code = "600378"
    _write(store, f"predictions/{code}.json", {
        "horizon": "5d", "direction": "down", "probability": 0.4,
        "confidence": "medium", "evidence": {"sample_count": 100, "backtest_win_rate": 0.3},
        "risk_flags": ["high_volatility"],
    })
    _write(store, f"signals/{code}.json", {"signal": "bullish"})
    _write(store, f"factors/{code}.json", {"factors": {"multi_factor_score": 70}})
    ctx = StockContext(code, store)
    out = review_prediction(ctx)
    assert out["alignment"] == "divergent"
    assert "signal_prediction_divergence" in out["failure_conditions"]


def test_build_agent_report(tmp_path: Path):
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    code = "600378"
    _write(store, f"stocks/{code}.json", {"code": code, "name": "昊华科技", "trade_date": "2026-07-06"})
    _write(store, f"factors/{code}.json", {"factors": {"multi_factor_score": 55}})
    _write(store, f"signals/{code}.json", {"signal": "neutral"})
    _write(store, "quality/latest.json", {
        "stocks": [{"code": code, "status": "ok", "quality_score": 100, "factor_eligible": True}],
    })
    ctx = StockContext(code, store)
    report = build_agent_report(ctx)
    assert report["code"] == code
    assert "stock_selection" in report
    assert "rule_based_only" in report["limitations"]
    assert report["provider"]["active"] == "rule"
    assert report["policy"]["passed"] is True
    assert report["audit"]["policy_passed"] is True


def test_evidence_package_marks_missing_inputs(tmp_path: Path):
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    code = "600378"
    _write(store, f"stocks/{code}.json", {"code": code, "name": "昊华科技", "trade_date": "2026-07-06"})
    ctx = StockContext(code, store)
    package = build_evidence_package(ctx).to_dict()

    assert package["code"] == code
    assert package["allowed_actions"] == ["analyze", "summarize", "suggest"]
    assert "prediction" in package["missing_inputs"]
    assert "stock" not in package["missing_inputs"]


def test_policy_blocks_forbidden_agent_output():
    evidence = {"allowed_actions": ["analyze", "summarize", "suggest"]}
    result = {
        "summary": "无需人工确认，直接下单",
        "evidence": ["因子较强"],
        "risks": ["波动较大"],
        "suggested_actions": ["买入"],
        "requires_human_review": False,
    }
    policy = validate_agent_output(result, evidence)

    assert policy["passed"] is False
    assert any("禁止表述" in x for x in policy["violations"])
    assert any("人工确认" in x for x in policy["violations"])


def test_llm_provider_falls_back_to_rule_with_audit(tmp_path: Path):
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    code = "600378"
    _write(store, f"stocks/{code}.json", {"code": code, "name": "昊华科技", "trade_date": "2026-07-06"})
    _write(store, f"factors/{code}.json", {"factors": {"multi_factor_score": 55}})
    _write(store, f"signals/{code}.json", {"signal": "neutral"})
    ctx = StockContext(code, store)
    report = build_agent_report(ctx, provider="llm")

    assert report["provider"]["requested"] == "llm"
    assert report["provider"]["active"] == "rule"
    assert "未配置" in report["provider"]["fallback_reason"]
    assert report["_audit_record"]["fallback_reason"] == report["provider"]["fallback_reason"]
