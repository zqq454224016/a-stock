#!/usr/bin/env bash
# macOS + Homebrew：使用 python / pip（非 python3）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Homebrew python@3.12 提供 python / pip，需加入 PATH
BREW_PYTHON_BIN="/opt/homebrew/opt/python@3.12/libexec/bin"
if [[ -d "$BREW_PYTHON_BIN" ]]; then
  export PATH="$BREW_PYTHON_BIN:$PATH"
fi

if ! command -v python &>/dev/null; then
  echo "未找到 python 命令。请先安装 Homebrew Python："
  echo "  brew install python@3.12"
  echo ""
  echo "并在 ~/.zshrc 中加入："
  echo '  export PATH="/opt/homebrew/opt/python@3.12/libexec/bin:$PATH"'
  exit 1
fi

echo "→ 使用 $(which python) ($(python --version))"
echo "→ 创建虚拟环境 .venv"
python -m venv .venv

echo "→ 激活虚拟环境并安装依赖"
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r script/requirements.txt

echo ""
echo "✓ 环境就绪。后续请在项目根目录执行："
echo ""
echo "  source .venv/bin/activate"
echo "  python script/fetch_data.py --mock"
echo "  python script/gen_report.py"
echo "  python -m http.server 8080"
echo ""
