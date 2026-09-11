#!/usr/bin/env python3
"""防御目的の隔離ランナー。未隔離のWindowsホスト上ではコードを実行しない。"""

import json
import os
import re
import shlex
import stat
import uuid
import subprocess
import threading
import tempfile
import shutil
from pathlib import Path

from glm_security import WorkspaceGuard, MAX_RESPONSE_CHARS, DEFAULT_MAX_CONCURRENT_SANDBOX


CONFIG_FILE = Path(__file__).parent / "sandbox.json"
DEFAULT_DISTRO = "GLM-Sandbox"
DEFAULT_MAX_PROCESSES = 32
DEFAULT_MEMORY_KB = 524288  # 512MB
_CONCURRENCY_LOCK = threading.Lock()
_CONCURRENCY_SEMAPHORES = {}


def decode_process_output(value):
    """Decode Windows/WSL subprocess bytes without relying on the console code page."""
    if not value:
        return ""
    if value.startswith((b"\xff\xfe", b"\xfe\xff")):
        return value.decode("utf-16", errors="replace")
    if value.count(b"\x00") > max(2, len(value) // 8):
        return value.decode("utf-16-le", errors="replace")
    for encoding in ("utf-8", "cp932"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def load_sandbox_config(config_file=CONFIG_FILE):
    try:
        config = json.loads(Path(config_file).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"enabled": False, "runtime": "none", "command": [], "distro": DEFAULT_DISTRO,
                "user": "", "max_concurrent": DEFAULT_MAX_CONCURRENT_SANDBOX, "network_mode": "deny",
                "limits": {"max_processes": DEFAULT_MAX_PROCESSES, "memory_kb": DEFAULT_MEMORY_KB, "hard_timeout_seconds": 300}}
    command = config.get("command", [])
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        command = []
    limits = config.get("limits", {}) if isinstance(config.get("limits"), dict) else {}
    return {
        "enabled": bool(config.get("enabled", False)),
        "runtime": str(config.get("runtime", "none")),
        "command": command,
        "distro": str(config.get("distro", DEFAULT_DISTRO)) or DEFAULT_DISTRO,
        "user": str(config.get("user", "")),
        "max_concurrent": max(1, int(config.get("max_concurrent", DEFAULT_MAX_CONCURRENT_SANDBOX))),
        "network_mode": str(config.get("network_mode", "deny")),
        "limits": {
            "max_processes": int(limits.get("max_processes", DEFAULT_MAX_PROCESSES)),
            "memory_kb": int(limits.get("memory_kb", DEFAULT_MEMORY_KB)),
            "hard_timeout_seconds": int(limits.get("hard_timeout_seconds", 300)),
        },
    }


def _semaphore_for(key, limit):
    with _CONCURRENCY_LOCK:
        semaphore = _CONCURRENCY_SEMAPHORES.get(key)
        if semaphore is None:
            semaphore = threading.Semaphore(limit)
            _CONCURRENCY_SEMAPHORES[key] = semaphore
        return semaphore


class SandboxRunner:
    """Configured isolation runtime via a fixed command template only."""

    def __init__(self, workspace, command_template=None, config_file=CONFIG_FILE):
        self.workspace = Path(workspace).resolve()
        self.guard = WorkspaceGuard(self.workspace)
        config = load_sandbox_config(config_file)
        self.runtime = config["runtime"]
        self.command_template = command_template if command_template is not None else config["command"]
        self.enabled = config["enabled"]
        self.distro = config["distro"]
        self.user = config["user"]
        self.network_mode = config["network_mode"]
        self.limits = config["limits"]
        self._semaphore = _semaphore_for(("wsl2", self.distro), config["max_concurrent"])

    def _available_distros(self):
        try:
            result = subprocess.run(["wsl.exe", "--list", "--quiet"], capture_output=True,
                                    timeout=10)
            return [decode_process_output(line.encode() if isinstance(line, str) else line).strip()
                    for line in decode_process_output(result.stdout).splitlines() if line.strip()]
        except (OSError, subprocess.TimeoutExpired):
            return []

    def runtime_status(self):
        if self.runtime != "wsl2":
            return {"runtime": self.runtime, "available": bool(self.enabled and self.command_template)}
        wsl = shutil.which("wsl.exe")
        if not wsl:
            return {"runtime": "wsl2", "available": False, "error": "wsl.exe is not installed"}
        try:
            distributions = self._available_distros()
            active_distro = self.distro if self.distro in distributions else (distributions[0] if distributions else None)
            degraded = bool(distributions) and active_distro != self.distro
            return {
                "runtime": "wsl2", "available": bool(active_distro),
                "distributions": distributions, "active_distro": active_distro,
                "degraded": degraded,
                "error": None if active_distro else "No WSL distribution is installed",
            }
        except (OSError, subprocess.TimeoutExpired) as error:
            return {"runtime": "wsl2", "available": False, "error": str(error)}

    @staticmethod
    def _wsl_path(path):
        drive = path.drive.rstrip(":").lower()
        return "/mnt/" + drive + path.as_posix()[2:]

    def _build_wsl_command(self, distro, remote_script_path, max_processes, memory_kb):
        """Stage the script via stdin inside the sandbox distro, apply resource limits, run, then remove it."""
        remote_dir = remote_script_path.rsplit("/", 1)[0]
        # シェルインジェクション対策: ファイル名由来のパスは必ずshlex.quoteで安全化してから埋め込む。
        quoted_dir = shlex.quote(remote_dir)
        quoted_script = shlex.quote(remote_script_path)
        run_python = f"ulimit -u {max_processes} 2>/dev/null; ulimit -v {memory_kb} 2>/dev/null; python3 {quoted_script}"
        if self.network_mode == "deny":
            # Unprivileged network namespace isolation: only loopback remains reachable.
            run_python = f"unshare --net --map-root-user -- bash -c {shlex.quote(run_python)}"
        script = (
            f"set -e; mkdir -p {quoted_dir}; cat > {quoted_script}; chmod 500 {quoted_script}; "
            f"({run_python}); rc=$?; rm -rf {quoted_dir}; exit $rc"
        )
        command = ["wsl.exe", "-d", distro]
        if self.user:
            command += ["-u", self.user]
        command += ["--", "bash", "-c", script]
        return command

    def run_python_file(self, target, timeout_seconds=30):
        source = self.guard.require_contained(target)
        if source.suffix.lower() != ".py":
            return {"ok": False, "error": "Only Python files are supported."}
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", source.name):
            return {"ok": False, "error": "File name contains unsupported characters."}
        if not 1 <= timeout_seconds <= 300:
            return {"ok": False, "error": "timeout_seconds must be between 1 and 300."}
        if not self.enabled:
            return {
                "ok": False,
                "error": "No enabled isolation runtime is configured; host execution is disabled.",
            }
        acquired = self._semaphore.acquire(timeout=max(1, timeout_seconds))
        if not acquired:
            return {"ok": False, "error": "Too many concurrent sandbox executions; try again shortly."}
        try:
            return self._execute(source, timeout_seconds)
        finally:
            self._semaphore.release()

    def run_shell(self, command, timeout_seconds=30):
        """Run an arbitrary shell command inside the configured isolation runtime.

        The command is staged via stdin as a bash script and executed in a fresh
        temporary directory inside the sandbox (resource limits and network
        isolation applied). It never runs on the Windows host. Fails closed when
        no isolation runtime is enabled.
        """
        if not isinstance(command, str) or not command.strip():
            return {"ok": False, "error": "No command provided."}
        if len(command) > 100_000:
            return {"ok": False, "error": "Command is too large."}
        try:
            timeout_seconds = int(timeout_seconds)
        except (TypeError, ValueError):
            timeout_seconds = 30
        timeout_seconds = max(1, min(timeout_seconds, 300))
        if not self.enabled:
            return {
                "ok": False,
                "error": "No enabled isolation runtime is configured; host execution is disabled.",
            }
        acquired = self._semaphore.acquire(timeout=max(1, timeout_seconds))
        if not acquired:
            return {"ok": False, "error": "Too many concurrent sandbox executions; try again shortly."}
        try:
            return self._execute_shell(command, timeout_seconds)
        finally:
            self._semaphore.release()

    def _execute_shell(self, command, timeout_seconds):
        hard_cap = min(timeout_seconds, self.limits.get("hard_timeout_seconds", 300))
        max_processes = self.limits.get("max_processes", DEFAULT_MAX_PROCESSES)
        memory_kb = self.limits.get("memory_kb", DEFAULT_MEMORY_KB)

        if self.runtime == "wsl2":
            status = self.runtime_status()
            if not status["available"]:
                return {"ok": False, "error": status.get("error", "WSL2 is unavailable")}
            distro = status["active_distro"]
            remote_dir = f"/tmp/glm-shell-{uuid.uuid4().hex}"
            remote_script = f"{remote_dir}/cmd.sh"
            quoted_dir = shlex.quote(remote_dir)
            quoted_script = shlex.quote(remote_script)
            run_script = (
                f"cd {quoted_dir}; "
                f"ulimit -u {max_processes} 2>/dev/null; ulimit -v {memory_kb} 2>/dev/null; "
                f"bash {quoted_script}"
            )
            if self.network_mode == "deny":
                run_script = f"unshare --net --map-root-user -- bash -c {shlex.quote(run_script)}"
            script = (
                f"set -e; mkdir -p {quoted_dir}; cat > {quoted_script}; chmod 500 {quoted_script}; "
                f"({run_script}); rc=$?; rm -rf {quoted_dir}; exit $rc"
            )
            wsl_command = ["wsl.exe", "-d", distro]
            if self.user:
                wsl_command += ["-u", self.user]
            wsl_command += ["--", "bash", "-c", script]
            try:
                wsl_env = {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"), "WSLENV": ""}
                completed = subprocess.run(wsl_command, input=command.encode("utf-8", errors="replace"),
                                           capture_output=True, timeout=hard_cap, env=wsl_env)
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "Sandbox execution timed out."}
            output = (decode_process_output(completed.stdout) + decode_process_output(completed.stderr))[:MAX_RESPONSE_CHARS]
            return {"ok": completed.returncode == 0, "exit_code": completed.returncode, "output": output}

        return {"ok": False, "error": "Shell execution requires the wsl2 isolation runtime."}

    def _execute(self, source, timeout_seconds):
        hard_cap = min(timeout_seconds, self.limits.get("hard_timeout_seconds", 300))
        max_processes = self.limits.get("max_processes", DEFAULT_MAX_PROCESSES)
        memory_kb = self.limits.get("memory_kb", DEFAULT_MEMORY_KB)

        if self.runtime == "wsl2":
            status = self.runtime_status()
            if not status["available"]:
                return {"ok": False, "error": status.get("error", "WSL2 is unavailable")}
            distro = status["active_distro"]
            remote_dir = f"/tmp/glm-sandbox-{uuid.uuid4().hex}"
            command = self._build_wsl_command(distro, f"{remote_dir}/{source.name}", max_processes, memory_kb)
            try:
                # WSLENVを空にし、Windows PATH全体をWSL側へ変換しようとする無関係な警告出力を防ぐ。
                wsl_env = {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"), "WSLENV": ""}
                completed = subprocess.run(command, input=source.read_bytes(), capture_output=True,
                                            timeout=hard_cap, env=wsl_env)
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "Sandbox execution timed out."}
            output = (decode_process_output(completed.stdout) + decode_process_output(completed.stderr))[:MAX_RESPONSE_CHARS]
            return {"ok": completed.returncode == 0, "exit_code": completed.returncode, "output": output}

        if not self.command_template:
            return {"ok": False, "error": "No isolation command is configured."}
        directory = tempfile.mkdtemp(prefix="glm-sandbox-")
        try:
            staged = Path(directory) / source.name
            staged.write_bytes(source.read_bytes())
            staged.chmod(stat.S_IRUSR | stat.S_IXUSR)  # read-only staging: target cannot self-modify during execution
            command = [item.format(script=str(staged), workdir=directory) for item in self.command_template]
            execution_env = os.environ.copy()
            execution_env.update({"TEMP": directory, "TMP": directory})
            try:
                completed = subprocess.run(command, cwd=directory, capture_output=True, text=False,
                                            timeout=hard_cap, env=execution_env)
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "Sandbox execution timed out."}
        finally:
            self._cleanup_directory(directory)
        output = (decode_process_output(completed.stdout) + decode_process_output(completed.stderr))[:MAX_RESPONSE_CHARS]
        return {"ok": completed.returncode == 0, "exit_code": completed.returncode, "output": output}

    @staticmethod
    def _cleanup_directory(directory, attempts=3):
        """Ensure staged files are removed, retrying briefly to tolerate transient Windows file locks."""
        for index in range(attempts):
            try:
                for path in Path(directory).glob("*"):
                    try:
                        path.chmod(stat.S_IWRITE | stat.S_IREAD)
                    except OSError:
                        pass
                shutil.rmtree(directory, ignore_errors=(index == attempts - 1))
                return
            except OSError:
                if index == attempts - 1:
                    return

class SandboxTool:
    name = "Sandbox"
    description = "Run a workspace Python file only through the configured isolation runtime."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative Python file path."},
            "timeout_seconds": {"type": "integer", "description": "Timeout from 1 to 300 seconds."},
        },
        "required": ["path"],
    }

    def __init__(self, workspace, config_file=CONFIG_FILE):
        self.runner = SandboxRunner(workspace, config_file=config_file)

    def get_schema(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}

    def execute(self, params):
        target = self.runner.workspace / str(params.get("path", ""))
        return format_result(self.runner.run_python_file(target, params.get("timeout_seconds", 30)))


def format_result(result):
    return json.dumps(result, ensure_ascii=False)