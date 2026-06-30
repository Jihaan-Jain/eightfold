"""
src/normalization/phone_normalizer.py
======================================

Normalizes the ``phones`` field of a :class:`~src.models.CanonicalRecord`.

Strategy
--------
1. Parse each phone string with ``phonenumbers``.
2. If parsing without a region fails, infer the country from
   ``record.location`` (e.g. ``"Bangalore, India"`` → ``"IN"``).
3. Format to E.164 (e.g. ``+14155552671``).
4. Deduplicate the result list.
5. Invalid / unparseable phones are kept unchanged with a WARNING.

Country Inference
-----------------
The location string is scanned for known country names / codes using
:func:`~src.normalization.country_normalizer.country_to_alpha2` so
that phone numbers without a ``+`` prefix can still be parsed correctly.
"""

from __future__ import annotations

import re
from typing import Any

from src.models import CanonicalRecord, NormalizationMethod
from src.normalization.base import BaseNormalizer
from src.normalization.utils import NormalizationResult, deduplicate

# Characters that are legal inside a phone number string
_PHONE_CLEAN_RE = re.compile(r"[^\d+\s\-().xX#,]")


def _infer_region(location: str | None) -> str | None:
    """
    Attempt to infer an ISO 3166-1 alpha-2 region code from a free-text
    location string.

    Parameters
    ----------
    location:
        Free-text location, e.g. ``"Bangalore, India"`` or ``"US"``.

    Returns
    -------
    str | None
        Two-letter region code (e.g. ``"IN"``) or ``None``.
    """
    if not location:
        return None
    try:
        from src.normalization.country_normalizer import country_to_alpha2
        # Try the last comma-separated token (usually country)
        parts = [p.strip() for p in location.split(",")]
        for part in reversed(parts):
            code = country_to_alpha2(part)
            if code:
                return code
    except Exception:
        pass
    return None


def normalize_phone(
    raw: str,
    *,
    default_region: str | None = None,
) -> NormalizationResult:
    """
    Normalize a single phone number string to E.164.

    Parameters
    ----------
    raw:
        Raw phone string as captured by the mapper.
    default_region:
        ISO 3166-1 alpha-2 region code used when the number has no
        country prefix.  E.g. ``"US"``, ``"IN"``.

    Returns
    -------
    NormalizationResult
        ``normalized`` is the E.164 string on success, or the original
        ``raw`` on failure.
    """
    try:
        import phonenumbers
    except ImportError:
        return NormalizationResult(
            original=raw,
            normalized=raw,
            method=NormalizationMethod.NONE,
            confidence=0.0,
            reason="phonenumbers package not installed.",
        )

    cleaned = _PHONE_CLEAN_RE.sub("", raw).strip()
    if not cleaned:
        return NormalizationResult(
            original=raw, normalized=raw,
            method=NormalizationMethod.NONE, confidence=0.0,
            reason="Empty after cleaning.",
        )

    # Attempt parse with supplied region
    regions_to_try: list[str | None] = [None, default_region]
    # Also try with explicit None (handles numbers with + prefix)
    for region in dict.fromkeys(regions_to_try):  # deduplicated, order-preserved
        try:
            parsed = phonenumbers.parse(cleaned, region)
            if phonenumbers.is_valid_number(parsed):
                e164 = phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
                return NormalizationResult(
                    original=raw,
                    normalized=e164,
                    method=NormalizationMethod.PHONE_E164,
                    confidence=1.0,
                    reason=f"E.164 via region={region!r}.",
                )
        except Exception:
            continue

    return NormalizationResult(
        original=raw, normalized=raw,
        method=NormalizationMethod.NONE, confidence=0.0,
        reason=f"Could not parse phone: {raw!r}",
    )


class PhoneNormalizer(BaseNormalizer):
    """
    Normalizes :attr:`~src.models.CanonicalRecord.phones`.

    Config Keys
    -----------
    ``default_region`` (str):
        Hard-coded fallback region code (e.g. ``"US"``).  The normalizer
        first tries to infer region from ``record.location``.
    ``drop_invalid`` (bool):
        Drop unparseable phone numbers.  Default ``False`` (kept as-is).
    """

    def supports(self, record: CanonicalRecord) -> bool:
        return bool(record.phones)

    def metadata(self) -> dict[str, Any]:
        return {
            "normalizer": self.__class__.__name__,
            "fields":     ["phones"],
            "method":     NormalizationMethod.PHONE_E164.value,
            "version":    "1.0.0",
        }

    def normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        return self._timed_normalize(record, self._do_normalize)

    def _do_normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        drop_invalid   = self._config.get("drop_invalid", False)
        config_region  = self._config.get("default_region")
        inferred_region = _infer_region(record.location)
        default_region  = config_region or inferred_region

        original_phones = list(record.phones)
        normalized: list[str] = []

        for raw_phone in original_phones:
            result = normalize_phone(raw_phone, default_region=default_region)

            if result.confidence == 0.0:
                self._log.warning(
                    "Phone not parseable",
                    extra={
                        "raw_phone": raw_phone,
                        "reason":    result.reason,
                        "source":    record.source_label,
                    },
                )
                if not drop_invalid:
                    normalized.append(raw_phone)
                self._add_provenance(
                    record,
                    field="phones",
                    original_value=raw_phone,
                    normalized_value=None if drop_invalid else raw_phone,
                    method=NormalizationMethod.NONE,
                    confidence=0.0,
                    reason=result.reason,
                )
                continue

            if result.changed:
                self._add_provenance(
                    record,
                    field="phones",
                    original_value=result.original,
                    normalized_value=result.normalized,
                    method=result.method,
                    confidence=result.confidence,
                    reason=result.reason,
                )

            normalized.append(result.normalized)

        record.phones = deduplicate(normalized)
        return record
