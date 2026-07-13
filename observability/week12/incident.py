"""Incident validation and postmortem rendering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema


def load_incident(path: Path, schema_path: Path) -> dict[str, Any]:
    incident = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(incident)
    return incident


def render_postmortem(incident: dict[str, Any]) -> str:
    spans = incident.get("span_evidence", [])
    span_lines = "\n".join(
        f"- `{item.get('name', 'unknown')}`: status={item.get('status', 'unknown')}, "
        f"latency_ms={item.get('latency_ms', 0)}, evidence_count={item.get('evidence_count', 'n/a')}"
        for item in spans
    ) or "- No span evidence captured"
    actions = "\n".join(f"- [ ] {item}" for item in incident.get("action_items", [])) or "- [ ] Add owner and due date"
    fix = incident.get("fix", {})
    return f"""# {incident['incident_id']} - {incident['summary']}

## 1. Summary

- Severity: `{incident['severity']}`
- Status: `{incident.get('status', 'triggered')}`
- Detected at: `{incident['detected_at']}`

## 2. Trace Evidence

- Trace ID: `{incident['trace_id']}`
- Trace URL: {incident.get('trace_url', 'n/a')}

{span_lines}

## 3. Root Cause

- Layer: `{incident['root_cause']['layer']}`
- Category: `{incident['root_cause']['category']}`
- Detail: {incident['root_cause']['detail']}

## 4. Fix

- Change: {fix.get('change', 'pending')}
- Release: `{fix.get('release_id', 'pending')}`
- Verification: {fix.get('verification', 'Week11 regression gate')}

## 5. Verify

- [ ] Reproduce the original bad answer from the trace evidence.
- [ ] Add the case to the Week11 eval set without mutating the canonical set.
- [ ] Run regression and require `gate.status=pass`.
- [ ] Check the same SLO window after the fix.

## 6. Lessons

This incident is not closed until the trace evidence, regression sample, and runbook update are linked.

## 7. Action Items

{actions}
"""


def write_postmortem(incident: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_postmortem(incident), encoding="utf-8")
    return output_path
