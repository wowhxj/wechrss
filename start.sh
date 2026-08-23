#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "未检测到 Python 3.10 或更高版本。"
  echo "请先通过系统包管理器或 https://www.python.org/downloads/ 安装 Python。"
  exit 1
fi

exec python3 scripts/bootstrap.py "$@"
