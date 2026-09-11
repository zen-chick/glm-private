#!/usr/bin/env python3
"""GLM Routerの状態を公開する読み取り専用MCP stdioサーバー。"""

import json
import sys
from pathlib import Path
from urllib.request import urlopen

from glm_notion import NotionReadClient
from glm_security import AuditLogger


ROUTER_URL = "http://127.0.0.1:8765"
SERVER_INFO = {"name": "glm-router", "version": "0.1.0"}
TOOLS = {
    "glm_status": "Return GLM Router hardware and cloud budget status.",
    "glm_sessions": "Return GLM Router session metadata.",
    "notion_search": "Search Notion pages accessible to the configured integration.",
    "notion_page": "Retrieve metadata for one Notion page accessible to the integration.",
}


def router_get(endpoint):
    with urlopen(ROUTER_URL + endpoint, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def tool_result(value):
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}


class MCPServer:
    def __init__(self, audit=None, fetch=None, notion=None):
        self.audit = audit or AuditLogger()
        self.fetch = fetch or router_get
        self.notion = notion or NotionReadClient()

    def handle(self, request):
        method = request.get("method", "")
        request_id = request.get("id")
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return self._response(request_id, {
                "protocolVersion": request.get("params", {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            })
        if method == "tools/list":
            return self._response(request_id, {
                "tools": [
                    {"name": name, "description": description, "inputSchema": self._schema(name)}
                    for name, description in TOOLS.items()
                ]
            })
        if method == "tools/call":
            return self._call_tool(request_id, request.get("params", {}))
        return self._error(request_id, -32601, "Method not found")

    def _call_tool(self, request_id, params):
        name = params.get("name")
        endpoints = {"glm_status": "/status", "glm_sessions": "/sessions"}
        endpoint = endpoints.get(name)
        if name == "notion_search":
            result = self.notion.search(params.get("arguments", {}).get("query", ""), params.get("arguments", {}).get("page_size", 10))
        elif name == "notion_page":
            result = self.notion.page(params.get("arguments", {}).get("page_id", ""))
        elif not endpoint:
            self.audit.record("mcp_request", "deny", detail={"reason": "tool_not_allowed", "tool": name})
            return self._error(request_id, -32602, "Tool is not available")
        else:
            try:
                result = self.fetch(endpoint)
            except Exception as error:
                self.audit.record("mcp_request", "error", detail={"tool": name, "error": str(error)[:200]})
                return self._response(request_id, {"content": [{"type": "text", "text": f"Router unavailable: {error}"}], "isError": True})
        self.audit.record("mcp_request", "allow", detail={"tool": name})
        return self._response(request_id, tool_result(result))

    @staticmethod
    def _schema(name):
        if name == "notion_search":
            return {"type": "object", "properties": {"query": {"type": "string"}, "page_size": {"type": "integer"}}}
        if name == "notion_page":
            return {"type": "object", "properties": {"page_id": {"type": "string"}}, "required": ["page_id"]}
        return {"type": "object", "properties": {}}

    @staticmethod
    def _response(request_id, result):
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id, code, message):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main():
    server = MCPServer()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = server.handle(request)
        except json.JSONDecodeError:
            response = MCPServer._error(None, -32700, "Parse error")
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()