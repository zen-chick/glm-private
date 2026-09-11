"""Explicit, short-lived stdio MCP client for configured local servers."""

import json
import os
import subprocess
from typing import Any, Dict, Optional


class MCPProcessManager:
    def __init__(self, registry, timeout_seconds: int = 15):
        self.registry = registry
        self.timeout_seconds = max(1, min(int(timeout_seconds), 60))

    def servers(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.registry.mcp_servers)

    def _entry(self, name: str) -> Dict[str, Any]:
        entry = self.registry.mcp_servers.get(name)
        if not entry or entry.get("enabled") is not True:
            raise ValueError("MCP server is not configured and enabled")
        command = entry.get("command")
        args = entry.get("args", [])
        if not isinstance(command, (str, list)) or not isinstance(args, list):
            raise ValueError("MCP command and args are invalid")
        return entry

    def _request(self, name: str, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        entry = self._entry(name)
        command = entry["command"] if isinstance(entry["command"], list) else [entry["command"]]
        command = [str(value) for value in command] + [str(value) for value in entry.get("args", [])]
        environment = os.environ.copy()
        configured_env = entry.get("env", {})
        if isinstance(configured_env, dict):
            for key, value in configured_env.items():
                if isinstance(key, str) and isinstance(value, str):
                    environment[key] = value
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "glm-ide", "version": "1.0"}}}
        calls = [initialize, {"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}}]
        payload = "\n".join(json.dumps(call, ensure_ascii=False) for call in calls) + "\n"
        try:
            completed = subprocess.run(command, input=payload, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=self.timeout_seconds,
                                       env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"MCP server failed: {error}") from error
        responses = []
        for line in completed.stdout.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and "id" in value:
                responses.append(value)
        if not responses:
            detail = completed.stderr.strip()[:500]
            raise RuntimeError(f"MCP server returned no response{': ' + detail if detail else ''}")
        response = responses[-1]
        if "error" in response:
            raise RuntimeError(str(response["error"]))
        return response.get("result", {})

    def list_tools(self, name: str) -> Dict[str, Any]:
        return self._request(name, "tools/list")

    def call_tool(self, name: str, tool: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not isinstance(tool, str) or not tool or len(tool) > 128:
            raise ValueError("invalid MCP tool name")
        return self._request(name, "tools/call", {"name": tool, "arguments": arguments or {}})


__all__ = ["MCPProcessManager"]
