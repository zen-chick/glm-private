"""Non-destructive live checks for Ollama and configured cloud providers."""
import json
import os
import ssl
import urllib.error
import urllib.request


def check(url, headers=None):
    try:
        request = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read(1024)
            return True, response.status
    except urllib.error.HTTPError as error:
        return False, error.code
    except (OSError, urllib.error.URLError, ValueError) as error:
        return False, type(error).__name__


results = {}
results["ollama"] = check(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/tags")
providers = {
    "anthropic": ("https://api.anthropic.com/v1/models", "ANTHROPIC_API_KEY", "x-api-key"),
    "openai": ("https://api.openai.com/v1/models", "OPENAI_API_KEY", "Authorization"),
    "groq": ("https://api.groq.com/openai/v1/models", "GROQ_API_KEY", "Authorization"),
}
for name, (url, env_name, header_name) in providers.items():
    key = os.environ.get(env_name, "")
    if not key:
        results[name] = (False, "not configured")
        continue
    value = key if header_name == "x-api-key" else f"Bearer {key}"
    results[name] = check(url, {header_name: value})

github_token = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")
if github_token:
    results["github"] = check("https://api.github.com/user", {
        "Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"
    })
else:
    results["github"] = (False, "not configured")

for name, (ok, detail) in results.items():
    print(json.dumps({"service": name, "reachable": ok, "result": detail}))
