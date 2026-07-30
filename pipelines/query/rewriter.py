"""Deterministic query rewrite and HyDE planning helpers for Week08.

Production systems often use an LLM for rewrite/HyDE. The classroom path keeps
this deterministic so Docker/Podman runs do not require an LLM key.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

ERROR_CODE_RE = re.compile(r"\b[A-Z]{2,}-[A-Z0-9-]+\b")
IDENTIFIER_RE = re.compile(r"\b[A-Z]+-\d{3,}(?:-[A-Z0-9]+)?\b")
FIRMWARE_TERMS = {"firmware", "upgrade", "rollback", "recovery", "boot"}


@dataclass
class QueryRewritePlan:
    original_query: str
    normalized_query: str
    lexical_terms: list[str]
    semantic_query: str
    hyde_document: str | None = None
    rewrite_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_query(query: str) -> str:
    return " ".join(query.strip().split())


def extract_lexical_terms(query: str) -> list[str]:
    terms = set(ERROR_CODE_RE.findall(query))
    terms.update(IDENTIFIER_RE.findall(query))
    lowered = query.lower()
    for term in FIRMWARE_TERMS:
        if term in lowered:
            terms.add(term)
    return sorted(terms)


def rewrite_query(query: str) -> QueryRewritePlan:
    normalized = normalize_query(query)
    lexical_terms = extract_lexical_terms(normalized)
    reasons: list[str] = []
    semantic_query = normalized

    if lexical_terms:
        reasons.append("preserve_lexical_identifiers")
        semantic_query = f"{normalized} {' '.join(lexical_terms)}"

    if "how do i" in normalized.lower() or "如何" in normalized:
        reasons.append("procedural_question")
        semantic_query = f"{semantic_query} troubleshooting steps recovery procedure"

    return QueryRewritePlan(
        original_query=query,
        normalized_query=normalized,
        lexical_terms=lexical_terms,
        semantic_query=semantic_query,
        rewrite_reasons=reasons or ["identity_rewrite"],
    )


def build_hyde_document(query: str) -> QueryRewritePlan:
    plan = rewrite_query(query)
    plan.hyde_document = (
        "A grounded support answer should identify the affected product, "
        "preserve exact error codes or identifiers, describe recovery steps, "
        "and cite the relevant runbook evidence."
    )
    plan.rewrite_reasons = sorted(set([*plan.rewrite_reasons, "hyde_document"]))
    return plan

