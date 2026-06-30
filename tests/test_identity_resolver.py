"""
tests/test_identity_resolver.py
=================================

Unit tests for src/merge/identity_resolver.py.
"""

from __future__ import annotations

import pytest

from src.merge.identity_resolver import (
    CandidateGroup,
    IdentityResolver,
    _UnionFind,
    _score_pair,
)
from src.models import CanonicalRecord, SourceType


def _rec(
    emails: list[str] | None = None,
    phones: list[str] | None = None,
    full_name: str | None = None,
    current_company: str | None = None,
    location: str | None = None,
    github_url: str | None = None,
    github_username: str | None = None,
    linkedin_url: str | None = None,
    source_type: SourceType = SourceType.CSV,
    mapped_fields: list[str] | None = None,
) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="r1",
        source_type=source_type,
        source_label="test.csv",
        emails=emails or [],
        phones=phones or [],
        full_name=full_name,
        current_company=current_company,
        location=location,
        github_url=github_url,
        github_username=github_username,
        linkedin_url=linkedin_url,
        mapped_fields=mapped_fields or [],
    )


# ================================================================
# UnionFind
# ================================================================


class TestUnionFind:
    def test_initial_each_own_root(self):
        uf = _UnionFind(3)
        assert uf.find(0) == 0
        assert uf.find(1) == 1
        assert uf.find(2) == 2

    def test_union_merges_sets(self):
        uf = _UnionFind(3)
        uf.union(0, 1)
        assert uf.find(0) == uf.find(1)

    def test_union_returns_true_on_new_merge(self):
        uf = _UnionFind(2)
        assert uf.union(0, 1) is True

    def test_union_returns_false_on_same_set(self):
        uf = _UnionFind(2)
        uf.union(0, 1)
        assert uf.union(0, 1) is False

    def test_transitivity(self):
        uf = _UnionFind(3)
        uf.union(0, 1)
        uf.union(1, 2)
        assert uf.find(0) == uf.find(2)

    def test_groups_single(self):
        uf = _UnionFind(3)
        groups = uf.groups(3)
        assert len(groups) == 3

    def test_groups_merged(self):
        uf = _UnionFind(3)
        uf.union(0, 1)
        groups = uf.groups(3)
        assert len(groups) == 2


# ================================================================
# _score_pair
# ================================================================


class TestScorePair:
    def test_email_match_gives_high_score(self):
        a = _rec(emails=["alice@example.com"])
        b = _rec(emails=["alice@example.com"])
        score, signals = _score_pair(a, b)
        # Email is a hard signal → score == IDENTITY_MATCH_THRESHOLD (0.85)
        assert score >= 0.85
        assert "email_match" in signals

    def test_email_case_insensitive(self):
        a = _rec(emails=["Alice@EXAMPLE.COM"])
        b = _rec(emails=["alice@example.com"])
        score, signals = _score_pair(a, b)
        assert "email_match" in signals

    def test_no_shared_email_no_email_signal(self):
        a = _rec(emails=["alice@x.com"])
        b = _rec(emails=["bob@x.com"])
        _, signals = _score_pair(a, b)
        assert "email_match" not in signals

    def test_phone_match(self):
        a = _rec(phones=["+14155552671"])
        b = _rec(phones=["+14155552671"])
        _, signals = _score_pair(a, b)
        assert "phone_match" in signals

    def test_github_url_match(self):
        a = _rec(github_url="https://github.com/alice")
        b = _rec(github_url="https://github.com/alice")
        _, signals = _score_pair(a, b)
        assert "github_match" in signals

    def test_github_username_match(self):
        a = _rec(github_username="alice")
        b = _rec(github_username="alice")
        _, signals = _score_pair(a, b)
        assert "github_match" in signals

    def test_linkedin_match(self):
        a = _rec(linkedin_url="https://linkedin.com/in/alice-smith")
        b = _rec(linkedin_url="https://linkedin.com/in/alice-smith")
        _, signals = _score_pair(a, b)
        assert "linkedin_match" in signals

    def test_name_company_match(self):
        a = _rec(full_name="Alice Smith", current_company="Google")
        b = _rec(full_name="Alice Smith", current_company="Google")
        score, signals = _score_pair(a, b)
        assert score > 0.0
        assert any("name" in s for s in signals)

    def test_completely_different_records_low_score(self):
        a = _rec(emails=["alice@x.com"], full_name="Alice Smith")
        b = _rec(emails=["bob@y.com"],   full_name="Bob Jones")
        score, _ = _score_pair(a, b)
        assert score < 0.5

    def test_empty_records_zero_score(self):
        a = _rec()
        b = _rec()
        score, signals = _score_pair(a, b)
        assert score == 0.0
        assert signals == []

    def test_score_capped_at_one(self):
        # Multiple matching signals — score must stay ≤ 1.0
        a = _rec(
            emails=["alice@x.com"], phones=["+14155552671"],
            github_url="https://github.com/alice",
            linkedin_url="https://linkedin.com/in/alice",
        )
        b = _rec(
            emails=["alice@x.com"], phones=["+14155552671"],
            github_url="https://github.com/alice",
            linkedin_url="https://linkedin.com/in/alice",
        )
        score, _ = _score_pair(a, b)
        assert score <= 1.0


