import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_mlops import JsonModelRegistry, MLOpsManager
from glm_orchestrator import AgentPolicy, Coordinator


class Audit:
    def __init__(self):
        self.events = []

    def record(self, *args, **kwargs):
        self.events.append((args, kwargs))


class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        self.audit = Audit()

    def tearDown(self):
        self.temp.cleanup()

    def test_plan_uses_safe_roles_and_denies_merge(self):
        coordinator = Coordinator(self.workspace, self.audit)
        plan = coordinator.create_plan("安全に変更を実装してテストする")
        roles = {task["role"] for task in plan["tasks"]}
        self.assertEqual(roles, {"researcher", "implementer", "tester", "security_reviewer"})
        task_id = next(task["task_id"] for task in plan["tasks"] if task["role"] == "implementer")
        self.assertTrue(coordinator.authorize_task(plan["session_id"], task_id, "write")["ok"])
        self.assertFalse(coordinator.authorize_task(plan["session_id"], task_id, "merge")["ok"])

    def test_worktree_requires_git_repository(self):
        coordinator = Coordinator(self.workspace, self.audit)
        plan = coordinator.create_plan("test")
        result = coordinator.create_worktrees(plan["session_id"])
        self.assertFalse(result["ok"])
        self.assertIn("git repository", result["error"])

    def test_registry_candidate_then_approval(self):
        registry = JsonModelRegistry(self.workspace / "registry.json")
        entry = registry.register("glm-test", "1", {"score": 0.9})
        self.assertEqual(entry["status"], "candidate")
        approved = registry.approve("glm-test", "1")
        self.assertEqual(approved["status"], "approved")

    def test_mlops_integrations_disabled_by_default(self):
        manager = MLOpsManager(self.workspace, self.audit)
        self.assertFalse(manager.airflow.enabled)
        self.assertFalse(manager.mlflow.enabled)
        self.assertTrue(manager.submit_airflow("glm_agent_workflow", {})["disabled"])
        self.assertTrue(manager.log_mlflow({"metrics": {"quality": 1}})["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
