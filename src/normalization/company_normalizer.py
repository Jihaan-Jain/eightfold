"""
src/normalization/company_normalizer.py
========================================

Normalizes ``current_company`` and company fields inside
``experience`` entries on a :class:`~src.models.CanonicalRecord`.

Operations (applied in order)
------------------------------
1. Strip surrounding whitespace.
2. Collapse internal whitespace runs.
3. Strip leading ``@`` (GitHub convention: ``"@Eightfold"`` → ``"Eightfold"``).
4. Remove legal entity suffixes (LLC, Inc., Ltd., Corp., etc.).
5. Collapse multiple spaces introduced by suffix removal.
6. Title-case the result.
7. Trim again.

The normalized company name is used for display and downstream grouping
only — it is not used for deduplication or identity resolution.

Legal Suffixes Removed
-----------------------
::

    LLC / L.L.C.         LLP / L.L.P.
    Inc / Inc.           Incorporated
    Corp / Corp.         Corporation
    Ltd / Ltd.           Limited
    Co / Co.             Company
    PLC / P.L.C.
    GmbH                 AG / A.G.
    S.A.                 S.A.S.
    B.V.                 N.V.
    Pvt / Pvt. Ltd.
    Private Limited
"""

from __future__ import annotations

import re
from typing import Any

from src.models import CanonicalRecord, NormalizationMethod
from src.normalization.base import BaseNormalizer
from src.normalization.utils import NormalizationResult, clean_text

# Legal suffix patterns to strip (case-insensitive, trailing position)
_SUFFIX_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r",?\s*" + p + r"\.?\s*$", re.IGNORECASE)
    for p in [
        r"private limited",
        r"pvt\.?\s*ltd",
        r"l\.l\.c",
        r"l\.l\.p",
        r"p\.l\.c",
        r"a\.g",
        r"s\.a\.s",
        r"s\.a",
        r"b\.v",
        r"n\.v",
        r"llc",
        r"llp",
        r"plc",
        r"incorporated",
        r"corporation",
        r"limited",
        r"company",
        r"inc",
        r"corp",
        r"ltd",
        r"gmbh",
        r"ag",
        r"co",
    ]
]

# Patterns that should NOT be stripped (false positive guards)
_FALSE_POSITIVE_NAMES: frozenset[str] = frozenset(
    {"co", "ag", "sa"}  # very short — only strip when not the full name
)


def _strip_legal_suffix(name: str) -> str:
    """
    Strip legal entity suffixes from ``name``.

    Applies all patterns in :data:`_SUFFIX_PATTERNS` iteratively.
    Stops when no pattern matches.

    Parameters
    ----------
    name:
        Company name (already cleaned).

    Returns
    -------
    str
        Name with legal suffixes removed.
    """
    previous = None
    current = name
    while current != previous:
        previous = current
        for pat in _SUFFIX_PATTERNS:
            m = pat.search(current)
            if m and m.start() > 0:  # don't strip if suffix IS the whole name
                current = current[: m.start()].strip().rstrip(",").strip()
    return current


def normalize_company(raw: str) -> NormalizationResult:
    """
    Normalize a single company name string.

    Parameters
    ----------
    raw:
        Raw company name as captured by the mapper.

    Returns
    -------
    NormalizationResult
        ``normalized`` is the cleaned company name.
    """
    if not raw or not raw.strip():
        return NormalizationResult(
            original=raw, normalized=raw,
            method=NormalizationMethod.COMPANY_STRIP_SUFFIX,
            confidence=0.0, reason="Empty company string.",
        )

    # Strip @ prefix (GitHub)
    cleaned = raw.strip().lstrip("@").strip()

    # Collapse whitespace
    cleaned = clean_text(cleaned)

    # Strip legal suffixes
    stripped = _strip_legal_suffix(cleaned)

    # Collapse whitespace again after suffix removal
    stripped = clean_text(stripped) if stripped else cleaned

    # Title-case
    titled = stripped.title() if stripped else cleaned.title()

    # Guard: if stripping produced empty, fall back
    normalized = titled if titled else cleaned.title()

    return NormalizationResult(
        original=raw,
        normalized=normalized,
        method=NormalizationMethod.COMPANY_STRIP_SUFFIX,
        confidence=0.9,
        reason=f"Legal suffix stripped; @-prefix removed; title-cased.",
    )


class CompanyNormalizer(BaseNormalizer):
    """
    Normalizes company name fields on a
    :class:`~src.models.CanonicalRecord`.

    Fields normalized:
    - ``current_company``
    - ``experience[i].company``

    Config Keys
    -----------
    ``strip_suffixes`` (bool):
        Enable legal suffix removal.  Default ``True``.
    ``title_case`` (bool):
        Apply title-casing after normalization.  Default ``True``.
    """

    def supports(self, record: CanonicalRecord) -> bool:
        return bool(
            record.current_company
            or any(e.get("company") for e in record.experience)
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "normalizer": self.__class__.__name__,
            "fields":     ["current_company", "experience[].company"],
            "method":     NormalizationMethod.COMPANY_STRIP_SUFFIX.value,
            "version":    "1.0.0",
        }

    def normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        return self._timed_normalize(record, self._do_normalize)

    def _do_normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        strip_suffixes = self._config.get("strip_suffixes", True)
        title_case     = self._config.get("title_case", True)

        # ── current_company ───────────────────────────────────
        if record.current_company:
            raw = record.current_company
            if strip_suffixes:
                result = normalize_company(raw)
            else:
                cleaned = clean_text(raw.lstrip("@").strip())
                normalized = cleaned.title() if title_case else cleaned
                result = NormalizationResult(
                    original=raw, normalized=normalized,
                    method=NormalizationMethod.COMPANY_STRIP_SUFFIX,
                    confidence=0.8, reason="Cleaned only (suffix stripping disabled).",
                )

            if result.changed and result.confidence > 0.0:
                record.current_company = result.normalized
                self._add_provenance(
                    record,
                    field="current_company",
                    original_value=result.original,
                    normalized_value=result.normalized,
                    method=result.method,
                    confidence=result.confidence,
                    reason=result.reason,
                )

        # ── experience[].company ──────────────────────────────
        for entry in record.experience:
            raw_co = entry.get("company")
            if raw_co and isinstance(raw_co, str):
                if strip_suffixes:
                    result = normalize_company(raw_co)
                else:
                    cleaned = clean_text(raw_co.lstrip("@").strip())
                    result = NormalizationResult(
                        original=raw_co, normalized=cleaned,
                        method=NormalizationMethod.COMPANY_STRIP_SUFFIX,
                        confidence=0.8, reason="Cleaned only.",
                    )
                if result.changed and result.confidence > 0.0:
                    entry["company"] = result.normalized

        return record
