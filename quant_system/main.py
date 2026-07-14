#!/usr/bin/env python3
"""量化系统启动入口。"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保项目根目录在 PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_system.apps.cli import build_parser, execute_command
from quant_system.monitoring.task_runs import TaskRunRecorder


def main() -> None:
    args = build_parser().parse_args()
    command = args.command or "help"
    recorder = TaskRunRecorder(command=command, argv=sys.argv[1:])
    recorder.start()
    try:
        execute_command(args)
    except SystemExit as exc:
        status = "success" if exc.code in (0, None) else "failed"
        recorder.finish(status=status, error=exc if status == "failed" else None)
        raise
    except BaseException as exc:
        recorder.finish(status="failed", error=exc)
        raise
    else:
        status = "skipped" if command == "help" else "success"
        recorder.finish(status=status)


if __name__ == "__main__":
    main()
