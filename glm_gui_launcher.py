#!/usr/bin/env python3
"""
GLM Standalone IDE - Single-Process Native GUI Launcher
- 子プロセス再帰起動・コンソール無限生成・ブラウザ連鎖を物理的に根絶
- バックエンドコア (8765) と Web UI 配信を同一プロセス内スレッドで一括起動
- MS Edge App Mode による単一アプリケーションウィンドウ起動
"""

import atexit
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import socket
from pathlib import Path

# パス設定
if getattr(sys, "frozen", False):
    SCRIPT_DIR = Path(sys._MEIPASS).resolve()
    default_workspace = Path.home() / "Desktop" / "新しいフォルダー"
else:
    SCRIPT_DIR = Path(__file__).parent.resolve()
    default_workspace = Path.home() / "Desktop" / "新しいフォルダー"

WORKING_DIR = Path(os.environ.get("GLM_STANDALONE_WORKSPACE", str(default_workspace))).expanduser().resolve()
WORKING_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(SCRIPT_DIR))

from glm_ide_core import start_unified_server, CORE_PORT

server_instance = None
service_instance = None
server_thread = None


def start_backend():
    global server_instance, service_instance, server_thread
    # 同一プロセス内の別スレッドで統合バックエンド (Port 8765) を起動
    for port in (CORE_PORT, 8775, 8785):
        try:
            server_instance, service_instance = start_unified_server(str(WORKING_DIR), port)
            break
        except OSError:
            server_instance = None
            service_instance = None
    if server_instance is None:
        raise RuntimeError("GLM Coreを起動できません。8765/8775/8785が使用中です。")
    server_thread = threading.Thread(target=server_instance.serve_forever, daemon=True)
    server_thread.start()

    # ヘルスとHTML配信を確認するまでアプリ画面を開かない
    for _ in range(10):
        time.sleep(0.5)
        try:
            selected_port = server_instance.server_port
            with urllib.request.urlopen(f"http://127.0.0.1:{selected_port}/health", timeout=1) as resp:
                if resp.status == 200:
                    with urllib.request.urlopen(f"http://127.0.0.1:{selected_port}/", timeout=1) as page:
                        if page.status == 200 and b"GLM" in page.read(4096):
                            return selected_port
        except Exception:
            pass
    raise RuntimeError("GLM Coreの起動確認に失敗しました。")


def shutdown_all():
    global server_instance, service_instance, server_thread
    if service_instance:
        try:
            service_instance.shutdown()
        except Exception:
            pass
    if server_instance:
        try:
            server_instance.shutdown()
        except Exception:
            pass
        try:
            server_instance.server_close()
        except Exception:
            pass
    if server_thread and server_thread.is_alive():
        server_thread.join(timeout=3)
    server_thread = None


atexit.register(shutdown_all)


def launch_single_app_window(url):
    """MS Edge --app モードで独立ウィンドウを 1 つだけ開く"""
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
        # 同期実行（ウィンドウが閉じられたら復帰）
        proc = subprocess.Popen(cmd)
        proc.wait()
    else:
        # デフォルトブラウザで開く
        subprocess.run(["powershell", "-Command", f"Start-Process '{url}'"])
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


def main():
    try:
        port = start_backend()
        url = f"http://127.0.0.1:{port}/"
        launch_single_app_window(url)
    except Exception as error:
        if getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(error), "GLM Standalone IDE", 0x10)
        else:
            raise
    finally:
        shutdown_all()


if __name__ == "__main__":
    main()
