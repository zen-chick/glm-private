#!/usr/bin/env python3
"""本格LSPクライアント: pyright-langserverをstdio JSON-RPCで駆動する。

VS CodeのPylance相当の型推論・補完・定義ジャンプ・参照検索・リネームを
GLM Coreから利用するための層。サーバーが利用できない場合は呼び出し側が
ASTベースのフォールバックへ退避できるよう、全APIが失敗を例外ではなく
戻り値で報告する。
"""

import json
import os
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

_SERVER_CMD_NAME = "pyright-langserver.cmd" if os.name == "nt" else "pyright-langserver"


def default_server_command():
    base = Path(__file__).resolve().parent / "ide-web" / "node_modules" / ".bin" / _SERVER_CMD_NAME
    if base.exists():
        return [str(base), "--stdio"]
    return None


class LspClient:
    """Minimal but real LSP client (Content-Length framed JSON-RPC over stdio)."""

    def __init__(self, workspace, command=None):
        self.workspace = Path(workspace).resolve()
        self.command = command if command is not None else default_server_command()
        self.process = None
        self._reader = None
        self._write_lock = threading.Lock()
        self._pending = {}       # id -> {"event": Event, "response": dict|None}
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._diagnostics = {}   # uri -> list[dict]
        self._diag_lock = threading.Lock()
        self._open_docs = {}     # uri -> version
        self._initialized = False
        self._dead = threading.Event()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def available(self):
        return bool(self.command)

    def start(self, timeout=30):
        if self._initialized and self.process and self.process.poll() is None:
            return True
        if not self.command:
            return False
        try:
            self.process = subprocess.Popen(
                self.command + (["--"] if False else []),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, cwd=str(self.workspace),
            )
        except OSError:
            self.process = None
            return False
        self._dead.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        try:
            root_uri = self.workspace.as_uri()
            self._request("initialize", {
                "processId": os.getpid(),
                "rootUri": root_uri,
                "capabilities": {
                    "textDocument": {
                        "completion": {"completionItem": {"snippetSupport": False}},
                        "hover": {}, "definition": {}, "references": {},
                        "rename": {}, "documentSymbol": {},
                        "publishDiagnostics": {},
                    }
                },
                "workspaceFolders": [{"uri": root_uri, "name": self.workspace.name}],
            }, timeout=timeout)
            self._notify("initialized", {})
            self._initialized = True
            return True
        except (TimeoutError, RuntimeError, OSError):
            self.shutdown()
            return False

    def shutdown(self):
        self._dead.set()
        try:
            if self.process and self.process.poll() is None:
                try:
                    self._request("shutdown", {}, timeout=3)
                    self._notify("exit", {})
                except Exception:
                    pass
                self.process.terminate()
        except Exception:
            pass
        self.process = None
        self._initialized = False
        self._open_docs.clear()

    def status(self):
        running = bool(self.process and self.process.poll() is None and self._initialized)
        return {"available": self.available(), "running": running,
                "open_documents": len(self._open_docs),
                "files_with_diagnostics": len(self._diagnostics),
                "engine": "pyright-langserver" if self.command else None}

    # ── JSON-RPC framing ─────────────────────────────────────────────────────
    def _read_loop(self):
        stream = self.process.stdout
        while not self._dead.is_set():
            try:
                headers = {}
                while True:
                    line = stream.readline()
                    if not line:
                        self._dead.set()
                        return
                    line = line.strip()
                    if not line:
                        break
                    key, _, value = line.partition(b":")
                    headers[key.strip().lower()] = value.strip()
                length = int(headers.get(b"content-length", b"0"))
                if length <= 0:
                    continue
                body = stream.read(length)
                if not body:
                    self._dead.set()
                    return
                message = json.loads(body.decode("utf-8", errors="replace"))
            except (OSError, ValueError, json.JSONDecodeError):
                if self._dead.is_set():
                    return
                continue
            self._dispatch(message)
        # mark dead on exit
        self._dead.set()

    def _dispatch(self, message):
        if "id" in message and ("result" in message or "error" in message):
            with self._id_lock:
                pending = self._pending.pop(message["id"], None)
            if pending:
                pending["response"] = message
                pending["event"].set()
            return
        method = message.get("method")
        if method == "textDocument/publishDiagnostics":
            params = message.get("params", {})
            uri = params.get("uri", "")
            with self._diag_lock:
                diagnostics = params.get("diagnostics", [])
                if diagnostics:
                    self._diagnostics[uri] = diagnostics
                else:
                    self._diagnostics.pop(uri, None)

    def _send(self, payload):
        body = json.dumps(payload).encode("utf-8")
        frame = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        with self._write_lock:
            self.process.stdin.write(frame)
            self.process.stdin.flush()

    def _request(self, method, params, timeout=15):
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("LSP server is not running")
        with self._id_lock:
            self._next_id += 1
            request_id = self._next_id
            pending = {"event": threading.Event(), "response": None}
            self._pending[request_id] = pending
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        if not pending["event"].wait(timeout):
            with self._id_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"LSP request timed out: {method}")
        response = pending["response"] or {}
        if "error" in response:
            raise RuntimeError(f"LSP error in {method}: {response['error']}")
        return response.get("result")

    def _notify(self, method, params):
        if not self.process or self.process.poll() is not None:
            return
        try:
            self._send({"jsonrpc": "2.0", "method": method, "params": params})
        except (OSError, ValueError):
            pass

    # ── document sync ────────────────────────────────────────────────────────
    def _uri(self, rel_path):
        return (self.workspace / rel_path).resolve().as_uri()

    def sync_document(self, rel_path, content):
        """didOpen/didChange でサーバーへ最新内容を同期する。"""
        uri = self._uri(rel_path)
        if uri in self._open_docs:
            self._open_docs[uri] += 1
            self._notify("textDocument/didChange", {
                "textDocument": {"uri": uri, "version": self._open_docs[uri]},
                "contentChanges": [{"text": content}],
            })
        else:
            self._open_docs[uri] = 1
            self._notify("textDocument/didOpen", {
                "textDocument": {"uri": uri, "languageId": "python",
                                 "version": 1, "text": content},
            })
        return uri

    def close_document(self, rel_path):
        uri = self._uri(rel_path)
        if uri in self._open_docs:
            self._open_docs.pop(uri, None)
            self._notify("textDocument/didClose", {"textDocument": {"uri": uri}})

    # ── language features ────────────────────────────────────────────────────
    def _position_params(self, uri, line, character):
        return {"textDocument": {"uri": uri},
                "position": {"line": max(0, int(line) - 1), "character": max(0, int(character) - 1)}}

    def completion(self, rel_path, line, character, content):
        uri = self.sync_document(rel_path, content)
        result = self._request("textDocument/completion",
                               self._position_params(uri, line, character), timeout=10)
        items = result.get("items", []) if isinstance(result, dict) else (result or [])
        return [{"label": item.get("label", ""), "kind": item.get("kind"),
                 "detail": item.get("detail", ""), "documentation": _doc_text(item.get("documentation"))}
                for item in items[:200]]

    def hover(self, rel_path, line, character, content):
        uri = self.sync_document(rel_path, content)
        result = self._request("textDocument/hover",
                               self._position_params(uri, line, character), timeout=10)
        if not result:
            return None
        contents = result.get("contents", {})
        if isinstance(contents, dict):
            return contents.get("value") or contents.get("contents") or ""
        if isinstance(contents, list):
            return "\n".join(c.get("value", "") if isinstance(c, dict) else str(c) for c in contents)
        return str(contents)

    def definition(self, rel_path, line, character, content):
        uri = self.sync_document(rel_path, content)
        result = self._request("textDocument/definition",
                               self._position_params(uri, line, character), timeout=10)
        return _locations(result, self.workspace)

    def references(self, rel_path, line, character, content):
        uri = self.sync_document(rel_path, content)
        params = self._position_params(uri, line, character)
        params["context"] = {"includeDeclaration": True}
        result = self._request("textDocument/references", params, timeout=15)
        return _locations(result, self.workspace)

    def rename(self, rel_path, line, character, new_name, content):
        uri = self.sync_document(rel_path, content)
        params = self._position_params(uri, line, character)
        params["newName"] = new_name
        result = self._request("textDocument/rename", params, timeout=15)
        changes = (result or {}).get("changes", {})
        edits = []
        for change_uri, text_edits in changes.items():
            path = _uri_to_rel(change_uri, self.workspace)
            for edit in text_edits:
                rng = edit.get("range", {})
                edits.append({"path": path,
                              "line": rng.get("start", {}).get("line", 0) + 1,
                              "column": rng.get("start", {}).get("character", 0) + 1,
                              "end_line": rng.get("end", {}).get("line", 0) + 1,
                              "end_column": rng.get("end", {}).get("character", 0) + 1,
                              "new_text": edit.get("newText", "")})
        return edits

    def document_symbols(self, rel_path, content):
        uri = self.sync_document(rel_path, content)
        result = self._request("textDocument/documentSymbol",
                               {"textDocument": {"uri": uri}}, timeout=10)
        symbols = []

        def _walk(items, container=None):
            for item in items or []:
                if "selectionRange" in item:  # DocumentSymbol
                    rng = item.get("selectionRange", {}).get("start", {})
                    symbols.append({"name": item.get("name", ""), "kind": item.get("kind"),
                                    "line": rng.get("line", 0) + 1,
                                    "column": rng.get("character", 0) + 1,
                                    "container": item.get("containerName") or container})
                    _walk(item.get("children"), item.get("name"))
                elif "location" in item:  # SymbolInformation
                    rng = item.get("location", {}).get("range", {}).get("start", {})
                    symbols.append({"name": item.get("name", ""), "kind": item.get("kind"),
                                    "line": rng.get("line", 0) + 1,
                                    "column": rng.get("character", 0) + 1,
                                    "container": item.get("containerName")})
        _walk(result if isinstance(result, list) else [])
        return symbols

    def diagnostics(self, rel_path=None):
        """publishDiagnostics で受信済みの診断を返す（プル型）。"""
        with self._diag_lock:
            snapshot = dict(self._diagnostics)
        result = {}
        for uri, diagnostics in snapshot.items():
            path = _uri_to_rel(uri, self.workspace)
            if rel_path and path != rel_path:
                continue
            result[path] = [{
                "line": d.get("range", {}).get("start", {}).get("line", 0) + 1,
                "column": d.get("range", {}).get("start", {}).get("character", 0) + 1,
                "end_line": d.get("range", {}).get("end", {}).get("line", 0) + 1,
                "end_column": d.get("range", {}).get("end", {}).get("character", 0) + 1,
                "message": d.get("message", ""),
                "severity": {1: "error", 2: "warning", 3: "information", 4: "hint"}.get(d.get("severity"), "information"),
                "rule": d.get("code") if isinstance(d.get("code"), str) else "",
                "source": d.get("source", "pyright"),
            } for d in diagnostics]
        return result


def _doc_text(documentation):
    if isinstance(documentation, dict):
        return documentation.get("value", "")
    return documentation or ""


def _uri_to_rel(uri, workspace):
    try:
        raw = uri
        if raw.lower().startswith("file://"):
            raw = raw[7:]  # keep authority-less path; localhost authority is dropped below
            if raw.startswith("localhost/"):
                raw = raw[len("localhost"):]
        decoded = urllib.parse.unquote(raw)
        # Windows形式 "/d%3A/..." → "D:/..." へ
        if len(decoded) >= 3 and decoded[0] == "/" and decoded[2] == ":":
            decoded = decoded[1:]
        path = Path(decoded).resolve()
        return path.relative_to(workspace).as_posix()
    except (ValueError, OSError):
        return urllib.parse.unquote(uri)


def _locations(result, workspace):
    if not result:
        return []
    if isinstance(result, dict):
        result = [result]
    locations = []
    for item in result:
        uri = item.get("uri") or item.get("targetUri", "")
        rng = item.get("range") or item.get("targetRange", {})
        start = rng.get("start", {})
        locations.append({"path": _uri_to_rel(uri, workspace),
                          "line": start.get("line", 0) + 1,
                          "column": start.get("character", 0) + 1})
    return locations
