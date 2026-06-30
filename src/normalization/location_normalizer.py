"""
src/normalization/location_normalizer.py
=========================================

Normalizes the ``location`` field of a :class:`~src.models.CanonicalRecord`.

Strategy
--------
1. Split the raw location string on commas.
2. Clean each part (strip, collapse whitespace).
3. Identify and normalize the country component (last token usually).
4. Re-join into a canonical ``"City, Country"`` or
   ``"City, State, Country"`` format.

The normalizer never attempts geocoding — it is a purely textual
operation.  It stores structured components in
``record.mapping_metadata["location_components"]`` for downstream use.
"""

from __future__ import annotations

from typing import Any

from src.models import CanonicalRecord, NormalizationMethod
from src.normalization.base import BaseNormalizer
from src.normalization.country_normalizer import country_to_alpha2
from src.normalization.utils import NormalizationResult, clean_text


def normalize_location(raw: str) -> NormalizationResult:
    """
    Normalize a free-text location string.

    Performs:
    - Whitespace collapse per part
    - Country component resolution to ISO alpha-2

    Parameters
    ----------
    raw:
        Free-text location, e.g. ``"Bangalore, Karnataka, India"``.

    Returns
    -------
    NormalizationResult
        ``normalized`` is the cleaned/joined string.
        ``reason`` describes the transformation.
    """
    if not raw or not raw.strip():
        return NormalizationResult(
            original=raw, normalized=raw,
            method=NormalizationMethod.LOCATION_DECOMPOSE,
            confidence=0.0,
            reason="Empty location string.",
        )

    parts = [clean_text(p) for p in raw.split(",") if clean_text(p)]
    if not parts:
        return NormalizationResult(
            original=raw, normalized=raw,
            method=NormalizationMethod.LOCATION_DECOMPOSE,
            confidence=0.5,
            reason="No parseable parts after splitting on comma.",
        )

    # Try to resolve the country from the last part
    country_code = country_to_alpha2(parts[-1]) if parts else None

    # Re-join all cleaned parts
    rejoined = ", ".join(parts)
    changed = rejoined != raw

    return NormalizationResult(
        original=raw,
        normalized=rejoined,
        method=NormalizationMethod.LOCATION_DECOMPOSE,
        confidence=0.9 if changed else 1.0,
        reason=(
            f"Parts cleaned; country={country_code!r}"
            if country_code
            else "Parts cleaned (country unresolved)."
        ),
    )


class LocationNormalizer(BaseNormalizer):
    """
    Normalizes :attr:`~src.models.CanonicalRecord.location`.

    Also stores structured components in
    ``record.mapping_metadata["location_components"]``.

    Config Keys
    -----------
    ``max_parts`` (int):
        Maximum number of comma-separated parts to keep (default: ``3``).
    """

    def supports(self, record: CanonicalRecord) -> bool:
        return bool(record.location)

    def metadata(self) -> dict[str, Any]:
        return {
            "normalizer": self.__class__.__name__,
            "fields":     ["location"],
            "method":     NormalizationMethod.LOCATION_DECOMPOSE.value,
            "version":    "1.0.0",
        }

    def normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        return self._timed_normalize(record, self._do_normalize)

    def _do_normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        if not record.location:
            return record

        raw = record.location
        max_parts = self._config.get("max_parts", 3)
        parts = [clean_text(p) for p in raw.split(",") if clean_text(p)]
        parts = parts[:max_parts]

        # Resolve country
        country_code: str | None = None
        country_name: str | None = None
        if parts:
            country_code = country_to_alpha2(parts[-1])
            country_name = parts[-1]

        # Build location_components dict
        components: dict[str, str | None] = {"raw": raw}
        if len(parts) == 1:
            components["city"]    = parts[0]
            components["state"]   = None
            components["country"] = country_code or parts[0]
        elif len(parts) == 2:
            components["city"]    = parts[0]
            components["state"]   = None
            components["country"] = country_code or parts[1]
        else:
            components["city"]    = parts[0]
            components["state"]   = parts[1] if len(parts) >= 3 else None
            components["country"] = country_code or (parts[-1] if parts else None)

        record.mapping_metadata["location_components"] = components
        if country_code:
            record.mapping_metadata["country_code"] = country_code

        # Normalize the string
        cleaned = ", ".join(parts)
        if cleaned != raw:
            self._add_provenance(
                record,
                field="location",
                original_value=raw,
                normalized_value=cleaned,
                method=NormalizationMethod.LOCATION_DECOMPOSE,
                confidence=0.9,
                reason=f"Whitespace collapsed; parts={parts!r}; country={country_code!r}",
            )
            record.location = cleaned

        # Also normalize location inside experience entries
        for entry in record.experience:
            entry_loc = entry.get("location")
            if entry_loc and isinstance(entry_loc, str):
                result = normalize_location(entry_loc)
                if result.changed:
                    entry["location"] = result.normalized

        return record
