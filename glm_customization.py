"""Workspace customization registry for skills, instructions, agents, hooks, and MCP metadata."""

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DOCUMENT_PATTERNS = {
    "skill": ("SKILL.md", "*.skill.md"),
    "instruction": ("*.instructions.md", ".github/copilot-instructions.md"),
    "prompt": ("*.prompt.md",),
    "agent": ("*.agent.md",),
}


def _read_text(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")[:limit]
    except (OSError, UnicodeError):
        return ""


def _frontmatter(text: str) -> Dict[str, Any]:
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    if len(lines) < 3:
        return {}
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return {}
    values: Dict[str, Any] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = [item.strip() for item in value[1:-1].split(",") if item.strip()]
        values[key.strip()] = value.strip('"\'') if isinstance(value, str) else value
    return values


class CustomizationRegistry:
    """Loads declarative customization files without executing arbitrary code."""

    def __init__(self, workspace: Path, global_root: Optional[Path] = None):
        self.workspace = Path(workspace).resolve()
        self.global_root = Path(global_root or (Path.home() / ".glm")).resolve()
        self.items: List[Dict[str, Any]] = []
        self.mcp_servers: Dict[str, Dict[str, Any]] = {}
        self.hooks: Dict[str, List[str]] = {}
        self.reload()

    def _roots(self) -> Iterable[Path]:
        return (self.workspace, self.workspace / ".github", self.workspace / ".glm" / "skills",
            self.workspace / ".github" / "skills", self.global_root, self.global_root / "skills")

    def reload(self) -> Dict[str, int]:
        items: List[Dict[str, Any]] = []
        seen = set()
        for root in self._roots():
            if not root.exists():
                continue
            for kind, patterns in DOCUMENT_PATTERNS.items():
                for pattern in patterns:
                    candidates = root.rglob(pattern) if root.is_dir() else []
                    if pattern.startswith(".") and root == self.workspace:
                        candidates = [self.workspace / pattern]
                    for path in candidates:
                        if not path.is_file() or path.resolve() in seen:
                            continue
                        seen.add(path.resolve())
                        text = _read_text(path)
                        if text:
                            items.append({"kind": kind, "name": path.stem,
                                          "path": str(path), "frontmatter": _frontmatter(text),
                                          "content": text})
        self.items = items
        self.mcp_servers = self._load_json_registry(
            [self.workspace / "mcp-servers.json", self.workspace / "mcp-servers.local.json",
             self.global_root / "mcp-servers.json"])
        self.hooks = self._load_hooks()
        return {"documents": len(self.items), "mcp_servers": len(self.mcp_servers),
                "hooks": sum(len(value) for value in self.hooks.values())}

    def _load_json_registry(self, paths: Iterable[Path]) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for path in paths:
            if not path.is_file():
                continue
            try:
                data = json.loads(_read_text(path))
            except json.JSONDecodeError:
                continue
            entries = data.get("servers", data.get("mcpServers", data)) if isinstance(data, dict) else {}
            if isinstance(entries, dict):
                for name, entry in entries.items():
                    if isinstance(entry, dict) and isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                        safe = {key: entry.get(key) for key in ("command", "args", "env", "enabled") if key in entry}
                        safe["name"] = name
                        safe["source"] = str(path)
                        result[name] = safe
        return result

    def _load_hooks(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for path in (self.workspace / ".glm" / "hooks.json", self.global_root / "hooks.json"):
            if not path.is_file():
                continue
            try:
                data = json.loads(_read_text(path))
            except json.JSONDecodeError:
                continue
            hooks = data.get("hooks", data) if isinstance(data, dict) else {}
            if not isinstance(hooks, dict):
                continue
            for event, commands in hooks.items():
                if isinstance(event, str) and isinstance(commands, list):
                    # Hook commands are exposed for inspection only until an explicit sandbox is selected.
                    result[event] = [str(command)[:500] for command in commands if isinstance(command, str)][:20]
        return result

    def summary(self) -> Dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "documents": [{key: item[key] for key in ("kind", "name", "path", "frontmatter")} for item in self.items],
            "mcp_servers": [{key: value.get(key) for key in ("name", "command", "args", "enabled", "source")} for value in self.mcp_servers.values()],
            "hooks": {event: len(commands) for event, commands in self.hooks.items()},
        }

    def files(self) -> List[Dict[str, Any]]:
        return [{"kind": item["kind"], "name": item["name"], "path": item["path"],
                 "frontmatter": item["frontmatter"], "content": item["content"]} for item in self.items]

    def _safe_path(self, path: Path) -> Path:
        target = path.resolve()
        allowed_roots = (self.workspace.resolve(), self.global_root.resolve())
        if not any(target == root or root in target.parents for root in allowed_roots):
            raise ValueError("customization path is outside an allowed root")
        return target

    def get_file(self, path: str) -> Dict[str, Any]:
        target = self._safe_path(Path(path))
        if not target.is_file():
            raise ValueError("customization file not found")
        text = _read_text(target)
        return {"path": str(target), "content": text, "frontmatter": _frontmatter(text)}

    def save_file(self, path: str, content: str) -> Dict[str, Any]:
        target = self._safe_path(Path(path))
        if target.suffix.lower() != ".md" or len(content) > 500_000:
            raise ValueError("customization files must be Markdown and under 500KB")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        self.reload()
        return self.get_file(str(target))

    def validate(self) -> List[Dict[str, Any]]:
        errors = []
        for item in self.items:
            text = item["content"]
            if text.startswith("---") and not _frontmatter(text):
                errors.append({"path": item["path"], "error": "invalid frontmatter"})
            if len(text) >= 200_000:
                errors.append({"path": item["path"], "error": "content was truncated at 200KB"})
        return errors

    def _selected(self, kind: str) -> List[Dict[str, Any]]:
        selected = []
        for item in self.items:
            if item["kind"] != kind:
                continue
            apply_to = item["frontmatter"].get("applyTo")
            if not apply_to or self._matches_apply_to(str(apply_to)):
                selected.append(item)
        return selected

    def _matches_apply_to(self, pattern: str) -> bool:
        pattern = pattern.strip()
        if pattern in ("*", "**/*"):
            return True
        return any(Path(path).match(pattern) for path in self._workspace_files())

    def _workspace_files(self) -> Iterable[str]:
        try:
            return (str(path.relative_to(self.workspace)) for path in self.workspace.rglob("*") if path.is_file())
        except OSError:
            return ()

    def prepare_messages(self, messages: List[dict]) -> List[dict]:
        blocks = []
        for kind in ("instruction", "skill", "agent", "prompt"):
            for item in self._selected(kind):
                blocks.append("[%s: %s]\n%s" % (kind, item["name"], item["content"]))
        if not blocks:
            return list(messages)
        system = {"role": "system", "content": "\n\n".join(blocks)[:500_000]}
        existing = list(messages)
        if existing and existing[0].get("role") == "system":
            existing[0] = {"role": "system", "content": existing[0].get("content", "") + "\n\n" + system["content"]}
            return existing
        return [system] + existing

    def emit(self, event: str, detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        commands = self.hooks.get(event, [])
        return {"event": event, "registered": len(commands), "executed": False,
                "reason": "hooks are declarative and require sandbox approval", "detail": detail or {},
                "timestamp": time.time()}


__all__ = ["CustomizationRegistry"]
