"""Convert a production incident into a versioned Week11 regression sample."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def build_eval_sample(incident: dict[str, Any]) -> dict[str, Any]:
    case_id = re.sub(r"[^A-Z0-9_-]", "_", f"W12-{incident['incident_id']}".upper())
    return {
        "case_id": case_id,
        "category": "adversarial",
        "query": incident["user_query"],
        "expected_answer": incident["expected_answer"],
        "expected_keywords": incident["expected_keywords"],
        "expected_context_keywords": incident.get(
            "expected_context_keywords", incident["expected_keywords"]
        ),
        "expected_citation_ids": incident["expected_evidence_ids"],
        "source_doc": incident.get("source_doc", "production-incident"),
        "doc_version": incident.get("doc_version", "incident-v1"),
        "tags": ["production_badcase", incident["root_cause"]["category"]],
        "thresholds": {
            "faithfulness": 0.55,
            "answer_relevance": 0.60,
            "context_precision": 0.50,
            "context_recall": 0.80,
            "answer_correctness": 0.60,
            "semantic_similarity": 0.40
        },
        "metadata": {
            "incident_id": incident["incident_id"],
            "trace_id": incident["trace_id"],
            "trace_url": incident.get("trace_url", ""),
            "actual_bad_answer": incident["actual_bad_answer"],
            "root_cause": incident["root_cause"],
        },
    }


def build_fixed_prediction(sample: dict[str, Any], trace_id: str) -> dict[str, Any]:
    contexts = []
    citations = []
    for index, evidence_id in enumerate(sample["expected_citation_ids"] or ["incident-evidence"]):
        chunk_id = f"incident-chunk-{index + 1}"
        citation = {
            "evidence_id": evidence_id,
            "chunk_id": chunk_id,
            "doc_id": sample["source_doc"],
        }
        citations.append(citation)
        contexts.append(
            {
                "chunk_id": chunk_id,
                "content": sample["expected_answer"],
                "score": 1.0,
                "citation": citation,
            }
        )
    return {
        "case_id": sample["case_id"],
        "answer": sample["expected_answer"],
        "confidence": 0.95,
        "trace_id": trace_id,
        "latency_ms": 450,
        "cost_usd": 0.002,
        "citations": citations,
        "retrieved_contexts": contexts,
    }


def prepare_regression_assets(
    *,
    incident: dict[str, Any],
    base_eval_set: Path,
    base_predictions: Path,
    output_dir: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sample = build_eval_sample(incident)
    eval_rows = [
        json.loads(line) for line in base_eval_set.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    prediction_rows = [
        json.loads(line)
        for line in base_predictions.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    eval_rows = [row for row in eval_rows if row["case_id"] != sample["case_id"]] + [sample]
    fixed = build_fixed_prediction(sample, incident["trace_id"])
    prediction_rows = [row for row in prediction_rows if row["case_id"] != sample["case_id"]] + [fixed]

    eval_path = output_dir / "rag_qa_golden_with_week12_badcase.jsonl"
    prediction_path = output_dir / "rag_predictions_with_week12_fix.jsonl"
    eval_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in eval_rows) + "\n",
        encoding="utf-8",
    )
    prediction_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in prediction_rows) + "\n",
        encoding="utf-8",
    )
    return eval_path, prediction_path, sample
