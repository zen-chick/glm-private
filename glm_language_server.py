#!/usr/bin/env python3
"""Minimal stdio LSP server backed by GLM's workspace language service."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from glm_dev_services import LanguageService


class GLMLanguageServer:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.language = LanguageService(self.workspace)
        self.documents = {}

    def _path(self, uri):
        parsed = urlparse(uri)
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path))
            if sys.platform == "win32" and path.as_posix().startswith("/"):
                path = Path(path.as_posix()[1:])
            return path
        return self.workspace / str(uri)

    def _uri(self, path):
        return path.resolve().as_uri()

    def _text(self, uri):
        if uri in self.documents:
            return self.documents[uri]
        path = self._path(uri)
        return path.read_text(encoding="utf-8-sig", errors="replace") if path.exists() else ""

    @staticmethod
    def _word_at(text, position):
        lines = text.splitlines()
        line = lines[position.get("line", 0)] if position.get("line", 0) < len(lines) else ""
        column = min(position.get("character", 0), len(line))
        match = re.search(r"[A-Za-z_]\w*", line[max(0, column - 80):column + 80])
        return match.group(0) if match else ""

    @staticmethod
    def _range(line, column, length=1):
        return {"start": {"line": max(line - 1, 0), "character": max(column - 1, 0)},
                "end": {"line": max(line - 1, 0), "character": max(column - 1, 0) + length}}

    def _diagnostics(self, uri):
        path = self._path(uri)
        rel = path.relative_to(self.workspace).as_posix()
        result = self.language.type_diagnostics(rel) if path.suffix.lower() == ".py" else self.language.diagnostics(rel, self._text(uri))
        severity = {"error": 1, "warning": 2, "information": 3, "hint": 4}
        return [{"range": self._range(item.get("line", 1), item.get("column", 1)),
                 "severity": severity.get(str(item.get("severity", "error")).lower(), 1),
                 "message": item.get("message", ""), "source": item.get("rule", "GLM")}
                for item in result.get("diagnostics", result.get("errors", []))]

    def _definitions(self, uri, name):
        path = self._path(uri)
        text = self._text(uri)
        result = []
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            return result
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                target = path
                result.append({"uri": self._uri(target), "range": self._range(node.lineno, node.col_offset + 1, len(name))})
        return result

    def handle(self, request):
        method = request.get("method", "")
        request_id = request.get("id")
        params = request.get("params", {})
        if method == "initialize":
            return self._response(request_id, {"capabilities": {
                "textDocumentSync": 1, "completionProvider": {"triggerCharacters": ["."]},
                "definitionProvider": True, "referencesProvider": True,
                "renameProvider": True, "documentSymbolProvider": True,
                "diagnosticProvider": {"interFileDependencies": False, "workspaceDiagnostics": False},
            }, "serverInfo": {"name": "GLM Language Server", "version": "0.1.0"}})
        if method in {"shutdown", "exit"}:
            return self._response(request_id, None) if method == "shutdown" else None
        if method == "initialized" or method.startswith("$/"):
            return None
        if method == "textDocument/didOpen":
            document = params.get("textDocument", {})
            self.documents[document.get("uri", "")] = document.get("text", "")
            return None
        if method == "textDocument/didChange":
            document = params.get("textDocument", {})
            changes = params.get("contentChanges", [])
            if changes and "text" in changes[-1]:
                self.documents[document.get("uri", "")] = changes[-1]["text"]
            return None
        if method == "textDocument/didClose":
            self.documents.pop(params.get("textDocument", {}).get("uri", ""), None)
            return None
        if method in {"textDocument/diagnostic", "textDocument/publishDiagnostics"}:
            uri = params.get("textDocument", {}).get("uri", "")
            if method == "textDocument/diagnostic":
                return self._response(request_id, {"kind": "full", "items": self._diagnostics(uri)})
            return {"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": uri, "diagnostics": self._diagnostics(uri)}}
        if method == "textDocument/completion":
            document = params.get("textDocument", {})
            word = self._word_at(self._text(document.get("uri", "")), params.get("position", {}))
            items = self.language.completions(self._path(document.get("uri", "")).relative_to(self.workspace).as_posix(), word, self._text(document.get("uri", ""))).get("items", [])
            return self._response(request_id, {"isIncomplete": False, "items": [{"label": item["label"], "kind": 6} for item in items]})
        if method == "textDocument/definition":
            uri = params.get("textDocument", {}).get("uri", "")
            return self._response(request_id, self._definitions(uri, self._word_at(self._text(uri), params.get("position", {}))))
        if method == "textDocument/documentSymbol":
            uri = params.get("textDocument", {}).get("uri", "")
            rel = self._path(uri).relative_to(self.workspace).as_posix()
            symbols = self.language.symbols(rel, self._text(uri)).get("symbols", [])
            return self._response(request_id, [{"name": item["name"], "kind": 12 if "Class" in item["kind"] else 12, "range": self._range(item["line"], item["column"]), "selectionRange": self._range(item["line"], item["column"], len(item["name"]))} for item in symbols])
        if method == "textDocument/references":
            uri = params.get("textDocument", {}).get("uri", "")
            path = self._path(uri)
            rel = path.relative_to(self.workspace).as_posix()
            name = self._word_at(self._text(uri), params.get("position", {}))
            references = self.language.references(rel, name).get("references", [])
            return self._response(request_id, [{"uri": self._uri(self.workspace / item["path"]), "range": self._range(item["line"], item["column"], len(name))} for item in references])
        if method == "textDocument/rename":
            uri = params.get("textDocument", {}).get("uri", "")
            path = self._path(uri)
            rel = path.relative_to(self.workspace).as_posix()
            old = self._word_at(self._text(uri), params.get("position", {}))
            edits = self.language.rename(rel, old, params.get("newName", "")).get("edits", [])
            changes = {}
            for item in edits:
                edit_uri = self._uri(self.workspace / item["path"])
                changes.setdefault(edit_uri, []).append({"range": self._range(item["line"], item["column"], len(old)), "newText": item["new_text"]})
            return self._response(request_id, {"changes": changes})
        return self._error(request_id, -32601, "Method not found")

    @staticmethod
    def _response(request_id, result):
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id, code, message):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def serve(self):
        for line in sys.stdin:
            try:
                response = self.handle(json.loads(line))
                if response is not None:
                    print(json.dumps(response, ensure_ascii=False), flush=True)
            except (ValueError, OSError, json.JSONDecodeError) as error:
                print(json.dumps(self._error(None, -32603, str(error))), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".")
    args = parser.parse_args()
    GLMLanguageServer(args.workspace).serve()


if __name__ == "__main__":
    main()
