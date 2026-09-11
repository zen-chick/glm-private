#!/usr/bin/env python3
"""
GLM Standalone IDE Daemon (統合プロセス & ワークスペース API マネージャー)
依存ライブラリ: なし（Python 3.8+ 標準ライブラリのみ）
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from glm_security import GLM_DIR, WorkspaceGuard, AuditLogger, AUTH_FILE, write_heartbeat, STOP_FILE

DEFAULT_IDE_PORT = 8769
ROUTER_PORT = 8765
BROKER_PORT = 8767


class IDEDaemonService:
    def __init__(self, workspace_path: Optional[str] = None):
        self.workspace = Path(workspace_path or Path.cwd()).resolve()
        self.guard = WorkspaceGuard(self.workspace)
        self.audit = AuditLogger()
        self.router_proc: Optional[subprocess.Popen] = None
        self.broker_proc: Optional[subprocess.Popen] = None
        self.watchdog_proc: Optional[subprocess.Popen] = None

    def start_all(self):
        """ルーター、承認ブローカー、監視プロセスを起動"""
        STOP_FILE.unlink(missing_ok=True)
        write_heartbeat(os.getpid(), "ide_daemon_running")

        # 1. Router 起動
        router_script = SCRIPT_DIR / "router.py"
        if router_script.exists():
            self.router_proc = subprocess.Popen(
                [sys.executable, str(router_script), "--port", str(ROUTER_PORT), "--no-watchdog"],
                cwd=str(self.workspace),
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )

        # 2. Approval Broker 起動
        broker_script = SCRIPT_DIR / "glm_approval_broker.py"
        if broker_script.exists():
            self.broker_proc = subprocess.Popen(
                [sys.executable, str(broker_script), "--port", str(BROKER_PORT)],
                cwd=str(self.workspace),
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )

        # 3. Security Watchdog 起動
        sec_script = SCRIPT_DIR / "glm_security.py"
        if sec_script.exists():
            self.watchdog_proc = subprocess.Popen(
                [sys.executable, str(sec_script), "--watch", "--pid", str(os.getpid())],
                cwd=str(self.workspace),
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )

    def stop_all(self):
        """全子プロセスの停止"""
        for proc in [self.router_proc, self.broker_proc, self.watchdog_proc]:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()

    def get_status(self) -> dict:
        def check_port(port):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                    return r.status == 200
            except Exception:
                return False

        return {
            "daemon_pid": os.getpid(),
            "workspace": str(self.workspace),
            "router_running": check_port(ROUTER_PORT),
            "broker_running": check_port(BROKER_PORT),
            "timestamp": time.time(),
        }

    def list_files(self) -> list:
        """ワークスペース内のファイルツリーを取得"""
        items = []
        skip_dirs = {".git", "__pycache__", ".venv", "node_modules", ".glm"}
        for root, dirs, files in os.walk(self.workspace):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            rel_root = Path(root).relative_to(self.workspace)
            for f in files:
                if f.startswith(".") or f.endswith((".pyc", ".vsix")):
                    continue
                rel_path = (rel_root / f).as_posix()
                if rel_path.startswith("./"):
                    rel_path = rel_path[2:]
                items.append(rel_path)
            if len(items) >= 500:
                break
        return sorted(items)

    def get_git_diff(self) -> str:
        """ワークスペースの git diff を取得"""
        try:
            r = subprocess.run(
                ["git", "diff", "--no-ext-diff"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=5,
            )
            return r.stdout if r.returncode == 0 else f"Error: {r.stderr}"
        except Exception as e:
            return f"Error running git diff: {e}"


class IDEDaemonHandler(BaseHTTPRequestHandler):
    service: IDEDaemonService

    def log_message(self, *_):
        pass

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health" or self.path == "/api/health":
            self._json({"status": "ok", "service": "glm-ide-daemon"})
        elif self.path == "/api/status":
            self._json(self.service.get_status())
        elif self.path == "/api/workspace/files":
            self._json({"files": self.service.list_files()})
        elif self.path == "/api/git/diff":
            self._json({"diff": self.service.get_git_diff()})
        else:
            self.send_response(404)
            self._cors_headers()
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/workspace/read":
            content_len = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_len) if content_len else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
                rel_path = payload.get("path", "")
                target = self.service.guard.require_contained(self.service.workspace / rel_path)
                if not target.exists() or not target.is_file():
                    self._json({"error": "File not found"}, 404)
                    return
                content = target.read_text(encoding="utf-8-sig", errors="replace")
                self._json({"path": rel_path, "content": content})
            except PermissionError as e:
                self._json({"error": str(e)}, 403)
            except Exception as e:
                self._json({"error": str(e)}, 500)
        else:
            self.send_response(404)
            self._cors_headers()
            self.end_headers()


def main():
    parser = argparse.ArgumentParser(description="GLM Standalone IDE Daemon")
    parser.add_argument("--port", type=int, default=DEFAULT_IDE_PORT)
    parser.add_argument("--workspace", type=str, default=None)
    args = parser.parse_args()

    service = IDEDaemonService(args.workspace)
    IDEDaemonHandler.service = service

    service.start_all()
    server = HTTPServer(("127.0.0.1", args.port), IDEDaemonHandler)
    print(f"GLM IDE Daemon running at http://127.0.0.1:{args.port}")
    print(f"Workspace: {service.workspace}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping GLM IDE Daemon...")
        service.stop_all()
        server.server_close()


if __name__ == "__main__":
    main()
