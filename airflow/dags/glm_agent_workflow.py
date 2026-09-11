"""GLM multi-agent workflow for Apache Airflow.

This DAG is intentionally an adapter: GLM Core remains the authority for
routing, approvals and workspace policy. Airflow only schedules the workflow.
"""

try:
    from airflow.sdk import DAG, task
except ImportError:  # Keeps the file importable in the GLM stdlib-only environment.
    DAG = None

from datetime import datetime


def build_dag():
    if DAG is None:
        return None
    with DAG("glm_agent_workflow", start_date=datetime(2026, 1, 1), schedule=None, catchup=False,
             tags=["glm", "agent", "mlops"], max_active_runs=1) as dag:

        @task
        def create_session():
            return {"status": "planned", "requires_approval": True}

        @task
        def collect_context(session):
            return {**session, "context_collected": True}

        @task
        def run_specialists(session):
            return {**session, "specialists": ["researcher", "implementer", "tester", "security_reviewer"]}

        @task
        def await_approval(session):
            # GLM Core/ApprovalBroker must perform the actual gate.
            return {**session, "approval_gate": "delegated_to_glm_core"}

        @task
        def record_evaluation(session):
            return {**session, "evaluation_recorded": True}

        record_evaluation(await_approval(run_specialists(collect_context(create_session()))))
    return dag


glm_agent_workflow = build_dag()
