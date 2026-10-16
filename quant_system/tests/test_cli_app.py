from __future__ import annotations

from argparse import Namespace

import quant_system.apps.cli as cli
import quant_system.apps.commands as commands
import quant_system.apps.pipeline as pipeline
from quant_system.main import _redacted_argv


def test_tickflow_key_is_redacted_from_task_log() -> None:
    assert _redacted_argv(["config", "--tickflow-key", "secret", "--tickflow-base-url", "x"]) == [
        "config", "--tickflow-key", "***", "--tickflow-base-url", "x",
    ]
    assert _redacted_argv(["config", "--tushare-token", "secret"]) == [
        "config", "--tushare-token", "***",
    ]


def test_parser_keeps_mvp_alias() -> None:
    args = cli.build_parser().parse_args(["mvp"])

    assert args.command == "mvp"


def test_removed_phase1_command_is_not_exposed() -> None:
    parser = cli.build_parser()

    try:
        parser.parse_args(["phase1-data"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("phase1-data must remain internal to the all pipeline")


def test_all_pipeline_starts_with_phase1_data(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(pipeline, "run_phase1_market_data", lambda: calls.append("phase1"))

    def stop_after_phase1(*args, **kwargs):
        calls.append("inspect")
        raise RuntimeError("stop")

    monkeypatch.setattr(pipeline, "run_data_inspect", stop_after_phase1)

    try:
        pipeline.run_all_pipeline()
    except RuntimeError as exc:
        assert str(exc) == "stop"
    else:
        raise AssertionError("test sentinel was not reached")

    assert calls == ["phase1", "inspect"]


def test_mvp_dispatch_uses_pipeline(monkeypatch) -> None:
    called = {}

    def fake_run_mvp_pipeline(**kwargs):
        called["kwargs"] = kwargs

    monkeypatch.setattr(commands, "run_mvp_pipeline", fake_run_mvp_pipeline)

    commands.execute_command(Namespace(command="mvp"))

    assert called["kwargs"] == {"skip_inspect": False}


def test_all_dispatch_forwards_skip_flags(monkeypatch) -> None:
    called = {}

    def fake_run_all_pipeline(**kwargs):
        called["kwargs"] = kwargs

    monkeypatch.setattr(commands, "run_all_pipeline", fake_run_all_pipeline)

    commands.execute_command(
        Namespace(
            command="all",
            skip_inspect=True,
            skip_backtest=False,
            skip_predict=True,
            skip_sentiment=False,
            skip_enhance=True,
        )
    )

    assert called["kwargs"] == {
        "skip_inspect": True,
        "skip_backtest": False,
        "skip_predict": True,
        "skip_sentiment": False,
        "skip_enhance": True,
    }


def test_unknown_command_prints_help(capsys) -> None:
    commands.execute_command(Namespace(command=None))

    captured = capsys.readouterr()
    assert "A股量化数据采集系统" in captured.out
