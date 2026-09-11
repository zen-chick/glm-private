"""Offline-first extension catalog and workspace installation state."""

import json
from pathlib import Path
from typing import Any, Dict, List


CATALOG = [
    {"id": "glm.core", "name": "GLM Core", "publisher": "pcgam", "version": "1.0.0", "category": "AI", "builtin": True, "description": "GLM routing, agent, approval, and audit services."},
    {"id": "glm.pylance-mcp", "name": "Pylance MCP Bridge", "publisher": "pcgam", "version": "1.0.0", "category": "Languages", "builtin": True, "description": "Expose Pyright/Pylance-compatible language tools through GLM."},
    {"id": "glm.agent-customization", "name": "Agent Customization", "publisher": "pcgam", "version": "1.0.0", "category": "AI", "builtin": True, "description": "Manage skills, instructions, prompts, agents, and hooks."},
    {"id": "glm.github-mcp", "name": "GitHub MCP", "publisher": "pcgam", "version": "1.0.0", "category": "SCM", "builtin": True, "description": "Audited GitHub MCP integration."},
]


class Marketplace:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        self.state_path = self.workspace / ".glm" / "extensions.json"

    def _state(self) -> Dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {"installed": {}}
        except (OSError, json.JSONDecodeError):
            return {"installed": {}}

    def list(self, query: str = "") -> List[Dict[str, Any]]:
        query = str(query or "").strip().lower()
        installed = self._state().get("installed", {})
        result = []
        for item in CATALOG:
            haystack = " ".join(str(item.get(key, "")) for key in ("id", "name", "publisher", "category", "description")).lower()
            if query and query not in haystack:
                continue
            result.append({**item, "installed": bool(installed.get(item["id"], {}).get("installed", False)),
                           "enabled": bool(installed.get(item["id"], {}).get("enabled", False))})
        return result

    def install(self, extension_id: str) -> Dict[str, Any]:
        item = next((item for item in CATALOG if item["id"] == extension_id), None)
        if not item:
            raise ValueError("extension is not in the trusted catalog")
        state = self._state()
        state.setdefault("installed", {})[extension_id] = {"installed": True, "enabled": True, "version": item["version"]}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.state_path)
        return {**item, "installed": True, "enabled": True}

    def uninstall(self, extension_id: str) -> Dict[str, Any]:
        item = next((item for item in CATALOG if item["id"] == extension_id), None)
        if not item:
            raise ValueError("unknown extension")
        if item.get("builtin"):
            raise ValueError("builtin extensions cannot be uninstalled")
        state = self._state()
        state.setdefault("installed", {}).pop(extension_id, None)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"id": extension_id, "installed": False}

    def toggle(self, extension_id: str, enabled: bool) -> Dict[str, Any]:
        if not any(item["id"] == extension_id for item in CATALOG):
            raise ValueError("unknown extension")
        state = self._state()
        current = state.setdefault("installed", {}).setdefault(extension_id, {"installed": True})
        current["installed"] = True
        current["enabled"] = bool(enabled)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"id": extension_id, "installed": True, "enabled": bool(enabled)}


__all__ = ["Marketplace"]
