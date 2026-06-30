"""
src/merge/provenance_aggregator.py
=====================================

Aggregates :class:`~src.models.Provenance` entries from all source
:class:`~src.models.CanonicalRecord` objects in a
:class:`~src.merge.identity_resolver.CandidateGroup` into a single
field-keyed provenance map suitable for
:class:`~src.models.CandidateProfile`.

Output Format
-------------
::

    {
        "emails":         [Provenance, Provenance, ...],
        "full_name":      [Provenance],
        "skills":         [Provenance, Provenance, ...],
        ...
    }

Each list is in chronological order (oldest first).

Additionally, the aggregator **appends a merge-stage provenance entry**
for every field that was touched by conflict resolution, so the full
chain reads:

    extraction → mapping → normalisation → conflict_resolution

"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.logging_config import get_logger
from src.models import (
    CanonicalRecord,
    ConfidenceMethod,
    NormalizationMethod,
    ProcessingStage,
    Provenance,
    SourceType,
)
from src.merge.conflict_resolver import ConflictRecord

_log = get_logger(__name__)


class ProvenanceAggregator:
    """
    Collects and merges :class:`~src.models.Provenance` entries from
    multiple source :class:`~src.models.CanonicalRecord` objects.

    Usage
    -----
    ::

        aggregator = ProvenanceAggregator()
        prov_map   = aggregator.aggregate(records, conflict_records)

    """

    def aggregate(
        self,
        records: list[CanonicalRecord],
        conflict_records: list[ConflictRecord] | None = None,
        winner_source_per_field: dict[str, SourceType] | None = None,
    ) -> dict[str, list[Provenance]]:
        """
        Merge all provenance entries from ``records`` into a single map.

        Parameters
        ----------
        records:
            All source :class:`~src.models.CanonicalRecord` objects in
            the candidate group.
        conflict_records:
            Conflicts produced by :class:`~src.merge.conflict_resolver.ConflictResolver`.
            When provided, a MERGE-stage provenance entry is appended for
            each resolved field.
        winner_source_per_field:
            Mapping of canonical field → winning source type, used to
            tag merge-stage provenance entries.

        Returns
        -------
        dict[str, list[Provenance]]
            Field-keyed provenance map, entries in chronological order.
        """
        prov_map: dict[str, list[Provenance]] = {}

        # ── Collect all provenance from every source record ───
        for record in records:
            for prov in record.provenance:
                prov_map.setdefault(prov.field, []).append(prov)

        # ── Sort each field's list chronologically ────────────
        for field_name in prov_map:
            prov_map[field_name].sort(key=lambda p: p.timestamp)

        # ── Append merge-stage conflict resolution entries ────
        if conflict_records:
            winner_sources = winner_source_per_field or {}
            for cr in conflict_records:
                source = winner_sources.get(cr.field, cr.winner_source)
                merge_prov = Provenance(
                    field=cr.field,
                    source=source,
                    method=NormalizationMethod.NONE,
                    original_value=str([d[0] for d in cr.discarded]),
                    normalized_value=cr.winner,
                    processing_stage=ProcessingStage.CONFLICT_RESOLUTION,
                    confidence=1.0,
                    reason=cr.reason,
                )
                prov_map.setdefault(cr.field, []).append(merge_prov)

        _log.debug(
            "Provenance aggregation complete",
            extra={
                "total_fields":   len(prov_map),
                "total_entries":  sum(len(v) for v in prov_map.values()),
                "conflict_fields": len(conflict_records or []),
            },
        )
        return prov_map

    def summary(self, prov_map: dict[str, list[Provenance]]) -> dict[str, Any]:
        """
        Return a human-readable summary of the provenance map.

        Useful for logging and the MergeReport.

        Parameters
        ----------
        prov_map:
            Output of :meth:`aggregate`.

        Returns
        -------
        dict[str, Any]
            ``{"field": {"sources": [...], "stages": [...], "entry_count": N}, ...}``
        """
        summary: dict[str, Any] = {}
        for field_name, entries in prov_map.items():
            summary[field_name] = {
                "sources":     list({e.source.value for e in entries}),
                "stages":      list({e.processing_stage.value for e in entries}),
                "entry_count": len(entries),
                "latest_value": entries[-1].normalized_value if entries else None,
            }
        return summary
