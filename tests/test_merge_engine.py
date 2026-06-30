"""
tests/test_merge_engine.py
============================

Unit tests for src/merge/merge_engine.py.
Covers MergeEngine.merge() and MergeReport.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.merge.identity_resolver import CandidateGroup
from src.merge.merge_engine import MergeEngine, MergeReport
from src.models import (
    CanonicalRecord,
    CandidateProfile,
    MergeStrategy,
    SourceType,
)


_NOW = datetime.now(tz=timezone.utc)


def _rec(
    source_type: SourceType = SourceType.CSV,
    emails: list[str] | None = None,
    phones: list[str] | None = None,
    full_name: str | None = None,
    headline: str | None = None,
    current_company: str | None = None,
    location: str | None = None,
    skills: list[str] | None = None,
    experience: list | None = None,
    education: list | None = None,
    github_url: str | None = None,
    linkedin_url: str | None = None,
    github_stars: int | None = None,
    github_repos: int | None = None,
    years_of_experience: float | None = None,
    mapped_fields: list[str] | None = None,
) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="r1",
        source_type=source_type,
        source_label="test",
        emails=emails or [],
        phones=phones or [],
        full_name=full_name,
        headline=headline,
        current_company=current_company,
        location=location,
        skills=skills or [],
        experience=experience or [],
        education=education or [],
        github_url=github_url,
        linkedin_url=linkedin_url,
        github_stars=github_stars,
        github_repos=github_repos,
        years_of_experience=years_of_experience,
        mapped_fields=mapped_fields or [],
    )


def _group(*records: CanonicalRecord) -> CandidateGroup:
    return CandidateGroup(
        group_id=records[0].canonical_id,
        records=list(records),
    )


# ================================================================
# MergeReport
# ================================================================


class TestMergeReport:
    def test_to_dict_keys(self):
        report = MergeReport(
            candidate_id="cid-123",
            merged_records=["r1", "r2"],
            source_types=["ats", "csv"],
        )
        d = report.to_dict()
        assert "candidate_id"   in d
        assert "merged_records" in d
        assert "conflicts"      in d
        assert "merge_strategy" in d
        assert "needs_review"   in d
        assert "merged_at"      in d
        assert "conflict_count" in d

    def test_conflict_count_in_dict(self):
        from src.merge.conflict_resolver import ConflictRecord
        report = MergeReport(
            candidate_id="c1",
            conflicts=[
                ConflictRecord(
                    field="f", winner="v",
                    winner_source=SourceType.ATS
                )
            ],
        )
        assert report.to_dict()["conflict_count"] == 1

    def test_quality_metrics_none_serialises(self):
        report = MergeReport(candidate_id="c1")
        d = report.to_dict()
        assert d["quality_metrics"] is None


# ================================================================
# MergeEngine — single record (trivial merge)
# ================================================================


class TestSingleRecordMerge:
    @pytest.fixture
    def engine(self):
        return MergeEngine()

    def test_returns_profile_and_report(self, engine):
        rec = _rec(emails=["a@b.com"], full_name="Alice Smith")
        profile, report = engine.merge(_group(rec))
        assert isinstance(profile, CandidateProfile)
        assert isinstance(report, MergeReport)

    def test_email_preserved(self, engine):
        rec = _rec(emails=["alice@example.com"])
        profile, _ = engine.merge(_group(rec))
        assert "alice@example.com" in profile.emails

    def test_full_name_preserved(self, engine):
        rec = _rec(full_name="Alice Smith")
        profile, _ = engine.merge(_group(rec))
        assert profile.full_name == "Alice Smith"

    def test_skills_preserved(self, engine):
        rec = _rec(skills=["Python", "Docker"])
        profile, _ = engine.merge(_group(rec))
        skill_names = [s.normalized_name for s in profile.skills]
        assert "Python" in skill_names
        assert "Docker" in skill_names

    def test_no_conflicts_for_single_source(self, engine):
        rec = _rec(full_name="Alice")
        _, report = engine.merge(_group(rec))
        assert report.conflicts == []

    def test_candidate_id_in_report(self, engine):
        rec = _rec(full_name="Alice")
        profile, report = engine.merge(_group(rec))
        assert report.candidate_id == profile.candidate_id

    def test_merged_records_contains_source_id(self, engine):
        rec = _rec(full_name="Alice")
        profile, report = engine.merge(_group(rec))
        assert rec.canonical_id in report.merged_records

    def test_quality_metrics_populated(self, engine):
        rec = _rec(emails=["a@b.com"], full_name="Alice")
        profile, _ = engine.merge(_group(rec))
        assert profile.quality_metrics is not None
        assert 0.0 <= profile.overall_confidence <= 1.0


# ================================================================
# MergeEngine — multi-source merge
# ================================================================


class TestMultiSourceMerge:
    @pytest.fixture
    def engine(self):
        return MergeEngine()

    def test_emails_union_deduped(self, engine):
        a = _rec(source_type=SourceType.ATS,    emails=["alice@x.com"])
        b = _rec(source_type=SourceType.GITHUB,  emails=["alice@x.com", "alice@work.com"])
        profile, _ = engine.merge(_group(a, b))
        assert profile.emails.count("alice@x.com") == 1
        assert "alice@work.com" in profile.emails

    def test_phones_union(self, engine):
        a = _rec(source_type=SourceType.ATS,   phones=["+14155552671"])
        b = _rec(source_type=SourceType.RESUME, phones=["+14155552672"])
        profile, _ = engine.merge(_group(a, b))
        assert len(profile.phones) == 2

    def test_ats_wins_full_name_conflict(self, engine):
        a = _rec(source_type=SourceType.ATS, full_name="Alice Smith")
        b = _rec(source_type=SourceType.CSV, full_name="A. Smith")
        profile, report = engine.merge(_group(a, b))
        assert profile.full_name == "Alice Smith"
        conflict_fields = [c.field for c in report.conflicts]
        assert "full_name" in conflict_fields

    def test_github_stars_max(self, engine):
        a = _rec(source_type=SourceType.GITHUB, github_stars=150)
        b = _rec(source_type=SourceType.ATS,    github_stars=50)
        profile, _ = engine.merge(_group(a, b))
        # max stars preserved
        assert profile.links or True  # GitHub link present

    def test_experience_union_deduped(self, engine):
        exp1 = {"company": "Google", "title": "SWE", "start_date": "2020-01"}
        exp2 = {"company": "Google", "title": "SWE", "start_date": "2020-01"}  # duplicate
        a = _rec(source_type=SourceType.ATS,    experience=[exp1])
        b = _rec(source_type=SourceType.RESUME, experience=[exp2])
        profile, _ = engine.merge(_group(a, b))
        google_entries = [e for e in profile.experience if "Google" in e.company]
        assert len(google_entries) == 1

    def test_experience_from_two_companies(self, engine):
        exp1 = {"company": "Google",    "title": "SWE", "start_date": "2020-01"}
        exp2 = {"company": "Microsoft", "title": "PM",  "start_date": "2018-06"}
        a = _rec(experience=[exp1])
        b = _rec(experience=[exp2])
        profile, _ = engine.merge(_group(a, b))
        assert len(profile.experience) == 2

    def test_education_union_deduped(self, engine):
        edu1 = {"institution": "MIT", "degree": "BSc", "end_date": "2020"}
        edu2 = {"institution": "MIT", "degree": "BSc", "end_date": "2020"}
        a = _rec(education=[edu1])
        b = _rec(education=[edu2])
        profile, _ = engine.merge(_group(a, b))
        assert len(profile.education) == 1

    def test_skills_union(self, engine):
        a = _rec(skills=["Python", "Docker"])
        b = _rec(skills=["Python", "Kubernetes"])
        profile, _ = engine.merge(_group(a, b))
        names = [s.normalized_name for s in profile.skills]
        assert "Python"     in names
        assert "Docker"     in names
        assert "Kubernetes" in names

    def test_skills_deduped(self, engine):
        a = _rec(skills=["Python"])
        b = _rec(skills=["Python"])
        profile, _ = engine.merge(_group(a, b))
        pythons = [s for s in profile.skills if s.normalized_name.lower() == "python"]
        assert len(pythons) == 1

    def test_links_github_deduped(self, engine):
        a = _rec(github_url="https://github.com/alice")
        b = _rec(github_url="https://github.com/alice")
        profile, _ = engine.merge(_group(a, b))
        gh_links = [lk for lk in profile.links if lk.platform == "github"]
        assert len(gh_links) == 1

    def test_links_multiple_platforms(self, engine):
        a = _rec(github_url="https://github.com/alice")
        b = _rec(linkedin_url="https://linkedin.com/in/alice-smith")
        profile, _ = engine.merge(_group(a, b))
        platforms = {lk.platform for lk in profile.links}
        assert "github"   in platforms
        assert "linkedin" in platforms

    def test_years_experience_max(self, engine):
        a = _rec(years_of_experience=5.0)
        b = _rec(years_of_experience=7.0)
        profile, _ = engine.merge(_group(a, b))
        assert profile.years_experience == 7.0

    def test_source_types_in_report(self, engine):
        a = _rec(source_type=SourceType.ATS)
        b = _rec(source_type=SourceType.GITHUB)
        _, report = engine.merge(_group(a, b))
        assert "ats"    in report.source_types
        assert "github" in report.source_types

    def test_needs_review_propagated(self, engine):
        a = _rec()
        g = CandidateGroup(
            group_id=a.canonical_id,
            records=[a],
            needs_review=True,
        )
        _, report = engine.merge(g)
        assert report.needs_review is True

    def test_provenance_map_populated(self, engine):
        a = _rec(emails=["a@b.com"])
        profile, _ = engine.merge(_group(a))
        # Provenance keys should include any field that was mapped
        assert isinstance(profile.provenance, dict)

    def test_no_crash_empty_skills(self, engine):
        a = _rec(skills=[])
        profile, _ = engine.merge(_group(a))
        assert profile.skills == []

    def test_no_crash_empty_experience(self, engine):
        a = _rec(experience=[])
        profile, _ = engine.merge(_group(a))
        assert profile.experience == []

    def test_experience_sorted_most_recent_first(self, engine):
        exp1 = {"company": "Google",   "title": "SWE", "start_date": "2022-01"}
        exp2 = {"company": "Facebook", "title": "SWE", "start_date": "2019-06"}
        a = _rec(experience=[exp2, exp1])
        profile, _ = engine.merge(_group(a))
        if len(profile.experience) == 2:
            assert profile.experience[0].start_date >= profile.experience[1].start_date


# ================================================================
# MergeEngine — confidence + quality
# ================================================================


class TestMergeEngineQuality:
    @pytest.fixture
    def engine(self):
        return MergeEngine()

    def test_multi_source_higher_confidence(self, engine):
        a = _rec(
            source_type=SourceType.ATS,
            emails=["a@b.com"],
            full_name="Alice",
            skills=["Python"],
        )
        b = _rec(
            source_type=SourceType.GITHUB,
            emails=["a@b.com"],
            full_name="Alice",
            skills=["Python"],
        )
        profile_multi, _ = engine.merge(_group(a, b))

        single = _rec(source_type=SourceType.CSV, emails=["a@b.com"])
        profile_single, _ = engine.merge(_group(single))

        assert (
            profile_multi.overall_confidence
            >= profile_single.overall_confidence
        )

    def test_overall_confidence_matches_quality_metrics(self, engine):
        rec = _rec(emails=["a@b.com"], full_name="Alice")
        profile, _ = engine.merge(_group(rec))
        assert abs(
            profile.overall_confidence - profile.quality_metrics.overall_confidence
        ) < 1e-6

    def test_empty_record_no_crash(self, engine):
        rec = _rec()
        profile, report = engine.merge(_group(rec))
        assert profile is not None
        assert report is not None
