"""
src/merge/utils.py
===================

Shared utility functions for the merge layer.

Nothing in this module imports from other merge sub-modules — it is a
pure leaf dependency.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, TypeVar

T = TypeVar("T")


# ── Text helpers ──────────────────────────────────────────────────


def clean_lower(s: str | None) -> str:
    """Strip, collapse whitespace, lowercase."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.strip()).lower()


def normalize_key(s: str | None) -> str:
    """
    Create a normalised string suitable for equality comparison.

    Performs: NFC → lowercase → strip punctuation → collapse spaces.
    """
    if not s:
        return ""
    nfc = unicodedata.normalize("NFC", s)
    lowered = nfc.lower().strip()
    no_punct = re.sub(r"[^\w\s]", "", lowered)
    return re.sub(r"\s+", " ", no_punct).strip()


def email_key(email: str) -> str:
    """Normalised email key for deduplication."""
    return email.strip().lower()


def phone_key(phone: str) -> str:
    """Strip non-digit non-plus chars for phone deduplication."""
    cleaned = re.sub(r"[^\d+]", "", phone.strip())
    return cleaned or phone.strip().lower()


def url_key(url: str) -> str:
    """Lowercase URL key; strip trailing slash."""
    return url.strip().lower().rstrip("/")


def github_login_from_url(url: str | None) -> str | None:
    """Extract GitHub login from a GitHub URL."""
    if not url:
        return None
    m = re.match(r"https?://(?:www\.)?github\.com/([a-zA-Z0-9\-]+)", url, re.IGNORECASE)
    return m.group(1).lower() if m else None


def linkedin_handle_from_url(url: str | None) -> str | None:
    """Extract LinkedIn handle from a LinkedIn URL."""
    if not url:
        return None
    m = re.match(r"https?://(?:www\.)?linkedin\.com/in/([a-zA-Z0-9\-_%]+)", url, re.IGNORECASE)
    return m.group(1).lower() if m else None


# ── List helpers ──────────────────────────────────────────────────


def union_lists(*lists: list[T], key: Any = None) -> list[T]:
    """
    Return the ordered union of multiple lists.

    Parameters
    ----------
    *lists:
        Lists to merge.
    key:
        Optional callable used to extract the comparison key per element.
        Defaults to identity.

    Returns
    -------
    list[T]
        Items from all lists with duplicates removed.  Order: first
        occurrence wins (earlier lists take precedence).
    """
    seen: set = set()
    result: list[T] = []
    for lst in lists:
        for item in lst:
            k = key(item) if key else item
            if k not in seen:
                seen.add(k)
                result.append(item)
    return result


def deduplicate_strings(values: list[str], *, key=str.lower) -> list[str]:
    """Deduplicate a list of strings using the given key function."""
    seen: set[str] = set()
    result: list[str] = []
    for v in values:
        k = key(v)
        if k not in seen:
            seen.add(k)
            result.append(v)
    return result


# ── Confidence helpers ────────────────────────────────────────────


def multi_source_confidence(values: list[Any], weights: list[float]) -> float:
    """
    Compute confidence from a set of source values and source weights.

    If all values agree → high confidence.
    If values disagree → penalised confidence.

    Parameters
    ----------
    values:
        Normalised values from each source.
    weights:
        Reliability weight per source (same order as ``values``).

    Returns
    -------
    float
        Confidence score in ``[0.0, 1.0]``.
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return float(weights[0]) if weights else 0.5

    total_weight = sum(weights) or 1.0
    # Find most common value by weighted vote
    vote: dict[Any, float] = {}
    for v, w in zip(values, weights):
        k = str(v).lower().strip() if isinstance(v, str) else v
        vote[k] = vote.get(k, 0.0) + w

    winner_weight = max(vote.values())
    agreement_ratio = winner_weight / total_weight
    # Scale: full agreement (1.0) → confidence = weighted mean;
    # half agreement → penalty
    return min(1.0, max(0.0, agreement_ratio * (winner_weight / total_weight)))


def freshness_score(timestamps: list[datetime]) -> float:
    """
    Compute a freshness score based on how recent the extraction timestamps are.

    Decays exponentially with a half-life of
    :data:`~src.constants.FRESHNESS_HALF_LIFE_DAYS` days.

    Parameters
    ----------
    timestamps:
        UTC-aware extraction datetimes.

    Returns
    -------
    float
        Score in ``[0.0, 1.0]``.  1.0 = all extracted today.
    """
    from src.constants import FRESHNESS_HALF_LIFE_DAYS
    if not timestamps:
        return 0.0
    now = datetime.now(tz=timezone.utc)
    scores = []
    for ts in timestamps:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - ts).total_seconds() / 86400)
        score = math.exp(-math.log(2) * age_days / FRESHNESS_HALF_LIFE_DAYS)
        scores.append(score)
    return sum(scores) / len(scores)


def completeness_score(profile_dict: dict[str, Any], expected_fields: list[str]) -> float:
    """
    Fraction of expected fields that are non-null / non-empty.

    Parameters
    ----------
    profile_dict:
        Dictionary of canonical field → value.
    expected_fields:
        List of canonical field names that are expected to be present.

    Returns
    -------
    float
        Score in ``[0.0, 1.0]``.
    """
    if not expected_fields:
        return 1.0
    populated = 0
    for f in expected_fields:
        v = profile_dict.get(f)
        if v is not None and v != "" and v != [] and v != {}:
            populated += 1
    return populated / len(expected_fields)


# ── Date helpers ──────────────────────────────────────────────────


def parse_year_month(date_str: str | None) -> tuple[int, int] | None:
    """
    Parse an ISO date string to (year, month) for sorting.

    Handles:
    - ``"2022-06-15"`` → ``(2022, 6)``
    - ``"2022-06"``    → ``(2022, 6)``
    - ``"2022"``       → ``(2022, 0)``

    Returns
    -------
    tuple[int, int] | None
        ``(year, month)`` or ``None`` when unparseable.
    """
    if not date_str:
        return None
    parts = date_str.split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 0
        return (year, month)
    except (ValueError, IndexError):
        return None


def experience_sort_key(entry: dict[str, Any]) -> tuple[int, int]:
    """Sort key for experience entries — most recent first."""
    start = parse_year_month(entry.get("start_date"))
    return start or (0, 0)


def education_sort_key(entry: dict[str, Any]) -> tuple[int, int]:
    """Sort key for education entries — most recent first."""
    end = parse_year_month(entry.get("end_date"))
    return end or (0, 0)
