# GLM MLOps / Multi-Agent Architecture

## 安全な既定値

- AirflowとMLflowの外部連携は無効。
- 自動マージと自動pushは無効。
- Coordinatorは計画作成専用で、直接書込み・実行・マージをしない。
- ResearcherとSecurity Reviewerは読み取り中心。
- worktree作成、モデル承認、main統合はApprovalBrokerの承認が必要。
- Model Registryは候補登録と承認済み状態を分離する。
- 監査イベントは既存のAuditLoggerへ記録する。

## API

- `POST /api/orchestrator/plan`
- `GET /api/orchestrator/sessions`
- `GET /api/orchestrator/profiles`
- `POST /api/orchestrator/worktrees`
- `POST /api/orchestrator/task/authorize`
- `POST /api/orchestrator/task/status`
- `GET /api/mlops/status`
- `POST /api/mlops/airflow/submit`
- `POST /api/mlops/mlflow/log`
- `POST /api/mlops/registry/register`
- `POST /api/mlops/registry/approve`

## Airflow

`airflow/dags/glm_agent_workflow.py` は、GLM Coreを実行主体として、セッション作成、コンテキスト収集、専門エージェント処理、承認ゲート、評価記録の順序を管理します。

Airflowは長時間・定期・再実行可能な処理だけを担当し、モデル選択・権限・ファイル操作はGLM Coreが担当します。

## MLflow

MLflowが無効でも `.glm/mlops/runs.jsonl` に評価記録を保存します。MLflowを有効化する場合は `settings.json` の `mlflow_enabled` と `mlflow_url` を明示的に設定します。

## Model Registry

ローカルRegistryは `.glm/mlops/model-registry.json` に保存されます。登録時は `candidate`、承認後は `approved` となり、候補を直接Routerの既定モデルへ反映しません。

## 段階的な有効化

1. Coordinator計画と専門Agent権限を確認する。
2. Gitリポジトリでworktree作成を承認付きで検証する。
3. Airflowを専用環境で起動し、GLM Core APIのDAG実行だけを許可する。
4. MLflowへ評価・コスト・品質メトリクスを送る。
5. Registryの承認済みモデルだけをRouterへ反映する仕組みを追加する。
