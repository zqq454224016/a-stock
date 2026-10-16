from __future__ import annotations

import json
from datetime import datetime

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.iteration.eta import build_iteration_eta


def _write(root, rel, payload):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_eta_is_conditional_without_promoted_strategy(tmp_path):
    cfg = CrawlerConfig()
    cfg.data_dir = tmp_path
    _write(tmp_path, "iteration/trading_readiness.json", {
        "status": "research_only",
        "missing": [
            {"name": "stable_promoted_strategy"},
            {"name": "paper_trading_observation"},
            {"name": "recommendation_instruction_engine"},
        ],
    })
    _write(tmp_path, "strategy_iterations/latest.json", {"promotion_passed": False})

    eta = build_iteration_eta(cfg, now=datetime(2026, 7, 30, 10, 0))

    assert eta["product_mode"] == "recommendation_only"
    assert eta["broker_integration"] is False
    assert eta["final_completion"]["expected_at"] is None
    assert eta["final_completion"]["confidence"] == "conditional"
    assert "券商" not in " ".join(eta["final_completion"]["blocking_conditions"])
    assert "推荐执行校验" in " ".join(eta["final_completion"]["blocking_conditions"])
    assert eta["fast_track"]["excludes"] == ["真实券商报单", "券商网关", "自动交易"]
    assert (tmp_path / "iteration/eta.json").exists()


def test_eta_marks_execution_complete_when_not_missing(tmp_path):
    cfg = CrawlerConfig()
    cfg.data_dir = tmp_path
    _write(tmp_path, "iteration/trading_readiness.json", {
        "status": "recommendation_pipeline_ready",
        "missing": [{"name": "stable_promoted_strategy"}],
    })
    _write(tmp_path, "strategy_iterations/latest.json", {"promotion_passed": False})
    _write(tmp_path, "forward_shadow/status.json", {
        "status": "evaluated",
        "recorded_trading_days": 60,
        "promotion_passed": True,
        "decision": "promote_from_forward_shadow",
    })

    eta = build_iteration_eta(cfg, now=datetime(2026, 10, 16, 10, 0))
    stage = next(s for s in eta["stages"] if s["name"] == "推荐执行校验基础设施")
    assert stage["status"] == "complete"
    assert stage["expected_at"] is None
    assert eta["fast_track"]["simulation_ready_expected_at"] is None
