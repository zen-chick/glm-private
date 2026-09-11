#!/usr/bin/env python3
"""認証必須・読み取り専用のGLMリモートJSON-RPCゲート。"""

import argparse
import hmac
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).parent))
from glm_security import AuditLogger, AUTH_FILE


DEFAULT_PORT = 8766
ROUTER_URL = "http://127.0.0.1:8765"
READ_ONLY_TOOLS = {
    "glm.status": "GLM RouterのGPU・予算・稼働状態を返す。",
    "glm.sessions": "GLMセッションのメタデータ一覧を返す。",
}


def is_private_client(address):
    candidate = ip_address(address)
    return candidate.is_loopback or candidate.is_private


def ensure_auth_token(token_file=AUTH_FILE):
    token_file = Path(token_file)
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    token_file.write_text(token + "\n", encoding="utf-8")
    return token


def router_get(path):
    with urlopen(ROUTER_URL + path, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class MCPGateHandler(BaseHTTPRequestHandler):
    audit = AuditLogger()

    def log_message(self, *_):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        expected = ensure_auth_token()
        return hmac.compare_digest(supplied, expected)

    def do_GET(self):
        if self.path != "/health":
            self._send(404, {"error": "not found"})
            return
        self._send(200, {"status": "ok", "mode": "read-only"})

    def do_POST(self):
        client_ip = self.client_address[0]
        if not is_private_client(client_ip):
            self.audit.record("remote_request", "deny", detail={"reason": "public_ip"})
            self._send(403, {"error": "private network only"})
            return
        if not self._authorized():
            self.audit.record("remote_request", "deny", detail={"reason": "unauthorized"})
            self._send(401, {"error": "unauthorized"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(min(size, 65536)).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self.audit.record("remote_request", "deny", detail={"reason": "invalid_json"})
            self._send(400, {"error": "invalid JSON"})
            return

        method = request.get("method")
        request_id = request.get("id")
        if method == "tools/list":
            result = {"tools": [{"name": name, "description": description} for name, description in READ_ONLY_TOOLS.items()]}
        elif method == "tools/call":
            tool_name = request.get("params", {}).get("name")
            if tool_name == "glm.status":
                result = router_get("/status")
            elif tool_name == "glm.sessions":
                result = router_get("/sessions")
            else:
                self.audit.record("remote_request", "deny", detail={"reason": "tool_not_allowed", "tool": tool_name})
                self._send(403, {"id": request_id, "error": "tool is not available remotely"})
                return
        else:
            self._send(404, {"id": request_id, "error": "method not found"})
            return

        self.audit.record("remote_request", "allow", detail={"method": method})
        self._send(200, {"id": request_id, "result": result})


def main():
    parser = argparse.ArgumentParser(description="GLM read-only remote MCP gate")
    parser.add_argument("--host", default="127.0.0.1", help="LAN公開時のみ0.0.0.0を指定")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--init-token", action="store_true")
    args = parser.parse_args()
    if args.init_token:
        ensure_auth_token()
        print(f"Token created: {AUTH_FILE}")
        return
    if args.host == "0.0.0.0":
        print("Warning: LAN exposure enabled. HTTPS/VPN is required outside a trusted LAN.", file=sys.stderr)
    server = ThreadingHTTPServer((args.host, args.port), MCPGateHandler)
    print(f"GLM read-only gate: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()