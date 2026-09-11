"""co-vibe AgentをGLM Coreから利用する統合Adapter。"""

import importlib.util
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from glm_sandbox import SandboxRunner
from glm_security import AuditLogger, WorkspaceGuard
from router import classify_risk


class GLMApprovalProvider:
    """co-vibeの承認要求をGLMのApprovalBrokerへ中継する。"""

    def __init__(self, broker, audit, timeout_seconds=60):
        self.broker = broker
        self.audit = audit
        self.timeout_seconds = timeout_seconds

    def ask_permission(self, tool_name, params):
        request_id = uuid.uuid4().hex
        risk = classify_risk(f"{tool_name} {json.dumps(params, ensure_ascii=False)}")
        request = {
            "type": "approval_request",
            "id": request_id,
            "tool": tool_name,
            "params": params,
            "reason": f"co-vibe Agent requested {tool_name}",
            "target": params.get("file_path", params.get("command", tool_name)),
            "scope": "workspace or configured tool scope",
            "expires_in_minutes": max(1, self.timeout_seconds // 60),
            "requested_by": "co-vibe-agent",
            "risk_category": risk,
        }
        self.broker.publish(request)
        self.audit.record("agent_approval", "pending", "co-vibe-agent",
                          {"tool": tool_name, "risk_category": risk, "request_id": request_id})
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            decision = self.broker.decision(request_id)
            if decision is not None:
                self.audit.record("agent_approval", "decision", "co-vibe-agent",
                                  {"tool": tool_name, "decision": decision, "request_id": request_id})
                return decision
            time.sleep(0.25)
        self.audit.record("agent_approval", "timeout", "co-vibe-agent",
                          {"tool": tool_name, "request_id": request_id})
        return False


class HeadlessTUI:
    """co-vibe Agent用のGUI向けTUI代替。端末出力をせず、結果とtraceを保持する。"""

    def __init__(self, module):
        self.module = module
        self.config = None
        self.is_interactive = False
        self.scroll_region = type("ScrollRegionState", (), {"_active": False})()
        self.trace = []
        self.last_text = ""

    def reset(self):
        self.trace = []
        self.last_text = ""

    def start_spinner(self, *args, **kwargs):
        return None

    def stop_spinner(self, *args, **kwargs):
        return None

    def start_tool_status(self, *args, **kwargs):
        return None

    def _scroll_print(self, *args, **kwargs):
        return None

    def _render_markdown(self, text):
        self.last_text = text

    def show_tool_call(self, name, params):
        self.trace.append({"event": "tool_call", "tool": name, "params": params})

    def show_tool_result(self, name, result, is_error=False, **kwargs):
        self.trace.append({"event": "tool_result", "tool": name,
                           "result": str(result)[:20000], "is_error": is_error})

    def show_sync_response(self, data, known_tools=None):
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "") or ""
        tool_calls = message.get("tool_calls", [])
        if not tool_calls and content and known_tools:
            extractor = getattr(self.module, "_extract_tool_calls_from_text", None)
            if extractor:
                tool_calls, content = extractor(content, known_tools)
        self.last_text = content
        return content, tool_calls

    def stream_response(self, response_iter):
        content = []
        tool_calls = {}
        for chunk in response_iter:
            choice = chunk.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            if delta.get("content"):
                content.append(delta["content"])
            for call in delta.get("tool_calls", []):
                index = call.get("index", 0)
                current = tool_calls.setdefault(index, {"id": "", "type": "function",
                                                        "function": {"name": "", "arguments": ""}})
                current["id"] = call.get("id", current["id"])
                function = call.get("function", {})
                current["function"]["name"] += function.get("name", "")
                current["function"]["arguments"] += function.get("arguments", "")
        text = "".join(content)
        self.last_text = text
        return text, [tool_calls[key] for key in sorted(tool_calls)]


class _SandboxedBashTool:
    """co-vibeのBashツールをGLMの隔離ランタイム(WSL2)実行へ強制するラッパー。

    ホスト上での直接実行経路を残さない。バックグラウンド実行は隔離ランタイムの
    ライフサイクルと両立しないため拒否する。
    """

    def __init__(self, inner, runner, audit):
        self._inner = inner
        self._runner = runner
        self._audit = audit
        self.name = inner.name
        self.description = (getattr(inner, "description", "")
                            + " Executed inside the GLM isolated sandbox (WSL2); host execution is disabled.")
        self.parameters = getattr(inner, "parameters", {"type": "object", "properties": {}})

    def get_schema(self):
        if hasattr(self._inner, "get_schema"):
            schema = self._inner.get_schema()
            schema["function"]["description"] = self.description
            return schema
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}

    def execute(self, params):
        command = str(params.get("command", ""))
        if params.get("run_in_background"):
            return "Error: run_in_background is not supported inside the GLM sandbox. Run synchronously."
        try:
            timeout_ms = float(params.get("timeout", 120000))
        except (TypeError, ValueError):
            timeout_ms = 120000
        timeout_seconds = max(1, min(int(timeout_ms / 1000), 300))
        result = self._runner.run_shell(command, timeout_seconds=timeout_seconds)
        self._audit.record("covibe_tool", "sandbox_bash", "co-vibe-agent",
                           {"command": command[:500], "ok": result.get("ok"),
                            "exit_code": result.get("exit_code")})
        if not result.get("ok") and not result.get("output"):
            return f"Error: {result.get('error', 'sandbox execution failed')}"
        output = result.get("output", "")
        if result.get("error"):
            output = f"{output}\nError: {result['error']}".strip()
        return output or "(no output)"


