"""Run the deterministic Week12 incident-to-regression closure."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import jsonschema

from evals.week11.runner import EvaluationRunner, write_report
from observability.week12.badcase import prepare_regression_assets
from observability.week12.incident import load_incident, write_postmortem
from observability.week12.slo import evaluate_slo, load_observations, load_policy


async def run(args: argparse.Namespace) -> dict:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    observations = load_observations(args.telemetry)
    policy = load_policy(args.slo_policy)
    slo_report = evaluate_slo(observations, policy)
    slo_schema = json.loads(args.slo_schema.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(slo_schema).validate(slo_report)
    slo_path = output_dir / "slo-report.json"
    slo_path.write_text(json.dumps(slo_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    incident = load_incident(args.incident, args.incident_schema)
    postmortem_path = write_postmortem(
        incident, output_dir / "postmortems" / f"{incident['incident_id']}.md"
    )
    eval_path, predictions_path, sample = prepare_regression_assets(
        incident=incident,
        base_eval_set=args.base_eval_set,
        base_predictions=args.base_predictions,
        output_dir=output_dir / "regression",
    )
    runner = EvaluationRunner(
        release_id=args.release_id,
        dataset_id="rag-qa-golden-week12-badcase",
        dataset_version="2.3.1",
    )
    eval_report = await runner.run_with_predictions(
        eval_set_path=eval_path,
        predictions_path=predictions_path,
    )
    eval_report_path = write_report(
        eval_report,
        output_dir / "regression",
        "week12-badcase-regression-report.json",
    )

    status = "pass" if slo_report["alerts"] and eval_report.gate["status"] == "pass" else "fail"
    closure = {
        "status": status,
        "detected_alerts": [item["name"] for item in slo_report["alerts"]],
        "incident_id": incident["incident_id"],
        "trace_id": incident["trace_id"],
        "postmortem_path": str(postmortem_path),
        "regression_case_id": sample["case_id"],
        "eval_set_path": str(eval_path),
        "predictions_path": str(predictions_path),
        "eval_report_path": str(eval_report_path),
        "eval_gate": eval_report.gate,
    }
    closure_path = output_dir / "closure-report.json"
    closure_path.write_text(json.dumps(closure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    closure["closure_report_path"] = str(closure_path)
    return closure


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Week12 observability learning loop")
    parser.add_argument(
        "--telemetry", type=Path, default=Path("tests/fixtures/week12/telemetry_window_bad.jsonl")
    )
    parser.add_argument(
        "--incident", type=Path, default=Path("tests/fixtures/week12/incident_bad_citation.json")
    )
    parser.add_argument(
        "--slo-policy", type=Path, default=Path("observability/slo/week12_slo.yaml")
    )
    parser.add_argument(
        "--incident-schema",
        type=Path,
        default=Path("contracts/observability/incident.schema.json"),
    )
    parser.add_argument(
        "--slo-schema",
        type=Path,
        default=Path("contracts/observability/slo_report.schema.json"),
    )
    parser.add_argument(
        "--base-eval-set", type=Path, default=Path("evals/sets/rag_qa_golden_v2_3_0.jsonl")
    )
    parser.add_argument(
        "--base-predictions",
        type=Path,
        default=Path("evals/fixtures/week11/rag_predictions_good.jsonl"),
    )
    parser.add_argument("--release-id", default="dev-week12-local")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/week12"))
    args = parser.parse_args(argv)
    closure = asyncio.run(run(args))
    print(json.dumps(closure, ensure_ascii=False, indent=2))
    return 0 if closure["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
