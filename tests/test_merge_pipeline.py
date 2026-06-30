"""
tests/test_merge_pipeline.py
==============================

Integration tests for the full merge pipeline:
  IdentityResolver → MergeEngine → CandidateProfile + MergeReport
"""

from __future__ import annotations

import pytest

from src.merge.factory import MergeFactory
from src.merge.identity_resolver import CandidateGroup, IdentityResolver
from src.merge.merge_engine import MergeEngine
from src.merge.pipeline import MergePipeline
from src.models import CanonicalRecord, CandidateProfile, SourceType


def _rec(
    source_type: SourceType = SourceType.CSV,
    emails: list[str] | None = None,
    full_name: str | None = None,
    skills: list[str] | None = None,
    github_url: str | None = None,
    linkedin_url: str | None = None,
    current_company: str | None = None,
    mapped_fields: list[str] | None = None,
) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="r1",
        source_type=source_type,
        source_label="test",
        emails=emails or [],
        full_name=full_name,
        skills=skills or [],
        github_url=github_url,
        linkedin_url=linkedin_url,
        current_company=current_company,
        mapped_fields=mapped_fields or ["emails"],
    )


def _build_pipeline(**config_kwargs) -> MergePipeline:
    return MergeFactory.build_default_pipeline(config=config_kwargs or None)


# ================================================================
# Basic pipeline execution
# ================================================================


class TestPipelineBasic:
    def test_empty_input_returns_empty(self):
        pipeline = _build_pipeline()
        profiles, reports = pipeline.run([])
        assert profiles == []
        assert reports == []

    def test_single_record_one_profile(self):
        pipeline = _build_pipeline()
        rec = _rec(emails=["a@b.com"])
        profiles, reports = pipeline.run([rec])
        assert len(profiles) == 1
        assert len(reports) == 1

    def test_returns_tuple_of_lists(self):
        pipeline = _build_pipeline()
        result = pipeline.run([_rec(emails=["a@b.com"])])
        assert isinstance(result, tuple)
        assert isinstance(result[0], list)
        assert isinstance(result[1], list)

    def test_profiles_and_reports_same_length(self):
        pipeline = _build_pipeline()
        records = [_rec(emails=[f"user{i}@x.com"]) for i in range(5)]
        profiles, reports = pipeline.run(records)
        assert len(profiles) == len(reports)

    def test_profile_is_candidate_profile_instance(self):
        pipeline = _build_pipeline()
        profiles, _ = pipeline.run([_rec(emails=["a@b.com"])])
        assert isinstance(profiles[0], CandidateProfile)


# ================================================================
# Identity grouping through pipeline
# ================================================================


class TestPipelineIdentityGrouping:
    def test_same_email_produces_one_profile(self):
        pipeline = _build_pipeline()
        a = _rec(source_type=SourceType.ATS,    emails=["alice@x.com"])
        b = _rec(source_type=SourceType.GITHUB,  emails=["alice@x.com"])
        profiles, _ = pipeline.run([a, b])
        assert len(profiles) == 1

    def test_different_emails_produce_two_profiles(self):
        pipeline = _build_pipeline()
        a = _rec(emails=["alice@x.com"])
        b = _rec(emails=["bob@x.com"])
        profiles, _ = pipeline.run([a, b])
        assert len(profiles) == 2

    def test_three_records_two_candidates(self):
        pipeline = _build_pipeline()
        a = _rec(emails=["alice@x.com"])
        b = _rec(emails=["alice@x.com"])  # same as a
        c = _rec(emails=["carol@x.com"])
        profiles, _ = pipeline.run([a, b, c])
        assert len(profiles) == 2

    def test_merged_records_contains_all_sources(self):
        pipeline = _build_pipeline()
        a = _rec(source_type=SourceType.ATS,    emails=["alice@x.com"])
        b = _rec(source_type=SourceType.GITHUB,  emails=["alice@x.com"])
        _, reports = pipeline.run([a, b])
        assert len(reports[0].merged_records) == 2


# ================================================================
# emit_single_source config
# ================================================================


class TestEmitSingleSource:
    def test_single_source_included_by_default(self):
        pipeline = _build_pipeline()
        rec = _rec(emails=["a@b.com"])
        profiles, _ = pipeline.run([rec])
        assert len(profiles) == 1

    def test_single_source_filtered_when_disabled(self):
        pipeline = MergeFactory.build_default_pipeline(config={
            "pipeline": {"emit_single_source": False}
        })
        a = _rec(emails=["a@b.com"])  # will be single-source group
        b = _rec(emails=["b@b.com"])  # also single-source
        c = _rec(source_type=SourceType.ATS,    emails=["c@b.com"])
        d = _rec(source_type=SourceType.GITHUB,  emails=["c@b.com"])  # merged with c
        profiles, _ = pipeline.run([a, b, c, d])
        # Only the merged group (c+d) should be emitted
        assert len(profiles) == 1


# ================================================================
# Conflict handling through pipeline
# ================================================================


