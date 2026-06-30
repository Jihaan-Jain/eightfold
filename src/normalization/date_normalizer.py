"""
src/normalization/date_normalizer.py
=====================================

Normalizes date strings found in experience / education entries and
any standalone date fields on a :class:`~src.models.CanonicalRecord`.

Accepted Input Formats
-----------------------
- ``"Jan 2024"``       → ``"2024-01"``
- ``"January 2024"``   → ``"2024-01"``
- ``"2024-01"``        → ``"2024-01"``
- ``"01/2024"``        → ``"2024-01"``
- ``"2024/01"``        → ``"2024-01"``
- ``"2024-01-15"``     → ``"2024-01-15"``
- ``"15 Jan 2024"``    → ``"2024-01-15"``
- ``"2024"``           → ``"2024"``
- ``"Present"``        → ``None``  (sentinel — omit end_date)
- ``"Current"``        → ``None``
- ``"Now"``            → ``None``

Output Formats
--------------
- Full date available → ``"YYYY-MM-DD"``
- Month + year only   → ``"YYYY-MM"``
- Year only           → ``"YYYY"``
- Present/Current     → ``None``
"""

from __future__ import annotations

import re
from typing import Any

from src.models import CanonicalRecord, NormalizationMethod
from src.normalization.base import BaseNormalizer
from src.normalization.utils import NormalizationResult

# Sentinel values that mean "end_date is the present"
_PRESENT_TOKENS: frozenset[str] = frozenset(
    {"present", "current", "now", "ongoing", "today", "till date",
     "till now", "to date", "to present", "–", "—", "-"}
)

# Regex: year-only strings
_YEAR_ONLY_RE = re.compile(r"^\s*(\d{4})\s*$")

# Regex: MM/YYYY or YYYY/MM
_SLASH_DATE_RE = re.compile(
    r"^\s*(?:(\d{1,2})/(\d{4})|(\d{4})/(\d{1,2}))\s*$"
)


def _parse_with_dateutil(raw: str) -> "tuple[int,int,int] | None":
    """
    Try to parse ``raw`` with ``dateutil.parser.parse``.

    Returns
    -------
    tuple[int,int,int] | None
        ``(year, month, day)`` or ``None`` on failure.
    """
    try:
        from dateutil import parser as du_parser
        from dateutil.parser import ParserError
        dt = du_parser.parse(raw, default=None)  # type: ignore[call-arg]
        if dt is None:
            return None
        return (dt.year, dt.month, dt.day)
    except Exception:
        return None


