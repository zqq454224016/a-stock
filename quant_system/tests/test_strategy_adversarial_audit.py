"""Adversarial audit for strategy non-promotion attribution."""

from __future__ import annotations

import json

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.tasks.strategy_adversarial_audit_job import run_strategy_adversarial_audit


def _write(root, rel, payload):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_adversarial_audit_flags_signal_portfolio_divergence(tmp_path):
    cfg = CrawlerConfig()
    cfg.data_dir = tmp_path
    _write(tmp_path, "strategy_iterations/latest.json", {
        "run_id": "t1",
        "research_version": "15.1.0",
        "selected_candidate": "demo",
        "selected_horizon": "swing",
        "promotion_passed": False,
        "decision": "research_diagnostic_wait_forward_shadow",
        "diagnostic_passed_horizons": ["swing"],
        "passed_horizons": [],
        "anti_overfit": {
            "historical_oos_already_observed": True,
            "historical_oos_can_promote_new_candidates": False,
            "recent_60d_diagnostic_cannot_select_or_tune": True,
            "oos_used_for_selection": False,
        },
        "horizon_results": {
            "swing": {
                "promotion_passed": True,
                "evaluation_scope": "contaminated_recent_60d_diagnostic_only",
            }
        },
        "candidates": [
            {
                "name": "demo",
                "horizon": "swing",
                "parameters": {"allowed_regimes": ["rising"]},
                "train_score": 1.0,
                "train": {
                    "trades": 500,
                    "hit_rate": 0.56,
                    "avg_net_return_pct": 1.5,
                    "median_net_return_pct": 1.0,
                    "portfolio": {
                        "accepted_trades": 10,
                        "rejected_capacity": 490,
                        "acceptance_rate": 0.02,
                        "hit_rate": 0.4,
                        "total_return_pct": -12.0,
                        "max_drawdown_pct": -20.0,
                    },
                },
                "development_stability": [
                    {"trades": 150, "avg_net_return_pct": 1.0, "median_net_return_pct": 0.5},
                    {"trades": 150, "avg_net_return_pct": 0.8, "median_net_return_pct": 0.4},
                ],
                "oos": {
                    "trades": 320,
                    "hit_rate": 0.55,
                    "avg_net_return_pct": 0.7,
                    "median_net_return_pct": 0.5,
                    "max_drawdown_pct": -3.0,
                    "portfolio": {
                        "accepted_trades": 8,
                        "rejected_capacity": 312,
                        "acceptance_rate": 0.025,
                        "total_return_pct": 1.0,
                        "max_drawdown_pct": -3.0,
                    },
                },
            },
            {
                "name": "baseline_long_only",
                "horizon": "swing",
                "parameters": {},
                "train": {"trades": 200, "avg_net_return_pct": -0.1, "hit_rate": 0.45},
                "development_stability": [
                    {"trades": 100, "avg_net_return_pct": -0.1, "median_net_return_pct": -0.1},
                    {"trades": 100, "avg_net_return_pct": -0.1, "median_net_return_pct": -0.1},
                ],
                "oos": {
                    "trades": 1000,
                    "hit_rate": 0.44,
                    "avg_net_return_pct": -0.2,
                    "median_net_return_pct": -0.5,
                    "max_drawdown_pct": -50.0,
                },
            },
        ],
    })

    result = run_strategy_adversarial_audit(cfg)
    assert result["status"] == "complete"
    assert result["verdict"] == "strategy_defect_and_policy_hold"
    assert result["signal_vs_portfolio"]["train"]["signal_positive_portfolio_negative"] is True
    assert (tmp_path / "strategy_iterations/adversarial_audit.json").exists()
