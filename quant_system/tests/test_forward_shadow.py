import json

from quant_system.strategy import forward_shadow


def _write(root, rel, payload):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _iteration(version="12.0.0", run_id="r1", updated_at="2026-01-01 09:00:00", candidate="tf_pullback_rising_regime"):
    return {
        "status": "complete",
        "research_version": version,
        "run_id": run_id,
        "updated_at": updated_at,
        "selected_candidate": candidate,
        "selected_horizon": "swing",
        "anti_overfit": {
            "candidate_space_frozen": True,
            "forward_shadow_start": "2026-01-01",
            "forward_shadow_signals_immutable": True,
        },
    }


def test_forward_shadow_is_immutable(monkeypatch, tmp_path):
    cfg = type("Cfg", (), {"data_dir": tmp_path})()
    monkeypatch.setattr(forward_shadow, "FORWARD_SHADOW_START", "2026-01-01")
    monkeypatch.setattr(forward_shadow, "FORWARD_SHADOW_MIN_TRADING_DAYS", 2)
    monkeypatch.setattr(
        forward_shadow, "historical_shadow_window", lambda as_of, min_days=2: ["2026-01-01", "2026-01-02"]
    )
    monkeypatch.setattr(
        forward_shadow,
        "_build_historical_signals",
        lambda *args, **kwargs: {
            "2026-01-01": [{"horizon": "swing", "code": "600001", "name": "一", "score": 70, "status": "signal"}],
            "2026-01-02": [{"horizon": "swing", "code": "600001", "name": "一", "score": 71, "status": "signal"}],
        },
    )
    monkeypatch.setattr(
        forward_shadow,
        "_load_market_regimes",
        lambda cfg: {"2026-01-01": "rising", "2026-01-02": "rising"},
    )
    _write(tmp_path, "strategy_iterations/latest.json", _iteration())
    _write(tmp_path, "recommendations/summary.json", {
        "updated_at": "first",
        "market_context": {"trade_date": "2026-01-02"},
        "periods": {"short": {"recommendations": [{"code": "600001", "score": 80}]}},
    })
    first = forward_shadow.record_forward_shadow(cfg)
    assert first["recorded_trading_days"] == 2
    assert first["status"] == "evaluation_due"
    stored = json.loads((tmp_path / "forward_shadow/signals/2026-01-02.json").read_text())
    assert stored["signals"][0]["code"] == "600001"
    _write(tmp_path, "recommendations/summary.json", {
        "updated_at": "second",
        "market_context": {"trade_date": "2026-01-02"},
        "periods": {"short": {"recommendations": [{"code": "600002", "score": 99}]}},
    })
    second = forward_shadow.record_forward_shadow(cfg)
    stored = json.loads((tmp_path / "forward_shadow/signals/2026-01-02.json").read_text())
    assert second["result"] == "already_recorded_immutable"
    assert stored["signals"][0]["code"] == "600001"


def test_forward_shadow_rejects_unregistered(monkeypatch, tmp_path):
    cfg = type("Cfg", (), {"data_dir": tmp_path})()
    monkeypatch.setattr(forward_shadow, "FORWARD_SHADOW_START", "2026-01-01")
    monkeypatch.setattr(forward_shadow, "FORWARD_SHADOW_MIN_TRADING_DAYS", 60)
    monkeypatch.setattr(
        forward_shadow, "historical_shadow_window", lambda as_of, min_days=60: ["2026-01-03"]
    )
    _write(tmp_path, "strategy_iterations/latest.json", {
        **_iteration(),
        "anti_overfit": {"candidate_space_frozen": False},
    })
    _write(tmp_path, "recommendations/summary.json", {
        "market_context": {"trade_date": "2026-01-03"},
    })
    rejected = forward_shadow.record_forward_shadow(cfg)
    assert rejected["result"] == "rejected_not_preregistered"
    assert rejected["recorded_trading_days"] == 0