def normalize_date(raw: str) -> NormalizationResult:
    """
    Normalize a single date string.

    Parameters
    ----------
    raw:
        Raw date string from a source record.

    Returns
    -------
    NormalizationResult
        ``normalized`` is ``None`` for Present/Current, an ISO string
        otherwise.  ``confidence=0.0`` when the string cannot be parsed.
    """
    if not raw or not raw.strip():
        return NormalizationResult(
            original=raw, normalized=raw,
            method=NormalizationMethod.NONE, confidence=0.0,
            reason="Empty date string.",
        )

    stripped = raw.strip()

    # ── Present / Current ─────────────────────────────────────
    if stripped.lower() in _PRESENT_TOKENS:
        return NormalizationResult(
            original=raw, normalized=None,
            method=NormalizationMethod.DATE_ISO8601, confidence=1.0,
            reason="Sentinel 'present/current' mapped to None.",
        )

    # ── Year only ─────────────────────────────────────────────
    m = _YEAR_ONLY_RE.match(stripped)
    if m:
        return NormalizationResult(
            original=raw, normalized=m.group(1),
            method=NormalizationMethod.DATE_ISO8601, confidence=0.9,
            reason="Year-only date.",
        )

    # ── MM/YYYY or YYYY/MM ────────────────────────────────────
    m = _SLASH_DATE_RE.match(stripped)
    if m:
        if m.group(1) and m.group(2):
            month, year = int(m.group(1)), int(m.group(2))
        else:
            year, month = int(m.group(3)), int(m.group(4))
        if 1 <= month <= 12 and 1900 <= year <= 2100:
            normalized = f"{year:04d}-{month:02d}"
            return NormalizationResult(
                original=raw, normalized=normalized,
                method=NormalizationMethod.DATE_ISO8601, confidence=0.95,
                reason="MM/YYYY or YYYY/MM pattern.",
            )

    # ── YYYY-MM (already ISO partial) ────────────────────────
    if re.match(r"^\d{4}-\d{2}$", stripped):
        return NormalizationResult(
            original=raw, normalized=stripped,
            method=NormalizationMethod.DATE_ISO8601, confidence=1.0,
            reason="Already ISO YYYY-MM.",
        )

    # ── Full ISO date ─────────────────────────────────────────
    if re.match(r"^\d{4}-\d{2}-\d{2}$", stripped):
        return NormalizationResult(
            original=raw, normalized=stripped,
            method=NormalizationMethod.DATE_ISO8601, confidence=1.0,
            reason="Already ISO YYYY-MM-DD.",
        )

    # ── dateutil fallback ─────────────────────────────────────
    parsed = _parse_with_dateutil(stripped)
    if parsed:
        year, month, day = parsed
        if 1900 <= year <= 2100:
            # Determine precision: if dateutil defaulted day=1 for strings
            # like "Jan 2024", we output YYYY-MM, not YYYY-MM-01.
            raw_has_day = bool(re.search(r"\b\d{1,2}\b", stripped))
            if raw_has_day and day != 1:
                normalized = f"{year:04d}-{month:02d}-{day:02d}"
            else:
                normalized = f"{year:04d}-{month:02d}"
            return NormalizationResult(
                original=raw, normalized=normalized,
                method=NormalizationMethod.DATE_ISO8601, confidence=0.85,
                reason="Parsed via python-dateutil.",
            )

    return NormalizationResult(
        original=raw, normalized=raw,
        method=NormalizationMethod.NONE, confidence=0.0,
        reason=f"Could not parse date: {raw!r}",
    )


def _normalize_entry_dates(entry: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize ``start_date`` and ``end_date`` in an experience / education
    entry dict.  Returns a **new** dict with updated date fields.
    """
    updated = dict(entry)
    for key in ("start_date", "end_date"):
        raw = updated.get(key)
        if raw is None or not isinstance(raw, str):
            continue
        result = normalize_date(raw)
        if result.confidence > 0.0:
            updated[key] = result.normalized
    return updated


class DateNormalizer(BaseNormalizer):
    """
    Normalizes date strings inside ``experience`` and ``education``
    entry dicts (``start_date``, ``end_date`` keys).

    Config Keys
    -----------
    ``strict`` (bool):
        When ``True``, entries whose ``start_date`` cannot be parsed are
        logged at WARNING instead of DEBUG.  Default ``True``.
    """

    def supports(self, record: CanonicalRecord) -> bool:
        return bool(record.experience or record.education)

    def metadata(self) -> dict[str, Any]:
        return {
            "normalizer": self.__class__.__name__,
            "fields":     ["experience[].start_date", "experience[].end_date",
                           "education[].start_date",  "education[].end_date"],
            "method":     NormalizationMethod.DATE_ISO8601.value,
            "version":    "1.0.0",
        }

    def normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        return self._timed_normalize(record, self._do_normalize)

    def _do_normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        for section_name in ("experience", "education"):
            entries: list[dict] = getattr(record, section_name)
            normalized_entries: list[dict] = []
            for entry in entries:
                updated = _normalize_entry_dates(entry)
                if updated != entry:
                    self._add_provenance(
                        record,
                        field=section_name,
                        original_value={k: entry.get(k) for k in ("start_date", "end_date")},
                        normalized_value={k: updated.get(k) for k in ("start_date", "end_date")},
                        method=NormalizationMethod.DATE_ISO8601,
                        confidence=0.9,
                        reason="start_date/end_date normalized to ISO 8601.",
                    )
                normalized_entries.append(updated)
            setattr(record, section_name, normalized_entries)
        return record
