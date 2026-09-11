"""Notion APIへの読み取り専用アクセス。"""

import json
import urllib.error
import urllib.request

from glm_security import SecretStore


NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionReadClient:
    def __init__(self, secrets=None, request=None):
        self.secrets = secrets or SecretStore()
        self.request = request or self._request

    def search(self, query="", page_size=10):
        try:
            page_size = max(1, min(20, int(page_size)))
        except (TypeError, ValueError):
            return {"error": "page_size must be an integer"}
        payload = {"page_size": page_size, "filter": {"property": "object", "value": "page"}}
        if query:
            payload["query"] = str(query)[:200]
        return self.request("POST", "/search", payload)

    def page(self, page_id):
        if not isinstance(page_id, str) or not page_id:
            return {"error": "page_id is required"}
        return self.request("GET", "/pages/" + page_id, None)

    def _request(self, method, endpoint, payload):
        token = self.secrets.get("notion_token")
        if not token:
            return {"error": "Notion is not configured. Add ~/.glm/secrets/notion_token."}
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            NOTION_API + endpoint,
            data=data,
            headers={
                "Authorization": "Bearer " + token,
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return self._redact(json.loads(response.read().decode("utf-8")))
        except urllib.error.HTTPError as error:
            return {"error": f"Notion returned HTTP {error.code}"}
        except (OSError, json.JSONDecodeError) as error:
            return {"error": f"Notion request failed: {error}"}

    @staticmethod
    def _redact(payload):
        if "results" in payload:
            return {"results": [NotionReadClient._page_summary(page) for page in payload["results"]]}
        return NotionReadClient._page_summary(payload)

    @staticmethod
    def _page_summary(page):
        return {
            "id": page.get("id"),
            "url": page.get("url"),
            "object": page.get("object"),
            "created_time": page.get("created_time"),
            "last_edited_time": page.get("last_edited_time"),
        }


class NotionReadTool:
    name = "NotionRead"
    description = "Search or retrieve Notion page metadata. This tool never writes to Notion."
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "page"]},
            "query": {"type": "string"},
            "page_id": {"type": "string"},
            "page_size": {"type": "integer"},
        },
        "required": ["action"],
    }

    def __init__(self, client=None):
        self.client = client or NotionReadClient()

    def execute(self, params):
        action = params.get("action")
        if action == "search":
            result = self.client.search(params.get("query", ""), params.get("page_size", 10))
        elif action == "page":
            result = self.client.page(params.get("page_id", ""))
        else:
            result = {"error": "action must be search or page"}
        return json.dumps(result, ensure_ascii=False)