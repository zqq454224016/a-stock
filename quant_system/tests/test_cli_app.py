from __future__ import annotations

from argparse import Namespace

import quant_system.apps.cli as cli
import quant_system.apps.commands as commands


def test_parser_keeps_mvp_alias() -> None:
    args = cli.build_parser().parse_args(["mvp"])

    assert args.command == "mvp"


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
