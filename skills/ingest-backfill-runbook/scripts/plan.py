#!/usr/bin/env python3
"""Create a bounded ingest backfill plan stub."""

from __future__ import annotations

import json
import sys


def main() -> int:
    scope = sys.argv[1] if len(sys.argv) > 1 else "unspecified"
    print(json.dumps({"status": "planned", "scope": scope, "requires_dry_run": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
