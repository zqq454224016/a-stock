import json
from types import SimpleNamespace

from quant_system.iteration import worker
from quant_system.iteration.worker import WorkerConfig


def _write(root, rel, payload):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_round_is_dependency_aware_and_ai_is_data_only(monkeypatch, tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    _write(tmp_path, "stocks/index.json", {"updated_at": "2026-07-24"})
    _write(tmp_path, "latest.json", {"trade_date": "2026-07-24"})
    calls = []
    monkeypatch.setattr(worker, "run_today_change_job", lambda: calls.append("today") or {})
    monkeypatch.setattr(worker, "run_trend_strategy_job", lambda: calls.append("strategy") or {})
    monkeypatch.setattr(worker, "launch_offline_validation", lambda: calls.append("validation") or {"status": "started"})
    monkeypatch.setattr(worker, "run_recommendation_job", lambda: calls.append("recommend") or {})
    monkeypatch.setattr(worker, "run_auto_iteration", lambda config: calls.append("audit") or {"status": "complete"})
    monkeypatch.setattr(worker, "_ai_advice_due", lambda config, policy: True)
    monkeypatch.setattr(worker, "_full_acquisition_due", lambda config: False)

    payload = worker.run_iteration_round(
        cfg,
        WorkerConfig(interval_sec=300, ai_cooldown_sec=3600, ai_enabled=True),
        advisor=lambda config: calls.append("ai_data") or {"status": "complete", "scope": "data_acquisition_methods_only"},
    )

    assert set(calls[:2]) == {"today", "strategy"}
    assert calls[2:] == ["validation", "recommend", "audit", "ai_data"]
    assert payload["ai_scope"] == "data_acquisition_methods_only"
    assert payload["execution_mode"] == "dependency_graph_parallel"
    assert (tmp_path / "iteration/worker_status.json").exists()


def test_round_skips_unchanged_hard_computations(monkeypatch, tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    dependencies = [
        "stocks/index.json", "latest.json", "strategy/index.json",
        "today_change/summary.json", "strategy_backtest/index.json",
        "recommendations/summary.json",
    ]
    for rel in dependencies:
        _write(tmp_path, rel, {})
    calls = []
    monkeypatch.setattr(worker, "run_auto_iteration", lambda config: calls.append("audit") or {})
    monkeypatch.setattr(worker, "_ai_advice_due", lambda config, policy: False)
    monkeypatch.setattr(worker, "_full_acquisition_due", lambda config: False)

    worker.run_iteration_round(cfg, WorkerConfig())

    assert calls == ["audit"]


def test_ai_advice_runs_only_when_evidence_changes(monkeypatch, tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    policy = WorkerConfig(ai_enabled=True)
    monkeypatch.setattr(worker, "acquisition_evidence", lambda config: {"version": 1})
    fingerprint = worker.evidence_fingerprint({"version": 1})

    assert worker._ai_advice_due(cfg, policy) is True
    _write(tmp_path, "iteration/data_acquisition_advice.json", {
        "status": "complete",
        "fingerprint": fingerprint,
    })
    assert worker._ai_advice_due(cfg, policy) is False
    monkeypatch.setattr(worker, "acquisition_evidence", lambda config: {"version": 2})
    assert worker._ai_advice_due(cfg, policy) is True


def test_rejected_ai_advice_is_not_retried_without_new_evidence(monkeypatch, tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    policy = WorkerConfig(ai_enabled=True)
    monkeypatch.setattr(worker, "acquisition_evidence", lambda config: {"version": 1})
    fingerprint = worker.evidence_fingerprint({"version": 1})
    _write(tmp_path, "iteration/data_acquisition_advice.json", {
        "status": "rejected", "fingerprint": fingerprint,
    })
    assert worker._ai_advice_due(cfg, policy) is False


def test_full_acquisition_due_is_trade_date_aware(monkeypatch, tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    monkeypatch.setattr(worker, "_latest_completed_trade_day", lambda: "2026-07-24")
    assert worker._full_acquisition_due(cfg) is True
    _write(tmp_path, "stocks/index.json", {"trade_date": "2026-07-24"})
    assert worker._full_acquisition_due(cfg) is False
    _write(tmp_path, "stocks/index.json", {"trade_date": "2026-07-23"})
    assert worker._full_acquisition_due(cfg) is True


def test_latest_completed_trade_day_uses_previous_session_before_close(monkeypatch):
    class Morning(worker.datetime):
        @classmethod
        def now(cls):
            return cls(2026, 7, 27, 14, 30)

    calendar = SimpleNamespace(
        latest_completed_trade_day=lambda value=None: "2026-07-24",
    )
    monkeypatch.setattr(worker, "datetime", Morning)
    monkeypatch.setattr(worker, "get_calendar", lambda: calendar)
    assert worker._latest_completed_trade_day() == "2026-07-24"


def test_strategy_iteration_due_when_research_version_changes(tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    latest = _write(tmp_path, "strategy_iterations/latest.json", {
        "research_version": "old",
    })
    assert worker._strategy_iteration_due(cfg, latest, []) is True


def test_market_regime_due_when_schema_version_changes(tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    path = _write(tmp_path, "market_regime/five_year.json", {"version": "old"})
    stock_index = _write(tmp_path, "stocks/index.json", {})
    assert worker._market_regime_due(cfg, path, stock_index) is True


def test_sector_data_due_when_rotation_lags(tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    sector_status = _write(tmp_path, "sector_data/status.json", {
        "version": worker.SECTOR_DATA_VERSION,
        "status": "complete",
        "latest_trade_date": "2026-07-29",
    })
    _write(tmp_path, "sector_data/rotation.json", {"trade_date": "2026-07-29"})
    stock_index = _write(tmp_path, "stocks/index.json", {"trade_date": "2026-09-11"})
    assert worker._sector_data_due(cfg, sector_status, stock_index) is True
    _write(tmp_path, "sector_data/status.json", {
        "version": worker.SECTOR_DATA_VERSION,
        "status": "complete",
        "latest_trade_date": "2026-07-29",
        "attempted_trade_date": "2026-09-11",
    })
    assert worker._sector_data_due(cfg, sector_status, stock_index) is False
    _write(tmp_path, "sector_data/rotation.json", {"trade_date": "2026-09-11"})
    _write(tmp_path, "sector_data/status.json", {
        "version": worker.SECTOR_DATA_VERSION,
        "status": "complete",
        "latest_trade_date": "2026-09-11",
        "attempted_trade_date": "2026-09-11",
    })
    assert worker._sector_data_due(cfg, sector_status, stock_index) is False


def test_market_regime_due_when_latest_trade_date_lags(tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    path = _write(tmp_path, "market_regime/five_year.json", {
        "version": worker.MARKET_REGIME_VERSION,
        "latest_trade_date": "2026-08-05",
        "items": [{"date": "2026-08-05", "regime": "range"}],
    })
    stock_index = _write(tmp_path, "stocks/index.json", {"trade_date": "2026-09-03"})
    # Make regime file look newer than stock_index so mtime alone would skip refresh.
    path.touch()
    assert worker._market_regime_due(cfg, path, stock_index) is True
    _write(tmp_path, "market_regime/five_year.json", {
        "version": worker.MARKET_REGIME_VERSION,
        "latest_trade_date": "2026-09-03",
        "items": [{"date": "2026-09-03", "regime": "range"}],
    })
    assert worker._market_regime_due(cfg, path, stock_index) is False


def test_strategy_waiting_state_explains_anti_overfit_pause(tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    _write(tmp_path, "strategy_iterations/latest.json", {
        "run_id": "run-1", "research_version": "10.0.0",
        "promotion_passed": False, "decision": "reject_keep_current_research_only",
    })
    state = worker._strategy_waiting_state(cfg, [])
    assert state["state"] == "waiting_for_new_oos_or_preregistered_research_version"
    assert "禁止" in state["reason"]


def test_public_financial_due_once_per_as_of_day(monkeypatch, tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    assert worker._public_financial_due(cfg) is True
    today = worker.datetime.now().date().isoformat()
    period = worker._period()
    _write(tmp_path, "point_in_time_financials/status.json", {
        "period": f"{period[:4]}-{period[4:6]}-{period[6:]}",
        "as_of": today,
    })
    assert worker._public_financial_due(cfg) is False
