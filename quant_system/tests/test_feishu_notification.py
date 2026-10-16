import json

from quant_system.notifications import feishu


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"code": 0}


def test_notification_sends_and_deduplicates(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(feishu.requests, "post", lambda *args, **kwargs: calls.append(kwargs["json"]) or _Response())
    payload = {"updated_at": "2026-07-27 09:00:00", "status": "round_complete", "actions": [
        {"name": "market_data", "status": "success"},
    ]}
    first = feishu.notify_iteration_progress(
        payload, webhook_url="https://example.test/hook/secret", data_dir=tmp_path,
    )
    second = feishu.notify_iteration_progress(
        payload, webhook_url="https://example.test/hook/secret", data_dir=tmp_path,
    )
    assert first["status"] == "sent"
    assert second["status"] == "skipped"
    assert len(calls) == 1
    assert "market_data" in calls[0]["content"]["text"]
    assert "本轮完成" in calls[0]["content"]["text"]
    stored = json.loads((tmp_path / "notifications/feishu_iteration.json").read_text())
    assert "secret" not in json.dumps(stored)


def test_mid_round_status_waits_until_round_complete(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(feishu.requests, "post", lambda *args, **kwargs: calls.append(1) or _Response())
    skipped = feishu.notify_iteration_progress(
        {"status": "running", "actions": [{"name": "st_events_sz", "status": "success"}]},
        webhook_url="https://example.test/hook/secret",
        data_dir=tmp_path,
    )
    assert skipped == {"status": "skipped", "reason": "await_round_complete"}
    assert calls == []


def test_eta_timestamp_drift_does_not_re_notify(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(feishu.requests, "post", lambda *args, **kwargs: calls.append(1) or _Response())
    base = {
        "status": "round_complete",
        "actions": [{"name": "iteration_audit", "status": "success", "result_status": None}],
        "strategy_iteration_state": {"state": "waiting_for_new_oos_or_preregistered_research_version"},
        "eta": {
            "current_iteration_expected_at": "2026-09-18 19:00:00",
            "stages": [{"name": "当前后台迭代轮次", "status": "running", "expected_at": "2026-09-18 19:00:00", "confidence": "medium"}],
        },
    }
    first = feishu.notify_iteration_progress(base, webhook_url="https://example.test/hook", data_dir=tmp_path)
    drifted = {
        **base,
        "eta": {
            "current_iteration_expected_at": "2026-09-18 19:05:00",
            "stages": [{"name": "当前后台迭代轮次", "status": "running", "expected_at": "2026-09-18 19:05:00", "confidence": "medium"}],
        },
    }
    second = feishu.notify_iteration_progress(drifted, webhook_url="https://example.test/hook", data_dir=tmp_path)
    assert first["status"] == "sent"
    assert second["status"] == "skipped"
    assert len(calls) == 1
