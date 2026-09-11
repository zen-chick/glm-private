"""Optional Airflow, MLflow and model registry adapters for GLM.

All integrations are disabled by default and communicate over explicit HTTP
endpoints only. The local JSON registry remains usable without extra packages.
"""

import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


class JsonModelRegistry:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self):
        if not self.path.exists():
            return {"models": []}
        try:
            return json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {"models": []}

    def list(self):
        return self._read()

    def register(self, model_id: str, version: str, metadata: Optional[Dict[str, Any]] = None):
        if not model_id or not version:
            raise ValueError("model_id and version are required")
        data = self._read()
        entry = {"model_id": model_id, "version": version, "status": "candidate",
                 "metadata": metadata or {}, "created_at": time.time()}
        data.setdefault("models", []).append(entry)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return entry

    def approve(self, model_id: str, version: str):
        data = self._read()
        found = False
        for entry in data.get("models", []):
            if entry.get("model_id") == model_id and entry.get("version") == version:
                entry["status"] = "approved"
                entry["approved_at"] = time.time()
                found = True
        if not found:
            raise KeyError("model version not found")
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "model_id": model_id, "version": version, "status": "approved"}


class OptionalHttpAdapter:
    def __init__(self, base_url: str = "", enabled: bool = False, timeout: int = 5):
        self.base_url = base_url.rstrip("/")
        self.enabled = bool(enabled and self.base_url)
        self.timeout = timeout

    def post(self, path: str, payload: Dict[str, Any]):
        if not self.enabled:
            return {"ok": False, "disabled": True}
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return {"ok": True, "status": response.status, "body": response.read().decode("utf-8", "replace")[:10000]}
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return {"ok": False, "error": str(error)[:500]}


class MLOpsManager:
    def __init__(self, root: Path, audit: Any, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.root = root / ".glm" / "mlops"
        self.root.mkdir(parents=True, exist_ok=True)
        self.audit = audit
        self.airflow = OptionalHttpAdapter(config.get("airflow_url", ""), config.get("airflow_enabled", False))
        self.mlflow = OptionalHttpAdapter(config.get("mlflow_url", ""), config.get("mlflow_enabled", False))
        self.registry = JsonModelRegistry(self.root / "model-registry.json")

    def submit_airflow(self, dag_id: str, conf: Dict[str, Any]):
        if not dag_id.replace("_", "").isalnum():
            return {"ok": False, "error": "invalid dag id"}
        result = self.airflow.post(f"/api/v2/dags/{dag_id}/dagRuns", {"dag_run_id": "glm-" + uuid.uuid4().hex[:12], "conf": conf})
        self.audit.record("mlops", "airflow_submit", detail={"dag_id": dag_id, "ok": result.get("ok"), "disabled": result.get("disabled", False)})
        return result

    def log_mlflow(self, run: Dict[str, Any]):
        payload = {"run_id": run.get("run_id", uuid.uuid4().hex), "params": run.get("params", {}),
                   "metrics": run.get("metrics", {}), "tags": run.get("tags", {})}
        result = self.mlflow.post("/api/2.0/mlflow/runs/create", payload)
        local = self.root / "runs.jsonl"
        with local.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.audit.record("mlops", "mlflow_record", detail={"run_id": payload["run_id"], "remote": result.get("ok", False)})
        return {"ok": True, "run_id": payload["run_id"], "remote": result}

    def status(self):
        return {"airflow_enabled": self.airflow.enabled, "airflow_url": self.airflow.base_url,
                "mlflow_enabled": self.mlflow.enabled, "mlflow_url": self.mlflow.base_url,
                "registry": self.registry.list()}
