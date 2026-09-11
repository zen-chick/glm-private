"""GLMの安全制約付きエージェントループ。"""

import json
import subprocess
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from glm_security import AuditLogger, MAX_RESPONSE_CHARS


DEFAULT_MAX_STEPS = 8
DEFAULT_MAX_SECONDS = 180
MAX_TOOL_OUTPUT_CHARS = 20_000


class AgentTool:
    def __init__(self, name: str, description: str, parameters: dict,
                 handler: Callable[[dict], dict], risk: str = "low"):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.risk = risk

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.parameters,
        }}


class AgentRunner:
    """LLMのtool_callsを上限付きで処理する。"""

    def __init__(self, llm: Callable[[List[dict], List[dict]], dict], tools: List[AgentTool],
                 audit: Optional[AuditLogger] = None, max_steps: int = DEFAULT_MAX_STEPS,
                 max_seconds: int = DEFAULT_MAX_SECONDS):
        self.llm = llm
        self.tools = {tool.name: tool for tool in tools}
        self.audit = audit or AuditLogger()
        self.max_steps = max(1, min(max_steps, 32))
        self.max_seconds = max(1, min(max_seconds, 600))

    def run(self, messages: List[dict], requested_by: str = "agent") -> dict:
        conversation = list(messages)
        started = time.monotonic()
        trace = []
        for step in range(self.max_steps):
            if time.monotonic() - started > self.max_seconds:
                return self._stopped(conversation, trace, "agent_time_limit_exceeded")
            response = self.llm(conversation, [tool.schema() for tool in self.tools.values()])
            message = response.get("choices", [{}])[0].get("message", {})
            conversation.append(message)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return {"ok": True, "message": message, "trace": trace,
                        "steps": step + 1, "elapsed_seconds": round(time.monotonic() - started, 3)}
            for call in tool_calls:
                result = self._run_tool(call, requested_by, step)
                trace.append({"step": step + 1, "tool": call.get("function", {}).get("name"),
                              "result": result})
                conversation.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                     "content": json.dumps(result, ensure_ascii=False)[:MAX_TOOL_OUTPUT_CHARS]})
        return self._stopped(conversation, trace, "agent_step_limit_exceeded")

    def _run_tool(self, call: dict, requested_by: str, step: int) -> dict:
        function = call.get("function", {})
        name = function.get("name", "")
        tool = self.tools.get(name)
        if not tool:
            self.audit.record("agent_tool", "deny", detail={"tool": name, "reason": "not_allowed"})
            return {"ok": False, "error": "tool is not allowed"}
        try:
            arguments = json.loads(function.get("arguments", "{}"))
        except (TypeError, json.JSONDecodeError):
            return {"ok": False, "error": "tool arguments must be valid JSON"}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "tool arguments must be an object"}
        self.audit.record("agent_tool", "allow", requested_by,
                          {"tool": name, "risk": tool.risk, "step": step + 1})
        try:
            result = tool.handler(arguments)
            return result if isinstance(result, dict) else {"ok": True, "value": str(result)}
        except Exception as error:
            self.audit.record("agent_tool", "error", requested_by,
                              {"tool": name, "error": str(error)[:300]})
            return {"ok": False, "error": str(error)[:500]}

    @staticmethod
    def _stopped(conversation, trace, reason):
        return {"ok": False, "stopped": True, "reason": reason,
                "message": conversation[-1] if conversation else {}, "trace": trace}


def read_disk_usage(_: dict) -> dict:
    """Windowsのドライブ容量を読み取り専用で取得する。"""
    command = ["powershell", "-NoProfile", "-Command",
               "Get-PSDrive -PSProvider FileSystem | Select-Object Name,Used,Free | ConvertTo-Json -Compress"]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=10)
    if completed.returncode != 0:
        return {"ok": False, "error": completed.stderr[:500]}
    try:
        data = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return {"ok": False, "error": "disk output was not valid JSON"}
    drives = data if isinstance(data, list) else [data]
    return {"ok": True, "drives": [{"name": item.get("Name"), "used": item.get("Used"),
                                     "free": item.get("Free")} for item in drives]}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def fetch_webpage(arguments: dict) -> dict:
    url = str(arguments.get("url", "")).strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"ok": False, "error": "url must use http or https"}
    request = urllib.request.Request(url, headers={"User-Agent": "GLM-IDE/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            content_type = response.headers.get_content_type()
            raw = response.read(200_001)
    except Exception as error:
        return {"ok": False, "error": str(error)[:500]}
    if len(raw) > 200_000:
        return {"ok": False, "error": "response exceeds 200000 bytes"}
    text = raw.decode("utf-8", errors="replace")
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _TextExtractor()
        parser.feed(text)
        text = "\n".join(parser.parts)
    return {"ok": True, "url": url, "content_type": content_type, "text": text[:100_000]}


def _todo_path(workspace: Path) -> Path:
    return Path(workspace).resolve() / ".glm" / "todos.json"


def todo_tool(workspace: Path, arguments: dict) -> dict:
    path = _todo_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"items": []}
    except (OSError, json.JSONDecodeError):
        data = {"items": []}
    items = data.get("items", []) if isinstance(data, dict) else []
    action = str(arguments.get("action", "list"))
    if action == "add":
        title = str(arguments.get("title", "")).strip()[:500]
        if not title:
            return {"ok": False, "error": "title is required"}
        items.append({"id": int(time.time() * 1000), "title": title, "completed": False})
    elif action == "complete":
        item_id = str(arguments.get("id", ""))
        for item in items:
            if str(item.get("id")) == item_id:
                item["completed"] = True
                break
        else:
            return {"ok": False, "error": "todo not found"}
    elif action != "list":
        return {"ok": False, "error": "action must be list, add, or complete"}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return {"ok": True, "items": items}


def default_diagnostic_tools(workspace: Optional[Path] = None) -> List[AgentTool]:
    tools = [AgentTool(
        "inspect_disk_usage", "Read-only disk usage inspection for local Windows drives.",
        {"type": "object", "properties": {}}, read_disk_usage,
    ), AgentTool(
        "fetch_webpage", "Fetch a public HTTP(S) page and return plain text.",
        {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}, fetch_webpage,
    )]
    if workspace is not None:
        tools.append(AgentTool(
            "todo", "List or update workspace agent todos.",
            {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["list", "add", "complete"]},
                "title": {"type": "string"}, "id": {"type": "string"}},
             "required": ["action"]}, lambda arguments: todo_tool(workspace, arguments),
        ))
    return tools
