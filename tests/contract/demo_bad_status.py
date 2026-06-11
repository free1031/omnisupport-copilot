"""契约门禁演练：用非枚举值 status="done" 测试 ticket_contract 能否拦截"""

import json
import sys
from pathlib import Path

import jsonschema

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONTRACT_PATH = PROJECT_ROOT / "contracts" / "data" / "ticket_contract.json"

# 一条合法的样本工单（从 test fixture 中摘取）
VALID_RECORD = {
    "ticket_id": "TKT-20260420-000001",
    "schema_version": "ticket_v1",
    "source_id": "structured:tickets:practice_ok",
    "ingest_batch_id": "batch-20260420-001",
    "customer_id": "cust-001",
    "org_id": "org-001",
    "status": "pending",
    "priority": "p2_high",
    "category": "configuration",
    "product_line": "northstar_workspace",
    "product_version": "2.4.1",
    "subject": "Workspace SSO redirects to an empty callback page",
    "description": "Customer sees a blank callback page after enabling SSO.",
    "error_codes": ["NSW-4012"],
    "asset_ids": ["asset-edge-001"],
    "assignee_id": "agent-007",
    "sla_tier": "enterprise",
    "sla_due_at": "2026-04-20T12:00:00Z",
    "created_at": "2026-04-20T08:00:00Z",
    "updated_at": "2026-04-20T08:15:00Z",
    "resolved_at": None,
    "pii_level": "high",
    "pii_redacted": True,
    "quality_gate": "pass",
    "owner": "support-ops",
    "tags": ["sso", "callback", "week02"],
}

# 把 status 改成契约枚举里没有的值
BAD_RECORD = dict(VALID_RECORD)
BAD_RECORD["status"] = "done"
BAD_RECORD["ticket_id"] = "TKT-20260420-099999"


def main():
    schema = json.loads(CONTRACT_PATH.read_text())

    # ── 1. 先验证合法记录应该通过 ──
    try:
        jsonschema.validate(VALID_RECORD, schema)
        print("[PASS] 合法工单（status=pending）校验通过 ✅")
    except jsonschema.ValidationError as e:
        print(f"[FAIL] 合法工单意外拦截: {e.message}")
        sys.exit(1)

    # ── 2. 验证坏数据应该被拦截 ──
    try:
        jsonschema.validate(BAD_RECORD, schema)
        print(f"[FAIL] 坏数据（status=done）未被拦截！契约有漏洞 ❌")
        sys.exit(1)
    except jsonschema.ValidationError as e:
        print(f"[PASS] 坏数据（status=done）被成功拦截 ✅")
        print(f"      错误信息: {e.message}")


if __name__ == "__main__":
    main()