"""Redact PII from text shown on partner-facing pages."""

from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_STREET = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9][\w\s.'#-]{2,40}\b(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Ln|Lane|Way|Ct|Court)\b",
    re.IGNORECASE,
)


def redact_partner_text(text: str) -> str:
    """Mask emails, phones, and street-like lines for external showcase."""
    out = _EMAIL.sub("[email redacted]", text)
    out = _PHONE.sub("[phone redacted]", out)
    out = _SSN.sub("[ssn redacted]", out)
    out = _STREET.sub("[address redacted]", out)
    return out


def excerpt_markdown(text: str, *, max_chars: int = 2400) -> str:
    body = text.strip()
    if len(body) <= max_chars:
        return body
    cut = body[:max_chars]
    if "\n\n" in cut:
        cut = cut.rsplit("\n\n", 1)[0]
    return cut.rstrip() + "\n\n… *(excerpt — full memo available to authorized operators)*"
