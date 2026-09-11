"""GLM multi-agent orchestration primitives.

The module is intentionally dependency-free. It creates plans and isolated git
worktrees, but never merges or executes a high-risk operation automatically.
"""

import json
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


SAFE_AGENT_PROFILES = {
    "coordinator": {"model": "auto", "tools": ["read", "plan"], "can_write": False, "can_execute": False, "allow_web": False},
    "researcher": {"model": "auto", "tools": ["read", "search", "web"], "can_write": False, "can_execute": False, "allow_web": False},
    "implementer": {"model": "GLM-0.2-fast", "tools": ["read", "write", "search"], "can_write": True, "can_execute": False, "allow_web": False},
    "tester": {"model": "auto", "tools": ["read", "test"], "can_write": False, "can_execute": True, "allow_web": False},
    "security_reviewer": {"model": "auto", "tools": ["read", "search", "security"], "can_write": False, "can_execute": False, "allow_web": False},
}


@dataclass
class AgentTask:
    task_id: str
    role: str
    objective: str
    depends_on: List[str]
    status: str = "pending"
    worktree: str = ""
    result: Optional[Dict[str, Any]] = None


class AgentPolicy:
    def __init__(self, profiles: Optional[Dict[str, Dict[str, Any]]] = None):
        self.profiles = profiles or SAFE_AGENT_PROFILES

    def profile(self, role: str) -> Dict[str, Any]:
        if role not in self.profiles:
            raise ValueError("unknown agent role")
        return dict(self.profiles[role])

    def authorize(self, role: str, operation: str) -> bool:
        profile = self.profile(role)
        return {
            "read": True,
            "plan": True,
            "search": True,
            "web": bool(profile.get("allow_web", False)),
            "write": bool(profile.get("can_write", False)),
            "execute": bool(profile.get("can_execute", False)),
            "merge": False,
            "push": False,
        }.get(operation, False)


class WorktreeManager:
    def __init__(self, workspace: Path, root: Optional[Path] = None):
        self.workspace = workspace.resolve()
        self.root = (root or self.workspace / ".glm" / "worktrees").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _run(self, args: List[str], timeout: int = 20) -> subprocess.CompletedProcess:
        return subprocess.run(args, cwd=str(self.workspace), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)

    def create(self, session_id: str, task_id: str) -> Dict[str, Any]:
        if not (self.workspace / ".git").exists():
            return {"ok": False, "error": "workspace is not a git repository"}
        if not re.fullmatch(r"[A-Za-z0-9._-]+", session_id) or not re.fullmatch(r"[A-Za-z0-9._-]+", task_id):
            return {"ok": False, "error": "invalid session or task id"}
        path = (self.root / session_id / task_id).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        branch = f"glm/{session_id}/{task_id}"
        result = self._run(["git", "worktree", "add", "-b", branch, str(path), "HEAD"])
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip()[:1000]}
        return {"ok": True, "path": str(path), "branch": branch}

    def remove(self, path: str) -> Dict[str, Any]:
        target = Path(path).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            return {"ok": False, "error": "worktree path is outside managed root"}
        result = self._run(["git", "worktree", "remove", "--force", str(target)])
        return {"ok": result.returncode == 0, "error": result.stderr.strip()[:1000]}


class Coordinator:
    def __init__(self, workspace: Path, audit: Any, policy: Optional[AgentPolicy] = None):
        self.workspace = workspace.resolve()
        self.audit = audit
        self.policy = policy or AgentPolicy()
        self.worktrees = WorktreeManager(self.workspace)
        self._lock = threading.Lock()
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def create_plan(self, objective: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        objective = str(objective or "").strip()[:4000]
        if not objective:
            raise ValueError("objective is required")
        session_id = session_id or "glm-" + uuid.uuid4().hex[:12]
        tasks = [
            AgentTask(session_id + "-research", "researcher", "調査と関連箇所の整理", []),
            AgentTask(session_id + "-implement", "implementer", "承認済み計画に基づく実装", [session_id + "-research"]),
            AgentTask(session_id + "-test", "tester", "変更のテストと診断", [session_id + "-implement"]),
            AgentTask(session_id + "-security", "security_reviewer", "差分・権限・外部送信の安全性確認", [session_id + "-implement"]),
        ]
        plan = {"session_id": session_id, "objective": objective, "status": "planned",
                "created_at": time.time(), "tasks": [asdict(task) for task in tasks],
                "auto_merge": False, "airflow": {"enabled": False}, "mlflow": {"enabled": False}}
        with self._lock:
            self.sessions[session_id] = plan
        self.audit.record("orchestrator", "plan_created", session_id, {"task_count": len(tasks)})
        return self.snapshot(session_id)

    def snapshot(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            if session_id not in self.sessions:
                raise KeyError(session_id)
            return json.loads(json.dumps(self.sessions[session_id]))

    def create_worktrees(self, session_id: str) -> Dict[str, Any]:
        plan = self.snapshot(session_id)
        created = []
        for task in plan["tasks"]:
            if task["role"] == "coordinator":
                continue
            result = self.worktrees.create(session_id, task["task_id"])
            if not result.get("ok"):
                self.audit.record("orchestrator", "worktree_denied", session_id, {"task_id": task["task_id"], "error": result.get("error")})
                return {"ok": False, "created": created, "error": result.get("error")}
            created.append(result)
            task["worktree"] = result["path"]
        with self._lock:
            self.sessions[session_id] = plan
            self.sessions[session_id]["status"] = "ready"
        self.audit.record("orchestrator", "worktrees_created", session_id, {"count": len(created)})
        return {"ok": True, "created": created, "session_id": session_id}

    def authorize_task(self, session_id: str, task_id: str, operation: str) -> Dict[str, Any]:
        plan = self.snapshot(session_id)
        task = next((item for item in plan["tasks"] if item["task_id"] == task_id), None)
        if not task:
            return {"ok": False, "error": "task not found"}
        allowed = self.policy.authorize(task["role"], operation)
        self.audit.record("orchestrator", "task_allow" if allowed else "task_deny", session_id,
                          {"task_id": task_id, "role": task["role"], "operation": operation})
        return {"ok": allowed, "role": task["role"], "operation": operation,
                "reason": "policy" if allowed else "operation is denied by default policy"}

    def mark_task(self, session_id: str, task_id: str, status: str, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if status not in {"pending", "running", "success", "failed", "blocked", "awaiting_approval"}:
            raise ValueError("invalid task status")
        with self._lock:
            plan = self.sessions.get(session_id)
            if not plan:
                raise KeyError(session_id)
            for task in plan["tasks"]:
                if task["task_id"] == task_id:
                    task["status"] = status
                    task["result"] = result
                    break
            else:
                raise KeyError(task_id)
        self.audit.record("orchestrator", "task_status", session_id, {"task_id": task_id, "status": status})
        return self.snapshot(session_id)