class TestPipelineConflicts:
    def test_conflict_recorded_in_report(self):
        pipeline = _build_pipeline()
        a = _rec(source_type=SourceType.ATS, emails=["alice@x.com"],
                 full_name="Alice Smith")
        b = _rec(source_type=SourceType.CSV, emails=["alice@x.com"],
                 full_name="A. Smith")
        _, reports = pipeline.run([a, b])
        conflict_fields = [c.field for c in reports[0].conflicts]
        assert "full_name" in conflict_fields

    def test_ats_name_beats_csv(self):
        pipeline = _build_pipeline()
        a = _rec(source_type=SourceType.ATS, emails=["alice@x.com"],
                 full_name="Alice Smith")
        b = _rec(source_type=SourceType.CSV, emails=["alice@x.com"],
                 full_name="A. Smith")
        profiles, _ = pipeline.run([a, b])
        assert profiles[0].full_name == "Alice Smith"


# ================================================================
# quality_metrics populated
# ================================================================


class TestPipelineQuality:
    def test_quality_metrics_not_none(self):
        pipeline = _build_pipeline()
        profiles, _ = pipeline.run([_rec(emails=["a@b.com"])])
        assert profiles[0].quality_metrics is not None

    def test_overall_confidence_in_range(self):
        pipeline = _build_pipeline()
        profiles, _ = pipeline.run([_rec(emails=["a@b.com"])])
        assert 0.0 <= profiles[0].overall_confidence <= 1.0


# ================================================================
# Factory presets
# ================================================================


class TestFactoryPresets:
    def test_strict_pipeline_builds(self):
        p = MergeFactory.build_strict_pipeline()
        assert isinstance(p, MergePipeline)

    def test_lenient_pipeline_builds(self):
        p = MergeFactory.build_lenient_pipeline()
        assert isinstance(p, MergePipeline)

    def test_majority_vote_pipeline_builds(self):
        p = MergeFactory.build_majority_vote_pipeline()
        assert isinstance(p, MergePipeline)

    def test_most_recent_pipeline_builds(self):
        p = MergeFactory.build_most_recent_pipeline()
        assert isinstance(p, MergePipeline)

    def test_strict_has_higher_threshold(self):
        strict  = MergeFactory.build_strict_pipeline()
        lenient = MergeFactory.build_lenient_pipeline()
        assert (
            strict._resolver._match_threshold
            > lenient._resolver._match_threshold
        )

    def test_custom_strategy_passed_through(self):
        p = MergeFactory.build_default_pipeline(config={"strategy": "majority_vote"})
        from src.models import MergeStrategy
        assert p._engine._resolver._strategy == MergeStrategy.MAJORITY_VOTE

    def test_field_strategy_override(self):
        p = MergeFactory.build_default_pipeline(config={
            "field_strategies": {"headline": "most_recent"}
        })
        from src.models import MergeStrategy
        assert p._engine._resolver._field_strategies.get("headline") == \
               MergeStrategy.MOST_RECENT


# ================================================================
# run_single_group
# ================================================================


class TestRunSingleGroup:
    def test_run_single_group(self):
        pipeline = _build_pipeline()
        a = _rec(emails=["a@b.com"])
        g = CandidateGroup(group_id=a.canonical_id, records=[a])
        profile, report = pipeline.run_single_group(g)
        assert isinstance(profile, CandidateProfile)

    def test_repr_contains_class_names(self):
        pipeline = _build_pipeline()
        r = repr(pipeline)
        assert "MergePipeline" in r


# ================================================================
# End-to-end integration
# ================================================================


class TestEndToEnd:
    def test_full_merge_four_sources(self):
        pipeline = _build_pipeline()
        ats    = _rec(source_type=SourceType.ATS,
                      emails=["alice@acme.com"],
                      full_name="Alice Smith",
                      current_company="ACME Corp",
                      skills=["Python", "SQL"])
        github = _rec(source_type=SourceType.GITHUB,
                      emails=["alice@acme.com"],
                      skills=["Python", "Docker", "Kubernetes"])
        csv    = _rec(source_type=SourceType.CSV,
                      emails=["alice@acme.com", "alice@personal.com"],
                      full_name="A. Smith")
        resume = _rec(source_type=SourceType.RESUME,
                      emails=["alice@acme.com"],
                      full_name="Alice M. Smith",
                      skills=["Python", "Machine Learning"])

        profiles, reports = pipeline.run([ats, github, csv, resume])

        assert len(profiles) == 1
        p = profiles[0]
        r = reports[0]

        # All emails collected
        assert "alice@acme.com" in p.emails
        assert "alice@personal.com" in p.emails
        assert p.emails.count("alice@acme.com") == 1  # deduped

        # ATS name wins over CSV
        assert p.full_name == "Alice Smith"

        # Skills union across all 4 sources
        skill_names = [s.normalized_name for s in p.skills]
        assert "Python"    in skill_names
        assert "Docker"    in skill_names
        assert "Kubernetes" in skill_names

        # Quality
        assert p.overall_confidence is not None
        assert p.quality_metrics.completeness > 0.0

        # 4 records merged
        assert len(r.merged_records) == 4