class _WorkspaceGuardedTool:
    """ファイル書き込み系ツールのパスをWorkspaceGuardで検証するラッパー。"""

    _PATH_KEYS = ("file_path", "notebook_path", "path")

    def __init__(self, inner, guard, audit):
        self._inner = inner
        self._guard = guard
        self._audit = audit
        self.name = inner.name
        self.description = getattr(inner, "description", "")
        self.parameters = getattr(inner, "parameters", {"type": "object", "properties": {}})

    def get_schema(self):
        if hasattr(self._inner, "get_schema"):
            return self._inner.get_schema()
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}

    def execute(self, params):
        for key in self._PATH_KEYS:
            raw = params.get(key)
            if not raw:
                continue
            candidate = Path(str(raw))
            if not candidate.is_absolute():
                candidate = self._guard.workspace / candidate
            try:
                self._guard.require_contained(candidate)
            except (PermissionError, OSError) as error:
                self._audit.record("covibe_tool", "deny", "co-vibe-agent",
                                   {"tool": self.name, "path": str(raw), "error": str(error)[:200]})
                return f"Error: access denied by GLM WorkspaceGuard: {error}"
        return self._inner.execute(params)


def _normalize_trace(events):
    """HeadlessTUIのイベント列をUI互換の {step, tool, result} 形式へ変換する。"""
    normalized = []
    step = 0
    for event in events:
        if event.get("event") == "tool_call":
            step += 1
            normalized.append({"step": step, "tool": event.get("tool", "?"),
                               "params": event.get("params", {}), "result": ""})
        elif event.get("event") == "tool_result" and normalized:
            normalized[-1]["result"] = event.get("result", "")
            normalized[-1]["is_error"] = bool(event.get("is_error"))
    return normalized


