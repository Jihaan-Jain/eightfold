"""
tests/test_normalization_pipeline.py
=======================================

Unit tests for src/normalization/pipeline.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from src.normalization.pipeline import NormalizationPipeline
from src.normalization.email_normalizer import EmailNormalizer
from src.normalization.name_normalizer import NameNormalizer
from src.normalization.skill_normalizer import SkillNormalizer
from src.normalization.company_normalizer import CompanyNormalizer
from src.normalization.url_normalizer import UrlNormalizer
from src.models import CanonicalRecord, SourceType


def _rec(**kwargs) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="test-id",
        source_type=SourceType.CSV,
        source_label="test.csv",
        **kwargs,
    )


# ================================================================
# Registration
# ================================================================


class TestRegistration:
    def test_add_normalizer(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        assert "EmailNormalizer" in pipeline.registered_names()

    def test_add_multiple(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        pipeline.add(NameNormalizer())
        names = pipeline.registered_names()
        assert "EmailNormalizer" in names
        assert "NameNormalizer" in names

    def test_order_preserved(self):
        pipeline = NormalizationPipeline()
        pipeline.add(NameNormalizer())
        pipeline.add(EmailNormalizer())
        names = pipeline.registered_names()
        assert names.index("NameNormalizer") < names.index("EmailNormalizer")

    def test_at_front_inserts_first(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        pipeline.add(NameNormalizer(), at_front=True)
        assert pipeline.registered_names()[0] == "NameNormalizer"

    def test_remove_existing(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        pipeline.add(NameNormalizer())
        result = pipeline.remove("EmailNormalizer")
        assert result is True
        assert "EmailNormalizer" not in pipeline.registered_names()

    def test_remove_nonexistent(self):
        pipeline = NormalizationPipeline()
        result = pipeline.remove("NonexistentNormalizer")
        assert result is False

    def test_len(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        pipeline.add(NameNormalizer())
        assert len(pipeline) == 2

    def test_repr_contains_names(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        r = repr(pipeline)
        assert "EmailNormalizer" in r


# ================================================================
# Execution — single record
# ================================================================


class TestSingleRun:
    def test_email_normalized(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        rec = _rec(emails=["ALICE@EXAMPLE.COM"])
        out = pipeline.run(rec)
        assert "alice@example.com" in out.emails

    def test_name_normalized(self):
        pipeline = NormalizationPipeline()
        pipeline.add(NameNormalizer())
        rec = _rec(full_name="alice smith")
        out = pipeline.run(rec)
        assert out.full_name == "Alice Smith"

    def test_skills_normalized(self):
        pipeline = NormalizationPipeline()
        pipeline.add(SkillNormalizer(config={"use_sbert": False}))
        rec = _rec(skills=["py", "js"])
        out = pipeline.run(rec)
        assert "Python" in out.skills
        assert "JavaScript" in out.skills

    def test_multiple_normalizers_chained(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        pipeline.add(NameNormalizer())
        rec = _rec(emails=["ALICE@EXAMPLE.COM"], full_name="alice smith")
        out = pipeline.run(rec)
        assert "alice@example.com" in out.emails
        assert out.full_name == "Alice Smith"

    def test_returns_same_record_object(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        rec = _rec(emails=["a@b.com"])
        out = pipeline.run(rec)
        assert out is rec  # mutated in-place

    def test_empty_pipeline_returns_record(self):
        pipeline = NormalizationPipeline()
        rec = _rec(emails=["a@b.com"])
        out = pipeline.run(rec)
        assert out.emails == ["a@b.com"]

    def test_no_crash_on_empty_record(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        pipeline.add(NameNormalizer())
        rec = _rec()
        out = pipeline.run(rec)
        assert out is not None


# ================================================================
# Disabled normalizers
# ================================================================


class TestDisabledNormalizers:
    def test_disabled_normalizer_skipped(self):
        pipeline = NormalizationPipeline(config={"disabled": ["EmailNormalizer"]})
        pipeline.add(EmailNormalizer())
        rec = _rec(emails=["ALICE@EXAMPLE.COM"])
        out = pipeline.run(rec)
        # Email NOT normalized because EmailNormalizer is disabled
        assert "ALICE@EXAMPLE.COM" in out.emails

    def test_other_normalizer_still_runs(self):
        pipeline = NormalizationPipeline(config={"disabled": ["EmailNormalizer"]})
        pipeline.add(EmailNormalizer())
        pipeline.add(NameNormalizer())
        rec = _rec(emails=["ALICE@EXAMPLE.COM"], full_name="alice smith")
        out = pipeline.run(rec)
        assert out.full_name == "Alice Smith"
        assert "ALICE@EXAMPLE.COM" in out.emails

    def test_multiple_disabled(self):
        pipeline = NormalizationPipeline(
            config={"disabled": ["EmailNormalizer", "NameNormalizer"]}
        )
        pipeline.add(EmailNormalizer())
        pipeline.add(NameNormalizer())
        rec = _rec(emails=["ALICE@EXAMPLE.COM"], full_name="alice smith")
        out = pipeline.run(rec)
        assert "ALICE@EXAMPLE.COM" in out.emails
        assert out.full_name == "alice smith"


# ================================================================
# supports() guard
# ================================================================


class TestSupportsGuard:
    def test_normalizer_skipped_when_supports_false(self):
        pipeline = NormalizationPipeline()
        n = EmailNormalizer()
        pipeline.add(n)
        # Record with no emails — supports() returns False
        rec = _rec()
        out = pipeline.run(rec)
        assert out.emails == []

    def test_normalizer_runs_when_supports_true(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        rec = _rec(emails=["ALICE@EXAMPLE.COM"])
        out = pipeline.run(rec)
        assert "alice@example.com" in out.emails


# ================================================================
# Batch — run_many
# ================================================================


class TestBatchRun:
    def test_run_many_returns_list(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        records = [
            _rec(emails=["A@B.COM"]),
            _rec(emails=["C@D.COM"]),
        ]
        results = pipeline.run_many(records)
        assert len(results) == 2

    def test_run_many_order_preserved(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        records = [
            _rec(emails=["A@B.COM"]),
            _rec(emails=["C@D.COM"]),
        ]
        results = pipeline.run_many(records)
        assert "a@b.com" in results[0].emails
        assert "c@d.com" in results[1].emails

    def test_run_many_empty_list(self):
        pipeline = NormalizationPipeline()
        results = pipeline.run_many([])
        assert results == []

    def test_run_many_mixed_records(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        pipeline.add(NameNormalizer())
        records = [
            _rec(emails=["A@B.COM"], full_name="alice"),
            _rec(emails=[], full_name="bob smith"),
        ]
        results = pipeline.run_many(records)
        assert "a@b.com" in results[0].emails
        assert results[1].full_name == "Bob Smith"


# ================================================================
# Provenance chain
# ================================================================


class TestProvenanceChain:
    def test_provenance_accumulated(self):
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        pipeline.add(NameNormalizer())
        rec = _rec(emails=["ALICE@EXAMPLE.COM"], full_name="alice smith")
        out = pipeline.run(rec)
        prov_fields = {p.field for p in out.provenance}
        assert "emails" in prov_fields
        assert "full_name" in prov_fields

    def test_provenance_stage_is_normalization(self):
        from src.models import ProcessingStage
        pipeline = NormalizationPipeline()
        pipeline.add(EmailNormalizer())
        rec = _rec(emails=["ALICE@EXAMPLE.COM"])
        out = pipeline.run(rec)
        for prov in out.provenance:
            assert prov.processing_stage == ProcessingStage.NORMALIZATION
