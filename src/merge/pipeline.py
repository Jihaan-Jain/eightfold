"""
src/merge/pipeline.py
======================

Orchestrates the full merge pipeline:

    list[CanonicalRecord]
        │
        ▼  IdentityResolver
    list[CandidateGroup]
        │
        ▼  MergeEngine (per group)
    list[CandidateProfile]  +  list[MergeReport]

Usage
-----
::

    from src.merge.pipeline import MergePipeline
    from src.merge.factory  import MergeFactory

    pipeline = MergeFactory.build_default_pipeline()
    profiles, reports = pipeline.run(canonical_records)

"""

from __future__ import annotations

import time
from typing import Any

from src.logging_config import get_logger
from src.models import CanonicalRecord, CandidateProfile
from src.merge.identity_resolver import CandidateGroup, IdentityResolver
from src.merge.merge_engine import MergeEngine, MergeReport

_log = get_logger(__name__)


class MergePipeline:
    """
    End-to-end merge pipeline: records → profiles + reports.

    Parameters
    ----------
    resolver:
        Configured :class:`~src.merge.identity_resolver.IdentityResolver`.
    engine:
        Configured :class:`~src.merge.merge_engine.MergeEngine`.
    config:
        Optional pipeline-level config.  Supported keys:

        - ``stop_on_error`` (bool, default ``False``):
          When ``True``, a failed group merge raises instead of continuing.
        - ``emit_single_source`` (bool, default ``True``):
          When ``False``, discard groups with only one source record.
    """

    def __init__(
        self,
        resolver: IdentityResolver,
        engine:   MergeEngine,
        config:   dict[str, Any] | None = None,
    ) -> None:
        self._resolver = resolver
        self._engine   = engine
        self._config   = config or {}

    # ── Public API ────────────────────────────────────────────

    def run(
        self,
        records: list[CanonicalRecord],
    ) -> tuple[list[CandidateProfile], list[MergeReport]]:
        """
        Run the full merge pipeline.

        Parameters
        ----------
        records:
            All normalised :class:`~src.models.CanonicalRecord` objects.

        Returns
        -------
        tuple[list[CandidateProfile], list[MergeReport]]
            ``(profiles, reports)`` in the same order (one per candidate group).
        """
        start = time.perf_counter()
        stop_on_error    = self._config.get("stop_on_error", False)
        emit_single_src  = self._config.get("emit_single_source", True)

        _log.info(
            "Merge pipeline started",
            extra={"input_records": len(records)},
        )

        # ── Step 1: Identity Resolution ───────────────────────
        groups: list[CandidateGroup] = self._resolver.resolve(records)

        if not emit_single_src:
            groups = [g for g in groups if g.size > 1]
            _log.debug(
                "Single-source groups filtered",
                extra={"retained": len(groups)},
            )

        # ── Step 2: Merge each group ──────────────────────────
        profiles: list[CandidateProfile] = []
        reports:  list[MergeReport]      = []

        for group in groups:
            try:
                profile, report = self._engine.merge(group)
                profiles.append(profile)
                reports.append(report)
            except Exception as exc:
                _log.error(
                    "Group merge failed",
                    extra={
                        "group_id": group.group_id,
                        "size":     group.size,
                        "error":    str(exc),
                    },
                    exc_info=True,
                )
                if stop_on_error:
                    raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        _log.info(
            "Merge pipeline complete",
            extra={
                "input_records":  len(records),
                "candidate_groups": len(groups),
                "profiles_produced": len(profiles),
                "total_conflicts":  sum(len(r.conflicts) for r in reports),
                "needs_review":     sum(1 for r in reports if r.needs_review),
                "elapsed_ms":       round(elapsed_ms, 2),
            },
        )
        return profiles, reports

    def run_single_group(
        self, group: CandidateGroup
    ) -> tuple[CandidateProfile, MergeReport]:
        """
        Merge a single pre-formed group (useful for testing).

        Parameters
        ----------
        group:
            A :class:`~src.merge.identity_resolver.CandidateGroup`.

        Returns
        -------
        tuple[CandidateProfile, MergeReport]
        """
        return self._engine.merge(group)

    # ── Introspection ─────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"MergePipeline("
            f"resolver={self._resolver.__class__.__name__}, "
            f"engine={self._engine.__class__.__name__})"
        )