class CoVibeAdapter:
    """GLMのワークスペース・承認・監査をco-vibe Agentへ接続する。

    セッションはsession_id単位で分離され、各ランタイムは独立した会話履歴を持つ。
    実行時にはGLMが受け取ったmessagesで履歴を再シードするため、要求間で
    履歴が混入しない。
    """

    MAX_SESSIONS = 8

    def __init__(self, workspace, broker, audit=None, co_vibe_path=None):
        self.workspace = Path(workspace).resolve()
        self.broker = broker
        self.audit = audit or AuditLogger()
        self.co_vibe_path = Path(co_vibe_path or Path(__file__).parent.parent / "co-vibe-core" / "co-vibe.py").resolve()
        self.guard = WorkspaceGuard(self.workspace)
        self.sandbox = SandboxRunner(self.workspace)
        self._lock = threading.RLock()
        self._module = None
        self._runtimes = {}  # session_id -> runtime dict

    def available(self):
        return self.co_vibe_path.is_file()

    def _load_module(self):
        if self._module is not None:
            return self._module
        if not self.available():
            raise RuntimeError(f"co-vibe core was not found: {self.co_vibe_path}")
        # co-vibeはモジュールimport時に signal.signal() を呼ぶため、
        # 非メインスレッドでの初回ロードは必ず失敗する。事前ロードを要求する。
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError(
                "co-vibe module must be preloaded on the main thread "
                "(call preload() during service startup)")
        covibe_root = str(self.co_vibe_path.parent)
        if covibe_root not in sys.path:
            sys.path.insert(0, covibe_root)
        spec = importlib.util.spec_from_file_location("glm_embedded_covibe", self.co_vibe_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load co-vibe module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._module = module
        return module

    def preload(self):
        """サービス起動時（メインスレッド）にco-vibeモジュールだけを先行ロードする。

        プロバイダ接続やセッション構築は行わない。失敗しても例外は投げず、
        利用可否はavailable()/実行時エラーで判定する。
        """
        try:
            self._load_module()
            return True
        except RuntimeError:
            return False

    def _harden_registry(self, registry):
        """Bashを隔離実行へ差し替え、書き込み系ツールへWorkspaceGuardを適用する。"""
        hardened = []
        for name in registry.names():
            tool = registry.get(name)
            if name == "Bash":
                tool = _SandboxedBashTool(tool, self.sandbox, self.audit)
            elif name in ("Write", "Edit", "NotebookEdit"):
                tool = _WorkspaceGuardedTool(tool, self.guard, self.audit)
            registry._tools[name] = tool
            hardened.append(name)
        registry._cached_schemas = None
        return hardened

    def _build_runtime(self, session_id="default"):
        module = self._load_module()
        config = module.Config()
        config.cwd = str(self.workspace)
        config.model = os.environ.get("GLM_COVIBE_MODEL", "qwen2.5-coder:7b")
        config.strategy = os.environ.get("GLM_COVIBE_STRATEGY", "auto")
        config.session_id = session_id
        config.yes_mode = False
        config.debug = False
        config.load([])
        client = module.MultiProviderClient(config)
        ok, models = client.check_connection(retries=1)
        if not ok:
            raise RuntimeError("co-vibe has no available provider")
        session = module.Session(config, module._build_system_prompt(config))
        session.set_client(client)
        registry = module.ToolRegistry().register_defaults()
        self._harden_registry(registry)
        permissions = module.PermissionMgr(
            config,
            approval_provider=GLMApprovalProvider(self.broker, self.audit),
        )
        tui = HeadlessTUI(module)
        agent = module.Agent(config, client, registry, permissions, session, tui)
        return {"module": module, "config": config, "client": client, "session": session,
                "registry": registry, "permissions": permissions, "tui": tui, "agent": agent,
                "models": models, "session_id": session_id}

    def _runtime_for(self, session_id):
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            while len(self._runtimes) >= self.MAX_SESSIONS:
                oldest = next(iter(self._runtimes))
                self._runtimes.pop(oldest)
            runtime = self._build_runtime(session_id)
            self._runtimes[session_id] = runtime
        else:
            self._runtimes[session_id] = self._runtimes.pop(session_id)  # LRU: re-insert at end
        return runtime

    def cancel(self, session_id="default"):
        """実行中のAgentループへ中断シグナルを送る。"""
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            return {"ok": False, "error": "no active session"}
        runtime["agent"]._interrupted.set()
        self.audit.record("covibe_agent", "cancel", "standalone-ui", {"session_id": session_id})
        return {"ok": True, "session_id": session_id}

    def run(self, messages, requested_by="standalone-ui", max_steps=8, max_seconds=180,
            session_id="default"):
        if not isinstance(messages, list) or not messages:
            return {"ok": False, "error": "messages must be a non-empty list"}
        session_id = str(session_id or "default")[:64]
        with self._lock:
            runtime = self._runtime_for(session_id)
            prompt = next((m.get("content", "") for m in reversed(messages)
                           if m.get("role") == "user"), "")
            if not prompt:
                return {"ok": False, "error": "a user message is required"}

            # 要求間の履歴混入を防ぐため、GLM側が受け取った履歴で再シードする。
            seeded = []
            history = messages[:-1] if messages and messages[-1].get("role") == "user" else messages
            for message in history[-40:]:
                role = message.get("role")
                content = message.get("content")
                if role in ("user", "assistant", "system") and isinstance(content, str):
                    seeded.append({"role": role, "content": content})
            runtime["session"].messages = seeded
            runtime["tui"].reset()
            runtime["agent"]._interrupted.clear()

            original_cwd = os.getcwd()
            try:
                os.chdir(self.workspace)
                agent = runtime["agent"]
                agent.MAX_ITERATIONS = max(1, min(int(max_steps), 50))
                worker = threading.Thread(target=agent.run, args=(prompt,), daemon=True)
                worker.start()
                worker.join(max(1, int(max_seconds)))
                if worker.is_alive():
                    agent._interrupted.set()
                    self.audit.record("covibe_agent", "timeout", requested_by,
                                      {"workspace": str(self.workspace), "max_seconds": max_seconds,
                                       "session_id": session_id})
                    return {"ok": False, "error": "co-vibe Agent timed out", "engine": "co-vibe",
                            "trace": _normalize_trace(runtime["tui"].trace),
                            "models": runtime["models"], "session_id": session_id}
            finally:
                os.chdir(original_cwd)
            assistant_messages = [m for m in runtime["session"].messages
                                  if m.get("role") == "assistant"]
            answer = assistant_messages[-1].get("content", "") if assistant_messages else runtime["tui"].last_text
            trace = _normalize_trace(runtime["tui"].trace)
            self.audit.record("covibe_agent", "complete", requested_by,
                              {"workspace": str(self.workspace), "models": runtime["models"],
                               "session_id": session_id, "steps": len(trace)})
            return {"ok": True, "engine": "co-vibe", "answer": answer, "steps": len(trace),
                    "trace": trace, "models": runtime["models"], "session_id": session_id}
