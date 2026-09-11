#!/usr/bin/env python3
"""GLMガバナンス評価レポート生成。

安全性・セキュリティ・プライバシー・アカウンタビリティ・透明性は実際の設定/監査ログから自動集計する。
公平性・有効性は定量評価が難しいため、手動で知見を追記できるログ形式（EFFECTIVENESS_LOG）で管理し、
レポート生成時にそのまま反映する。
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from glm_security import GLM_DIR, AuditLogger, ADMIN_TOTP_SECRET_NAME, SecretStore
from router import Registry, Settings, HIGH_RISK_CATEGORIES

EFFECTIVENESS_LOG = GLM_DIR / "governance_effectiveness.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_effectiveness_log(path: Path = EFFECTIVENESS_LOG) -> dict:
    """手動更新される有効性・公平性評価ログを読み込む。存在しなければ空のテンプレートを返す。"""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"entries": []}


def add_effectiveness_entry(
    area: str,
    finding: str,
    evidence: str = "",
    status: str = "unknown",
    axis: str = "有効性",
    path: Path = EFFECTIVENESS_LOG,
) -> dict:
    """新しい知見を有効性・公平性評価ログへ追記する（手動アップデートの入口）。"""
    if status not in ("good", "needs_attention", "unknown"):
        raise ValueError("status must be one of: good, needs_attention, unknown")
    if not area or not finding:
        raise ValueError("area and finding are required")
    log = load_effectiveness_log(path)
    entry = {
        "date": _utc_now(), "axis": axis, "area": area,
        "finding": finding, "evidence": evidence, "status": status,
    }
    log.setdefault("entries", []).append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def _safety_and_security_summary() -> dict:
    settings = Settings()
    audit = AuditLogger()
    return {
        "high_risk_categories": sorted(HIGH_RISK_CATEGORIES.keys()),
        "audit_integrity": audit.verify_integrity(),
        "admin_totp_configured": bool(SecretStore().get(ADMIN_TOTP_SECRET_NAME)),
        "permissions_deny_count": len(settings._d.get("permissions", {}).get("deny", [])),
    }


def _privacy_summary() -> dict:
    settings = Settings()
    return {"privacy_settings": settings.privacy()}


def _transparency_summary() -> dict:
    return {
        "routing_reason_exposed": True,  # /v1/chat/completions 応答に glm_routing を付与済み
        "budget_limit_usd": Registry().budget_limit(),
    }


def generate_report(effectiveness_path: Path = EFFECTIVENESS_LOG) -> dict:
    """7軸のガバナンス評価レポートを生成する。有効性・公平性は手動ログをそのまま反映する。"""
    effectiveness_log = load_effectiveness_log(effectiveness_path)
    return {
        "generated_at": _utc_now(),
        "safety_security": _safety_and_security_summary(),
        "privacy": _privacy_summary(),
        "transparency_accountability": _transparency_summary(),
        "fairness_effectiveness_manual_log": {
            "note": "この区分は自動計測できないため、add_effectiveness_entry()または--add-effectivenessで手動追記する。",
            "entries": effectiveness_log.get("entries", []),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="GLM governance report")
    parser.add_argument("--add-effectiveness", action="store_true", help="有効性/公平性ログへ知見を追記する")
    parser.add_argument("--axis", default="有効性", choices=["有効性", "公平性"])
    parser.add_argument("--area", default="")
    parser.add_argument("--finding", default="")
    parser.add_argument("--evidence", default="")
    parser.add_argument("--status", default="unknown", choices=["good", "needs_attention", "unknown"])
    args = parser.parse_args()

    if args.add_effectiveness:
        entry = add_effectiveness_entry(args.area, args.finding, args.evidence, args.status, args.axis)
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return

    print(json.dumps(generate_report(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
