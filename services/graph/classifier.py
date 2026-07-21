"""Deterministic query classifier with conservative graph admission."""

from __future__ import annotations

import re

from services.graph.models import RouteDecision

GLOBAL_PATTERNS = (
    r"总体|全局|共同|共性|主要问题|归纳|趋势|过去.*所有|跨文档",
    r"overall|global|common pattern|summari[sz]e|across (all|documents)",
)
MULTIHOP_PATTERNS = (
    r"关联|关系链|传播路径|影响.*版本|从.*到.*怎么|哪些.*导致.*解决",
    r"multi.?hop|relationship path|how .* lead to|which .* caused .* resolved",
)
LOCAL_PATTERNS = (
    r"原因|导致|症状|解决方案|修复|影响了?什么",
    r"cause|symptom|resolution|fix|affect",
)
SIMPLE_PATTERNS = (
    r"怎么重置|如何安装|是什么|在哪里|步骤|价格",
    r"how to|what is|where is|steps?|price",
)


def classify_query(question: str, *, threshold: float = 0.70) -> RouteDecision:
    text = question.strip().casefold()
    if not text:
        return RouteDecision("hybrid", 1.0, ("empty_query",))
    scores = {
        "graph_global": _pattern_score(text, GLOBAL_PATTERNS),
        "graph_multihop": _pattern_score(text, MULTIHOP_PATTERNS),
        "graph_local": _pattern_score(text, LOCAL_PATTERNS),
        "hybrid": _pattern_score(text, SIMPLE_PATTERNS),
    }
    if not any(scores.values()):
        return RouteDecision("hybrid", 0.55, ("no_graph_signal",))
    if scores["graph_multihop"]:
        mode, score = "graph_multihop", scores["graph_multihop"]
    elif scores["graph_global"] and scores["graph_local"]:
        mode, score = "graph_drift", scores["graph_global"] + scores["graph_local"]
    elif scores["graph_global"]:
        mode, score = "graph_global", scores["graph_global"]
    elif scores["graph_local"]:
        mode, score = "graph_local", scores["graph_local"]
    else:
        return RouteDecision(
            "hybrid",
            min(0.95, 0.70 + scores["hybrid"] * 0.1),
            ("simple_factual_signal",),
        )
    confidence = min(0.96, 0.64 + score * 0.11)
    if confidence < threshold:
        return RouteDecision("hybrid", confidence, (f"low_graph_confidence:{mode}",))
    reasons = [f"matched:{mode}"]
    return RouteDecision(mode, confidence, tuple(reasons))


def _pattern_score(text: str, patterns: tuple[str, ...]) -> int:
    return sum(len(re.findall(pattern, text, flags=re.IGNORECASE)) for pattern in patterns)
