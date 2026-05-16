#!/bin/zsh
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

if [ ! -x ".venv/bin/python" ]; then
  echo "没有找到项目里的 Python 3.14 环境。"
  echo "请先配置 .venv 后再启动。"
  read "?按回车退出..."
  exit 1
fi

".venv/bin/python" run_mobile.py
