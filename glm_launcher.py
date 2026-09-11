"""Single-entry GLM Workbench launcher.

The executable starts the local GLM Core once, then opens the public Code-OSS
Workbench with the GLM Router extension. The large Workbench runtime remains
next to this launcher so the launcher stays small and replaceable.
"""

import atexit
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PORT = 8765


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_root() -> Path:
    candidates = [
        app_root(),
        app_root().parent,
        Path(r"D:\Users\新しいフォルダー\AIIDE"),
    ]
    for candidate in candidates:
        if (candidate / "glm" / "glm_ide_core.py").exists():
            return candidate
        if (candidate / "glm_ide_core.py").exists():
            return candidate.parent
    raise FileNotFoundError("GLM project root was not found")


def health_ready() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def existing_core(workspace: Path) -> bool:
    try:
        import subprocess as process
        query = "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*glm_ide_core.py*--port 8765*' } | Select-Object -First 20"
        result = process.run(["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", query], capture_output=True, text=True, timeout=3)
        return bool(result.stdout.strip()) and str(workspace) in result.stdout
    except Exception:
        return health_ready()


def start_core(root: Path, workspace: Path) -> subprocess.Popen | None:
    if existing_core(workspace):
        return None
    if health_ready():
        raise RuntimeError("GLM Core port 8765 is already used by another workspace")
    core = root / "glm" / "glm_ide_core.py"
    python = os.environ.get("GLM_PYTHON", "")
    if not python:
        if getattr(sys, "frozen", False):
            python = shutil.which("py.exe") or shutil.which("python.exe") or ""
        else:
            python = sys.executable
    if not python:
        raise RuntimeError("Python runtime is required for GLM Core. Set GLM_PYTHON or install py.exe.")
    process = subprocess.Popen(
        [python, str(core), "--workspace", str(workspace), "--port", str(PORT)],
        cwd=str(core.parent), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(30):
        if health_ready():
            return process
        time.sleep(0.5)
    process.terminate()
    raise RuntimeError("GLM Core did not become ready on port 8765")


def main() -> int:
    root = find_root()
    workspace = Path(os.environ.get("GLM_WORKSPACE", str(Path.home() / "Desktop" / "新しいフォルダー"))).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    core_process = start_core(root, workspace)
    code_oss = root / "code-oss"
    electron = code_oss / ".build" / "electron" / "GLM Workbench.exe"
    main_js = code_oss / "out" / "main.js"
    extension = code_oss / "extensions" / "glm-router"
    if not electron.exists() or not main_js.exists() or not (extension / "package.json").exists():
        raise FileNotFoundError("GLM Workbench artifacts or GLM Router extension are missing")
    user_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "GLMWorkbench"
    user_data.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env.pop("VSCODE_PID", None)
    try:
        launcher_log = Path(os.environ.get("GLM_LAUNCHER_LOG", str(app_root() / "glm-launcher.log")))
        launcher_log.parent.mkdir(parents=True, exist_ok=True)
        log_stream = launcher_log.open("a", encoding="utf-8")
        workbench = subprocess.Popen(
            [str(electron), str(main_js), "--no-sandbox", "--disable-telemetry", "--disable-updates", "--skip-welcome",
             f"--user-data-dir={user_data}", f"--extensionDevelopmentPath={extension}", str(workspace)],
            cwd=str(code_oss), env=env, stdout=log_stream, stderr=subprocess.STDOUT,
        )
    except Exception:
        if core_process and core_process.poll() is None:
            core_process.terminate()
            core_process.wait(timeout=5)
        raise
    try:
        return workbench.wait()
    finally:
        log_stream.close()
        if core_process and core_process.poll() is None:
            core_process.terminate()
            core_process.wait(timeout=5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        if getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(error), "GLM Workbench", 0x10)
        else:
            raise
