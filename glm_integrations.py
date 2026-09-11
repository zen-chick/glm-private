#!/usr/bin/env python3
"""秘密値を表示せずに外部連携の登録状態を確認する。"""

import argparse
import json
from pathlib import Path

from glm_security import SecretStore


REGISTRY_FILE = Path(__file__).parent / "integrations.json"


class IntegrationRegistry:
    def __init__(self, registry_file=REGISTRY_FILE, secrets=None):
        self.registry_file = Path(registry_file)
        self.secrets = secrets or SecretStore()

    def entries(self):
        data = json.loads(self.registry_file.read_text(encoding="utf-8-sig"))
        return data.get("integrations", {})

    def set_enabled(self, name, enabled):
        data = json.loads(self.registry_file.read_text(encoding="utf-8-sig"))
        entries = data.get("integrations", {})
        if name not in entries:
            raise ValueError("unknown integration")
        enabled = bool(enabled)
        missing = [secret for secret in entries[name]["required_secrets"] if not self.secrets.get(secret)]
        if enabled and missing:
            raise ValueError("required credentials are missing")
        entries[name]["enabled"] = enabled
        temporary = self.registry_file.with_suffix(self.registry_file.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.registry_file)
        return self.status(name)[name]

    def status(self, name=None):
        entries = self.entries()
        selected = {name: entries[name]} if name else entries
        result = {}
        for integration_name, entry in selected.items():
            missing = [secret for secret in entry["required_secrets"] if not self.secrets.get(secret)]
            result[integration_name] = {
                "enabled": bool(entry["enabled"]),
                "mode": entry["mode"],
                "ready": bool(entry["enabled"]) and not missing,
                "missing_secrets": missing,
                "minimum_scopes": entry["minimum_scopes"],
                "available_features": entry["available_features"],
                "blocked_features": entry["blocked_features"],
            }
        return result


def main():
    parser = argparse.ArgumentParser(description="GLM integration status")
    parser.add_argument("--name", choices=["notion", "slack_webhook", "slack_bot", "sharepoint"])
    args = parser.parse_args()
    print(json.dumps(IntegrationRegistry().status(args.name), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()