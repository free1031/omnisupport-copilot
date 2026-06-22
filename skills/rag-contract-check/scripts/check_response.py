#!/usr/bin/env python3
"""Minimal RAG response contract checker."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED = ["answer", "citations", "evidence_ids", "release_id", "index_release_id", "prompt_release_id", "trace_id"]


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "message": "usage: check_response.py <response-json>"}))
        return 2
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    missing = [field for field in REQUIRED if field not in payload]
    if not payload.get("abstain_reason") and not payload.get("evidence_ids"):
        missing.append("evidence_ids_or_abstain_reason")
    print(json.dumps({"status": "ok" if not missing else "fail", "missing": missing}))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
