"""
src/merge/conflict_resolver.py
================================

Resolves field-level conflicts when multiple :class:`~src.models.CanonicalRecord`
objects provide different values for the same canonical field.

Strategies (configured via :class:`~src.models.MergeStrategy`)
--------------------------------------------------------------
SOURCE_PRIORITY (default):
    The source with the **lowest priority number** wins.
    Priority defined in ``constants.SOURCE_PRIORITY``
    (lower number = higher trust; e.g. ATS=1 beats CSV=3).

MAJORITY_VOTE:
    When ≥ 2 of ≥ 3 sources agree on a normalised value, that value
    wins regardless of priority.  Falls back to SOURCE_PRIORITY on tie.

MOST_RECENT:
    The value from the record with the most recent ``mapped_at``
    timestamp wins.

MANUAL:
    All conflicts are preserved as unresolved entries for human review.
    The highest-priority source value is used as a provisional winner.

Output
------
Every conflict produces a :class:`ConflictRecord` that explains exactly
which source won, what was discarded, and why.  These records are
collected in :class:`~src.merge.merge_engine.MergeReport`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.constants import SOURCE_PRIORITY
from src.logging_config import get_logger
from src.models import MergeStrategy, SourceType
from src.merge.utils import normalize_key

_log = get_logger(__name__)


# ================================================================
# ConflictRecord  (the "MergeReport" field suggested in the screenshot)
# ================================================================


@dataclass
class ConflictRecord:
    """
    A single field-level conflict record.

    Attributes
    ----------
    field:
        Canonical field name where sources disagreed.
    winner:
        The value that was chosen as the canonical winner.
    winner_source:
        The source type that provided the winning value.
    discarded:
        List of ``(value, source_type)`` pairs that were discarded.
    reason:
        Human-readable explanation of why ``winner`` was chosen.
    strategy:
        The :class:`~src.models.MergeStrategy` that resolved this conflict.
    resolved_at:
        UTC timestamp of resolution.
    """

    field:          str
    winner:         Any
    winner_source:  SourceType
    discarded:      list[tuple[Any, SourceType]] = field(default_factory=list)
    reason:         str = ""
    strategy:       MergeStrategy = MergeStrategy.SOURCE_PRIORITY
    resolved_at:    datetime = field(
        default_factory=lambda: datetime.now(__import__("datetime").timezone.utc)
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialisable representation for MergeReport."""
        return {
            "field":         self.field,
            "winner":        self.winner,
            "winner_source": self.winner_source.value,
            "discarded": [
                {"value": v, "source": s.value}
                for v, s in self.discarded
            ],
            "reason":        self.reason,
            "strategy":      self.strategy.value,
        }


# ================================================================
# _SourceValue — internal helper
# ================================================================


@dataclass
class _SourceValue:
    """Bundles a field value with its source and timestamp."""
    value:      Any
    source:     SourceType
    mapped_at:  datetime
    priority:   int  # lower = higher trust


# ================================================================
# ConflictResolver
# ================================================================


