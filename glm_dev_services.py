#!/usr/bin/env python3
"""Optional development services with stdlib-only fallbacks."""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import socket
import re
import struct
import itertools
import time
from pathlib import Path

from glm_security import GLM_DIR, WorkspaceGuard

try:
    from jupyter_client import KernelManager
except ImportError:
    KernelManager = None


class LanguageService:
    """Python AST diagnostics, symbols, and definition lookup."""

    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.guard = WorkspaceGuard(self.workspace)

    def type_diagnostics(self, rel_path):
        target = self.guard.require_contained(self.workspace / rel_path)
        if target.suffix.lower() != ".py":
            return {"ok": True, "path": rel_path, "diagnostics": [], "engine": "pyright"}
        pyright = Path(__file__).resolve().parent / "ide-web" / "node_modules" / ".bin" / ("pyright.cmd" if os.name == "nt" else "pyright")
        if not pyright.exists():
            return {"ok": False, "path": rel_path, "diagnostics": [], "engine": "pyright", "error": "Pyright is not installed"}
        try:
            result = subprocess.run([str(pyright), str(target), "--outputjson", "--level", "warning"],
                                    cwd=str(self.workspace), capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=30)
            payload = json.loads(result.stdout or "{}")
            diagnostics = []
            for item in payload.get("generalDiagnostics", []):
                range_data = item.get("range", {})
                start = range_data.get("start", {})
                diagnostics.append({"line": start.get("line", 0) + 1, "column": start.get("character", 0) + 1,
                                    "message": item.get("message", ""), "severity": item.get("severity", "error"),
                                    "rule": item.get("rule", "")})
            return {"ok": not diagnostics, "path": rel_path, "diagnostics": diagnostics, "engine": "pyright"}
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            return {"ok": False, "path": rel_path, "diagnostics": [], "engine": "pyright", "error": str(error)}

    def diagnostics(self, rel_path, content=None):
        target = self.guard.require_contained(self.workspace / rel_path)
        text = content if content is not None else target.read_text(encoding="utf-8-sig", errors="replace")
        diagnostics = []
        if target.suffix.lower() == ".py":
            try:
                ast.parse(text, filename=str(target))
            except SyntaxError as error:
                diagnostics.append({"line": error.lineno or 1, "column": error.offset or 1, "message": error.msg, "severity": "error"})
        elif target.suffix.lower() == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as error:
                diagnostics.append({"line": error.lineno, "column": error.colno, "message": error.msg, "severity": "error"})
        return {"ok": not diagnostics, "path": rel_path, "diagnostics": diagnostics}

    def symbols(self, rel_path, content=None):
        target = self.guard.require_contained(self.workspace / rel_path)
        text = content if content is not None else target.read_text(encoding="utf-8-sig", errors="replace")
        result = []
        if target.suffix.lower() == ".py":
            try:
                tree = ast.parse(text, filename=str(target))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        result.append({"name": node.name, "kind": type(node).__name__, "line": node.lineno, "column": node.col_offset + 1})
            except SyntaxError:
                pass
        return {"ok": True, "path": rel_path, "symbols": sorted(result, key=lambda item: item["line"])}

    def completions(self, rel_path, prefix="", content=None):
        target = self.guard.require_contained(self.workspace / rel_path)
        text = content if content is not None else target.read_text(encoding="utf-8-sig", errors="replace")
        names = {"True", "False", "None", "self", "str", "int", "float", "list", "dict", "set", "len", "print", "range"}
        if target.suffix.lower() == ".py":
            try:
                tree = ast.parse(text, filename=str(target))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        names.add(node.name)
                    elif isinstance(node, ast.Name):
                        names.add(node.id)
                    elif isinstance(node, ast.alias):
                        names.add(node.asname or node.name.split(".")[0])
            except SyntaxError:
                pass
        prefix = str(prefix or "")
        return {"ok": True, "path": rel_path, "items": [
            {"label": name, "kind": "variable"} for name in sorted(names) if name.startswith(prefix)
        ]}

    def references(self, rel_path, name, content=None):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*", name):
            return {"ok": False, "error": "invalid symbol name", "references": []}
        target = self.guard.require_contained(self.workspace / rel_path)
        if content is not None:
            files = [(target, content)]
        else:
            files = []
            for path in self.workspace.rglob("*.py"):
                try:
                    path = self.guard.require_contained(path)
                    files.append((path, path.read_text(encoding="utf-8-sig", errors="replace")))
                except (OSError, PermissionError):
                    continue
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        references = []
        for path, text in files:
            rel = path.relative_to(self.workspace).as_posix()
            for line_number, line in enumerate(text.splitlines(), 1):
                for match in pattern.finditer(line):
                    references.append({"path": rel, "line": line_number, "column": match.start() + 1})
        return {"ok": True, "path": rel_path, "name": name, "references": references}

    def rename(self, rel_path, name, new_name, content=None):
        if not re.fullmatch(r"[A-Za-z_]\w*", name or "") or not re.fullmatch(r"[A-Za-z_]\w*", new_name or ""):
            return {"ok": False, "error": "invalid symbol name", "edits": []}
        result = self.references(rel_path, name, content)
        if not result["ok"]:
            return result
        edits = []
        for reference in result["references"]:
            edits.append({**reference, "new_text": new_name})
        return {"ok": True, "path": rel_path, "name": name, "new_name": new_name, "edits": edits}