# ================================================================
# IdentityResolver
# ================================================================


class TestIdentityResolver:
    @pytest.fixture
    def resolver(self):
        return IdentityResolver()

    def test_empty_returns_empty(self, resolver):
        assert resolver.resolve([]) == []

    def test_single_record_one_group(self, resolver):
        rec = _rec(emails=["a@b.com"])
        groups = resolver.resolve([rec])
        assert len(groups) == 1
        assert groups[0].size == 1

    def test_two_identical_emails_merged(self, resolver):
        a = _rec(emails=["alice@x.com"])
        b = _rec(emails=["alice@x.com"])
        groups = resolver.resolve([a, b])
        assert len(groups) == 1
        assert groups[0].size == 2

    def test_different_emails_separate_groups(self, resolver):
        a = _rec(emails=["alice@x.com"])
        b = _rec(emails=["bob@y.com"])
        groups = resolver.resolve([a, b])
        assert len(groups) == 2

    def test_github_url_merges_records(self, resolver):
        a = _rec(github_url="https://github.com/alice")
        b = _rec(github_url="https://github.com/alice")
        groups = resolver.resolve([a, b])
        assert len(groups) == 1

    def test_three_records_two_groups(self, resolver):
        a = _rec(emails=["alice@x.com"])
        b = _rec(emails=["alice@x.com"])   # same as a
        c = _rec(emails=["carol@x.com"])   # different
        groups = resolver.resolve([a, b, c])
        assert len(groups) == 2

    def test_transitivity_merges_three_records(self, resolver):
        # a↔b via email, b↔c via phone → all three in one group
        a = _rec(emails=["alice@x.com"])
        b = _rec(emails=["alice@x.com"], phones=["+14155552671"])
        c = _rec(phones=["+14155552671"])
        groups = resolver.resolve([a, b, c])
        assert len(groups) == 1
        assert groups[0].size == 3

    def test_identity_signals_populated(self, resolver):
        a = _rec(emails=["alice@x.com"])
        b = _rec(emails=["alice@x.com"])
        groups = resolver.resolve([a, b])
        assert "email_match" in groups[0].identity_signals

    def test_source_types_populated(self, resolver):
        a = _rec(emails=["a@b.com"], source_type=SourceType.CSV)
        b = _rec(emails=["a@b.com"], source_type=SourceType.ATS)
        groups = resolver.resolve([a, b])
        src_types = groups[0].source_types
        assert "csv" in src_types
        assert "ats" in src_types

    def test_primary_record_most_mapped_fields(self, resolver):
        a = _rec(emails=["a@b.com"], mapped_fields=["emails"])
        b = _rec(emails=["a@b.com"], mapped_fields=["emails", "full_name", "location"])
        groups = resolver.resolve([a, b])
        assert groups[0].primary_record_id == b.canonical_id

    def test_metadata_dict(self, resolver):
        m = resolver.metadata()
        assert "match_threshold" in m
        assert "signals" in m

    def test_custom_thresholds(self):
        # Email hard signal scores IDENTITY_MATCH_THRESHOLD (0.85)
        # With threshold=0.80, email match merges
        resolver = IdentityResolver(match_threshold=0.80, review_threshold=0.60)
        a = _rec(emails=["alice@x.com"])
        b = _rec(emails=["alice@x.com"])
        groups = resolver.resolve([a, b])
        assert len(groups) == 1  # email match passes threshold 0.80

    def test_high_threshold_requires_multiple_signals(self):
        # With threshold > IDENTITY_MATCH_THRESHOLD (e.g. 0.99), single email alone
        # is not enough — records remain separate
        resolver = IdentityResolver(match_threshold=0.99, review_threshold=0.90)
        a = _rec(emails=["alice@x.com"])
        b = _rec(emails=["alice@x.com"])
        # Score from email = IDENTITY_MATCH_THRESHOLD = 0.85 < 0.99 → separate
        groups = resolver.resolve([a, b])
        assert len(groups) == 2  # insufficient score at threshold 0.99


# ================================================================
# CandidateGroup
# ================================================================


class TestCandidateGroup:
    def test_size_property(self):
        a = _rec(emails=["a@b.com"])
        b = _rec(emails=["a@b.com"])
        g = CandidateGroup(group_id="g1", records=[a, b])
        assert g.size == 2

    def test_add_record_updates_size(self):
        a = _rec()
        g = CandidateGroup(group_id="g1", records=[a])
        b = _rec()
        g.add(b)
        assert g.size == 2

    def test_source_types_derived(self):
        a = _rec(source_type=SourceType.ATS)
        b = _rec(source_type=SourceType.GITHUB)
        g = CandidateGroup(group_id="g1", records=[a, b])
        assert "ats" in g.source_types
        assert "github" in g.source_types

    def test_primary_record_most_fields(self):
        a = _rec(mapped_fields=["emails"])
        b = _rec(mapped_fields=["emails", "full_name"])
        g = CandidateGroup(group_id="g1", records=[a, b])
        assert g.primary_record_id == b.canonical_id
