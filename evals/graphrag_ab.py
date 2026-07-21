"""CLI for the Week13 category-aware GraphRAG A/B gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.week13.ab import compare_by_category, load_paired_cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare GraphRAG and hybrid retrieval per category")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--vector-release-id", required=True)
    parser.add_argument("--graph-release-id", required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/week13/graphrag-ab-report.json"))
    parser.add_argument("--min-samples", type=int, default=2)
    args = parser.parse_args(argv)
    report = compare_by_category(
        load_paired_cases(args.cases),
        vector_release_id=args.vector_release_id,
        graph_release_id=args.graph_release_id,
        min_samples=args.min_samples,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "experiment_id": report["experiment_id"],
        "gate": report["gate"],
        "routing_policy": report["routing_policy"],
        "report_path": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0 if report["gate"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
