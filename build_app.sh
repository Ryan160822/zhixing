#!/bin/zsh
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYBIN="${PYBIN:-/opt/homebrew/bin/python3.12}"
if [ ! -x "$PYBIN" ]; then
  echo "找不到 Python 3.12：$PYBIN"
  echo "请先安装：brew install python@3.12"
  exit 1
fi

if [ ! -x ".venv-build/bin/python" ]; then
  "$PYBIN" -m venv .venv-build
fi

.venv-build/bin/python -m pip install --upgrade pip
.venv-build/bin/python -m pip install -r requirements-build.txt
.venv-build/bin/python -m PyInstaller --noconfirm zxgk_tool.spec

echo ""
echo "完成：dist/被执行人查询助手.app"
echo "首次打开若被拦截，右键 → 打开，或运行："
echo "  xattr -dr com.apple.quarantine 'dist/被执行人查询助手.app'"
