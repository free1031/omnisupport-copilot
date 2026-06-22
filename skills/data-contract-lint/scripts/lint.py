#!/usr/bin/env python3
"""Minimal Week09 skill script placeholder for data contract linting."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "message": "usage: lint.py <json-path>"}))
        return 2
    path = Path(sys.argv[1])
    payload = json.loads(path.read_text(encoding="utf-8"))
    missing = [field for field in ["$schema", "type"] if field not in payload]
    print(json.dumps({"status": "ok" if not missing else "warn", "missing": missing}))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