def test_forward_shadow_archives_old_version_in_window(monkeypatch, tmp_path):
    cfg = type("Cfg", (), {"data_dir": tmp_path})()
    monkeypatch.setattr(forward_shadow, "FORWARD_SHADOW_START", "2026-01-01")
    monkeypatch.setattr(forward_shadow, "FORWARD_SHADOW_MIN_TRADING_DAYS", 2)
    monkeypatch.setattr(
        forward_shadow, "historical_shadow_window", lambda as_of, min_days=2: ["2026-01-02", "2026-01-03"]
    )
    monkeypatch.setattr(
        forward_shadow,
        "_build_historical_signals",
        lambda *args, **kwargs: {
            "2026-01-02": [{"horizon": "swing", "code": "600001", "name": "一", "score": 70, "status": "signal"}],
            "2026-01-03": [{"horizon": "swing", "code": "600002", "name": "二", "score": 71, "status": "signal"}],
        },
    )
    monkeypatch.setattr(
        forward_shadow,
        "_load_market_regimes",
        lambda cfg: {"2026-01-02": "rising", "2026-01-03": "rising"},
    )
    _write(tmp_path, "forward_shadow/signals/2026-01-02.json", {
        "trade_date": "2026-01-02",
        "strategy_version": "12.9.0",
        "immutable": True,
        "signals": [{"code": "999999"}],
    })
    _write(tmp_path, "strategy_iterations/latest.json", _iteration("13.0.0", "r13"))
    _write(tmp_path, "recommendations/summary.json", {
        "market_context": {"trade_date": "2026-01-03"},
    })
    status = forward_shadow.backfill_forward_shadow_from_history(cfg)
    assert status["recorded_trading_days"] == 2
    assert status["status"] == "evaluation_due"
    assert status["archived_incompatible"] == 1
    stored = json.loads((tmp_path / "forward_shadow/signals/2026-01-02.json").read_text())
    assert stored["strategy_version"] == "13.0.0"
    assert stored["signals"][0]["code"] == "600001"


def test_forward_shadow_counts_only_valid_snapshots(monkeypatch, tmp_path):
    cfg = type("Cfg", (), {"data_dir": tmp_path})()
    monkeypatch.setattr(forward_shadow, "FORWARD_SHADOW_START", "2026-01-01")
    monkeypatch.setattr(forward_shadow, "FORWARD_SHADOW_MIN_TRADING_DAYS", 2)
    monkeypatch.setattr(
        forward_shadow, "historical_shadow_window", lambda as_of, min_days=2: ["2026-01-01", "2026-01-02"]
    )
    monkeypatch.setattr(
        forward_shadow,
        "_build_historical_signals",
        lambda *args, **kwargs: {
            "2026-01-01": [],
            "2026-01-02": [{"horizon": "swing", "code": "600001", "name": "一", "score": 70, "status": "signal"}],
        },
    )
    monkeypatch.setattr(
        forward_shadow,
        "_load_market_regimes",
        lambda cfg: {"2026-01-01": "rising", "2026-01-02": "rising"},
    )
    _write(tmp_path, "forward_shadow/signals/junk.json", {"trade_date": "bad"})
    _write(tmp_path, "strategy_iterations/latest.json", _iteration())
    _write(tmp_path, "recommendations/summary.json", {
        "market_context": {"trade_date": "2026-01-02"},
    })
    status = forward_shadow.record_forward_shadow(cfg)
    assert status["recorded_trading_days"] == 2
    assert status["remaining_trading_days"] == 0
    assert status["progress_pct"] == 100.0
    assert status["source"] == "historical_real_window"


def test_historical_shadow_window_uses_calendar(monkeypatch):
    monkeypatch.setattr(
        forward_shadow,
        "get_calendar",
        lambda: type("Cal", (), {"fetch_dates": lambda self: [
            "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-06", "2026-01-07",
        ]})(),
    )
    assert forward_shadow.historical_shadow_window("2026-01-07", min_days=3) == [
        "2026-01-03", "2026-01-06", "2026-01-07",
    ]


