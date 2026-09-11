#!/usr/bin/env python3
"""
GLM IDE Unified Core (単一プロセス統合型バックエンド)
- 子プロセス無限生成や黒画面ループを根絶
- HTTP API / WS / SSE ストリーミングの一括提供
- 自己修復 (Self-healing) & 接続維持 (Resilience)
- アプリ終了時の一括完全シャットダウン
- 依存ゼロ（Python 3.8+ 標準ライブラリのみ）
"""

import atexit
import argparse
import ast
import ipaddress
import json
import logging
import os
import re
import secrets
import select
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, List, Optional

# パス・定数設定
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from router import GLMRouter, estimate_tokens, build_bridge, OLLAMA_URL
from glm_security import (
    GLM_DIR, WorkspaceGuard, AuditLogger, AUTH_FILE, write_heartbeat, STOP_FILE, LOCK_FILE,
    request_stop, emergency_kill, ensure_auth_token, MAX_REQUEST_BODY_BYTES,
    SecretStore, ADMIN_TOTP_SECRET_NAME, generate_totp_secret, verify_totp, provisioning_uri,
    BoundedThreadingHTTPServer,
)
from glm_approval_broker import ApprovalBroker
from glm_dev_services import DAPService, JupyterService, LanguageService, SFTPService, TerminalService
from glm_github_mcp import GitHubMCPClient
from glm_agent import AgentRunner, default_diagnostic_tools
from glm_covibe_adapter import CoVibeAdapter
from glm_lsp import LspClient
from glm_orchestrator import Coordinator
from glm_mlops import MLOpsManager
from glm_integrations import IntegrationRegistry
from glm_notion import NotionReadClient
from glm_customization import CustomizationRegistry
from glm_mcp_bootstrap import MCPProcessManager
from glm_marketplace import Marketplace

# 統合サーバー ポート定数
CORE_PORT = 8765  # Router / Daemon / Broker を単一ポート(8765)に統合

logging.basicConfig(level=logging.INFO, format="%(asctime)s [GLM-Core] %(message)s")
log = logging.getLogger("glm-core")

PROVIDER_SECRETS = {
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "github": "github_token",
}

TAILSCALE_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def validate_bind_host(host: str) -> str:
    """Allow only local or Tailscale addresses; never expose Core to a LAN/WAN wildcard."""
    value = str(host or "").strip()
    if value.lower() == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise ValueError("--bind-host must be a loopback or Tailscale IP address") from error
    if address.is_loopback or address in TAILSCALE_NETWORK:
        return str(address)
    raise ValueError("--bind-host is restricted to loopback or Tailscale (100.64.0.0/10) addresses")


