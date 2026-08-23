#!/usr/bin/env python3
"""Create an isolated environment and launch WeRSS.

This script intentionally uses only the Python standard library so it can run
before project dependencies have been installed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
MIN_PYTHON = (3, 10)


def dependency_fingerprint(*paths: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def venv_python(venv_dir: Path = VENV_DIR) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run(command: list[str]) -> None:
    printable = " ".join(command)
    print(f"  > {printable}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def ensure_runtime() -> Path:
    if sys.version_info < MIN_PYTHON:
        required = ".".join(map(str, MIN_PYTHON))
        current = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise RuntimeError(f"需要 Python {required} 或更高版本，当前版本为 {current}")

    python = venv_python()
    if not python.exists():
        print("[1/3] 正在创建独立运行环境…", flush=True)
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
    else:
        print("[1/3] 独立运行环境已就绪", flush=True)

    requirements = ROOT / "requirements.txt"
    version_file = ROOT / "VERSION"
    fingerprint = dependency_fingerprint(requirements, version_file)
    marker = VENV_DIR / ".werss-ready"
    installed = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    if installed != fingerprint:
        print("[2/3] 正在安装运行依赖，首次运行可能需要几分钟…", flush=True)
        run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)])
        print("[3/3] 正在安装链接识别所需的 Chromium…", flush=True)
        run([str(python), "-m", "playwright", "install", "chromium"])
        marker.write_text(fingerprint, encoding="utf-8")
    else:
        print("[2/3] 运行依赖已是最新", flush=True)
        print("[3/3] Chromium 已就绪", flush=True)
    return python


def open_when_ready(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                if response.status == 200:
                    print(f"\n管理页面：{url}", flush=True)
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.4)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="一键安装并启动 WeRSS")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8080, help="监听端口，默认 8080")
    parser.add_argument("--no-open", action="store_true", help="启动后不自动打开浏览器")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print("\n====================================")
    print("  WeRSS 一键安装与启动")
    print("====================================\n")
    try:
        python = ensure_runtime()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"\n安装没有完成：{exc}", file=sys.stderr)
        print("请检查网络连接和 Python 版本后重新运行。", file=sys.stderr)
        return 1

    browser_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{browser_host}:{args.port}"
    command = [
        str(python),
        str(ROOT / "web_app.py"),
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    print("\n正在启动 WeRSS，按 Ctrl+C 可以停止。\n", flush=True)
    process = subprocess.Popen(command, cwd=ROOT)
    if not args.no_open:
        threading.Thread(target=open_when_ready, args=(url, process), daemon=True).start()
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            return process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
