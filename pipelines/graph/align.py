"""Conservative entity resolution with quarantine instead of forced merging."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

from pipelines.graph.models import AlignmentDecision, EntityMention
from pipelines.graph.schema import GraphSchema


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalized)


def stable_entity_id(entity_type: str, canonical_name: str, namespace: str = "default") -> str:
    digest = hashlib.sha256(
        f"{namespace}:{entity_type}:{normalize_name(canonical_name)}".encode()
    ).hexdigest()
    return f"ent-{digest[:24]}"


class EntityAligner:
    def __init__(self, schema: GraphSchema):
        self.schema = schema
        self._registry: dict[tuple[str, str], dict[str, str]] = {}

    def align(self, mention: EntityMention, *, namespace: str = "default") -> AlignmentDecision:
        self.schema.validate_entity_type(mention.entity_type)
        normalized = normalize_name(mention.name)
        if not normalized:
            return AlignmentDecision(
                entity_id="",
                entity_type=mention.entity_type,
                canonical_name=mention.name,
                normalized_name=normalized,
                status="rejected",
                reason="empty_normalized_name",
                confidence=mention.confidence,
            )
        if mention.confidence < self.schema.min_entity_confidence:
            return self._decision(mention, mention.name, normalized, "rejected", "low_confidence")

        aliases = self.schema.alias_map(mention.entity_type)
        canonical = aliases.get(normalized)
        if canonical:
            canonical_normalized = normalize_name(canonical)
            self._registry.setdefault((namespace, mention.entity_type), {})[
                canonical_normalized
            ] = canonical
            return self._decision(
                mention, canonical, canonical_normalized, "accepted", "schema_alias", namespace
            )

        registry = self._registry.setdefault((namespace, mention.entity_type), {})
        if normalized in registry:
            return self._decision(
                mention, registry[normalized], normalized, "accepted", "exact_match", namespace
            )

        similarities = sorted(
            (
                (SequenceMatcher(None, normalized, candidate).ratio(), candidate, name)
                for candidate, name in registry.items()
            ),
            reverse=True,
        )
        if similarities:
            best_score, best_normalized, best_name = similarities[0]
            second_score = similarities[1][0] if len(similarities) > 1 else 0.0
            if best_score >= self.schema.fuzzy_auto_merge_threshold and best_score - second_score >= 0.03:
                return self._decision(
                    mention, best_name, best_normalized, "accepted",
                    f"unique_fuzzy:{best_score:.3f}", namespace,
                )
            if best_score >= self.schema.fuzzy_review_threshold:
                return self._decision(
                    mention, mention.name, normalized, "quarantined",
                    f"ambiguous_fuzzy:{best_score:.3f}", namespace,
                )

        registry[normalized] = mention.name
        return self._decision(
            mention, mention.name, normalized, "accepted", "new_entity", namespace
        )

    def _decision(
        self,
        mention: EntityMention,
        canonical_name: str,
        normalized_name: str,
        status: str,
        reason: str,
        namespace: str = "default",
    ) -> AlignmentDecision:
        return AlignmentDecision(
            entity_id=(
                stable_entity_id(mention.entity_type, canonical_name, namespace)
                if status == "accepted"
                else ""
            ),
            entity_type=mention.entity_type,
            canonical_name=canonical_name,
            normalized_name=normalized_name,
            status=status,
            reason=reason,
            confidence=mention.confidence,
        )
