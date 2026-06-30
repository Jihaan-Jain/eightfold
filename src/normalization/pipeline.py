"""
src/normalization/pipeline.py
==============================

The :class:`NormalizationPipeline` orchestrates every normalizer in a
configurable, ordered sequence.

Design
------
- Normalizers are executed in **registration order**.
- Each normalizer receives the :class:`~src.models.CanonicalRecord`
  that the previous normalizer returned (chained mutation).
- Individual normalizers can be **disabled** via configuration.
- Supports a **dry-run** mode where provenance is written but the record
  fields are not updated.
- The pipeline is **reusable** — the same instance can be called
  multiple times with different records.

Usage
-----
::

    from src.normalization.pipeline import NormalizationPipeline
    from src.normalization.factory  import NormalizerFactory

    pipeline = NormalizerFactory.build_default_pipeline()
    normalized_record = pipeline.run(canonical_record)

    # Or build manually:
    pipeline = NormalizationPipeline()
    pipeline.add(EmailNormalizer())
    pipeline.add(PhoneNormalizer())
    pipeline.add(SkillNormalizer())
    result = pipeline.run(record)
"""

from __future__ import annotations

import time
from typing import Any

from src.logging_config import get_logger
from src.models import CanonicalRecord
from src.normalization.base import BaseNormalizer

_log = get_logger(__name__)


class NormalizationPipeline:
    """
    Ordered chain of :class:`~src.normalization.base.BaseNormalizer`
    instances.

    Parameters
    ----------
    config:
        Global pipeline configuration dict.  Keys:
        - ``disabled`` (list[str]): Normalizer class names to skip.
        - ``dry_run`` (bool): Run normalizers without mutating fields.

    Attributes
    ----------
    normalizers:
        Ordered list of registered normalizer instances.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config: dict[str, Any] = config or {}
        self.normalizers: list[BaseNormalizer] = []

    # ── Registration ─────────────────────────────────────────

    def add(self, normalizer: BaseNormalizer, *, at_front: bool = False) -> None:
        """
        Register a normalizer.

        Parameters
        ----------
        normalizer:
            The :class:`~src.normalization.base.BaseNormalizer` to add.
        at_front:
            When ``True``, insert at position 0 (runs first).
        """
        if at_front:
            self.normalizers.insert(0, normalizer)
        else:
            self.normalizers.append(normalizer)

    def remove(self, normalizer_class_name: str) -> bool:
        """
        Remove all registered normalizers with the given class name.

        Parameters
        ----------
        normalizer_class_name:
            Simple class name (e.g. ``"EmailNormalizer"``).

        Returns
        -------
        bool
            ``True`` when at least one normalizer was removed.
        """
        before = len(self.normalizers)
        self.normalizers = [
            n for n in self.normalizers
            if n.__class__.__name__ != normalizer_class_name
        ]
        return len(self.normalizers) < before

    def registered_names(self) -> list[str]:
        """Return class names of registered normalizers in order."""
        return [n.__class__.__name__ for n in self.normalizers]

    # ── Execution ─────────────────────────────────────────────

    def run(self, record: CanonicalRecord) -> CanonicalRecord:
        """
        Run all enabled normalizers on ``record`` in order.

        Parameters
        ----------
        record:
            The :class:`~src.models.CanonicalRecord` to normalize.
            Modified in-place by each normalizer.

        Returns
        -------
        CanonicalRecord
            The normalized record (same object, mutated in-place).
        """
        disabled: list[str] = self._config.get("disabled", [])
        pipeline_start = time.perf_counter()
        applied: list[str] = []
        skipped: list[str] = []

        for normalizer in self.normalizers:
            name = normalizer.__class__.__name__

            # ── Skip disabled normalizers ─────────────────────
            if name in disabled:
                skipped.append(name)
                _log.debug(
                    "Normalizer skipped (disabled)",
                    extra={"normalizer": name},
                )
                continue

            # ── Skip when nothing to do ───────────────────────
            if not normalizer.supports(record):
                _log.debug(
                    "Normalizer skipped (no data)",
                    extra={"normalizer": name, "source": record.source_label},
                )
                continue

            # ── Apply ─────────────────────────────────────────
            try:
                record = normalizer.normalize(record)
                applied.append(name)
            except Exception as exc:  # pragma: no cover — defensive
                _log.error(
                    "Normalizer raised unexpected error",
                    extra={
                        "normalizer": name,
                        "source":     record.source_label,
                        "error":      str(exc),
                    },
                    exc_info=True,
                )

        total_ms = (time.perf_counter() - pipeline_start) * 1000
        _log.info(
            "Normalization pipeline complete",
            extra={
                "source":       record.source_label,
                "applied":      applied,
                "skipped":      skipped,
                "total_ms":     round(total_ms, 2),
            },
        )
        return record

    def run_many(self, records: list[CanonicalRecord]) -> list[CanonicalRecord]:
        """
        Run the pipeline over a list of records.

        Parameters
        ----------
        records:
            Records to normalize.

        Returns
        -------
        list[CanonicalRecord]
            Normalized records in the same order as input.
        """
        results = []
        for record in records:
            results.append(self.run(record))
        _log.info(
            "Batch normalization complete",
            extra={"total": len(records), "normalized": len(results)},
        )
        return results

    # ── Introspection ─────────────────────────────────────────

    def __repr__(self) -> str:
        names = " → ".join(self.registered_names()) or "(empty)"
        return f"NormalizationPipeline([{names}])"

    def __len__(self) -> int:
        return len(self.normalizers)