class TerminalService:
    """統合ターミナル: ワークスペースをcwdとするPowerShellプロセスを入出力パイプで駆動する。

    stdlibのみで動作する簡易PTY相当。UIは /api/terminal/* 経由で入出力する。
    """

    _MAX_CHUNKS = 2000

    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.process = None
        self._chunks = []
        self._base = 0  # 破棄済みチャンク数（cursorの絶対位置管理用）
        self._lock = threading.Lock()

    def _append(self, text):
        if not text:
            return
        with self._lock:
            self._chunks.append(text)
            if len(self._chunks) > self._MAX_CHUNKS:
                drop = len(self._chunks) - self._MAX_CHUNKS
                self._chunks = self._chunks[drop:]
                self._base += drop

    def _pump(self, stream):
        while True:
            try:
                data = stream.read(4096)
            except (OSError, ValueError):
                return
            if not data:
                return
            for encoding in ("utf-8", "cp932"):
                try:
                    self._append(data.decode(encoding))
                    break
                except UnicodeDecodeError:
                    continue
            else:
                self._append(data.decode("utf-8", errors="replace"))

    def status(self):
        running = bool(self.process and self.process.poll() is None)
        return {"running": running, "pid": self.process.pid if running else None,
                "cwd": str(self.workspace)}

    def start(self):
        with self._lock:
            if self.process and self.process.poll() is None:
                return {"ok": True, "already_running": True, "pid": self.process.pid}
            shell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
            if not shell:
                return {"ok": False, "error": "PowerShellが見つかりません"}
            try:
                self.process = subprocess.Popen(
                    [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"],
                    cwd=str(self.workspace), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
            except OSError as error:
                self.process = None
                return {"ok": False, "error": str(error)}
            self._chunks = []
            self._base = 0
        threading.Thread(target=self._pump, args=(self.process.stdout,), daemon=True).start()
        return {"ok": True, "pid": self.process.pid}

    def write(self, data):
        if not self.process or self.process.poll() is not None:
            return {"ok": False, "error": "ターミナルが起動していません"}
        if not isinstance(data, str):
            return {"ok": False, "error": "data must be a string"}
        if len(data) > 100_000:
            return {"ok": False, "error": "入力が大きすぎます"}
        try:
            self.process.stdin.write(data.encode("utf-8", errors="replace"))
            self.process.stdin.flush()
        except (OSError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True}

    def read(self, since=0):
        with self._lock:
            try:
                since = int(since)
            except (TypeError, ValueError):
                since = 0
            cursor = self._base + len(self._chunks)
            if since < self._base:
                since = self._base  # バッファローテーション: 取りこぼし分は最初から返す
            offset = max(0, since - self._base)
            data = "".join(self._chunks[offset:])
        running = bool(self.process and self.process.poll() is None)
        return {"ok": True, "data": data, "cursor": cursor, "running": running}

    def stop(self):
        with self._lock:
            process = self.process
            self.process = None
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        return {"ok": True}


class JupyterService:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.guard = WorkspaceGuard(self.workspace)
        self.kernel = None
        self.client = None
        self._lock = threading.Lock()
        self.last_execution_count = None

    def status(self):
        available = KernelManager is not None
        running = self.kernel is not None and self.kernel.is_alive()
        return {"available": available, "command": shutil.which("jupyter") if available else None,
            "kernel_running": running,
            "kernel_id": getattr(self.kernel, "kernel_id", None) if running else None,
            "execution_count": self.last_execution_count}

    def start(self):
        if KernelManager is None:
            return {"ok": False, "error": "jupyter_client is not installed. Install it later to enable kernels."}
        if self.kernel is not None and self.kernel.is_alive():
            return {"ok": True, "already_running": True}
        self.kernel = KernelManager()
        self.kernel.start_kernel(cwd=str(self.workspace))
        self.client = self.kernel.client()
        self.client.start_channels()
        self.client.wait_for_ready(timeout=15)
        pid = getattr(getattr(self.kernel, "provisioner", None), "pid", None)
        return {"ok": True, "pid": pid}

    def restart(self):
        with self._lock:
            stopped = self.stop()
            if not stopped.get("ok"):
                return stopped
            return self.start()

    def interrupt(self):
        if self.kernel is None or not self.kernel.is_alive():
            return {"ok": False, "error": "kernel is not running"}
        try:
            self.kernel.interrupt_kernel()
            return {"ok": True}
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def stop(self):
        if self.kernel is None or not self.kernel.is_alive():
            return {"ok": True, "already_stopped": True}
        if self.client is not None:
            self.client.stop_channels()
        self.kernel.shutdown_kernel(now=True)
        self.client = None
        self.kernel = None
        self.last_execution_count = None
        return {"ok": True}

    def execute(self, source, timeout=30):
        if not isinstance(source, str) or not source.strip():
            return {"ok": False, "error": "source is required"}
        if not 1 <= timeout <= 300:
            return {"ok": False, "error": "timeout must be between 1 and 300"}
        with self._lock:
            started_here = self.kernel is None or not self.kernel.is_alive()
            try:
                if started_here:
                    started = self.start()
                    if not started.get("ok"):
                        return started
                msg_id = self.client.execute(source)
                stdout = []
                stderr = []
                while True:
                    message = self.client.get_iopub_msg(timeout=timeout)
                    if message.get("parent_header", {}).get("msg_id") != msg_id:
                        continue
                    msg_type = message.get("msg_type")
                    content = message.get("content", {})
                    if msg_type == "execute_input":
                        self.last_execution_count = content.get("execution_count")
                    if msg_type == "stream":
                        (stdout if content.get("name") == "stdout" else stderr).append(content.get("text", ""))
                    elif msg_type in {"execute_result", "display_data"}:
                        data = content.get("data", {})
                        if "text/plain" in data:
                            stdout.append(data["text/plain"] + "\n")
                    elif msg_type == "error":
                        stderr.append("\n".join(content.get("traceback", [])) + "\n")
                    elif msg_type == "status" and content.get("execution_state") == "idle":
                        result = {"ok": not bool(stderr),
                                  "stdout": "".join(stdout)[:10000], "stderr": "".join(stderr)[:10000],
                                  "returncode": 0 if not stderr else 1}
                        if started_here:
                            self.stop()
                        return result
            except Exception as error:
                return {"ok": False, "error": f"Kernel execution failed: {error}"}


class DAPService:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.process = None
        self.port = None
        self.client_socket = None
        self._sequence = itertools.count(1)
        self._dap_lock = threading.Lock()
        self._dap_buffer = b""
        self._dap_events = []
        self._dap_responses = {}

    def status(self):
        available = False
        try:
            import debugpy
            available = debugpy is not None
        except ImportError:
            pass
        running = self.process is not None and self.process.poll() is None
        return {"available": available, "kernel_running": running, "port": self.port if running else None,
                "client_connected": self.client_socket is not None,
                "note": "Attach a DAP client to the loopback debugpy endpoint."}

    def _read_dap_message(self, timeout=5):
        self.client_socket.settimeout(timeout)
        while b"\r\n\r\n" not in self._dap_buffer:
            self._dap_buffer += self.client_socket.recv(65536)
        header, self._dap_buffer = self._dap_buffer.split(b"\r\n\r\n", 1)
        match = re.search(rb"Content-Length:\s*(\d+)", header, re.IGNORECASE)
        if not match:
            raise ValueError("DAP response has no Content-Length")
        length = int(match.group(1))
        while len(self._dap_buffer) < length:
            self._dap_buffer += self.client_socket.recv(65536)
        body, self._dap_buffer = self._dap_buffer[:length], self._dap_buffer[length:]
        return json.loads(body.decode("utf-8"))

    def _dap_request(self, command, arguments=None, timeout=10):
        if self.client_socket is None:
            return {"success": False, "message": "DAP client is not connected"}
        with self._dap_lock:
            sequence = self._dap_send_request(command, arguments)
            return self._dap_wait_for_response(sequence, timeout)

    def _dap_send_request(self, command, arguments=None):
        sequence = next(self._sequence)
        body = json.dumps({"seq": sequence, "type": "request", "command": command,
                           "arguments": arguments or {}}, separators=(",", ":")).encode()
        packet = b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        self.client_socket.sendall(packet)
        return sequence

    def _dap_wait_for_response(self, sequence, timeout=10):
        if sequence in self._dap_responses:
            return self._dap_responses.pop(sequence)
        while True:
            message = self._read_dap_message(timeout)
            if message.get("type") == "response" and message.get("request_seq") == sequence:
                return message
            if message.get("type") == "event":
                self._dap_events.append(message)

    def _dap_wait_for_event(self, event_name, timeout=30):
        for index, event in enumerate(self._dap_events):
            if event.get("event") == event_name:
                return self._dap_events.pop(index)
        while True:
            message = self._read_dap_message(timeout)
            if message.get("type") == "event":
                if message.get("event") == event_name:
                    return message
                self._dap_events.append(message)
            elif message.get("type") == "response":
                self._dap_responses[message.get("request_seq")] = message

    def connect_client(self):
        if self.client_socket is not None:
            return {"ok": True, "already_connected": True}
        if self.port is None or self.process is None or self.process.poll() is not None:
            return {"ok": False, "error": "DAP process is not running"}
        try:
            last_error = None
            for _ in range(20):
                try:
                    self.client_socket = socket.create_connection(("127.0.0.1", self.port), timeout=1)
                    break
                except OSError as error:
                    last_error = error
                    time.sleep(0.1)
            if self.client_socket is None:
                raise last_error or OSError("DAP port is unavailable")
            initialize = self._dap_request("initialize", {"adapterID": "glm", "clientID": "glm-ide",
                                                            "linesStartAt1": True, "columnsStartAt1": True}, timeout=30)
            if not initialize.get("success", False):
                raise RuntimeError(initialize.get("message", "initialize failed"))
            attach_sequence = self._dap_send_request("attach", {"type": "python", "request": "attach",
                                                                  "name": "GLM IDE", "justMyCode": True})
            initialized = self._dap_wait_for_event("initialized", timeout=30)
            if not initialized:
                raise RuntimeError("debugpy did not send initialized event")
            configuration_sequence = self._dap_send_request("configurationDone")
            configuration = self._dap_wait_for_response(configuration_sequence, timeout=30)
            if not configuration.get("success", False):
                raise RuntimeError(configuration.get("message", "configurationDone failed"))
            attach = self._dap_wait_for_response(attach_sequence, timeout=30)
            if not attach.get("success", False):
                raise RuntimeError(attach.get("message", "attach failed"))
            return {"ok": True}
        except (OSError, RuntimeError, ValueError) as error:
            if self.client_socket is not None:
                self.client_socket.close()
            self.client_socket = None
            self.stop()
            return {"ok": False, "error": f"DAP connection failed: {error}"}

    def set_breakpoints(self, rel_path, lines):
        target = WorkspaceGuard(self.workspace).require_contained(self.workspace / rel_path)
        if not isinstance(lines, list) or any(not isinstance(line, int) or line < 1 for line in lines):
            return {"ok": False, "error": "lines must be positive integers"}
        connected = self.connect_client()
        if not connected.get("ok"):
            return connected
        response = self._dap_request("setBreakpoints", {"source": {"path": str(target)},
                                                         "breakpoints": [{"line": line} for line in lines]})
        return {"ok": response.get("success", False), "breakpoints": response.get("body", {}).get("breakpoints", []),
                "error": response.get("message", "")}

    def control(self, command, arguments=None):
        connected = self.connect_client()
        if not connected.get("ok"):
            return connected
        response = self._dap_request(command, arguments)
        return {"ok": response.get("success", False), "body": response.get("body", {}),
                "error": response.get("message", "")}

    def events(self):
        return {"ok": True, "events": list(self._dap_events)}

    def launch(self, rel_path, wait_for_client=True):
        target = WorkspaceGuard(self.workspace).require_contained(self.workspace / rel_path)
        if target.suffix.lower() != ".py":
            return {"ok": False, "error": "DAP launch currently supports Python files only."}
        try:
            import debugpy
        except ImportError:
            return {"ok": False, "error": "debugpy is not installed. DAP launch is disabled."}
        if self.process is not None and self.process.poll() is None:
            return {"ok": True, "already_running": True, "pid": self.process.pid, "port": self.port}
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        command = [sys.executable, "-m", "debugpy", "--listen", f"127.0.0.1:{port}"]
        if wait_for_client:
            command.append("--wait-for-client")
        command.append(str(target))
        try:
            self.process = subprocess.Popen(
                command, cwd=str(self.workspace), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.port = port
            return {"ok": True, "pid": self.process.pid, "port": port,
                    "host": "127.0.0.1", "wait_for_client": wait_for_client}
        except OSError as error:
            self.process = None
            self.port = None
            return {"ok": False, "error": f"DAP launch failed: {error}"}

    def stop(self):
        if self.process is None or self.process.poll() is not None:
            return {"ok": True, "already_stopped": True}
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                           capture_output=True, check=False)
        else:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        self.process = None
        self.port = None
        if self.client_socket is not None:
            self.client_socket.close()
        self.client_socket = None
        self._dap_buffer = b""
        return {"ok": True}


class SFTPService:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.profile_file = GLM_DIR / "sftp_profiles.json"

    def status(self):
        return {"available": bool(shutil.which("sftp")), "command": shutil.which("sftp"), "mode": "non-interactive list/upload/download"}

    def list_profiles(self):
        try:
            if not self.profile_file.exists() or self.profile_file.is_symlink():
                return {"ok": True, "profiles": []}
            data = json.loads(self.profile_file.read_text(encoding="utf-8-sig"))
            return {"ok": True, "profiles": data if isinstance(data, list) else []}
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "error": "SFTP profile file is invalid", "profiles": []}

    def save_profile(self, name, host, user=None, port=22, remote_path="."):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
            return {"ok": False, "error": "invalid profile name"}
        error = self._validate_connection(host, remote_path, port)
        if error:
            return {"ok": False, "error": error}
        profile = {"name": name, "host": host, "user": user or "", "port": int(port), "remote_path": remote_path}
        listed = self.list_profiles()
        if not listed["ok"]:
            return listed
        profiles = [item for item in listed["profiles"] if item.get("name") != name]
        profiles.append(profile)
        GLM_DIR.mkdir(parents=True, exist_ok=True)
        temp_file = self.profile_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_file.replace(self.profile_file)
        try:
            os.chmod(self.profile_file, 0o600)
        except OSError:
            pass
        return {"ok": True, "profile": profile}

    def delete_profile(self, name):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
            return {"ok": False, "error": "invalid profile name"}
        listed = self.list_profiles()
        if not listed["ok"]:
            return listed
        profiles = [item for item in listed["profiles"] if item.get("name") != name]
        self.profile_file.parent.mkdir(parents=True, exist_ok=True)
        self.profile_file.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(self.profile_file, 0o600)
        except OSError:
            pass
        return {"ok": True, "deleted": name, "profiles": profiles}

    @staticmethod
    def _validate_connection(host, remote_path, port):
        if not host or not remote_path:
            return "host and remote_path are required"
        if any(not isinstance(value, str) or not value or value.startswith("-") or any(char in value for char in "\r\n\x00")
               for value in (host, remote_path)):
            return "invalid host or remote path"
        try:
            port = int(port)
        except (TypeError, ValueError):
            return "port must be an integer"
        if not 1 <= port <= 65535:
            return "port must be between 1 and 65535"
        return None

    @staticmethod
    def _validate_user(user):
        if user is None or user == "":
            return None
        if not isinstance(user, str) or user.startswith("-") or any(char in user for char in "\r\n\x00@"):
            return "invalid user name"
        return None

    def _run_batch(self, host, batch, user=None, port=22):
        if not shutil.which("sftp"):
            return {"ok": False, "error": "OpenSSH sftp is not installed"}
        destination = f"{user}@{host}" if user else host
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as batch_file:
            batch_file.write(batch)
            batch_path = batch_file.name
        try:
            result = subprocess.run(["sftp", "-b", batch_path, "-P", str(int(port)), destination],
                                    cwd=str(self.workspace), capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=60)
            return {"ok": result.returncode == 0, "stdout": result.stdout[-10000:], "stderr": result.stderr[-10000:]}
        finally:
            Path(batch_path).unlink(missing_ok=True)

    def list_remote(self, host, remote_path=".", user=None, port=22):
        error = self._validate_connection(host, remote_path, port)
        error = error or self._validate_user(user)
        if error:
            return {"ok": False, "error": error, "entries": []}
        result = self._run_batch(host, f"ls -1 {remote_path}\n", user, port)
        result["entries"] = [line.strip() for line in result.get("stdout", "").splitlines() if line.strip()]
        return result

    def test_connection(self, host, user=None, port=22):
        error = self._validate_connection(host, ".", port) or self._validate_user(user)
        if error:
            return {"ok": False, "error": error}
        return self._run_batch(host, "pwd\n", user, port)

    def download(self, host, remote_path, local_path, user=None, port=22):
        error = self._validate_connection(host, remote_path, port)
        error = error or self._validate_user(user)
        if error or not local_path:
            return {"ok": False, "error": error or "local_path is required"}
        try:
            target = WorkspaceGuard(self.workspace).require_contained(self.workspace / local_path)
        except PermissionError as error:
            return {"ok": False, "error": str(error)}
        if not isinstance(local_path, str) or local_path.startswith("-") or any(char in local_path for char in "\r\n\x00"):
            return {"ok": False, "error": "option-like paths are rejected"}
        target.parent.mkdir(parents=True, exist_ok=True)
        return self._run_batch(host, f"get {remote_path} {target}\n", user, port)

    def upload(self, host, local_path, remote_path, user=None, port=22):
        error = self._validate_connection(host, remote_path, port)
        error = error or self._validate_user(user)
        if error or not local_path:
            return {"ok": False, "error": error or "local_path is required"}
        try:
            source = WorkspaceGuard(self.workspace).require_contained(self.workspace / local_path)
        except PermissionError as error:
            return {"ok": False, "error": str(error)}
        if not source.is_file():
            return {"ok": False, "error": "local file not found"}
        if local_path.startswith("-") or any(char in local_path for char in "\r\n\x00"):
            return {"ok": False, "error": "option-like paths are rejected"}
        return self._run_batch(host, f"put {source} {remote_path}\n", user, port)
