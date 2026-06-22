#!/usr/bin/env python3
"""Create a minimal prompt release planning payload."""

from __future__ import annotations

import json
import sys


def main() -> int:
    prompt_release_id = sys.argv[1] if len(sys.argv) > 1 else "prompt-draft"
    print(json.dumps({"status": "planned", "prompt_release_id": prompt_release_id, "requires_eval": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