class ConflictResolver:
    """
    Resolves conflicts between multiple source values for the same field.

    Parameters
    ----------
    strategy:
        Default :class:`~src.models.MergeStrategy`.
        Can be overridden per-field via ``field_strategies``.
    field_strategies:
        Mapping of canonical field name → :class:`~src.models.MergeStrategy`.
        Overrides ``strategy`` for specific fields.
    """

    def __init__(
        self,
        strategy: MergeStrategy = MergeStrategy.SOURCE_PRIORITY,
        field_strategies: dict[str, MergeStrategy] | None = None,
    ) -> None:
        self._strategy = strategy
        self._field_strategies: dict[str, MergeStrategy] = field_strategies or {}

    # ── Public API ────────────────────────────────────────────

    def resolve(
        self,
        field_name: str,
        source_values: list[tuple[Any, SourceType, datetime]],
    ) -> tuple[Any, list[ConflictRecord]]:
        """
        Choose a winner from competing source values for ``field_name``.

        Parameters
        ----------
        field_name:
            Canonical field name.
        source_values:
            List of ``(value, source_type, mapped_at)`` tuples,
            one per source that provided this field.

        Returns
        -------
        tuple[Any, list[ConflictRecord]]
            ``(winner_value, conflicts)`` where ``conflicts`` is empty
            when all sources agree.
        """
        # Filter out None / empty values
        non_null = [
            (v, s, t) for v, s, t in source_values
            if v is not None and v != "" and v != [] and v != {}
        ]

        if not non_null:
            return None, []

        if len(non_null) == 1:
            return non_null[0][0], []

        # Wrap in _SourceValue for easier access
        svs = [
            _SourceValue(
                value=v,
                source=s,
                mapped_at=t,
                priority=SOURCE_PRIORITY.get(s.value, 99),
            )
            for v, s, t in non_null
        ]

        # Check for agreement first — no conflict needed
        normalised = [
            normalize_key(str(sv.value)) if isinstance(sv.value, str)
            else sv.value
            for sv in svs
        ]
        if len(set(str(n) for n in normalised)) == 1:
            # All agree — use highest-priority value directly
            best = min(svs, key=lambda sv: sv.priority)
            return best.value, []

        # Resolve conflict by strategy
        effective = self._field_strategies.get(field_name, self._strategy)
        if effective == MergeStrategy.MAJORITY_VOTE:
            winner_sv, conflicts = self._majority_vote(field_name, svs)
        elif effective == MergeStrategy.MOST_RECENT:
            winner_sv, conflicts = self._most_recent(field_name, svs)
        elif effective == MergeStrategy.MANUAL:
            winner_sv, conflicts = self._manual(field_name, svs)
        else:
            winner_sv, conflicts = self._source_priority(field_name, svs)

        _log.debug(
            "Conflict resolved",
            extra={
                "field":    field_name,
                "strategy": effective.value,
                "winner":   str(winner_sv.value)[:80],
                "sources":  [sv.source.value for sv in svs],
            },
        )
        return winner_sv.value, conflicts

    # ── Strategies ────────────────────────────────────────────

    def _source_priority(
        self, field: str, svs: list[_SourceValue]
    ) -> tuple[_SourceValue, list[ConflictRecord]]:
        """Lowest priority number wins (highest trust)."""
        sorted_svs = sorted(svs, key=lambda sv: sv.priority)
        winner = sorted_svs[0]
        discarded = [(sv.value, sv.source) for sv in sorted_svs[1:]]
        conflict = ConflictRecord(
            field=field,
            winner=winner.value,
            winner_source=winner.source,
            discarded=discarded,
            reason=(
                f"{winner.source.value} outranks "
                f"{', '.join(sv.source.value for sv in sorted_svs[1:])} "
                f"(priority {winner.priority} vs "
                f"{', '.join(str(sv.priority) for sv in sorted_svs[1:])})."
            ),
            strategy=MergeStrategy.SOURCE_PRIORITY,
        )
        return winner, [conflict]

    def _majority_vote(
        self, field: str, svs: list[_SourceValue]
    ) -> tuple[_SourceValue, list[ConflictRecord]]:
        """
        Majority vote: value with the most support wins.
        Falls back to SOURCE_PRIORITY on tie.
        """
        votes: dict[str, list[_SourceValue]] = {}
        for sv in svs:
            k = normalize_key(str(sv.value)) if isinstance(sv.value, str) else str(sv.value)
            votes.setdefault(k, []).append(sv)

        max_votes = max(len(v) for v in votes.values())
        candidates = [v for v in votes.values() if len(v) == max_votes]

        if len(candidates) == 1:
            # Clear majority
            winner_group = candidates[0]
            winner = min(winner_group, key=lambda sv: sv.priority)
            discarded = [
                (sv.value, sv.source)
                for sv in svs
                if sv is not winner
            ]
            reason = (
                f"Majority vote: {len(winner_group)}/{len(svs)} sources agreed on "
                f"'{winner.value}'. Winner chosen by source priority."
            )
        else:
            # Tie — fall back to priority
            winner = min(svs, key=lambda sv: sv.priority)
            discarded = [(sv.value, sv.source) for sv in svs if sv is not winner]
            reason = (
                f"Majority vote tie — fell back to source priority. "
                f"{winner.source.value} (priority {winner.priority}) wins."
            )

        conflict = ConflictRecord(
            field=field,
            winner=winner.value,
            winner_source=winner.source,
            discarded=discarded,
            reason=reason,
            strategy=MergeStrategy.MAJORITY_VOTE,
        )
        return winner, [conflict]

    def _most_recent(
        self, field: str, svs: list[_SourceValue]
    ) -> tuple[_SourceValue, list[ConflictRecord]]:
        """Most recently extracted record wins."""
        sorted_svs = sorted(svs, key=lambda sv: sv.mapped_at, reverse=True)
        winner = sorted_svs[0]
        discarded = [(sv.value, sv.source) for sv in sorted_svs[1:]]
        conflict = ConflictRecord(
            field=field,
            winner=winner.value,
            winner_source=winner.source,
            discarded=discarded,
            reason=(
                f"Most recent extraction: {winner.source.value} "
                f"mapped at {winner.mapped_at.isoformat()}."
            ),
            strategy=MergeStrategy.MOST_RECENT,
        )
        return winner, [conflict]

    def _manual(
        self, field: str, svs: list[_SourceValue]
    ) -> tuple[_SourceValue, list[ConflictRecord]]:
        """
        MANUAL strategy: conflict flagged for human review.
        Provisional winner = highest-priority source.
        """
        sorted_svs = sorted(svs, key=lambda sv: sv.priority)
        winner = sorted_svs[0]
        discarded = [(sv.value, sv.source) for sv in sorted_svs[1:]]
        conflict = ConflictRecord(
            field=field,
            winner=winner.value,
            winner_source=winner.source,
            discarded=discarded,
            reason=(
                f"MANUAL strategy: conflict requires human review. "
                f"Provisional winner: {winner.source.value} (priority {winner.priority})."
            ),
            strategy=MergeStrategy.MANUAL,
        )
        return winner, [conflict]
