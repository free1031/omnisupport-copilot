"""CLI adapter for Week12 bad-case to Week11 regression assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from observability.week12.badcase import prepare_regression_assets
from observability.week12.incident import load_incident


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert a Week12 incident to eval assets")
    parser.add_argument("--incident", type=Path, required=True)
    parser.add_argument(
        "--incident-schema",
        type=Path,
        default=Path("contracts/observability/incident.schema.json"),
    )
    parser.add_argument(
        "--base-eval-set", type=Path, default=Path("evals/sets/rag_qa_golden_v2_3_0.jsonl")
    )
    parser.add_argument(
        "--base-predictions",
        type=Path,
        default=Path("evals/fixtures/week11/rag_predictions_good.jsonl"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports/week12/regression"))
    args = parser.parse_args(argv)
    incident = load_incident(args.incident, args.incident_schema)
    eval_path, prediction_path, sample = prepare_regression_assets(
        incident=incident,
        base_eval_set=args.base_eval_set,
        base_predictions=args.base_predictions,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "case_id": sample["case_id"],
                "eval_set_path": str(eval_path),
                "predictions_path": str(prediction_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
