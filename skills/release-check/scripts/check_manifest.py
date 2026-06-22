#!/usr/bin/env python3
"""Minimal release manifest evidence checker."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "message": "usage: check_manifest.py <manifest-json>"}))
        return 2
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    missing = [field for field in ["release_id"] if field not in payload]
    print(json.dumps({"status": "ok" if not missing else "fail", "missing": missing}))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
