"""Normalize chunk text before vectorization.

Cleaning is deliberately light. Aggressive stemming or stop-word removal
would strip the domain vocabulary the analysis depends on, so the module
lowercases, normalizes whitespace and punctuation artefacts, and protects a
configured list of insurance, health, economic, and demographic terms.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("preprocess")

# pypdf leaves hyphenation and ligature artefacts; these are repaired so the
# same word is not split into two different features.
_DEHYPHENATE = re.compile(r"(\w)-\s+(\w)")
_MULTISPACE = re.compile(r"\s+")
_NON_TEXT = re.compile(r"[^\w\s%$.,'-]")
_STANDALONE_NUM = re.compile(r"\b\d+\b")


def clean(text: str, config: dict) -> str:
    """Apply the configured normalization steps to one chunk."""
    pre = config["preprocessing"]

    if pre.get("lowercase", True):
        text = text.lower()

    text = _DEHYPHENATE.sub(r"\1\2", text)
    text = _NON_TEXT.sub(" ", text)

    # Bare numbers carry no thematic signal once separated from their unit,
    # and they inflate the vocabulary. Percentages stay because "%" survives
    # the character filter above and marks a rate.
    text = _STANDALONE_NUM.sub(" ", text)

    if pre.get("normalize_whitespace", True):
        text = _MULTISPACE.sub(" ", text)

    # Drop very short tokens, keeping any protected domain term.
    min_len = pre.get("min_token_length", 3)
    protected = {t.lower() for t in pre.get("protected_terms", [])}
    tokens = [t for t in text.split() if len(t) >= min_len or t in protected]

    return " ".join(tokens).strip()


def clean_all(texts: list[str], config: dict) -> list[str]:
    """Clean a list of chunk texts and report how much was removed."""
    cleaned = [clean(t, config) for t in texts]
    before = sum(len(t.split()) for t in texts)
    after = sum(len(t.split()) for t in cleaned)
    if before:
        log.info("Preprocessing kept %d/%d tokens (%.1f%%)",
                 after, before, 100 * after / before)
    return cleaned
