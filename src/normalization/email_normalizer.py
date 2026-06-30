"""
src/normalization/email_normalizer.py
======================================

Normalizes the ``emails`` field of a :class:`~src.models.CanonicalRecord`.

Operations (applied in order)
------------------------------
1. Strip surrounding whitespace.
2. Lowercase the entire address.
3. Validate structure with ``email-validator``.
4. Deduplicate the list (case-insensitive).

Invalid addresses are dropped with a WARNING log.
Valid addresses that are unchanged still appear in the result;
provenance is only written for addresses that were actually modified.
"""

from __future__ import annotations

import re
from typing import Any

from src.models import CanonicalRecord, NormalizationMethod
from src.normalization.base import BaseNormalizer
from src.normalization.utils import NormalizationResult, deduplicate

# Lightweight RFC 5322-compatible email regex used as a fallback when
# the ``email-validator`` package is not installed.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def _is_valid_email(address: str) -> bool:
    """Return ``True`` when ``address`` passes RFC validation."""
    try:
        from email_validator import validate_email, EmailNotValidError
        try:
            validate_email(address, check_deliverability=False)
            return True
        except EmailNotValidError:
            return False
    except ImportError:
        return bool(_EMAIL_RE.match(address))


def normalize_email(raw: str) -> NormalizationResult:
    """
    Normalize a single email address string.

    Parameters
    ----------
    raw:
        Raw email string as extracted by the mapper.

    Returns
    -------
    NormalizationResult
        Contains the original, the normalized value (or the original
        when invalid), and the method/confidence.
    """
    stripped = raw.strip()
    lowered  = stripped.lower()

    if not _is_valid_email(lowered):
        return NormalizationResult(
            original=raw,
            normalized=raw,
            method=NormalizationMethod.NONE,
            confidence=0.0,
            reason=f"Invalid email address: {raw!r}",
        )

    return NormalizationResult(
        original=raw,
        normalized=lowered,
        method=NormalizationMethod.EMAIL_LOWERCASE,
        confidence=1.0,
        reason="Lowercased and whitespace-stripped.",
    )


class EmailNormalizer(BaseNormalizer):
    """
    Normalizes :attr:`~src.models.CanonicalRecord.emails`.

    Config Keys
    -----------
    ``drop_invalid`` (bool):
        When ``True`` (default), invalid email addresses are removed
        from the list.  When ``False``, they are kept as-is.
    """

    def supports(self, record: CanonicalRecord) -> bool:
        return bool(record.emails)

    def metadata(self) -> dict[str, Any]:
        return {
            "normalizer": self.__class__.__name__,
            "fields":     ["emails"],
            "method":     NormalizationMethod.EMAIL_LOWERCASE.value,
            "version":    "1.0.0",
        }

    def normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        return self._timed_normalize(record, self._do_normalize)

    def _do_normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        drop_invalid = self._config.get("drop_invalid", True)
        original_emails = list(record.emails)
        normalized: list[str] = []

        for raw_email in original_emails:
            result = normalize_email(raw_email)

            if not result.changed and result.confidence == 1.0:
                # Already valid and canonical — keep without provenance noise
                normalized.append(result.normalized)
                continue

            if result.confidence == 0.0:
                # Invalid
                if not drop_invalid:
                    normalized.append(raw_email)
                self._log.warning(
                    "Invalid email dropped",
                    extra={
                        "raw_email": raw_email,
                        "source":    record.source_label,
                    },
                )
                if result.changed or drop_invalid:
                    self._add_provenance(
                        record,
                        field="emails",
                        original_value=raw_email,
                        normalized_value=None if drop_invalid else raw_email,
                        method=NormalizationMethod.NONE,
                        confidence=0.0,
                        reason=result.reason,
                    )
                continue

            normalized.append(result.normalized)
            self._add_provenance(
                record,
                field="emails",
                original_value=result.original,
                normalized_value=result.normalized,
                method=result.method,
                confidence=result.confidence,
                reason=result.reason,
            )

        # Deduplicate (case-insensitive)
        record.emails = deduplicate(normalized, key=str.lower)
        return record
