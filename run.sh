#!/usr/bin/env bash
# 绕过 zsh「python」alias，始终使用项目 .venv
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$ROOT/.venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
  echo "未找到 .venv，请先运行: ./setup.sh"
  exit 1
fi

exec "$VENV_PY" "$ROOT/quant_system/main.py" "$@"
