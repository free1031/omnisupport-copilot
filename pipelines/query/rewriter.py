"""Query normalization and deterministic rewrite safety primitives.

The online service may use an LLM, but every request first passes through this
deterministic layer.  It provides the lossless fallback and protects exact
identifiers from being removed or invented by a model-generated rewrite.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
ERROR_CODE_RE = re.compile(r"\b[A-Z]{2,}-[A-Z0-9-]+\b")
IDENTIFIER_RE = re.compile(r"\b[A-Z]+-\d{3,}(?:-[A-Z0-9]+)?\b")
CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
VERSION_RE = re.compile(r"(?<![\w.])v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][A-Za-z0-9.-]+)?\b")
FIRMWARE_TERMS = {"firmware", "upgrade", "rollback", "recovery", "boot"}
PROTECTED_TERM_PATTERNS = (ERROR_CODE_RE, IDENTIFIER_RE, CVE_RE, UUID_RE, VERSION_RE)


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
    """Remove transport control characters and collapse whitespace."""

    without_controls = CONTROL_CHARACTER_RE.sub(" ", str(query))
    return " ".join(without_controls.strip().split())


def extract_protected_terms(query: str) -> list[str]:
    """Return exact tokens whose mutation can materially change retrieval."""

    terms: set[str] = set()
    for pattern in PROTECTED_TERM_PATTERNS:
        terms.update(match.group(0) for match in pattern.finditer(query))
    return sorted(terms, key=lambda value: (value.casefold(), value))


def extract_lexical_terms(query: str) -> list[str]:
    terms = set(extract_protected_terms(query))
    lowered = query.lower()
    for term in FIRMWARE_TERMS:
        if term in lowered:
            terms.add(term)
    return sorted(terms, key=lambda value: (value.casefold(), value))


def invented_protected_terms(original_query: str, candidate: str) -> list[str]:
    """Find protected identifiers introduced by a candidate rewrite."""

    original = {value.casefold() for value in extract_protected_terms(original_query)}
    return [
        value
        for value in extract_protected_terms(candidate)
        if value.casefold() not in original
    ]


def preserve_protected_terms(original_query: str, candidate: str) -> str:
    """Append any exact identifiers omitted by an otherwise valid rewrite."""

    normalized = normalize_query(candidate)
    candidate_terms = {value.casefold() for value in extract_protected_terms(normalized)}
    missing = [
        value
        for value in extract_protected_terms(original_query)
        if value.casefold() not in candidate_terms
    ]
    return normalize_query(" ".join([normalized, *missing]))


def remove_invented_protected_terms(
    original_query: str,
    candidate: str,
) -> tuple[str, list[str]]:
    """Remove model-invented identifier tokens without guessing replacements.

    A malformed value such as ``EG-3:000`` may be detected as the protected
    prefix ``EG-3``.  Removing its entire whitespace-delimited token is safer
    than attempting a fuzzy correction; the validated deterministic baseline
    restores the user's exact original identifier later in the pipeline.
    """

    repaired = normalize_query(candidate)
    invented = invented_protected_terms(original_query, repaired)
    for term in invented:
        repaired = re.sub(
            rf"(?<!\S)\S*{re.escape(term)}\S*(?!\S)",
            " ",
            repaired,
            flags=re.IGNORECASE,
        )
    return normalize_query(repaired), invented


def rewrite_query(query: str) -> QueryRewritePlan:
    """Build a lossless deterministic rewrite used for fallback and local mode."""

    normalized = normalize_query(query)
    lexical_terms = extract_lexical_terms(normalized)
    reasons: list[str] = []
    semantic_query = normalized

    if lexical_terms:
        reasons.append("preserve_lexical_identifiers")

    lowered = normalized.casefold()
    if "how do i" in lowered or "如何" in normalized or "怎么" in normalized:
        reasons.append("procedural_expansion")
        expansion = (
            "根因 排查步骤 恢复步骤 验证方法"
            if re.search(r"[\u4e00-\u9fff]", normalized)
            else "root cause troubleshooting recovery steps verification"
        )
        semantic_query = f"{semantic_query} {expansion}"

    semantic_query = preserve_protected_terms(normalized, semantic_query)
    return QueryRewritePlan(
        original_query=query,
        normalized_query=normalized,
        lexical_terms=lexical_terms,
        semantic_query=semantic_query,
        rewrite_reasons=reasons or ["identity_rewrite"],
    )


def build_hyde_document(query: str) -> QueryRewritePlan:
    """Build the deterministic no-LLM HyDE fallback without asserting facts."""

    plan = rewrite_query(query)
    plan.hyde_document = (
        "A relevant support runbook would address this request: "
        f"{plan.semantic_query}. It would preserve exact identifiers, explain "
        "diagnosis and recovery steps, define verification checks, and cite governed evidence."
    )
    plan.rewrite_reasons = sorted(set([*plan.rewrite_reasons, "hyde_document"]))
    return plan
