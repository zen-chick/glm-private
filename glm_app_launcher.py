#!/usr/bin/env python3
"""
GLM Standalone IDE - Native GUI Launcher (Single Process, No Console Window)
- コンソール黒画面の無限生成・ループを物理的に根絶
- 単一ポート(8765) 統合バックエンドコアを内部スレッド/直接呼び出し
- MS Edge App Mode または Webview2 による完全独立アプリケーションウィンドウ
- アプリウィンドウ終了時の一括シャットダウン (Process & Threads Cleanup)
"""

import atexit
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# パス設定
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from glm_ide_core import start_unified_server, CORE_PORT

server_instance = None
service_instance = None


def start_backend_and_web():
    global server_instance, service_instance

    # 1. 統合バックエンドコア (Port 8765) の内部起動
    server_instance, service_instance = start_unified_server(str(SCRIPT_DIR), CORE_PORT)
    server_thread = threading.Thread(target=server_instance.serve_forever, daemon=True)
    server_thread.start()

    # Unified Coreが静的フロントエンドも同一オリジンから配信する
    for _ in range(10):
        time.sleep(0.3)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{CORE_PORT}/health", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:
            pass


def shutdown_all():
    """アプリ終了時の一括シャットダウン処理"""
    global server_instance, service_instance
    print("Executing GLM Standalone IDE All-in-One Shutdown...")

    if service_instance:
        try:
            service_instance.shutdown()
        except Exception:
            pass

    if server_instance:
        try:
            server_instance.server_close()
        except Exception:
            pass

atexit.register(shutdown_all)


def launch_native_window(url):
    """MS Edge App Mode を使用し、アドレスバー・タブ・コンソールのない独立ウィンドウで起動"""
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge_bin = next((p for p in edge_paths if os.path.exists(p)), None)

    if edge_bin:
        cmd = [
            edge_bin,
            f"--app={url}",
            "--name=GLM Standalone IDE",
            "--window-size=1360,860",
            f"--user-data-dir={Path.home() / '.glm' / 'edge_profile'}"
        ]
        # ウィンドウをブロック同期で起動（ウィンドウが閉じられたらプログラム終了）
        proc = subprocess.Popen(cmd)
        proc.wait()
    else:
        # フォールバック：デフォルトブラウザで起動して終了待機
        subprocess.run(["powershell", "-Command", f"Start-Process '{url}'"])
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


def main():
    start_backend_and_web()
    url = f"http://127.0.0.1:{CORE_PORT}/"
    try:
        launch_native_window(url)
    finally:
        shutdown_all()


if __name__ == "__main__":
    main()
