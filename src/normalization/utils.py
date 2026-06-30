"""
src/normalization/utils.py
===========================

Shared utility functions for the normalization layer.

Provides
--------
- :func:`clean_text`        — strip and collapse whitespace
- :func:`ascii_normalize`   — Unicode NFC + optional ASCII transliteration
- :func:`deduplicate`       — order-preserving list deduplication
- :func:`similarity`        — token-sort ratio via RapidFuzz
- :class:`NormalizationResult` — typed result container
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from src.models import NormalizationMethod

# ── whitespace collapse ────────────────────────────────────────
_MULTI_WS = re.compile(r"\s+")


def clean_text(value: str) -> str:
    """
    Strip leading/trailing whitespace and collapse internal runs of
    whitespace to a single space.

    Parameters
    ----------
    value:
        Raw input string.

    Returns
    -------
    str
        Cleaned string.
    """
    return _MULTI_WS.sub(" ", value).strip()


def ascii_normalize(value: str, *, transliterate: bool = False) -> str:
    """
    Apply Unicode NFC normalisation to ``value``.

    When ``transliterate=True``, characters outside ASCII are converted
    to their closest ASCII equivalent (e.g. ``é`` → ``e``) using
    NFKD decomposition + ASCII encoding.

    Parameters
    ----------
    value:
        Raw Unicode string.
    transliterate:
        When ``True``, strip non-ASCII codepoints.  Default ``False``.

    Returns
    -------
    str
        NFC-normalised string (optionally transliterated).
    """
    normalised = unicodedata.normalize("NFC", value)
    if not transliterate:
        return normalised
    nfkd = unicodedata.normalize("NFKD", normalised)
    return nfkd.encode("ascii", errors="ignore").decode("ascii")


def deduplicate(items: list[Any], *, key: Any = None) -> list[Any]:
    """
    Remove duplicates from ``items`` while preserving insertion order.

    Parameters
    ----------
    items:
        Input list, possibly containing duplicates.
    key:
        Optional callable ``(item) -> hashable`` used for equality
        comparison.  When ``None``, items are compared directly.

    Returns
    -------
    list[Any]
        Deduplicated list in original order.
    """
    seen: set = set()
    result: list[Any] = []
    for item in items:
        k = key(item) if key else item
        if k not in seen:
            seen.add(k)
            result.append(item)
    return result


def similarity(a: str, b: str) -> float:
    """
    Compute the RapidFuzz token-sort ratio between two strings.

    The score is normalised to ``[0.0, 1.0]`` (RapidFuzz returns
    ``[0, 100]`` by default).

    Parameters
    ----------
    a, b:
        Strings to compare.

    Returns
    -------
    float
        Similarity in ``[0.0, 1.0]``.  ``1.0`` = identical.
    """
    try:
        from rapidfuzz import fuzz
        return fuzz.token_sort_ratio(a, b) / 100.0
    except ImportError:
        # Fallback: simple char-set Jaccard similarity
        sa, sb = set(a.lower().split()), set(b.lower().split())
        if not sa and not sb:
            return 1.0
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)


# ================================================================
# NormalizationResult
# ================================================================


@dataclass
class NormalizationResult:
    """
    Typed result container returned by every field-level normalizer.

    Attributes
    ----------
    original:
        The raw value before normalization.
    normalized:
        The value after normalization.  Equals ``original`` when
        ``changed=False``.
    method:
        The :class:`~src.models.NormalizationMethod` that produced this
        result.
    confidence:
        Confidence in the normalized value (``[0.0, 1.0]``).
    changed:
        ``True`` when ``normalized != original``.
    reason:
        Optional human-readable explanation.
    """

    original:   Any
    normalized: Any
    method:     NormalizationMethod = NormalizationMethod.NONE
    confidence: float = 1.0
    changed:    bool  = False
    reason:     str | None = None

    def __post_init__(self) -> None:
        self.changed = self.original != self.normalized