class UnifiedCoreService:
    """単一プロセス内で Router, Approval Broker, Workspace API を一元管理"""

    def __init__(self, workspace_path: Optional[str] = None):
        self.workspace = Path(workspace_path or Path.cwd()).resolve()
        self.guard = WorkspaceGuard(self.workspace)
        self.audit = AuditLogger()
        self.secrets = SecretStore()
        self.integrations = IntegrationRegistry(secrets=self.secrets)
        self.customizations = CustomizationRegistry(self.workspace)
        self.mcp = MCPProcessManager(self.customizations)
        self.marketplace = Marketplace(self.workspace)
        self.model_preference_path = self.workspace / ".glm" / "model-selection.json"
        self.router = GLMRouter(mode="STRATEGY")
        self.broker = ApprovalBroker(timeout_seconds=60)
        self.language = LanguageService(self.workspace)
        self.jupyter = JupyterService(self.workspace)
        self.dap = DAPService(self.workspace)
        self.sftp = SFTPService(self.workspace)
        self.terminal = TerminalService(self.workspace)
        self.github_mcp = GitHubMCPClient(token_getter=lambda: self.provider_api_key("github"))
        self.covibe = CoVibeAdapter(self.workspace, self.broker, self.audit)
        # co-vibeはimport時にsignalを登録するため、メインスレッドで事前ロードする
        if not self.covibe.preload():
            self.audit.record("covibe_agent", "preload_failed",
                              detail={"path": str(self.covibe.co_vibe_path)})
        self.lsp = LspClient(self.workspace)
        self.orchestrator = Coordinator(self.workspace, self.audit)
        mlops_config = {}
        settings_path = SCRIPT_DIR / "settings.json"
        try:
            mlops_config = json.loads(settings_path.read_text(encoding="utf-8-sig")).get("mlops", {})
        except (OSError, json.JSONDecodeError, AttributeError):
            mlops_config = {}
        self.mlops = MLOpsManager(self.workspace, self.audit, mlops_config)
        self._lsp_lock = threading.Lock()
        atexit.register(self.lsp.shutdown)
        self.running = True
        self.errors_log: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self.auth_token = self._load_auth_token()

        # ヘルスチェック・自己修復ループの準備
        self.health_thread = threading.Thread(target=self._self_healing_loop, daemon=True)
        self.health_thread.start()

    def provider_status(self) -> Dict[str, Dict[str, Any]]:
        """Return configured provider names only; credential values never leave SecretStore."""
        return {
            provider: {"configured": bool(os.environ.get(env_name) or self.secrets.get(secret_name))}
            for provider, (env_name, secret_name) in {
                "openai": ("OPENAI_API_KEY", PROVIDER_SECRETS["openai"]),
                "anthropic": ("ANTHROPIC_API_KEY", PROVIDER_SECRETS["anthropic"]),
                "github": ("GITHUB_TOKEN", PROVIDER_SECRETS["github"]),
            }.items()
        }

    def save_provider_secret(self, provider: str, value: str) -> None:
        if provider not in PROVIDER_SECRETS:
            raise ValueError("Unsupported provider")
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise ValueError("Credential must be between 1 and 4096 characters")
        self.secrets.set(PROVIDER_SECRETS[provider], value.strip())
        self.audit.record("provider_credential", "saved", detail={"provider": provider})

    def provider_api_key(self, provider: str) -> str:
        if provider not in PROVIDER_SECRETS:
            raise ValueError("Unsupported provider")
        env_name = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "github": "GITHUB_TOKEN"}[provider]
        return os.environ.get(env_name, "") or self.secrets.get(PROVIDER_SECRETS[provider]) or ""

    def available_models(self) -> Dict[str, Any]:
        try:
            registry = json.loads((SCRIPT_DIR / "registry.json").read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            registry = {}
        models = []
        for item in registry.get("routing_tiers", []) + registry.get("nano_models", []) + registry.get("models", []):
            if not isinstance(item, dict) or not item.get("model_id", item.get("id")):
                continue
            model_id = item.get("model_id", item.get("id"))
            models.append({"id": model_id, "name": model_id, "base_model": item.get("base_model", model_id),
                           "execution": item.get("execution", "local"), "provider": item.get("provider", "ollama"),
                           "available": True})
        for provider, config in registry.get("cloud_api", {}).get("providers", {}).items():
            for model_id in config.get("models", []):
                models.append({"id": model_id, "name": model_id, "base_model": model_id,
                               "execution": "cloud", "provider": provider,
                               "available": self.provider_status().get(provider, {}).get("configured", False)})
        try:
            selected = json.loads(self.model_preference_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            selected = {"model": "auto", "temperature": 0.3, "max_tokens": 2048}
        return {"models": models, "selection": selected}

    def save_model_selection(self, model: str, temperature: Any, max_tokens: Any) -> Dict[str, Any]:
        catalog = {item["id"] for item in self.available_models()["models"]}
        if model != "auto" and model not in catalog:
            raise ValueError("Unknown model")
        try:
            temperature = max(0.0, min(float(temperature), 2.0))
            max_tokens = max(1, min(int(max_tokens), 32768))
        except (TypeError, ValueError):
            raise ValueError("Invalid model parameters")
        selection = {"model": model, "temperature": temperature, "max_tokens": max_tokens}
        self.model_preference_path.parent.mkdir(parents=True, exist_ok=True)
        self.model_preference_path.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
        self.audit.record("model_selection", "saved", detail={"model": model})
        return selection

    def test_provider(self, provider: str) -> Dict[str, Any]:
        api_key = self.provider_api_key(provider)
        if not api_key:
            return {"ok": False, "provider": provider, "message": "Credential is not configured"}
        requests = {
            "openai": ("https://api.openai.com/v1/models", {"Authorization": f"Bearer {api_key}"}),
            "anthropic": ("https://api.anthropic.com/v1/models", {"x-api-key": api_key, "anthropic-version": "2023-06-01"}),
            "github": ("https://api.github.com/user", {"Authorization": f"Bearer {api_key}", "Accept": "application/vnd.github+json"}),
        }
        target, headers = requests[provider]
        try:
            with urllib.request.urlopen(urllib.request.Request(target, headers=headers), timeout=15) as response:
                ok = 200 <= response.status < 300
            self.audit.record("provider_connection", "ok" if ok else "error", detail={"provider": provider})
            return {"ok": ok, "provider": provider, "message": "Connection verified" if ok else "Connection failed"}
        except urllib.error.HTTPError as error:
            self.audit.record("provider_connection", "error", detail={"provider": provider, "http_status": error.code})
            return {"ok": False, "provider": provider, "message": f"Provider rejected the credential (HTTP {error.code})"}
        except (OSError, urllib.error.URLError) as error:
            self.audit.record("provider_connection", "error", detail={"provider": provider, "error_type": type(error).__name__})
            return {"ok": False, "provider": provider, "message": "Provider connection could not be established"}

    @staticmethod
    def _load_auth_token() -> str:
        """Create a per-user token used by local IDE mutation APIs (fail-closed on error)."""
        try:
            return ensure_auth_token(AUTH_FILE)
        except RuntimeError:
            return ""

    def record_error(self, component: str, error_msg: str) -> Dict[str, Any]:
        """エラーの記録・監査DB同期と自己修復サーキットブレーカー管理"""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "component": component,
            "error": error_msg,
            "healed": True
        }
        with self._lock:
            self.errors_log.append(entry)
            if len(self.errors_log) > 50:
                self.errors_log = self.errors_log[-50:]
        
        # 監査DBに記録（自己修復過剰ループ検知用）
        self.audit.record("healed_error", "auto_heal", detail={"component": component, "error": error_msg[:100]})
        
        # 過去1分間に5回以上の修復が発生した場合は暴走と判定し自己修復を遮断（Circuit Breaker）
        if self.audit.count_since(time.time() - 60, "healed_error") > 5:
            log.error(f"Circuit Breaker Triggered! Too many self-healing events for [{component}]. Stopping IDE.")
            request_stop(f"circuit_breaker_healed_error_limit:{component}")

        log.warning(f"Self-healing triggered for [{component}]: {error_msg}")
        return entry

    def ensure_lsp(self) -> bool:
        """LSPサーバーを必要時起動する。失敗時はFalse（呼び出し側がASTへ退避）。"""
        with self._lsp_lock:
            if self.lsp.status()["running"]:
                return True
            started = self.lsp.start()
            self.audit.record("lsp", "start" if started else "unavailable",
                              detail={"engine": "pyright-langserver"})
            return started

    def lsp_completion(self, path, line, character, content):
        if not self.ensure_lsp():
            return {"ok": False, "engine": "ast-fallback",
                    **self.language.completions(path, "", content)}
        try:
            return {"ok": True, "engine": "pyright-lsp",
                    "items": self.lsp.completion(path, line, character, content or "")}
        except (TimeoutError, RuntimeError, OSError) as error:
            self.record_error("lsp_completion", str(error))
            return {"ok": False, "engine": "ast-fallback", "error": str(error),
                    **self.language.completions(path, "", content)}

    def lsp_hover(self, path, line, character, content):
        if not self.ensure_lsp():
            return {"ok": False, "error": "LSP server unavailable"}
        try:
            return {"ok": True, "engine": "pyright-lsp",
                    "hover": self.lsp.hover(path, line, character, content or "")}
        except (TimeoutError, RuntimeError, OSError) as error:
            return {"ok": False, "error": str(error)}

    def lsp_definition(self, path, line, character, content):
        if not self.ensure_lsp():
            return {"ok": False, "error": "LSP server unavailable"}
        try:
            return {"ok": True, "engine": "pyright-lsp",
                    "locations": self.lsp.definition(path, line, character, content or "")}
        except (TimeoutError, RuntimeError, OSError) as error:
            return {"ok": False, "error": str(error)}

    def lsp_references(self, path, line, character, content):
        if not self.ensure_lsp():
            return {"ok": False, "error": "LSP server unavailable"}
        try:
            return {"ok": True, "engine": "pyright-lsp",
                    "references": self.lsp.references(path, line, character, content or "")}
        except (TimeoutError, RuntimeError, OSError) as error:
            return {"ok": False, "error": str(error)}

    def lsp_rename(self, path, line, character, new_name, content):
        if not self.ensure_lsp():
            return {"ok": False, "error": "LSP server unavailable"}
        try:
            return {"ok": True, "engine": "pyright-lsp",
                    "edits": self.lsp.rename(path, line, character, new_name, content or "")}
        except (TimeoutError, RuntimeError, OSError) as error:
            return {"ok": False, "error": str(error)}

    def lsp_symbols(self, path, content):
        if not self.ensure_lsp():
            return self.language.symbols(path, content)
        try:
            return {"ok": True, "engine": "pyright-lsp",
                    "symbols": self.lsp.document_symbols(path, content or "")}
        except (TimeoutError, RuntimeError, OSError) as error:
            self.record_error("lsp_symbols", str(error))
            return self.language.symbols(path, content)

    def lsp_diagnostics(self, path=None, content=None):
        """LSPのpublishDiagnosticsを優先し、未起動時はAST診断へ退避する。"""
        if path and content is not None and self.ensure_lsp():
            try:
                self.lsp.sync_document(path, content)
                time.sleep(0.3)  # publishDiagnostics通知の到着を短く待つ
            except (TimeoutError, RuntimeError, OSError):
                pass
            lsp_diag = self.lsp.diagnostics(path)
            if path in lsp_diag or self.lsp.status()["running"]:
                return {"ok": True, "engine": "pyright-lsp",
                        "diagnostics": lsp_diag.get(path, [])}
        return self.language.diagnostics(path, content) if path else {"ok": True, "diagnostics": []}

    def run_agent(self, messages, requested_by="glm-agent", max_steps=8, max_seconds=180,
                  session_id="default", model="auto"):
        messages = self.customizations.prepare_messages(messages)
        self.audit.record("customization", "agent_before",
                  requested_by, self.customizations.emit("before_agent", {"session_id": session_id}))
        format_request = self._format_workspace_request(messages)
        if format_request:
            return self._run_format_workspace_request(format_request, requested_by, session_id)
        explicit_write = self._explicit_write_request(messages)
        if explicit_write:
            return self._run_explicit_write(explicit_write, requested_by, session_id)
        if self.covibe.available():
            try:
                if model and model != "auto":
                    os.environ["GLM_COVIBE_MODEL"] = model
                result = self.covibe.run(messages, requested_by=requested_by,
                                         max_steps=max_steps, max_seconds=max_seconds,
                                         session_id=session_id)
                if result.get("ok"):
                    result["message"] = {"role": "assistant", "content": result.pop("answer", "")}
                result["customizations"] = self.customizations.summary()
                self.audit.record("customization", "agent_after",
                                  requested_by, self.customizations.emit("after_agent", {"session_id": session_id}))
                return result
            except Exception as error:
                import traceback as _tb
                log.error("co-vibe fallback: %s", _tb.format_exc())
                self.audit.record("covibe_agent", "fallback", requested_by,
                                  {"error": str(error)[:300],
                                   "traceback": _tb.format_exc()[-1500:]})

        def call_llm(conversation, tools):
            payload = {"model": "qwen2.5-coder:7b", "messages": conversation,
                       "tools": tools, "stream": False}
            request = urllib.request.Request(
                f"{OLLAMA_URL}/v1/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))

        result = AgentRunner(call_llm, default_diagnostic_tools(self.workspace), self.audit,
                             max_steps=max_steps, max_seconds=max_seconds).run(
                                 messages, requested_by=requested_by)
        result["customizations"] = self.customizations.summary()
        self.audit.record("customization", "agent_after",
                          requested_by, self.customizations.emit("after_agent", {"session_id": session_id}))
        return result

    @staticmethod
    def _format_workspace_request(messages):
        prompt = next((str(item.get("content", "")) for item in reversed(messages)
                       if item.get("role") == "user"), "")
        if not re.search(r"ファイル形式|拡張子|file formats?|対応できる", prompt, re.IGNORECASE):
            return None
        if not re.search(r"作っ|作成|create|workspace|ワークスペース", prompt, re.IGNORECASE):
            return None
        return prompt

    @staticmethod
    def _supported_workspace_formats():
        return {
            "py": "# GLM Standalone Python format check\nprint('python')\n",
            "json": '{"source":"GLM Standalone","format":"json"}\n',
            "js": "// GLM Standalone JavaScript format check\nconsole.log('javascript');\n",
            "ts": "// GLM Standalone TypeScript format check\nconst format: string = 'typescript';\n",
            "md": "# GLM Standalone Markdown format check\n",
            "html": "<!doctype html>\n<html><body>GLM Standalone HTML format check</body></html>\n",
            "css": "/* GLM Standalone CSS format check */\nbody { color: #cdd6f4; }\n",
            "cpp": "// GLM Standalone C++ format check\nint main() { return 0; }\n",
            "c": "/* GLM Standalone C format check */\nint main(void) { return 0; }\n",
            "java": "// GLM Standalone Java format check\nclass Main { public static void main(String[] args) {} }\n",
            "ps1": "# GLM Standalone PowerShell format check\nWrite-Output 'powershell'\n",
            "sh": "#!/bin/sh\n# GLM Standalone shell format check\nprintf '%s\\n' shell\n",
            "xml": "<?xml version=\"1.0\"?><format-check source=\"GLM Standalone\" />\n",
            "sql": "-- GLM Standalone SQL format check\nSELECT 'sql' AS format;\n",
            "ipynb": json.dumps({"cells": [{"cell_type": "code", "metadata": {}, "source": ["print('notebook')\\n"], "outputs": [], "execution_count": None}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}, ensure_ascii=False, indent=2) + "\n",
            "txt": "GLM Standalone plain text format check\n",
        }

    def _run_format_workspace_request(self, prompt, requested_by, session_id):
        samples = self._supported_workspace_formats()
        folder = self.workspace / "glm-format-check"
        self.guard.require_contained(folder)
        folder.mkdir(parents=True, exist_ok=True)
        created = []
        for extension, content in samples.items():
            target = folder / f"format-check.{extension}"
            self.guard.require_contained(target)
            target.write_text(content, encoding="utf-8")
            created.append(target.relative_to(self.workspace).as_posix())
        self.audit.record("agent_format_workspace", "allow", requested_by,
                          {"count": len(created), "session_id": session_id})
        answer = "対応形式のサンプルを作成しました: " + ", ".join(created)
        return {
            "ok": True,
            "engine": "glm-format-workspace-tool",
            "message": {"role": "assistant", "content": answer},
            "steps": len(created),
            "trace": [{"step": index, "tool": "Write", "result": {"ok": True, "path": path}}
                      for index, path in enumerate(created, 1)],
            "session_id": session_id,
        }

    @staticmethod
    def _explicit_write_request(messages):
        prompt = next((str(item.get("content", "")) for item in reversed(messages)
                       if item.get("role") == "user"), "")
        if not re.search(r"write|書き込|作成", prompt, re.IGNORECASE):
            return None
        path_match = re.search(r"(?:file_path|path)\s*[=:：]\s*[`\"']?([^`\"'、,\s]+)", prompt, re.IGNORECASE)
        content_match = re.search(r"content\s*[=:：]\s*[`\"']?(.+?)[`\"']?(?:。|$)", prompt, re.IGNORECASE)
        if not path_match:
            path_match = re.search(r"(?:直下の|ファイル(?:名)?[はを])\s*[`\"']?([^`\"'、,\s]+)", prompt)
        if not content_match:
            content_match = re.search(r"(?:内容を|内容は)\s*[`\"']?(.+?)[`\"']?(?:と書|。|$)", prompt)
        if not path_match or not content_match:
            return None
        return path_match.group(1).strip(), content_match.group(1).strip().rstrip("。")

    def _run_explicit_write(self, request, requested_by, session_id):
        rel_path, content = request
        target = self.guard.require_contained(self.workspace / rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.audit.record("agent_explicit_write", "allow", requested_by,
                          {"path": rel_path, "session_id": session_id})
        return {
            "ok": True,
            "engine": "glm-explicit-workspace-tool",
            "message": {"role": "assistant", "content": f"Write完了: {rel_path}"},
            "steps": 1,
            "trace": [{"step": 1, "tool": "Write", "result": {"ok": True, "path": rel_path}}],
            "session_id": session_id,
        }

    def _self_healing_loop(self):
        """定期的なヘルスチェックと心拍更新（Ollama未起動は正常なオフライン状態として扱い、自死ストップは発火させない）"""
        while self.running:
            try:
                write_heartbeat(os.getpid(), "unified_core_running")
                # Ollama 疎通チェック (バックグラウンド)
                req = urllib.request.Request(f"{OLLAMA_URL}/api/ps", method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    pass
            except Exception:
                # Ollama 未起動等は正常なオフライン状態として扱い、エラーログや強制ストップは発火させない
                pass
            time.sleep(10)

    def list_files(self) -> List[str]:
        """ワークスペース内の安全なファイル一覧取得"""
        items = []
        skip_dirs = {".git", "__pycache__", ".venv", "node_modules", ".glm", "build", "dist", "target", "out", ".next", ".cache"}
        for root, dirs, files in os.walk(self.workspace):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            rel_root = Path(root).relative_to(self.workspace)
            for f in files:
                if f.startswith(".") or f.endswith((".pyc", ".vsix", ".exe", ".dll")):
                    continue
                rel_path = (rel_root / f).as_posix()
                if rel_path.startswith("./"):
                    rel_path = rel_path[2:]
                items.append(rel_path)
            if len(items) >= 600:
                break
        return sorted(items)

    def read_file(self, rel_path: str) -> str:
        """ワークスペース内ファイルの読み込み"""
        target = self.guard.require_contained(self.workspace / rel_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"File not found: {rel_path}")
        return target.read_text(encoding="utf-8-sig", errors="replace")

    def save_file(self, rel_path: str, content: str) -> bool:
        """ワークスペース内ファイルへの直接保存 (Ctrl+S 用)"""
        target = self.guard.require_contained(self.workspace / rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # バックアップ一時書き込み後にアトミック置換
        temp_target = target.with_suffix(target.suffix + ".tmp")
        temp_target.write_text(content, encoding="utf-8")
        temp_target.replace(target)
        self.audit.record("file_save", "allow", detail={"path": rel_path})
        return True

    def create_file(self, rel_path: str, content: str = "") -> bool:
        target = self.guard.require_contained(self.workspace / rel_path)
        if target.exists():
            raise FileExistsError(f"File already exists: {rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.audit.record("file_create", "allow", detail={"path": rel_path})
        return True

    def create_folder(self, rel_path: str) -> bool:
        target = self.guard.require_contained(self.workspace / rel_path)
        if target.exists():
            raise FileExistsError(f"Path already exists: {rel_path}")
        target.mkdir(parents=True)
        self.audit.record("folder_create", "allow", detail={"path": rel_path})
        return True

    def delete_file(self, rel_path: str) -> bool:
        target = self.guard.require_contained(self.workspace / rel_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"File not found: {rel_path}")
        target.unlink()
        self.audit.record("file_delete", "allow", detail={"path": rel_path})
        return True

    def delete_entry(self, rel_path: str) -> bool:
        """Delete a workspace file or directory after containment validation."""
        target = self.guard.require_contained(self.workspace / rel_path)
        if not target.exists():
            raise FileNotFoundError(f"Path not found: {rel_path}")
        is_directory = target.is_dir()
        if is_directory:
            shutil.rmtree(target)
        else:
            target.unlink()
        self.audit.record("workspace_delete", "allow", detail={"path": rel_path, "directory": is_directory})
        return True

    def move_file(self, source: str, destination: str) -> bool:
        source_path = self.guard.require_contained(self.workspace / source)
        destination_path = self.guard.require_contained(self.workspace / destination)
        if not source_path.exists() or not (source_path.is_file() or source_path.is_dir()):
            raise FileNotFoundError(f"File not found: {source}")
        if destination_path.exists():
            raise FileExistsError(f"Destination already exists: {destination}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.replace(destination_path)
        self.audit.record("file_move", "allow", detail={"source": source, "destination": destination})
        return True

    def search_files(self, query: str, max_results: int = 100) -> list:
        if not query:
            return []
        query = query[:200].casefold()
        results = []
        for rel_path in self.list_files():
            if len(results) >= max_results:
                break
            try:
                target = self.guard.require_contained(self.workspace / rel_path)
                if target.stat().st_size > 2_000_000:
                    continue
                text = target.read_text(encoding="utf-8-sig", errors="ignore")
                for line_number, line in enumerate(text.splitlines(), 1):
                    if query in line.casefold():
                        results.append({"path": rel_path, "line": line_number, "text": line[:500]})
                        if len(results) >= max_results:
                            break
            except (OSError, UnicodeError, PermissionError):
                continue
        return results

    def get_git_diff(self) -> str:
        """作業ツリーの git diff を取得"""
        try:
            r = subprocess.run(
                ["git", "diff", "--no-ext-diff"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=5,
            )
            return r.stdout if r.returncode == 0 else f"Git output: {r.stderr}"
        except Exception as e:
            return f"Git diff unavailable: {e}"

    def get_git_status(self) -> dict:
        """Git 変更ステータスの一覧を取得"""
        try:
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = [line.strip() for line in r.stdout.splitlines() if line.strip()]
            files = []
            for line in lines:
                status_code = line[:2]
                file_path = line[3:].strip()
                files.append({"status": status_code, "path": file_path})
            return {"ok": True, "files": files}
        except Exception as e:
            return {"ok": False, "error": str(e), "files": []}

    def git_stage(self, paths: list) -> dict:
        if not isinstance(paths, list) or not paths:
            return {"ok": False, "error": "paths is required"}
        try:
            safe_paths = [str(self.guard.require_contained(self.workspace / path).relative_to(self.workspace)) for path in paths]
            result = subprocess.run(["git", "add", "--", *safe_paths], cwd=str(self.workspace), capture_output=True, text=True, timeout=10)
            return {"ok": result.returncode == 0, "output": result.stdout, "error": result.stderr}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def git_branches(self) -> dict:
        try:
            result = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=str(self.workspace), capture_output=True, text=True, timeout=5)
            current = subprocess.run(["git", "branch", "--show-current"], cwd=str(self.workspace), capture_output=True, text=True, timeout=5)
            return {"ok": result.returncode == 0, "current": current.stdout.strip(), "branches": [line.strip() for line in result.stdout.splitlines() if line.strip()]}
        except Exception as e:
            return {"ok": False, "error": str(e), "branches": []}

    def git_checkout(self, branch: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch or "") or branch.startswith("-"):
            return {"ok": False, "error": "Invalid branch name"}
        try:
            result = subprocess.run(["git", "checkout", branch], cwd=str(self.workspace), capture_output=True, text=True, timeout=10)
            return {"ok": result.returncode == 0, "output": result.stdout, "error": result.stderr}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def git_push(self, remote="origin", branch="") -> dict:
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", remote or "") or remote.startswith("-"):
            return {"ok": False, "error": "Invalid remote name"}
        args = ["git", "push", remote]
        if branch:
            if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or branch.startswith("-"):
                return {"ok": False, "error": "Invalid branch name"}
            args.append(branch)
        try:
            result = subprocess.run(args, cwd=str(self.workspace), capture_output=True, text=True, timeout=30)
            return {"ok": result.returncode == 0, "output": result.stdout, "error": result.stderr}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def git_conflicts(self) -> dict:
        status = self.get_git_status()
        conflicts = [item["path"] for item in status.get("files", []) if "U" in item.get("status", "") or item.get("status") in {"AA", "DD"}]
        return {"ok": status.get("ok", False), "conflicts": conflicts}

    def git_commit(self, message: str) -> dict:
        """全変更のステージングと Git コミットの実行"""
        if not message or not message.strip():
            return {"ok": False, "error": "Commit message is required"}
        try:
            # git add -A
            subprocess.run(["git", "add", "-A"], cwd=str(self.workspace), check=True, capture_output=True)
            # git commit -m
            r = subprocess.run(
                ["git", "commit", "-m", message.strip()],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0:
                self.audit.record("git_commit", "allow", detail={"message": message})
                return {"ok": True, "output": r.stdout}
            return {"ok": False, "error": r.stderr or r.stdout}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def check_syntax(self, rel_path: str, content: Optional[str] = None) -> dict:
        """構文エラー・簡易診断 (Syntax Diagnostics) の検証"""
        target = self.guard.require_contained(self.workspace / rel_path)
        ext = target.suffix.lower()
        errors = []

        if ext == ".py":
            # Python 構文チェック
            try:
                if content is not None:
                    compile(content, str(target), "exec")
                elif target.exists():
                    compile(target.read_text(encoding="utf-8-sig"), str(target), "exec")
            except SyntaxError as se:
                errors.append({
                    "line": se.lineno or 1,
                    "column": se.offset or 1,
                    "message": f"SyntaxError: {se.msg}",
                    "severity": "Error"
                })
        elif ext == ".json":
            # JSON 構文チェック
            try:
                text_data = content if content is not None else (target.read_text(encoding="utf-8-sig") if target.exists() else "")
                if text_data:
                    json.loads(text_data)
            except json.JSONDecodeError as jde:
                errors.append({
                    "line": jde.lineno,
                    "column": jde.colno,
                    "message": f"JSONDecodeError: {jde.msg}",
                    "severity": "Error"
                })

        return {"ok": len(errors) == 0, "path": rel_path, "errors": errors}

    def find_definitions(self, rel_path: str, name: str, content: Optional[str] = None) -> dict:
        target = self.guard.require_contained(self.workspace / rel_path)
        text = content if content is not None else target.read_text(encoding="utf-8-sig", errors="replace")
        definitions = []
        if target.suffix.lower() == ".py":
            try:
                tree = compile(text, str(target), "exec", flags=ast.PyCF_ONLY_AST)
                definitions = self._definitions_in_tree(tree, name, rel_path)
                if not definitions:
                    for imported_name, module_name, level in self._imports_for_name(tree, name):
                        imported_path = self._resolve_python_import(target, module_name, level)
                        if not imported_path:
                            continue
                        imported_text = imported_path.read_text(encoding="utf-8-sig", errors="replace")
                        imported_tree = compile(imported_text, str(imported_path), "exec", flags=ast.PyCF_ONLY_AST)
                        definitions = self._definitions_in_tree(
                            imported_tree, imported_name, imported_path.relative_to(self.workspace).as_posix()
                        )
                        if definitions:
                            break
            except SyntaxError:
                pass
        return {"ok": True, "path": rel_path, "name": name, "definitions": definitions}

    @staticmethod
    def _definitions_in_tree(tree, name: str, rel_path: str) -> list:
        definitions = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                definitions.append({"name": name, "path": rel_path, "line": node.lineno,
                                    "column": node.col_offset + 1, "kind": type(node).__name__})
            elif isinstance(node, ast.Assign):
                for target_node in node.targets:
                    if isinstance(target_node, ast.Name) and target_node.id == name:
                        definitions.append({"name": name, "path": rel_path, "line": node.lineno,
                                            "column": node.col_offset + 1, "kind": "variable"})
        return definitions

    @staticmethod
    def _imports_for_name(tree, name: str) -> list:
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    bound_name = alias.asname or alias.name.split(".")[0]
                    if bound_name == name:
                        imports.append((alias.name, node.module or "", node.level))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    bound_name = alias.asname or alias.name.split(".")[0]
                    if bound_name == name:
                        imports.append((alias.name.rsplit(".", 1)[-1], alias.name, 0))
        return imports

    def _resolve_python_import(self, source_path: Path, module_name: str, level: int) -> Optional[Path]:
        base = source_path.parent
        for _ in range(max(level - 1, 0)):
            base = base.parent
        module_parts = [part for part in module_name.split(".") if part]
        module_path = base.joinpath(*module_parts)
        candidates = [module_path.with_suffix(".py"), module_path / "__init__.py"]
        for candidate in candidates:
            try:
                candidate = self.guard.require_contained(candidate)
            except PermissionError:
                continue
            if candidate.is_file():
                return candidate
        return None

    def run_notebook_cell(self, source: str, timeout: int = 30) -> dict:
        return self.jupyter.execute(source, timeout)

    def execute_code(self, rel_path: str, content: Optional[str] = None, timeout: int = 10) -> dict:
        """Python / PowerShell / C++ / Java スクリプトのワンクリック安全実行"""
        try:
            target = self.guard.require_contained(self.workspace / rel_path)
            ext = target.suffix.lower()
            if content is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            if ext == ".py":
                cmd = [sys.executable, str(target)]
            elif ext == ".ps1":
                cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(target)]
            elif ext in (".c", ".cpp"):
                exe_name = target.with_suffix(".exe")
                compiler = "g++" if ext == ".cpp" else "gcc"
                build = subprocess.run([compiler, str(target), "-o", str(exe_name)], capture_output=True, text=True, timeout=10)
                if build.returncode != 0:
                    return {"ok": False, "error": f"Build Error:\n{build.stderr}"}
                cmd = [str(exe_name)]
            elif ext == ".java":
                build = subprocess.run(["javac", str(target)], capture_output=True, text=True, timeout=10)
                if build.returncode != 0:
                    return {"ok": False, "error": f"Build Error:\n{build.stderr}"}
                cmd = ["java", "-cp", str(target.parent), target.stem]
            else:
                return {"ok": False, "error": f"Execution for extension '{ext}' is not supported."}

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(target.parent))
            return {
                "ok": proc.returncode == 0,
                "stdout": proc.stdout[:10000],
                "stderr": proc.stderr[:10000],
                "returncode": proc.returncode
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Execution timed out ({timeout}s)"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def read_ipynb(self, rel_path: str) -> dict:
        """Jupyter Notebook (.ipynb) のセルのパース・表示用JSON返却"""
        try:
            target = self.guard.require_contained(self.workspace / rel_path)
            raw = target.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
            cells = []
            for cell in data.get("cells", []):
                cells.append({
                    "cell_type": cell.get("cell_type", "code"),
                    "source": "".join(cell.get("source", [])),
                    "outputs": cell.get("outputs", [])
                })
            return {"ok": True, "path": rel_path, "cells": cells}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def shutdown(self):
        """完全一括シャットダウン処理"""
        self.running = False
        self.jupyter.stop()
        self.dap.stop()
        STOP_FILE.write_text(json.dumps({"reason": "ide_shutdown"}), encoding="utf-8")
        log.info("Unified Core Service shutdown complete.")


class UnifiedCoreHandler(BaseHTTPRequestHandler):
    """Router, Broker, Workspace API を単一のポート・ハンドラで処理"""
    service: UnifiedCoreService

    def log_message(self, *_):
        pass

    def _origin_allowed(self):
        origin = self.headers.get("Origin", "")
        if not origin:
            return True
        port = self.server.server_port
        return origin in {
            f"http://127.0.0.1:{port}", f"http://localhost:{port}",
            # Tauri v2 WebView origins（デスクトップアプリからの接続を許可）
            "http://tauri.localhost", "https://tauri.localhost",
            "tauri://localhost",
        }

    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin and self._origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        if not self._origin_allowed():
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _json(self, data: Any, code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code: int, msg: str):
        self._json({"error": msg}, code)

    def _authenticated(self):
        if not self.service.auth_token:
            return False
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer ") and authorization[7:] == self.service.auth_token:
            return True
        cookies = {}
        for item in self.headers.get("Cookie", "").split(";"):
            if "=" in item:
                key, value = item.strip().split("=", 1)
                cookies[key] = value
        return cookies.get("glm_auth") == self.service.auth_token

    def _loopback_client(self):
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def _totp_verified(self):
        """管理者向け監査APIの二段階認証。未設定の場合は常に拒否する（フェイルクローズ）。"""
        secret = SecretStore().get(ADMIN_TOTP_SECRET_NAME)
        if not secret:
            return False
        code = self.headers.get("X-TOTP-Code", "")
        return verify_totp(secret, code)

    def _serve_static_file(self, rel_path: str):
        """ide-web の静的ファイル（HTML/CSS/JS/Monaco assets）の直接配信"""
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys._MEIPASS) / "ide-web"
        else:
            base_dir = SCRIPT_DIR / "ide-web"

        clean_path = rel_path.split("?")[0].split("#")[0]
        if clean_path in ("/", "", "/index.html"):
            target = base_dir / "index.html"
        else:
            target = (base_dir / clean_path.lstrip("/")).resolve()

        try:
            target.relative_to(base_dir.resolve())
        except ValueError:
            self.send_response(403); self.end_headers(); return

        if not target.exists() or not target.is_file():
            self.send_response(404); self.end_headers(); return

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".woff": "font/woff",
            ".woff2": "font/woff2",
            ".ttf": "font/ttf"
        }
        ct = content_types.get(target.suffix.lower(), "application/octet-stream")

        try:
            content = target.read_bytes()
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(content)))
            if target.name == "index.html":
                self.send_header("Set-Cookie", f"glm_auth={self.service.auth_token}; Path=/; HttpOnly; SameSite=Strict")
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_response(500); self.end_headers()

    def do_GET(self):
        s = self.service
        path = urllib.parse.urlparse(self.path).path
        if not self._origin_allowed():
            self._err(403, "Origin is not allowed")
            return

        static_suffixes = {".html", ".css", ".js", ".json", ".png", ".ico", ".woff", ".woff2", ".ttf"}
        is_static = path in {"/", "", "/index.html"} or Path(path).suffix.lower() in static_suffixes
        if path not in {"/health", "/api/health", "/api/auth/local-token"} and not is_static and not self._authenticated():
            self._err(401, "Authentication required")
            return

        if path == "/health" or path == "/api/health":
            self._json({"status": "ok", "mode": s.router.mode, "service": "glm-unified-core"})
        elif path == "/api/auth/local-token":
            # Tauri WebView専用: 同一マシンのデスクトップUIのみにBearerトークンを返す。
            # 他オリジンのブラウザからはCORSで読み取れず、ローカルの非ブラウザプロセスは
            # 認証ファイルを直接読めるため、実効的な露出面は変わらない。発行は監査する。
            origin = self.headers.get("Origin", "")
            if not self._loopback_client() or (origin and "tauri.localhost" not in origin and origin != "tauri://localhost"):
                self._err(403, "Origin is not allowed")
                return
            s.audit.record("auth_token", "issued", detail={"origin": origin or "(none)", "via": "local-token"})
            self._json({"ok": True, "token": s.auth_token})
        elif path == "/status" or path == "/api/status":
            hw = s.router.hw
            self._json({
                "vram_used_gb":  round(hw.vram_used_gb(), 2),
                "vram_free_gb":  round(hw.vram_free_gb(), 2),
                "gpu_temp":      hw.gpu_temp(),
                "gpu_util":      hw.gpu_util(),
                "throttling":    hw.is_throttling(),
                "budget_ratio":  round(s.router.budget.ratio(), 3),
                "budget_spent":  round(s.router.budget.spent(), 4),
                "errors_count":  len(s.errors_log),
                "orchestrator": {"sessions": len(s.orchestrator.sessions)},
                "mlops": s.mlops.status(),
            })
        elif path == "/api/orchestrator/sessions":
            self._json({"sessions": [s.orchestrator.snapshot(session_id)
                                      for session_id in list(s.orchestrator.sessions)]})
        elif path == "/api/orchestrator/profiles":
            self._json({"profiles": s.orchestrator.policy.profiles})
        elif path.startswith("/api/orchestrator/session/"):
            session_id = path.removeprefix("/api/orchestrator/session/")
            try:
                self._json(s.orchestrator.snapshot(session_id))
            except KeyError:
                self._err(404, "session not found")
        elif path == "/api/mlops/status":
            self._json(s.mlops.status())
        elif path == "/sessions":
            self._json(s.router.sess.list())
        elif path.startswith("/sessions/"):
            session_id = urllib.parse.unquote(path.removeprefix("/sessions/").split("?", 1)[0])
            if not re.fullmatch(r"[0-9A-Za-z_.-]+", session_id or ""):
                self._err(400, "invalid session id")
                return
            session = s.router.sess.get(session_id) or s.router.sess.load(session_id)
            if not session:
                self._err(404, "session not found")
                return
            self._json({
                "id": session.get("session_id", session_id),
                "title": session.get("title") or "無題",
                "model": session.get("model_used"),
                "turns": session.get("turns", 0),
                "messages": session.get("messages", []),
                "token_count": session.get("token_count", 0),
                "last_active": session.get("last_active"),
            })
        elif path == "/pending":
            self._json({"requests": s.broker.pending()})
        elif path.startswith("/decision/"):
            req_id = path.removeprefix("/decision/")
            dec = s.broker.decision(req_id)
            self._json({"ready": dec is not None, "decision": dec})
        elif path == "/api/workspace/files":
            self._json({"files": s.list_files()})
        elif path == "/api/git/diff":
            self._json({"diff": s.get_git_diff()})
        elif path == "/api/git/status":
            self._json(s.get_git_status())
        elif path == "/api/dev/status":
            self._json({"jupyter": s.jupyter.status(), "dap": s.dap.status(), "sftp": s.sftp.status(),
                        "lsp": s.lsp.status()})
        elif path == "/api/providers/status":
            self._json({"providers": s.provider_status()})
        elif path == "/api/customizations":
            self._json(s.customizations.summary())
        elif path == "/api/customizations/files":
            self._json({"files": s.customizations.files()})
        elif path == "/api/mcp/servers":
            self._json({"servers": list(s.mcp.servers().values())})
        elif path == "/api/models":
            self._json(s.available_models())
        elif path == "/api/marketplace/extensions":
            query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query).get("q", [""])[0]
            self._json({"extensions": s.marketplace.list(query)})
        elif path == "/api/pylance/mcp/status":
            self._json({"ok": True, "engine": "pyright-lsp", "status": s.lsp.status(),
                        "tools": ["diagnostics", "completions", "hover", "definition", "references", "rename", "symbols"]})
        elif path == "/api/integrations/status":
            self._json({"integrations": s.integrations.status()})
        elif path == "/api/lsp/status":
            self._json(s.lsp.status())
        elif path == "/api/lsp/problems":
            self._json({"ok": True, "engine": "pyright-lsp", "problems": s.lsp.diagnostics()})
        elif path.startswith("/api/terminal/output"):
            if not self._authenticated():
                self._err(401, "Authentication required")
            else:
                query = urllib.parse.urlparse(self.path).query
                since = dict(urllib.parse.parse_qsl(query)).get("since", 0)
                self._json(s.terminal.read(since))
        elif path == "/api/mcp/github/tools":
            try:
                self._json({"ok": True, **s.github_mcp.list_tools()})
            except Exception as error:
                self._json({"ok": False, "error": str(error)}, 503)
        elif path == "/api/sftp/profiles":
            if not self._authenticated():
                self._err(401, "Authentication required")
            else:
                self._json(s.sftp.list_profiles())
        elif path == "/api/git/branches":
            self._json(s.git_branches())
        elif path == "/api/git/conflicts":
            self._json(s.git_conflicts())
        elif path == "/api/errors":
            self._json({"errors": s.errors_log})
        elif path == "/api/admin/audit/verify":
            if not self._totp_verified():
                self._err(401, "TOTP verification required")
            else:
                self._json(s.audit.verify_integrity())
        elif path == "/api/admin/audit/events":
            if not self._totp_verified():
                self._err(401, "TOTP verification required")
            else:
                import sqlite3
                connection = sqlite3.connect(s.audit.database)
                try:
                    rows = connection.execute(
                        "SELECT id, timestamp_utc, event_type, decision, session_id, detail_json "
                        "FROM audit_events ORDER BY id DESC LIMIT 200"
                    ).fetchall()
                finally:
                    connection.close()
                events = [{"id": r[0], "timestamp_utc": r[1], "event_type": r[2],
                          "decision": r[3], "session_id": r[4], "detail": json.loads(r[5])} for r in rows]
                self._json({"events": events})
        else:
            self._serve_static_file(path)

    def do_POST(self):
        s = self.service
        path = self.path
        if not self._origin_allowed():
            self._err(403, "Origin is not allowed")
            return
        if not self._authenticated():
            self._err(401, "Authentication required")
            return
        content_length = int(self.headers.get("Content-Length", 0) or 0)
        if content_length > MAX_REQUEST_BODY_BYTES:
            s.audit.record("request", "deny", detail={"reason": "request_too_large", "path": path, "bytes": content_length})
            self._err(413, "Request body too large")
            return

        # 0. 非常時緊急物理キルスイッチ (Emergency Kill)
        if path == "/api/kill":
            self._json({"status": "killing", "message": "Emergency kill signal issued."})
            threading.Thread(target=lambda: emergency_kill("user_gui_emergency_button")).start()
            return

        # 0.5 管理者向け監査画面のTOTPセットアップ（既存シークレットがある場合は現行TOTPで再発行を確認）
        if path == "/api/admin/totp/setup":
            store = SecretStore()
            existing = store.get(ADMIN_TOTP_SECRET_NAME)
            if existing and not self._totp_verified():
                self._err(401, "Existing TOTP code required to rotate the secret")
                return
            secret = generate_totp_secret()
            store.set(ADMIN_TOTP_SECRET_NAME, secret)
            s.audit.record("admin_totp", "rotate" if existing else "create")
            self._json({"secret": secret, "provisioning_uri": provisioning_uri(secret)})
            return

        if path == "/api/providers/save":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                provider = str(payload.get("provider", ""))
                s.save_provider_secret(provider, payload.get("credential", ""))
                self._json({"ok": True, "provider": provider})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path == "/api/customizations/reload":
            try:
                result = s.customizations.reload()
                s.audit.record("customization", "reloaded", detail=result)
                self._json({"ok": True, "summary": s.customizations.summary(), "counts": result})
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path == "/api/models/set":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._json({"ok": True, "selection": s.save_model_selection(
                    str(payload.get("model", "auto")), payload.get("temperature", 0.3), payload.get("max_tokens", 2048))})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path in ("/api/customizations/save", "/api/customizations/validate"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                if path.endswith("validate"):
                    self._json({"ok": not s.customizations.validate(), "errors": s.customizations.validate()})
                else:
                    saved = s.customizations.save_file(str(payload.get("path", "")), str(payload.get("content", "")))
                    s.audit.record("customization", "saved", detail={"path": saved["path"]})
                    self._json({"ok": True, "file": saved})
            except (ValueError, TypeError, json.JSONDecodeError, OSError) as error:
                self._err(400, str(error))
            return

        if path in ("/api/marketplace/install", "/api/marketplace/uninstall", "/api/marketplace/toggle"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                extension_id = str(payload.get("id", ""))
                if path.endswith("install"):
                    result = s.marketplace.install(extension_id)
                elif path.endswith("uninstall"):
                    result = s.marketplace.uninstall(extension_id)
                else:
                    result = s.marketplace.toggle(extension_id, bool(payload.get("enabled", True)))
                s.audit.record("extension", "changed", detail={"id": extension_id, "action": path.rsplit("/", 1)[-1]})
                self._json({"ok": True, "extension": result})
            except (ValueError, TypeError, json.JSONDecodeError, OSError) as error:
                self._err(400, str(error))
            return

        if path == "/api/mcp/list-tools" or path == "/api/mcp/call":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                server = str(payload.get("server", ""))
                if path.endswith("list-tools"):
                    result = s.mcp.list_tools(server)
                    action = "list_tools"
                else:
                    tool = str(payload.get("tool", ""))
                    if re.search(r"(?:write|create|update|delete|push|send|execute|run)", tool, re.IGNORECASE) and not payload.get("approved"):
                        self._err(409, "This MCP operation requires explicit approval")
                        return
                    result = s.mcp.call_tool(server, tool, payload.get("arguments", {}))
                    action = "call"
                s.audit.record("mcp_external", action, detail={"server": server})
                self._json({"ok": True, "result": result})
            except (ValueError, TypeError, json.JSONDecodeError, RuntimeError) as error:
                s.audit.record("mcp_external", "error", detail={"error": str(error)[:300]})
                self._err(400, str(error))
            return

        if path == "/api/providers/test":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._json(s.test_provider(str(payload.get("provider", ""))))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path == "/api/integrations/credential/save":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                secret_name = str(payload.get("secret_name", ""))
                value = payload.get("credential", "")
                allowed = {secret for entry in s.integrations.entries().values() for secret in entry["required_secrets"]}
                if secret_name not in allowed:
                    raise ValueError("Unsupported integration credential")
                if not isinstance(value, str) or not value.strip() or len(value) > 4096:
                    raise ValueError("Credential must be between 1 and 4096 characters")
                s.secrets.set(secret_name, value.strip())
                s.audit.record("integration_credential", "saved", detail={"secret_name": secret_name})
                self._json({"ok": True, "secret_name": secret_name})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path == "/api/integrations/set-enabled":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                name = str(payload.get("name", ""))
                status = s.integrations.set_enabled(name, payload.get("enabled", False))
                s.audit.record("integration", "enabled" if status["enabled"] else "disabled", detail={"name": name})
                self._json({"ok": True, "name": name, "status": status})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path == "/api/integrations/notion/read":
            try:
                status = s.integrations.status("notion")["notion"]
                if not status["ready"]:
                    self._err(409, "Notion integration is not enabled and ready")
                    return
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                action = str(payload.get("action", ""))
                client = NotionReadClient(secrets=s.secrets)
                if action == "search":
                    result = client.search(str(payload.get("query", "")), payload.get("page_size", 10))
                elif action == "page":
                    result = client.page(str(payload.get("page_id", "")))
                else:
                    self._err(400, "action must be search or page")
                    return
                s.audit.record("integration_notion", action, detail={"ok": "error" not in result})
                self._json({"ok": "error" not in result, "result": result})
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path == "/api/terminal/start":
            result = s.terminal.start()
            s.audit.record("terminal", "start" if result.get("ok") else "error",
                           detail={"error": result.get("error")})
            self._json(result)
            return

        if path == "/api/terminal/input":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.terminal.write(payload.get("data", "")))
            except Exception as error:
                self._err(400, str(error))
            return

        if path == "/api/terminal/stop":
            result = s.terminal.stop()
            s.audit.record("terminal", "stop")
            self._json(result)
            return

        if path == "/api/agent/run":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                messages = payload.get("messages", [])
                if not isinstance(messages, list) or not messages:
                    self._err(400, "messages must be a non-empty list")
                    return
                result = s.run_agent(
                    messages,
                    requested_by=str(payload.get("requested_by", "glm-agent")),
                    max_steps=int(payload.get("max_steps", 8)),
                    max_seconds=int(payload.get("max_seconds", 180)),
                    session_id=str(payload.get("session_id", "default")),
                    model=str(payload.get("model", "auto")),
                )
                self._json(result)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            except Exception as error:
                s.record_error("agent_run", str(error))
                self._err(502, f"Agent backend error: {error}")
            return

        if path == "/api/orchestrator/plan":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                plan = s.orchestrator.create_plan(payload.get("objective", ""), payload.get("session_id"))
                self._json({"ok": True, "plan": plan})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path == "/api/orchestrator/worktrees":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                approval_id = str(payload.get("approval_id", ""))
                if s.broker.decision(approval_id) not in (True, "yes_mode", "allow_all"):
                    self._json({"ok": False, "requires_approval": True, "operation": "create_worktrees"}, 202)
                    return
                self._json(s.orchestrator.create_worktrees(str(payload.get("session_id", ""))))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            except KeyError:
                self._err(404, "session not found")
            return

        if path == "/api/orchestrator/task/authorize":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._json(s.orchestrator.authorize_task(str(payload.get("session_id", "")),
                                                         str(payload.get("task_id", "")),
                                                         str(payload.get("operation", ""))))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path == "/api/orchestrator/task/status":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._json({"ok": True, "plan": s.orchestrator.mark_task(
                    str(payload.get("session_id", "")), str(payload.get("task_id", "")),
                    str(payload.get("status", "")), payload.get("result"))})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            except KeyError:
                self._err(404, "session or task not found")
            return

        if path == "/api/mlops/airflow/submit":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._json(s.mlops.submit_airflow(str(payload.get("dag_id", "")), payload.get("conf", {})))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path == "/api/mlops/mlflow/log":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._json(s.mlops.log_mlflow(payload))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path == "/api/mlops/registry/register":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                entry = s.mlops.registry.register(str(payload.get("model_id", "")),
                                                   str(payload.get("version", "")), payload.get("metadata", {}))
                s.audit.record("model_registry", "candidate_registered", detail={"model_id": entry["model_id"], "version": entry["version"]})
                self._json({"ok": True, "entry": entry})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            return

        if path == "/api/mlops/registry/approve":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                approval_id = str(payload.get("approval_id", ""))
                if s.broker.decision(approval_id) not in (True, "yes_mode", "allow_all"):
                    self._json({"ok": False, "requires_approval": True}, 202)
                    return
                self._json(s.mlops.registry.approve(str(payload.get("model_id", "")), str(payload.get("version", ""))))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            except KeyError:
                self._err(404, "model version not found")
            return

        if path == "/api/feedback":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                rating = str(payload.get("rating", ""))
                if rating not in ("up", "down"):
                    self._err(400, "rating must be 'up' or 'down'")
                    return
                s.audit.record("chat_feedback", rating, str(payload.get("session_id", "")),
                               detail={"text": str(payload.get("text", ""))[:500]})
                self._json({"ok": True})
            except Exception as error:
                self._err(400, str(error))
            return

        if path == "/api/agent/cancel":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                session_id = str(payload.get("session_id", "default"))
                result = s.covibe.cancel(session_id)
                s.audit.record("agent_cancel", "request", detail={"session_id": session_id})
                self._json(result)
            except Exception as error:
                self._err(400, str(error))
            return

        # 1. ワークスペースファイル読み込み
        if path == "/api/workspace/read":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                rel_path = payload.get("path", "")
                content = s.read_file(rel_path)
                self._json({"path": rel_path, "content": content})
            except Exception as e:
                s.record_error("read_file", str(e))
                self._err(400, str(e))
            return

        # 1.5 ワークスペース全文検索
        if path == "/api/workspace/search":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                query = str(payload.get("query", ""))[:200]
                results = s.search_files(query) if query else []
                self._json({"ok": True, "results": results})
            except Exception as e:
                s.record_error("search_files", str(e))
                self._err(400, str(e))
            return

        # 2. ワークスペースファイル保存 (Ctrl+S)
        if path == "/api/workspace/save":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                rel_path = payload.get("path", "")
                content = payload.get("content", "")
                s.save_file(rel_path, content)
                self._json({"success": True, "path": rel_path})
            except Exception as e:
                s.record_error("save_file", str(e))
                self._err(400, str(e))
            return

        if path == "/api/language/diagnostics":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.language.diagnostics(payload.get("path", ""), payload.get("content")))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/mcp/github/call":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                result = s.github_mcp.call_tool(payload.get("name", ""), payload.get("arguments", {}))
                self._json({"ok": True, **result})
            except Exception as error:
                self._json({"ok": False, "error": str(error)}, 502)
            return

        if path == "/api/language/type-diagnostics":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.language.type_diagnostics(payload.get("path", "")))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/language/symbols":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.language.symbols(payload.get("path", ""), payload.get("content")))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/language/completions":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.language.completions(payload.get("path", ""), payload.get("prefix", ""), payload.get("content")))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/language/references":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.language.references(payload.get("path", ""), payload.get("name", ""), payload.get("content")))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/language/rename":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.language.rename(payload.get("path", ""), payload.get("name", ""), payload.get("new_name", ""), payload.get("content")))
            except Exception as e:
                self._err(400, str(e))
            return

        # ── 本格LSP (pyright-langserver) エンドポイント ──────────────────────
        if path.startswith("/api/lsp/"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                cmd = path.removeprefix("/api/lsp/")
                lsp_path = payload.get("path", "")
                line = int(payload.get("line", 1))
                character = int(payload.get("character", 1))
                content = payload.get("content")
                if content is None and lsp_path:
                    try:
                        content = s.read_file(lsp_path)
                    except Exception:
                        content = ""
                if cmd == "completions":
                    self._json(s.lsp_completion(lsp_path, line, character, content))
                elif cmd == "hover":
                    self._json(s.lsp_hover(lsp_path, line, character, content))
                elif cmd == "definition":
                    self._json(s.lsp_definition(lsp_path, line, character, content))
                elif cmd == "references":
                    self._json(s.lsp_references(lsp_path, line, character, content))
                elif cmd == "rename":
                    self._json(s.lsp_rename(lsp_path, line, character,
                                            payload.get("new_name", ""), content))
                elif cmd == "symbols":
                    self._json(s.lsp_symbols(lsp_path, content))
                elif cmd == "diagnostics":
                    self._json(s.lsp_diagnostics(lsp_path, content))
                elif cmd == "sync":
                    if s.ensure_lsp():
                        s.lsp.sync_document(lsp_path, content or "")
                        self._json({"ok": True})
                    else:
                        self._json({"ok": False, "error": "LSP server unavailable"})
                else:
                    self._err(404, f"Unknown LSP command: {cmd}")
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._err(400, str(error))
            except Exception as error:
                s.record_error("lsp_api", str(error))
                self._err(502, f"LSP backend error: {error}")
            return

        if path == "/api/jupyter/start":
            self._json(s.jupyter.start())
            return

        if path == "/api/jupyter/stop":
            self._json(s.jupyter.stop())
            return

        if path == "/api/jupyter/restart":
            self._json(s.jupyter.restart())
            return

        if path == "/api/jupyter/interrupt":
            self._json(s.jupyter.interrupt())
            return

        if path == "/api/dap/launch":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.dap.launch(payload.get("path", ""), payload.get("wait_for_client", True)))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/dap/stop":
            self._json(s.dap.stop())
            return

        if path == "/api/dap/connect":
            self._json(s.dap.connect_client())
            return

        if path == "/api/dap/events":
            self._json(s.dap.events())
            return

        if path == "/api/dap/breakpoints":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.dap.set_breakpoints(payload.get("path", ""), payload.get("lines", [])))
            except Exception as e:
                self._err(400, str(e))
            return

        if path in {"/api/dap/continue", "/api/dap/next", "/api/dap/step-in", "/api/dap/step-out",
                    "/api/dap/threads", "/api/dap/stack-trace", "/api/dap/scopes", "/api/dap/variables"}:
            command_map = {"/api/dap/continue": "continue", "/api/dap/next": "next",
                           "/api/dap/step-in": "stepIn", "/api/dap/step-out": "stepOut",
                           "/api/dap/threads": "threads", "/api/dap/stack-trace": "stackTrace",
                           "/api/dap/scopes": "scopes", "/api/dap/variables": "variables"}
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                self._json(s.dap.control(command_map[path], payload))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/sftp/list":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.sftp.list_remote(payload.get("host", ""), payload.get("remote_path", "."), payload.get("user"), payload.get("port", 22)))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/sftp/test":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.sftp.test_connection(payload.get("host", ""), payload.get("user"), payload.get("port", 22)))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/sftp/profile/save":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.sftp.save_profile(payload.get("name", ""), payload.get("host", ""), payload.get("user"), payload.get("port", 22), payload.get("remote_path", ".")))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/sftp/profile/delete":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.sftp.delete_profile(payload.get("name", "")))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/sftp/download":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.sftp.download(payload.get("host", ""), payload.get("remote_path", ""), payload.get("local_path", ""), payload.get("user"), payload.get("port", 22)))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/sftp/upload":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.sftp.upload(payload.get("host", ""), payload.get("local_path", ""), payload.get("remote_path", ""), payload.get("user"), payload.get("port", 22)))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/workspace/definitions":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.find_definitions(payload.get("path", ""), payload.get("name", ""), payload.get("content")))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/workspace/notebook/execute":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.run_notebook_cell(payload.get("source", ""), payload.get("timeout", 30)))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/git/stage":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.git_stage(payload.get("paths", [])))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/git/checkout":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.git_checkout(payload.get("branch", "")))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/git/push":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(s.git_push(payload.get("remote", "origin"), payload.get("branch", "")))
            except Exception as e:
                self._err(400, str(e))
            return

        if path == "/api/workspace/create":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                s.create_file(payload.get("path", ""), payload.get("content", ""))
                self._json({"success": True, "path": payload.get("path", "")})
            except Exception as e:
                s.record_error("create_file", str(e))
                self._err(400, str(e))
            return

        if path == "/api/workspace/create-folder":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                rel_path = payload.get("path", "")
                s.create_folder(rel_path)
                self._json({"success": True, "path": rel_path})
            except Exception as e:
                s.record_error("create_folder", str(e))
                self._err(400, str(e))
            return

        if path == "/api/workspace/delete":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                s.delete_entry(payload.get("path", ""))
                self._json({"success": True, "path": payload.get("path", "")})
            except Exception as e:
                s.record_error("delete_file", str(e))
                self._err(400, str(e))
            return

        if path == "/api/workspace/move":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                s.move_file(payload.get("source", ""), payload.get("destination", ""))
                self._json({"success": True})
            except Exception as e:
                s.record_error("move_file", str(e))
                self._err(400, str(e))
            return

        if path == "/api/workspace/search":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json({"results": s.search_files(payload.get("query", ""), payload.get("max_results", 100))})
            except Exception as e:
                self._err(400, str(e))
            return

        # 2.1 ワンクリックコード実行 (Python / PowerShell / C++ / Java)
        if path == "/api/workspace/execute":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                rel_path = payload.get("path", "")
                content = payload.get("content", None)
                res = s.execute_code(rel_path, content)
                self._json(res)
            except Exception as e:
                s.record_error("execute_code", str(e))
                self._err(400, str(e))
            return

        # 2.2 Jupyter Notebook (.ipynb) パース
        if path == "/api/workspace/ipynb":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                rel_path = payload.get("path", "")
                res = s.read_ipynb(rel_path)
                self._json(res)
            except Exception as e:
                self._err(400, str(e))
            return

        # 2.5 構文チェック (Syntax Diagnostics)
        if path == "/api/workspace/syntax":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                rel_path = payload.get("path", "")
                content = payload.get("content", None)
                res = s.check_syntax(rel_path, content)
                self._json(res)
            except Exception as e:
                self._err(400, str(e))
            return

        # 2.6 Git ステージング & コミット
        if path == "/api/git/commit":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                msg = payload.get("message", "")
                res = s.git_commit(msg)
                self._json(res)
            except Exception as e:
                self._err(400, str(e))
            return

        # 3. 承認ブローカー応答
        if path == "/respond":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                accepted = s.broker.respond(payload.get("id", ""), payload.get("decision"))
                self._json({"accepted": accepted})
            except Exception as e:
                self._err(400, str(e))
            return

        # 4. OpenAI 互換チャット completions & SSE ストリーミング
        if path == "/v1/chat/completions":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                payload = json.loads(raw) if raw else {}
                messages = payload.get("messages", [])
                sid = payload.get("session_id") or s.router._cur_sid
                if not sid:
                    sid = s.router.sess.new("unknown")
                    s.router._cur_sid = sid

                tier_name, needs_bridge, tokens = s.router.decide_tier(messages, sid)
                tier = s.router.tier_info(tier_name)

                if needs_bridge and messages:
                    bridge = build_bridge(messages)
                    if messages[0].get("role") == "system":
                        messages[0]["content"] = bridge + messages[0].get("content", "")
                    else:
                        messages.insert(0, {"role": "system", "content": bridge})

                self._forward_llm(payload, messages, tier, sid, tier_name)
            except Exception as e:
                s.record_error("llm_completions", str(e))
                self._err(500, f"Router completion error: {e}")
            return

        self.send_response(404)
        self._cors_headers()
        self.end_headers()

    def _forward_llm(self, payload: dict, messages: list, tier: dict, sid: str, tier_name: str):
        """Ollama または クラウド API へのリクエストフォワード (SSEストリーミング対応)"""
        execution = tier.get("execution", "gpu")
        fwd = dict(payload)
        fwd["messages"] = messages
        is_stream = bool(fwd.get("stream", False))

        if execution in ("gpu", "cpu"):
            target = OLLAMA_URL + "/v1/chat/completions"
            requested_model = tier.get("base_model", "qwen2.5-coder:7b")
            fwd["model"] = requested_model
            headers = {"Content-Type": "application/json"}
        else:
            providers = self.service.router.reg._d.get("cloud_api", {}).get("providers", {})
            provider = str(payload.get("provider") or tier.get("provider", "anthropic"))
            config = providers.get(provider)
            if not config:
                self._err(400, "Unsupported cloud provider")
                return
            api_key = self.service.provider_api_key(provider)
            if not api_key:
                self._err(500, "Cloud API key not set")
                return
            requested_model = str(payload.get("model") or tier.get("base_model", ""))
            if requested_model not in config.get("models", []):
                self._err(400, "Model is not enabled for this provider")
                return
            target = config["base_url"]
            fwd["model"] = requested_model
            if provider == "openai":
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            else:
                system_messages = [str(message.get("content", "")) for message in messages if message.get("role") == "system"]
                fwd["messages"] = [message for message in messages if message.get("role") != "system"]
                if system_messages:
                    fwd["system"] = "\n\n".join(system_messages)
                fwd["max_tokens"] = int(fwd.pop("max_tokens", 2048))
                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                }

        body = json.dumps(fwd).encode("utf-8")
        try:
            req = urllib.request.Request(target, data=body, headers=headers, method="POST")
            try:
                response = urllib.request.urlopen(req, timeout=120)
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
                # registryの旧モデルが未取得でも、利用可能なローカルモデルへ退避する。
                with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=5) as tags_response:
                    installed = json.loads(tags_response.read().decode("utf-8")).get("models", [])
                installed_names = [str(model.get("name", "")) for model in installed]
                fallback = "qwen2.5-coder:7b" if "qwen2.5-coder:7b" in installed_names else (installed_names[0] if installed_names else "")
                if not fallback or fallback == requested_model:
                    raise
                fwd["model"] = fallback
                log.warning("Ollama model %s is unavailable; falling back to %s", requested_model, fallback)
                req = urllib.request.Request(target, data=json.dumps(fwd).encode("utf-8"), headers=headers, method="POST")
                response = urllib.request.urlopen(req, timeout=120)
            with response as resp:
                if is_stream:
                    self.send_response(200)
                    self._cors_headers()
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    while True:
                        chunk = resp.read(1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    self.service.router.sess.update(
                        sid, messages,
                        tokens=sum(estimate_tokens(m.get("content", "") if isinstance(m.get("content"), str) else "") for m in messages),
                        tier=tier_name
                    )
                else:
                    resp_body = resp.read()
                    self.service.router.sess.update(
                        sid, messages,
                        tokens=sum(estimate_tokens(m.get("content", "") if isinstance(m.get("content"), str) else "") for m in messages),
                        tier=tier_name
                    )
                    self._json(json.loads(resp_body))
        except Exception as e:
            self.service.record_error("llm_forward", str(e))
            self._err(502, f"Backend connection issue: {e}")


def start_unified_server(workspace: Optional[str] = None, port: int = CORE_PORT, bind_host: str = "127.0.0.1"):
    """単一プロセスサーバーの起動と終了アテグジット登録"""
    bind_host = validate_bind_host(bind_host)
    service = UnifiedCoreService(workspace)
    UnifiedCoreHandler.service = service

    try:
        server = BoundedThreadingHTTPServer((bind_host, port), UnifiedCoreHandler)
    except OSError as error:
        # 旧プロセス残存によるポート競合を静かに見逃さず、明示的に失敗させる
        log.error("Port %d is already in use (旧Coreプロセスが残っている可能性): %s", port, error)
        print(f"[GLM] ERROR: ポート {port} は使用中です。既存のCoreプロセスを終了してください。", flush=True)
        raise SystemExit(2) from error

    def cleanup():
        log.info("Executing shutdown cleanup...")
        service.shutdown()
        try:
            server.server_close()
        except Exception:
            pass

    atexit.register(cleanup)
    log.info("GLM Unified Core running at http://%s:%d", bind_host, port)
    print(f"[GLM] Core listening on http://{bind_host}:{port} (preload co-vibe: {service.covibe._module is not None})", flush=True)
    return server, service


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GLM IDE Unified Core Daemon")
    parser.add_argument("--port", type=int, default=CORE_PORT)
    parser.add_argument("--workspace", type=str, default=None)
    parser.add_argument("--bind-host", type=str, default="127.0.0.1",
                        help="Loopback or this PC's Tailscale IPv4 address")
    args = parser.parse_args()

    server, service = start_unified_server(args.workspace, args.port, args.bind_host)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
