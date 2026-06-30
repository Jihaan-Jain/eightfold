"""
src/mapping/factory.py
=======================

Mapper factory — automatically selects the correct
:class:`~src.mapping.base.BaseMapper` for a given
:class:`~src.models.RawRecord`.

Design
------
- Mappers are registered in priority order.
- The factory calls :meth:`~src.mapping.base.BaseMapper.supports`
  on each registered mapper in order and returns the first match.
- A default :class:`~src.mapping.base.BaseMapper`-based stub is
  returned when no mapper claims the record; it logs a warning and
  produces an empty :class:`~src.models.CanonicalRecord`.
- Mappers can be registered at runtime via
  :meth:`MapperFactory.register` for extensibility.

Usage
-----
::

    from src.mapping.factory import MapperFactory

    factory = MapperFactory()
    canonical = factory.map(raw_record)

    # Or batch:
    results = factory.map_many(raw_records)
"""

from __future__ import annotations

from typing import Any

from src.logging_config import get_logger
from src.mapping.ats_mapper import ATSMapper
from src.mapping.base import BaseMapper
from src.mapping.csv_mapper import CsvMapper
from src.mapping.field_registry import REGISTRY, FieldRegistry
from src.mapping.github_mapper import GithubMapper
from src.mapping.resume_mapper import ResumePdfMapper
from src.models import CanonicalRecord, RawRecord

_log = get_logger(__name__)


# ================================================================
# Fallback (No-op) Mapper
# ================================================================


class _FallbackMapper(BaseMapper):
    """
    A no-op mapper returned when no registered mapper supports
    a given record.

    Produces an empty :class:`~src.models.CanonicalRecord` and logs
    a warning.  Never raises.
    """

    def supports(self, record: RawRecord) -> bool:
        return True  # always claimed — used only as a last resort

    def metadata(self) -> dict[str, Any]:
        return {
            "mapper":      self.__class__.__name__,
            "source_type": "unknown",
            "version":     "1.0.0",
        }

    def map(self, record: RawRecord) -> CanonicalRecord:
        canonical = self._make_canonical(record)
        canonical.mapping_metadata["mapper"] = "FallbackMapper"
        canonical.mapping_metadata["warning"] = (
            f"No mapper supports source_type={record.source_type.value!r}. "
            "Returning empty CanonicalRecord."
        )
        _log.warning(
            "No mapper found for record",
            extra={
                "record_id":   record.record_id,
                "source_type": record.source_type.value,
                "source":      record.source,
            },
        )
        return canonical


# ================================================================
# MapperFactory
# ================================================================


class MapperFactory:
    """
    Selects and applies the correct :class:`~src.mapping.base.BaseMapper`
    for a :class:`~src.models.RawRecord`.

    Mappers are checked in registration order; the first mapper whose
    :meth:`~src.mapping.base.BaseMapper.supports` returns ``True``
    is used.

    The built-in registration order is:

    1. :class:`~src.mapping.csv_mapper.CsvMapper`
    2. :class:`~src.mapping.ats_mapper.ATSMapper`
    3. :class:`~src.mapping.github_mapper.GithubMapper`
    4. :class:`~src.mapping.resume_mapper.ResumePdfMapper`

    Parameters
    ----------
    registry:
        Shared :class:`~src.mapping.field_registry.FieldRegistry`.
        Defaults to the module-level ``REGISTRY`` singleton.
    config:
        Optional mapper-specific config dict keyed by mapper class name.
        E.g. ``{"CsvMapper": {"ignored_fields": ["stage"]}}``
    """

    def __init__(
        self,
        registry: FieldRegistry | None = None,
        config: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._registry = registry or REGISTRY
        self._config = config or {}
        self._mappers: list[BaseMapper] = []
        self._fallback = _FallbackMapper(registry=self._registry)
        self._register_defaults()

    # ── Registration ─────────────────────────────────────────

    def _register_defaults(self) -> None:
        """Register the four built-in mappers."""
        for cls in (CsvMapper, ATSMapper, GithubMapper, ResumePdfMapper):
            mapper_cfg = self._config.get(cls.__name__, {})
            self._mappers.append(
                cls(registry=self._registry, config=mapper_cfg)  # type: ignore[call-arg]
            )

    def register(self, mapper: BaseMapper, *, at_front: bool = False) -> None:
        """
        Register a custom mapper at runtime.

        Parameters
        ----------
        mapper:
            The :class:`~src.mapping.base.BaseMapper` instance to add.
        at_front:
            When ``True``, insert the mapper at the front so it is
            checked before the built-ins.  Default: ``False``
            (appended to the end, before the fallback).
        """
        if at_front:
            self._mappers.insert(0, mapper)
        else:
            self._mappers.append(mapper)
        _log.info(
            "Registered custom mapper",
            extra={"mapper": mapper.__class__.__name__},
        )

    def registered_mappers(self) -> list[str]:
        """Return the class names of all registered mappers in order."""
        return [m.__class__.__name__ for m in self._mappers]

    # ── Mapping ───────────────────────────────────────────────

    def select(self, record: RawRecord) -> BaseMapper:
        """
        Return the first mapper that supports ``record``.

        Falls back to :class:`_FallbackMapper` when none match.

        Parameters
        ----------
        record:
            The :class:`~src.models.RawRecord` to classify.

        Returns
        -------
        BaseMapper
            The selected mapper instance.
        """
        for mapper in self._mappers:
            if mapper.supports(record):
                return mapper
        return self._fallback

    def map(self, record: RawRecord) -> CanonicalRecord:
        """
        Map a single :class:`~src.models.RawRecord` to a
        :class:`~src.models.CanonicalRecord`.

        Parameters
        ----------
        record:
            Source record to map.

        Returns
        -------
        CanonicalRecord
            Populated canonical record.  Never raises — errors are
            caught and logged; an empty record is returned on failure.
        """
        mapper = self.select(record)
        try:
            return mapper.map(record)
        except Exception as exc:  # pragma: no cover — defensive only
            _log.error(
                "Mapper raised unexpected error",
                extra={
                    "mapper":      mapper.__class__.__name__,
                    "record_id":   record.record_id,
                    "source_type": record.source_type.value,
                    "error":       str(exc),
                },
                exc_info=True,
            )
            canonical = CanonicalRecord(
                source_record_id=record.record_id,
                source_type=record.source_type,
                source_label=record.source,
            )
            canonical.mapping_metadata["error"] = str(exc)
            return canonical

    def map_many(self, records: list[RawRecord]) -> list[CanonicalRecord]:
        """
        Map a list of :class:`~src.models.RawRecord` objects.

        Parameters
        ----------
        records:
            Source records to map.

        Returns
        -------
        list[CanonicalRecord]
            One result per input record, in the same order.
        """
        results: list[CanonicalRecord] = []
        for record in records:
            results.append(self.map(record))
        _log.info(
            "Batch mapping complete",
            extra={
                "total":   len(records),
                "mapped":  len(results),
            },
        )
        return results
