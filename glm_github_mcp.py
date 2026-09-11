"""GitHub MCP Server を GLM から呼び出す stdio クライアント。"""

import json
import os
import queue
import subprocess
import threading
from typing import Any, Dict, Optional


DEFAULT_IMAGE = "ghcr.io/github/github-mcp-server:latest"


class GitHubMCPClient:
    """Docker 経由の GitHub MCP Server に1リクエスト単位で接続する。"""

    def __init__(self, image: Optional[str] = None, runner=None, timeout: int = 30, token_getter=None):
        self.image = image or os.environ.get("GLM_GITHUB_MCP_IMAGE", DEFAULT_IMAGE)
        self.runner = runner or subprocess.Popen
        self.timeout = timeout
        self.token_getter = token_getter

    def _environment(self):
        token = (self.token_getter() if self.token_getter else "") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
        if not token:
            raise RuntimeError("GITHUB_TOKEN or GITHUB_PERSONAL_ACCESS_TOKEN is not configured")
        environment = os.environ.copy()
        environment["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
        return environment

    def _exchange(self, requests):
        process = self.runner(
            ["docker", "run", "--rm", "-i", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", self.image],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            env=self._environment(),
        )
        payload = "".join(json.dumps(request, ensure_ascii=False) + "\n" for request in requests)
        responses = []
        messages = queue.Queue()

        def read_messages():
            for line in iter(process.stdout.readline, ""):
                try:
                    messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue

        reader = threading.Thread(target=read_messages, daemon=True)
        reader.start()
        try:
            process.stdin.write(payload)
            process.stdin.flush()
            expected_ids = {request["id"] for request in requests if "id" in request}
            while expected_ids:
                try:
                    message = messages.get(timeout=self.timeout)
                except queue.Empty:
                    raise RuntimeError("GitHub MCP Server timed out")
                if "id" in message and ("result" in message or "error" in message):
                    responses.append(message)
                    expected_ids.discard(message["id"])
        finally:
            try:
                process.stdin.close()
            except (AttributeError, OSError):
                pass
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        if not responses:
            raise RuntimeError("GitHub MCP Server returned no JSON-RPC response")
        return responses

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None):
        responses = self._exchange([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "glm", "version": "0.1.0"},
            }},
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}},
        ])
        response = next((item for item in responses if item.get("id") == 2), responses[-1])
        if "error" in response:
            raise RuntimeError(response["error"].get("message", "GitHub MCP request failed"))
        return response.get("result", {})

    def list_tools(self):
        return self._request("tools/list")

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tool name is required")
        return self._request("tools/call", {"name": name, "arguments": arguments or {}})
