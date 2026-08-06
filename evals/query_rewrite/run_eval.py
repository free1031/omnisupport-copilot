"""Run the release gate for query rewrite quality, safety and degradation."""

# ruff: noqa: E402 - service path is installed before app imports

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "rag_api"))
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.query_rewrite import QueryRewriteService

from observability.runtime import hash_text
from pipelines.query.rewriter import invented_protected_terms


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    seen = set()
    required = {
        "case_id",
        "query",
        "expected_protected_terms",
        "expected_semantic_terms",
        "forbidden_terms",
    }
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        missing = required - set(case)
        if missing:
            raise ValueError(f"{path}:{line_no}: missing {', '.join(sorted(missing))}")
        if case["case_id"] in seen:
            raise ValueError(f"{path}:{line_no}: duplicate case_id {case['case_id']}")
        if not case["query"].strip():
            raise ValueError(f"{path}:{line_no}: query must not be empty")
        seen.add(case["case_id"])
        cases.append(case)
    if not cases:
        raise ValueError(f"{path}: no evaluation cases")
    return cases


async def evaluate_cases(
    cases: list[dict[str, Any]],
    service: QueryRewriteService,
    *,
    strategy: str,
    max_fallback_rate: float = 0.0,
    max_latency_p95_ms: float = 1000.0,
) -> dict[str, Any]:
    rows = []
    retained_count = 0
    expected_count = 0
    invented_case_count = 0
    fallback_count = 0
    latencies = []

    for case in cases:
        result = await service.rewrite(case["query"], tenant_id="offline-eval")
        semantic_folded = result.semantic_query.casefold()
        retained = [
            term
            for term in case["expected_protected_terms"]
            if term.casefold() in semantic_folded
        ]
        missing_semantic = [
            term
            for term in case["expected_semantic_terms"]
            if term.casefold() not in semantic_folded
        ]
        forbidden_found = [
            term for term in case["forbidden_terms"] if term.casefold() in semantic_folded
        ]
        invented = invented_protected_terms(case["query"], result.semantic_query)
        protected_ok = len(retained) == len(case["expected_protected_terms"])
        passed = protected_ok and not invented and not missing_semantic and not forbidden_found
        expected_count += len(case["expected_protected_terms"])
        retained_count += len(retained)
        invented_case_count += int(bool(invented))
        fallback_count += int(result.mode == "fallback")
        latencies.append(result.latency_ms)
        rows.append(
            {
                "case_id": case["case_id"],
                "query_sha256": hash_text(case["query"]),
                "mode": result.mode,
                "passed": passed,
                "protected_terms_retained": protected_ok,
                "invented_protected_terms": invented,
                "missing_semantic_terms": missing_semantic,
                "forbidden_terms_found": forbidden_found,
                "fallback_reason": result.fallback_reason,
                "latency_ms": result.latency_ms,
            }
        )

    case_count = len(rows)
    metrics = {
        "case_count": case_count,
        "case_pass_rate": _ratio(sum(row["passed"] for row in rows), case_count),
        "protected_term_retention_rate": _ratio(retained_count, expected_count),
        "invented_protected_term_rate": _ratio(invented_case_count, case_count),
        "fallback_rate": _ratio(fallback_count, case_count),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }
    blockers = []
    if metrics["case_pass_rate"] < 1.0:
        blockers.append(f"case_pass_rate:{metrics['case_pass_rate']}<1.0")
    if metrics["protected_term_retention_rate"] < 1.0:
        blockers.append(
            f"protected_term_retention_rate:{metrics['protected_term_retention_rate']}<1.0"
        )
    if metrics["invented_protected_term_rate"] > 0.0:
        blockers.append(
            f"invented_protected_term_rate:{metrics['invented_protected_term_rate']}>0.0"
        )
    if metrics["fallback_rate"] > max_fallback_rate:
        blockers.append(f"fallback_rate:{metrics['fallback_rate']}>{max_fallback_rate}")
    if metrics["latency_p95_ms"] > max_latency_p95_ms:
        blockers.append(f"latency_p95_ms:{metrics['latency_p95_ms']}>{max_latency_p95_ms}")

    return {
        "schema_version": "query_rewrite_eval_v1",
        "strategy": strategy,
        "prompt_release_id": service.config.query_rewrite_prompt_release_id,
        "metrics": metrics,
        "cases": rows,
        "gate": {"status": "pass" if not blockers else "fail", "blocking_reasons": blockers},
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile + 0.999999)))
    return round(ordered[index], 2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "evals" / "fixtures" / "query_rewrite_cases_v1.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "query_rewrite" / "eval_report.json",
    )
    parser.add_argument(
        "--strategy",
        choices=("auto", "llm", "deterministic", "disabled"),
        default="deterministic",
    )
    parser.add_argument("--max-fallback-rate", type=float, default=0.0)
    parser.add_argument("--max-latency-p95-ms", type=float, default=1000.0)
    args = parser.parse_args(argv)

    eval_config = settings.model_copy(update={"query_rewrite_strategy": args.strategy})
    service = QueryRewriteService(config=eval_config)
    report = asyncio.run(
        evaluate_cases(
            load_cases(args.cases),
            service,
            strategy=args.strategy,
            max_fallback_rate=args.max_fallback_rate,
            max_latency_p95_ms=args.max_latency_p95_ms,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "gate": report["gate"], "metrics": report["metrics"]}))
    return 0 if report["gate"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
