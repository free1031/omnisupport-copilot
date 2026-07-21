"""CLI for an atomic release-pointer rollback."""

from __future__ import annotations

import argparse
import json
import os

from release.registry import ReleaseRegistry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rollback all release components by switching one pointer")
    parser.add_argument("--target-release-id", required=True)
    parser.add_argument("--current-release-id", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    args = parser.parse_args(argv)
    generation = ReleaseRegistry(args.database_url).rollback(
        args.target_release_id,
        actor=args.actor,
        expected_current_release_id=args.current_release_id,
        reason=args.reason,
    )
    print(json.dumps({"status": "rolled_back", "active_release_id": args.target_release_id, "generation": generation}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
