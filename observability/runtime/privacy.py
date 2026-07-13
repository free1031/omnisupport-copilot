"""PII-safe helpers for trace attributes.

Trace backends are operational systems, not a second copy of user content.
The default path records hashes, lengths, counters, and decision metadata.
Preview capture is explicit and always redacted.
"""

from __future__ import annotations

import hashlib
import re

_REDACTION_PATTERNS = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"), "[PHONE]"),
    (re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"), "[NATIONAL_ID]"),
    (re.compile(r"(?<!\d)(?:\d[ -]?){15,19}(?!\d)"), "[PAYMENT_CARD]"),
    (re.compile(r"(?i)(api[_-]?key|token|password)\s*[:=]\s*\S+"), r"\1=[SECRET]"),
)


def redact_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def safe_preview(value: str, *, limit: int = 200) -> str:
    """Return a bounded, redacted, single-line preview."""

    compact = " ".join(str(value).split())
    return redact_text(compact)[: max(limit, 0)]


def hash_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
