#!/usr/bin/env python3
"""Start the local Lightmail app. Default mode never touches a real account."""
import argparse
from pathlib import Path
import signal
import threading
import webbrowser

from gmail_unsubscriber.application import Application
from gmail_unsubscriber.server import LocalServer
from gmail_unsubscriber.runtime import InstanceLock


def main():
    parser = argparse.ArgumentParser(description="轻邮 · 本机 Gmail 订阅整理工作台")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--demo", action="store_true", help="合成演示邮箱（默认，不访问真实邮箱）")
    modes.add_argument("--live", action="store_true", help="真实邮箱模式；需在界面中明确点击连接")
    parser.add_argument("--port", type=int, default=0, help="本机端口，默认自动选择")
    parser.add_argument("--data-dir", type=Path, help="新版本地数据目录")
    parser.add_argument("--credentials", type=Path, default=Path(__file__).parent / "credentials.json", help="Google 桌面 OAuth 客户端凭据，仅连接时读取")
    parser.add_argument("--no-browser", action="store_true", help="只显示地址，不自动打开浏览器")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("端口必须在 0–65535 之间")
    mode = "live" if args.live else "demo"
    data_dir = args.data_dir or Path(__file__).parent / ".local" / f"v2-{mode}"
    try:
        lock = InstanceLock(data_dir)
        lock.__enter__()
    except (RuntimeError, OSError) as exc:
        parser.exit(1, f"无法启动：{exc}\n")
    application = None
    server = None
    try:
        application = Application(data_dir, mode, args.credentials)
        server = LocalServer(application, args.port)
    except Exception:
        if application is not None:
            application.close()
        lock.__exit__()
        parser.exit(1, "Startup failed [startup_failed]. Check the data directory and port. See docs/V2_USAGE.md.\n")
    def stop(*_):
        print("Stopping: waiting for the current operation; sent requests cannot be recalled.", flush=True)
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"轻邮 · {'演示邮箱（无真实网络操作）' if mode == 'demo' else '真实邮箱模式（等待你点击连接）'}", flush=True)
    print(f"打开 {server.origin}", flush=True)
    print("在此终端按 Control+C 关闭应用。不会安装后台服务。", flush=True)
    if not args.no_browser:
        webbrowser.open(server.origin)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        application.close()
        server.server_close()
        lock.__exit__()


if __name__ == "__main__":
    main()
