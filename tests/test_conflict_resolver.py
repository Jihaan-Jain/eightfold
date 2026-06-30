"""
tests/test_conflict_resolver.py
=================================

Unit tests for src/merge/conflict_resolver.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.merge.conflict_resolver import ConflictRecord, ConflictResolver
from src.models import MergeStrategy, SourceType


_NOW = datetime.now(tz=timezone.utc)
_ATS    = SourceType.ATS
_CSV    = SourceType.CSV
_RESUME = SourceType.RESUME
_GITHUB = SourceType.GITHUB


def _sv(value, source, ts=None):
    return (value, source, ts or _NOW)


# ================================================================
# ConflictRecord
# ================================================================


class TestConflictRecord:
    def test_to_dict_keys(self):
        cr = ConflictRecord(
            field="full_name",
            winner="Alice Smith",
            winner_source=_ATS,
            discarded=[("Alice", _CSV)],
            reason="ATS outranks CSV",
            strategy=MergeStrategy.SOURCE_PRIORITY,
        )
        d = cr.to_dict()
        assert d["field"] == "full_name"
        assert d["winner"] == "Alice Smith"
        assert d["winner_source"] == "ats"
        assert len(d["discarded"]) == 1
        assert d["discarded"][0]["value"] == "Alice"
        assert d["strategy"] == "source_priority"

    def test_to_dict_empty_discarded(self):
        cr = ConflictRecord(
            field="email",
            winner="a@b.com",
            winner_source=_ATS,
        )
        d = cr.to_dict()
        assert d["discarded"] == []


# ================================================================
# ConflictResolver — no conflict (agreement)
# ================================================================


class TestNoConflict:
    @pytest.fixture
    def resolver(self):
        return ConflictResolver()

    def test_single_source_no_conflict(self, resolver):
        winner, conflicts = resolver.resolve(
            "full_name", [_sv("Alice Smith", _ATS)]
        )
        assert winner == "Alice Smith"
        assert conflicts == []

    def test_all_sources_agree_no_conflict(self, resolver):
        winner, conflicts = resolver.resolve(
            "full_name",
            [_sv("Alice Smith", _ATS), _sv("Alice Smith", _CSV)],
        )
        assert winner == "Alice Smith"
        assert conflicts == []

    def test_case_insensitive_agreement(self, resolver):
        winner, conflicts = resolver.resolve(
            "full_name",
            [_sv("alice smith", _ATS), _sv("Alice Smith", _CSV)],
        )
        # normalised keys match — no conflict expected
        assert conflicts == []

    def test_all_null_returns_none(self, resolver):
        winner, conflicts = resolver.resolve(
            "full_name", [_sv(None, _ATS), _sv(None, _CSV)]
        )
        assert winner is None
        assert conflicts == []

    def test_empty_source_values_returns_none(self, resolver):
        winner, conflicts = resolver.resolve("full_name", [])
        assert winner is None
        assert conflicts == []

    def test_null_filtered_out(self, resolver):
        winner, conflicts = resolver.resolve(
            "full_name",
            [_sv(None, _ATS), _sv("Alice Smith", _CSV)],
        )
        assert winner == "Alice Smith"
        assert conflicts == []


# ================================================================
# SOURCE_PRIORITY strategy
# ================================================================


class TestSourcePriority:
    @pytest.fixture
    def resolver(self):
        return ConflictResolver(strategy=MergeStrategy.SOURCE_PRIORITY)

    def test_ats_beats_csv(self, resolver):
        winner, conflicts = resolver.resolve(
            "full_name",
            [_sv("Alice (ATS)", _ATS), _sv("alice (csv)", _CSV)],
        )
        assert winner == "Alice (ATS)"
        assert len(conflicts) == 1
        assert conflicts[0].winner_source == _ATS

    def test_ats_beats_resume(self, resolver):
        # ATS priority=1, RESUME priority=5
        winner, _ = resolver.resolve(
            "headline",
            [_sv("ML Engineer", _ATS), _sv("Software Engineer", _RESUME)],
        )
        assert winner == "ML Engineer"

    def test_conflict_has_discarded(self, resolver):
        _, conflicts = resolver.resolve(
            "location",
            [_sv("San Francisco", _ATS), _sv("New York", _CSV)],
        )
        assert len(conflicts[0].discarded) == 1
        assert conflicts[0].discarded[0][0] == "New York"

    def test_conflict_reason_contains_source_names(self, resolver):
        _, conflicts = resolver.resolve(
            "location",
            [_sv("San Francisco", _ATS), _sv("New York", _CSV)],
        )
        reason = conflicts[0].reason.lower()
        assert "ats" in reason or "csv" in reason

    def test_conflict_strategy_is_source_priority(self, resolver):
        _, conflicts = resolver.resolve(
            "location",
            [_sv("A", _ATS), _sv("B", _CSV)],
        )
        assert conflicts[0].strategy == MergeStrategy.SOURCE_PRIORITY

    def test_three_sources_one_winner(self, resolver):
        winner, conflicts = resolver.resolve(
            "full_name",
            [
                _sv("Alice (ATS)", _ATS),
                _sv("Alice (CSV)", _CSV),
                _sv("Alice (GH)",  _GITHUB),
            ],
        )
        assert winner == "Alice (ATS)"
        assert len(conflicts[0].discarded) == 2


# ================================================================
# MAJORITY_VOTE strategy
# ================================================================


class TestMajorityVote:
    @pytest.fixture
    def resolver(self):
        return ConflictResolver(strategy=MergeStrategy.MAJORITY_VOTE)

    def test_clear_majority_wins(self, resolver):
        winner, conflicts = resolver.resolve(
            "location",
            [
                _sv("San Francisco", _ATS),
                _sv("San Francisco", _CSV),
                _sv("New York",      _GITHUB),
            ],
        )
        assert "San Francisco" in str(winner)
        assert len(conflicts) == 1
        assert conflicts[0].strategy == MergeStrategy.MAJORITY_VOTE

    def test_tie_falls_back_to_priority(self, resolver):
        winner, conflicts = resolver.resolve(
            "location",
            [_sv("San Francisco", _ATS), _sv("New York", _CSV)],
        )
        # Tie (1 vs 1) → priority → ATS wins
        assert winner == "San Francisco"

    def test_majority_reason_mentions_count(self, resolver):
        _, conflicts = resolver.resolve(
            "location",
            [
                _sv("X", _ATS),
                _sv("X", _CSV),
                _sv("Y", _GITHUB),
            ],
        )
        assert "2/3" in conflicts[0].reason or "Majority" in conflicts[0].reason


# ================================================================
# MOST_RECENT strategy
# ================================================================


class TestMostRecent:
    @pytest.fixture
    def resolver(self):
        return ConflictResolver(strategy=MergeStrategy.MOST_RECENT)

    def test_most_recent_wins(self, resolver):
        from datetime import timedelta
        older = _NOW - timedelta(days=30)
        winner, _ = resolver.resolve(
            "headline",
            [_sv("Old Title", _CSV, older), _sv("New Title", _ATS, _NOW)],
        )
        assert winner == "New Title"

    def test_strategy_recorded_in_conflict(self, resolver):
        from datetime import timedelta
        older = _NOW - timedelta(days=1)
        _, conflicts = resolver.resolve(
            "headline",
            [_sv("A", _CSV, older), _sv("B", _ATS, _NOW)],
        )
        assert conflicts[0].strategy == MergeStrategy.MOST_RECENT


# ================================================================
# MANUAL strategy
# ================================================================


class TestManual:
    @pytest.fixture
    def resolver(self):
        return ConflictResolver(strategy=MergeStrategy.MANUAL)

    def test_manual_uses_priority_as_provisional(self, resolver):
        winner, conflicts = resolver.resolve(
            "full_name",
            [_sv("Alice (ATS)", _ATS), _sv("Alice (CSV)", _CSV)],
        )
        # Provisional = highest priority = ATS
        assert winner == "Alice (ATS)"
        assert conflicts[0].strategy == MergeStrategy.MANUAL
        assert "review" in conflicts[0].reason.lower()


# ================================================================
# Per-field strategy override
# ================================================================


class TestFieldStrategyOverride:
    def test_field_override_applied(self):
        resolver = ConflictResolver(
            strategy=MergeStrategy.SOURCE_PRIORITY,
            field_strategies={"headline": MergeStrategy.MAJORITY_VOTE},
        )
        _, conflicts = resolver.resolve(
            "headline",
            [_sv("X", _ATS), _sv("Y", _CSV), _sv("X", _GITHUB)],
        )
        assert conflicts[0].strategy == MergeStrategy.MAJORITY_VOTE

    def test_other_fields_use_default(self):
        resolver = ConflictResolver(
            strategy=MergeStrategy.SOURCE_PRIORITY,
            field_strategies={"headline": MergeStrategy.MAJORITY_VOTE},
        )
        _, conflicts = resolver.resolve(
            "location",
            [_sv("A", _ATS), _sv("B", _CSV)],
        )
        assert conflicts[0].strategy == MergeStrategy.SOURCE_PRIORITY
