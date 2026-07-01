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

if ! .venv-build/bin/python -c "import tkinter" >/dev/null 2>&1; then
  echo "缺少 tkinter（Homebrew 的 python@3.12 默认不含）。"
  echo "请先安装：brew install python-tk@3.12"
  exit 1
fi

.venv-build/bin/python -m pip install --upgrade pip
.venv-build/bin/python -m pip install -r requirements-build.txt
.venv-build/bin/python -m PyInstaller --noconfirm zxgk_tool.spec

APP="dist/被执行人查询助手.app"
echo ""
echo "清理扩展属性并 ad-hoc 重新签名..."
# Homebrew 的 Python.framework 会带 com.apple.FinderInfo，PyInstaller 自带签名会失败；
# 这里清理后手动 ad-hoc 签名。顶层目录的 FinderInfo 可能被 Finder 写回（无害，不影响运行）。
xattr -cr "$APP" 2>/dev/null || true
codesign --force --deep --sign - "$APP" 2>/dev/null || true

echo ""
echo "完成：$APP"
echo "首次打开若被拦截，右键 → 打开，或运行："
echo "  xattr -dr com.apple.quarantine '$APP'"
