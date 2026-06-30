"""
src/normalization/base.py
==========================

Abstract base class for every field-level normalizer.

Each concrete normalizer:
1. Operates on specific fields of a :class:`~src.models.CanonicalRecord`.
2. Returns the **same** (mutated) record — records are mutable at
   this stage.
3. Appends a :class:`~src.models.Provenance` entry for every field it
   changes.
4. Never raises — unknown / unparseable values are left unchanged and
   a WARNING is logged.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from src.logging_config import get_logger
from src.models import (
    CanonicalRecord,
    NormalizationMethod,
    ProcessingStage,
    Provenance,
    SourceType,
)


class BaseNormalizer(ABC):
    """
    Abstract base for all field-level normalizers.

    Sub-classes must implement:

    - :meth:`normalize`  — mutate the relevant fields of ``record``
    - :meth:`supports`   — return ``True`` when the record has data to normalize
    - :meth:`metadata`   — return a static descriptor dict

    Parameters
    ----------
    config:
        Optional normalizer-specific configuration dict.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config: dict[str, Any] = config or {}
        self._log = get_logger(self.__class__.__module__)

    # ── Abstract interface ────────────────────────────────────

    @abstractmethod
    def normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        """
        Normalize the field(s) this normalizer is responsible for.

        Must never raise.  Leave fields unchanged and log a WARNING
        when a value cannot be normalized.

        Parameters
        ----------
        record:
            Mutable :class:`~src.models.CanonicalRecord` to normalize.

        Returns
        -------
        CanonicalRecord
            The same ``record`` object, fields updated in-place.
        """

    @abstractmethod
    def supports(self, record: CanonicalRecord) -> bool:
        """
        Return ``True`` when this normalizer has work to do on ``record``.

        A normalizer that handles ``emails`` should return ``True`` only
        when ``record.emails`` is non-empty.
        """

    @abstractmethod
    def metadata(self) -> dict[str, Any]:
        """
        Return a static descriptor dict.

        Should include at minimum:
        ``normalizer``, ``fields``, ``method``, ``version``.
        """

    # ── Helpers for sub-classes ───────────────────────────────

    def _add_provenance(
        self,
        record: CanonicalRecord,
        *,
        field: str,
        original_value: Any,
        normalized_value: Any,
        method: NormalizationMethod,
        confidence: float = 1.0,
        reason: str | None = None,
    ) -> None:
        """
        Append a :class:`~src.models.Provenance` entry to ``record``
        for a single field normalization.

        Parameters
        ----------
        record:
            The record being normalized.
        field:
            Canonical field name that was changed.
        original_value:
            Value before normalization.
        normalized_value:
            Value after normalization.
        method:
            The :class:`~src.models.NormalizationMethod` applied.
        confidence:
            Confidence score (default ``1.0``).
        reason:
            Optional human-readable reason string.
        """
        prov = Provenance(
            field=field,
            source=record.source_type,
            method=method,
            original_value=original_value,
            normalized_value=normalized_value,
            processing_stage=ProcessingStage.NORMALIZATION,
            confidence=confidence,
            reason=reason or f"[{method.value}] {field!r} normalized",
            timestamp=datetime.now(tz=timezone.utc),
        )
        record.provenance.append(prov)

    def _timed_normalize(
        self,
        record: CanonicalRecord,
        impl: Any,
    ) -> CanonicalRecord:
        """
        Timing wrapper — calls ``impl(record)`` and logs structured
        telemetry (normalizer name, duration).

        Parameters
        ----------
        record:
            The :class:`~src.models.CanonicalRecord` being normalized.
        impl:
            Callable ``(CanonicalRecord) -> CanonicalRecord``.
        """
        start = time.perf_counter()
        result = impl(record)
        duration_ms = (time.perf_counter() - start) * 1000
        self._log.debug(
            "Normalization complete",
            extra={
                "normalizer":  self.__class__.__name__,
                "source":      record.source_label,
                "duration_ms": round(duration_ms, 3),
            },
        )
        return result
