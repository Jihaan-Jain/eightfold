"""
src/mapping/base.py
====================

Abstract base class for all mapper implementations.

Every concrete mapper must:

1. Implement :meth:`BaseMapper.supports` — accept or reject a
   :class:`~src.models.RawRecord` before mapping is attempted.
2. Implement :meth:`BaseMapper.map` — return a
   :class:`~src.models.CanonicalRecord`.
3. Implement :meth:`BaseMapper.metadata` — return a static dict
   describing the mapper.

The base class provides:

- :attr:`_registry` — shared :class:`~src.mapping.field_registry.FieldRegistry`
- :attr:`_log` — pre-configured structured logger
- :meth:`_make_canonical` — factory method for a blank
  :class:`~src.models.CanonicalRecord` seeded with identity fields
- :meth:`_record_unknown` — log and track unmapped raw fields
- :meth:`_timed_map` — timing wrapper for structured telemetry
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from src.logging_config import get_logger
from src.mapping.field_registry import REGISTRY, FieldRegistry
from src.models import CanonicalRecord, RawRecord, SourceType


class BaseMapper(ABC):
    """
    Abstract base for all source-specific mappers.

    Sub-classes must implement:

    - :meth:`supports`  — return ``True`` for the source types handled
    - :meth:`map`       — perform the actual mapping
    - :meth:`metadata`  — return a static descriptor dict

    Sub-classes may override :meth:`validate` to add pre-mapping
    source-specific validation.

    Parameters
    ----------
    registry:
        :class:`~src.mapping.field_registry.FieldRegistry` instance.
        Defaults to the module-level ``REGISTRY`` singleton.
    config:
        Optional mapper configuration dict.  Keys are mapper-specific.
    """

    def __init__(
        self,
        registry: FieldRegistry | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._registry: FieldRegistry = registry or REGISTRY
        self._config: dict[str, Any] = config or {}
        self._log = get_logger(self.__class__.__module__)

    # ── Abstract interface ────────────────────────────────────

    @abstractmethod
    def supports(self, record: RawRecord) -> bool:
        """
        Return ``True`` when this mapper can handle ``record``.

        Parameters
        ----------
        record:
            The :class:`~src.models.RawRecord` to test.
        """

    @abstractmethod
    def map(self, record: RawRecord) -> CanonicalRecord:
        """
        Convert ``record`` to a :class:`~src.models.CanonicalRecord`.

        Must never raise.  Unknown fields are logged as warnings and
        stored in :attr:`~src.models.CanonicalRecord.unknown_fields`.

        Parameters
        ----------
        record:
            A :class:`~src.models.RawRecord` for which
            :meth:`supports` returned ``True``.

        Returns
        -------
        CanonicalRecord
            Populated canonical record with provenance entries.
        """

    @abstractmethod
    def metadata(self) -> dict[str, Any]:
        """
        Return a static descriptor dict for this mapper.

        Should include at minimum:
        ``extractor``, ``source_type``, ``version``.
        """

    # ── Optional override ─────────────────────────────────────

    def validate(self, record: RawRecord) -> bool:
        """
        Optional pre-mapping validation.

        Return ``False`` to skip mapping for this record (the caller
        should log a warning and return an empty/stub CanonicalRecord).

        Default implementation always returns ``True``.
        """
        return True

    # ── Helpers for sub-classes ───────────────────────────────

    def _make_canonical(self, record: RawRecord) -> CanonicalRecord:
        """
        Create a blank :class:`~src.models.CanonicalRecord` seeded
        with identity fields from ``record``.

        Parameters
        ----------
        record:
            The source :class:`~src.models.RawRecord`.

        Returns
        -------
        CanonicalRecord
            Empty record ready for field population.
        """
        return CanonicalRecord(
            source_record_id=record.record_id,
            source_type=record.source_type,
            source_label=record.source,
        )

    def _record_unknown(
        self,
        canonical: CanonicalRecord,
        raw_key: str,
    ) -> None:
        """
        Record a raw field name as unknown and emit a structured warning.

        Parameters
        ----------
        canonical:
            The :class:`~src.models.CanonicalRecord` being built.
        raw_key:
            Raw source-side field name that could not be resolved.
        """
        if raw_key not in canonical.unknown_fields:
            canonical.unknown_fields.append(raw_key)
        self._log.warning(
            "Unknown field — no canonical mapping",
            extra={
                "source_type": canonical.source_type.value,
                "raw_field":   raw_key,
                "mapper":      self.__class__.__name__,
            },
        )

    def _record_ignored(
        self,
        canonical: CanonicalRecord,
        raw_key: str,
    ) -> None:
        """
        Record a raw field name as intentionally ignored.

        Parameters
        ----------
        canonical:
            The :class:`~src.models.CanonicalRecord` being built.
        raw_key:
            Raw source-side field name to ignore.
        """
        if raw_key not in canonical.ignored_fields:
            canonical.ignored_fields.append(raw_key)

    def _timed_map(
        self,
        record: RawRecord,
        impl: Any,
    ) -> CanonicalRecord:
        """
        Timing wrapper — calls ``impl(record)`` and logs structured
        telemetry (duration, mapped / ignored / unknown field counts).

        Parameters
        ----------
        record:
            The :class:`~src.models.RawRecord` being mapped.
        impl:
            Callable ``(RawRecord) -> CanonicalRecord``.

        Returns
        -------
        CanonicalRecord
            Result from ``impl``.
        """
        start = time.perf_counter()
        result: CanonicalRecord = impl(record)
        duration_ms = (time.perf_counter() - start) * 1000

        self._log.info(
            "Mapping complete",
            extra={
                "mapper":         self.__class__.__name__,
                "source":         record.source,
                "source_type":    record.source_type.value,
                "mapped_fields":  len(result.mapped_fields),
                "ignored_fields": len(result.ignored_fields),
                "unknown_fields": len(result.unknown_fields),
                "duration_ms":    round(duration_ms, 2),
            },
        )
        return result