def test_evaluate_forward_shadow_runs_once(monkeypatch, tmp_path):
    import pandas as pd

    cfg = type("Cfg", (), {"data_dir": tmp_path})()
    monkeypatch.setattr(forward_shadow, "FORWARD_SHADOW_MIN_TRADING_DAYS", 2)
    monkeypatch.setattr(
        forward_shadow,
        "get_calendar",
        lambda: type("Cal", (), {"fetch_dates": lambda self: ["2026-01-01", "2026-01-02"]})(),
    )
    monkeypatch.setattr(
        forward_shadow,
        "_load_market_regimes",
        lambda cfg: {"2026-01-01": "rising", "2026-01-02": "rising"},
    )
    monkeypatch.setattr(
        forward_shadow,
        "_collect_window_trades",
        lambda cfg, candidate, window, regimes: pd.DataFrame(),
    )
    _write(tmp_path, "strategy_iterations/latest.json", _iteration("15.1.0", "r15"))
    _write(tmp_path, "forward_shadow/status.json", {
        "status": "evaluation_due",
        "start": "2026-01-01",
        "end": "2026-01-02",
        "recorded_trading_days": 2,
        "overwrite_forbidden": True,
    })
    for day in ("2026-01-01", "2026-01-02"):
        _write(tmp_path, f"forward_shadow/signals/{day}.json", {
            "trade_date": day, "strategy_version": "15.1.0", "immutable": True, "signals": [],
        })
    first = forward_shadow.evaluate_forward_shadow(cfg)
    assert first["status"] == "evaluated"
    assert first["promotion_passed"] is False
    assert first["decision"] == "reject_keep_research"
    assert first["regime_coverage_complete"] is True
    assert any("trades<" in x for x in first["fail_reasons"])
    second = forward_shadow.evaluate_forward_shadow(cfg)
    assert second["result"] == "already_evaluated_immutable"
    stored = json.loads((tmp_path / "forward_shadow/evaluation.json").read_text())
    assert stored["immutable"] is True
    assert json.loads((tmp_path / "forward_shadow/status.json").read_text())["status"] == "evaluated"


def test_evaluate_rejects_incomplete_regime_coverage(monkeypatch, tmp_path):
    cfg = type("Cfg", (), {"data_dir": tmp_path})()
    monkeypatch.setattr(forward_shadow, "FORWARD_SHADOW_MIN_TRADING_DAYS", 2)
    monkeypatch.setattr(
        forward_shadow,
        "get_calendar",
        lambda: type("Cal", (), {"fetch_dates": lambda self: ["2026-01-01", "2026-01-02"]})(),
    )
    monkeypatch.setattr(forward_shadow, "_load_market_regimes", lambda cfg: {"2026-01-01": "rising"})
    _write(tmp_path, "strategy_iterations/latest.json", _iteration("15.1.0", "r15"))
    _write(tmp_path, "forward_shadow/status.json", {
        "status": "evaluation_due",
        "start": "2026-01-01",
        "end": "2026-01-02",
        "recorded_trading_days": 2,
    })
    for day in ("2026-01-01", "2026-01-02"):
        _write(tmp_path, f"forward_shadow/signals/{day}.json", {
            "trade_date": day, "strategy_version": "15.1.0", "immutable": True, "signals": [],
        })
    result = forward_shadow.evaluate_forward_shadow(cfg)
    assert result["result"] == "rejected_incomplete_market_regime"
    assert result["missing_regime_days"] == 1
    assert not (tmp_path / "forward_shadow/evaluation.json").exists()


def test_invalidate_incomplete_forward_shadow(tmp_path):
    cfg = type("Cfg", (), {"data_dir": tmp_path})()
    _write(tmp_path, "forward_shadow/evaluation.json", {
        "status": "evaluated",
        "regime_counts": {"missing": 21, "falling": 26},
        "regime_coverage_complete": False,
    })
    _write(tmp_path, "forward_shadow/status.json", {"status": "evaluated", "evaluation_locked": True})
    _write(tmp_path, "forward_shadow/signals/2026-01-01.json", {
        "trade_date": "2026-01-01", "strategy_version": "15.1.0", "immutable": True, "signals": [],
    })
    result = forward_shadow.invalidate_incomplete_forward_shadow(cfg)
    assert result["result"] == "invalidated_incomplete_evaluation"
    assert not (tmp_path / "forward_shadow/evaluation.json").exists()
    assert (tmp_path / "forward_shadow/signals").exists()
    assert not list((tmp_path / "forward_shadow/signals").glob("*.json"))
