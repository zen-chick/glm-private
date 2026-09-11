#!/usr/bin/env python3
"""co-vibeの承認要求をlocalhost上のVSCodeへ中継する。"""

import json
import secrets
import threading
import time
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from glm_security import AUTH_FILE
from router import classify_risk


class ApprovalBroker:
    def __init__(self, token=None, timeout_seconds=60):
        self.token = token or secrets.token_urlsafe(32)
        self.timeout_seconds = timeout_seconds
        self._requests = {}
        self._lock = threading.Lock()

    def attach(self, request_id, responder):
        with self._lock:
            self._requests[request_id] = {"request": None, "created": time.monotonic(), "decision": None, "responder": responder}

    def publish(self, request):
        request_id = request["id"]
        with self._lock:
            self._expire()
            entry = self._requests.get(request_id, {})
            entry.update({"request": request, "created": time.monotonic(), "decision": None})
            self._requests[request_id] = entry

    def pending(self):
        with self._lock:
            self._expire()
            return [entry["request"] for entry in self._requests.values()
                    if entry["request"] is not None and entry["decision"] is None]

    def respond(self, request_id, decision):
        if decision not in (True, False, "yes_mode", "allow_all", "deny_all"):
            return False
        with self._lock:
            self._expire()
            entry = self._requests.get(request_id)
            if not entry or entry["decision"] is not None:
                return False
            entry["decision"] = decision
            responder = entry.get("responder")
        if responder:
            responder(request_id, decision)
        return True

    def decision(self, request_id):
        with self._lock:
            self._expire()
            entry = self._requests.get(request_id)
            if not entry:
                return None
            return entry["decision"]

    def _expire(self):
        now = time.monotonic()
        expired = [request_id for request_id, entry in self._requests.items()
                   if now - entry["created"] > self.timeout_seconds]
        for request_id in expired:
            del self._requests[request_id]


class BrokerHandler(BaseHTTPRequestHandler):
    broker = None

    def log_message(self, *_):
        pass

    def _authorized(self):
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        return self.broker and secrets.compare_digest(supplied, self.broker.token)

    def _send(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        if self.path == "/pending":
            self._send(200, {"requests": self.broker.pending()})
            return
        if self.path.startswith("/decision/"):
            decision = self.broker.decision(self.path.removeprefix("/decision/"))
            self._send(200, {"ready": decision is not None, "decision": decision})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 4096)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"error": "invalid JSON"})
            return
        if self.path == "/request":
            request_id = body.get("id", "")
            if not request_id or not isinstance(body.get("tool"), str) or not isinstance(body.get("params"), dict):
                self._send(400, {"error": "invalid approval request"})
                return
            # B-3たたき台: 対象/目的/影響範囲/有効期限を承認要求に含める（reasonは常に必須）。
            reason = body.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                self._send(400, {"error": "reason is required for approval requests"})
                return
            action_text = f"{body['tool']} {json.dumps(body['params'], ensure_ascii=False)}"
            risk_category = classify_risk(action_text)
            if risk_category is not None:
                # 高リスク操作はtarget/scope/expires_in_minutes/requested_byも必須化する（B-3：高リスク操作のみ必須化）。
                missing = [field for field in ("target", "scope", "expires_in_minutes", "requested_by") if not body.get(field)]
                if missing:
                    self._send(400, {"error": f"high-risk approval ({risk_category}) requires: {', '.join(missing)}"})
                    return
            request = {
                "type": "approval_request", "id": request_id, "tool": body["tool"], "params": body["params"],
                "risk_category": risk_category,
                "target": body.get("target", body["tool"]),
                "reason": reason,
                "scope": body.get("scope", "unspecified"),
                "expires_in_minutes": body.get("expires_in_minutes", self.broker.timeout_seconds // 60 or 1),
                "requested_by": body.get("requested_by", "unknown"),
            }
            self.broker.publish(request)
            self._send(202, {"accepted": True})
            return
        if self.path == "/respond":
            accepted = self.broker.respond(body.get("id", ""), body.get("decision"))
            self._send(200 if accepted else 404, {"accepted": accepted})
            return
        self._send(404, {"error": "not found"})


def create_server(broker, port=8767):
    BrokerHandler.broker = broker
    return ThreadingHTTPServer(("127.0.0.1", port), BrokerHandler)


def load_token(token_file=AUTH_FILE):
    token_file = Path(token_file)
    if not token_file.exists():
        raise RuntimeError(f"Authentication token is missing: {token_file}")
    token = token_file.read_text(encoding="utf-8-sig").strip()
    if not token:
        raise RuntimeError(f"Authentication token is empty: {token_file}")
    return token


def main():
    parser = argparse.ArgumentParser(description="GLM localhost approval broker")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    server = create_server(ApprovalBroker(load_token(), args.timeout), args.port)
    print(f"GLM approval broker: http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()