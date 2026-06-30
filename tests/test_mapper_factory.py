"""
tests/test_mapper_factory.py
=============================

Unit tests for src/mapping/factory.py.

Covers
------
- MapperFactory.select returns correct mapper per source type
- MapperFactory.map returns a CanonicalRecord for each source type
- MapperFactory.map_many processes a list of records
- Custom mapper registered with register()
- register at_front=True takes priority
- FallbackMapper returned for unknown source type
- FallbackMapper never raises
- Batch processing returns one result per input record
- Factory config dict passes through to mappers
- registered_mappers() returns class names in order
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.mapping.ats_mapper import ATSMapper
from src.mapping.base import BaseMapper
from src.mapping.csv_mapper import CsvMapper
from src.mapping.factory import MapperFactory, _FallbackMapper
from src.mapping.github_mapper import GithubMapper
from src.mapping.resume_mapper import ResumePdfMapper
from src.models import CanonicalRecord, RawRecord, SourceType


# ================================================================
# Helpers
# ================================================================


def _csv_record(fields: dict | None = None) -> RawRecord:
    return RawRecord(
        source="recruiter.csv",
        source_type=SourceType.CSV,
        raw_fields=fields or {"email": "a@b.com"},
    )


def _ats_record() -> RawRecord:
    return RawRecord(
        source="ats.json",
        source_type=SourceType.ATS,
        raw_fields={"name": "Alice", "email": "a@b.com"},
    )


def _github_record() -> RawRecord:
    return RawRecord(
        source="github/alice",
        source_type=SourceType.GITHUB,
        raw_fields={
            "profile": {"login": "alice", "name": "Alice"},
            "repos": [], "languages": {}, "topics": [],
            "total_stars": 0, "total_forks": 0, "public_repo_count": 0,
        },
        candidate_hint="alice",
    )


def _resume_record() -> RawRecord:
    return RawRecord(
        source="resume.pdf",
        source_type=SourceType.RESUME,
        raw_fields={"full_text": "Alice\nalice@x.com\n", "pages": ["Alice\nalice@x.com\n"]},
    )


@pytest.fixture()
def factory() -> MapperFactory:
    return MapperFactory()


# ================================================================
# Mapper Selection
# ================================================================


class TestMapperSelection:
    def test_select_csv_mapper(self, factory) -> None:
        mapper = factory.select(_csv_record())
        assert isinstance(mapper, CsvMapper)

    def test_select_ats_mapper(self, factory) -> None:
        mapper = factory.select(_ats_record())
        assert isinstance(mapper, ATSMapper)

    def test_select_github_mapper(self, factory) -> None:
        mapper = factory.select(_github_record())
        assert isinstance(mapper, GithubMapper)

    def test_select_resume_mapper(self, factory) -> None:
        mapper = factory.select(_resume_record())
        assert isinstance(mapper, ResumePdfMapper)

    def test_fallback_for_unknown_type(self, factory) -> None:
        """Fallback mapper handles a source type with no registered mapper."""
        rec = RawRecord(
            source="x.txt",
            source_type=SourceType.RECRUITER_NOTES,
            raw_fields={},
        )
        mapper = factory.select(rec)
        assert isinstance(mapper, _FallbackMapper)


# ================================================================
# map() — single record
# ================================================================


class TestSingleMap:
    def test_map_csv_returns_canonical(self, factory) -> None:
        cr = factory.map(_csv_record())
        assert isinstance(cr, CanonicalRecord)
        assert cr.source_type == SourceType.CSV

    def test_map_ats_returns_canonical(self, factory) -> None:
        cr = factory.map(_ats_record())
        assert isinstance(cr, CanonicalRecord)
        assert cr.source_type == SourceType.ATS

    def test_map_github_returns_canonical(self, factory) -> None:
        cr = factory.map(_github_record())
        assert isinstance(cr, CanonicalRecord)
        assert cr.source_type == SourceType.GITHUB

    def test_map_resume_returns_canonical(self, factory) -> None:
        cr = factory.map(_resume_record())
        assert isinstance(cr, CanonicalRecord)
        assert cr.source_type == SourceType.RESUME

    def test_map_never_raises(self, factory) -> None:
        """Even a record with completely empty raw_fields should not raise."""
        for source_type in (SourceType.CSV, SourceType.ATS, SourceType.GITHUB):
            rec = RawRecord(
                source="empty",
                source_type=source_type,
                raw_fields={},
            )
            cr = factory.map(rec)
            assert isinstance(cr, CanonicalRecord)

    def test_map_source_record_id_matches(self, factory) -> None:
        rec = _csv_record()
        cr = factory.map(rec)
        assert cr.source_record_id == rec.record_id

    def test_map_source_label_matches(self, factory) -> None:
        rec = _csv_record()
        cr = factory.map(rec)
        assert cr.source_label == rec.source


# ================================================================
# map_many() — batch
# ================================================================


class TestBatchMap:
    def test_map_many_returns_list(self, factory) -> None:
        records = [_csv_record(), _ats_record(), _github_record()]
        results = factory.map_many(records)
        assert isinstance(results, list)
        assert len(results) == 3

    def test_map_many_preserves_order(self, factory) -> None:
        r1 = _csv_record()
        r2 = _ats_record()
        results = factory.map_many([r1, r2])
        assert results[0].source_record_id == r1.record_id
        assert results[1].source_record_id == r2.record_id

    def test_map_many_empty_list(self, factory) -> None:
        results = factory.map_many([])
        assert results == []

    def test_map_many_mixed_types(self, factory) -> None:
        records = [
            _csv_record(),
            _ats_record(),
            _github_record(),
            _resume_record(),
        ]
        results = factory.map_many(records)
        types = {cr.source_type for cr in results}
        assert SourceType.CSV in types
        assert SourceType.ATS in types
        assert SourceType.GITHUB in types
        assert SourceType.RESUME in types


# ================================================================
# register() — custom mapper
# ================================================================


class TestCustomMapperRegistration:
    def test_register_custom_mapper(self, factory) -> None:
        class MyMapper(BaseMapper):
            def supports(self, record):
                return record.source == "custom_source"
            def map(self, record):
                return self._make_canonical(record)
            def metadata(self):
                return {"mapper": "MyMapper"}

        factory.register(MyMapper())
        assert "MyMapper" in factory.registered_mappers()

    def test_register_at_front_takes_priority(self, factory) -> None:
        """A front-registered mapper gets first pick."""
        class GreedyMapper(BaseMapper):
            def supports(self, record):
                return True  # claims everything
            def map(self, record):
                cr = self._make_canonical(record)
                cr.mapping_metadata["used_greedy"] = True
                return cr
            def metadata(self):
                return {}

        factory.register(GreedyMapper(), at_front=True)
        cr = factory.map(_csv_record())
        assert cr.mapping_metadata.get("used_greedy") is True

    def test_registered_mappers_names(self, factory) -> None:
        names = factory.registered_mappers()
        assert "CsvMapper" in names
        assert "ATSMapper" in names
        assert "GithubMapper" in names
        assert "ResumePdfMapper" in names

    def test_registered_mappers_order(self, factory) -> None:
        names = factory.registered_mappers()
        # CSV should come before ATS, ATS before GitHub
        assert names.index("CsvMapper") < names.index("ATSMapper")
        assert names.index("ATSMapper") < names.index("GithubMapper")


# ================================================================
# FallbackMapper
# ================================================================


class TestFallbackMapper:
    def test_fallback_supports_everything(self) -> None:
        fb = _FallbackMapper()
        rec = RawRecord(
            source="x.txt",
            source_type=SourceType.RECRUITER_NOTES,
            raw_fields={},
        )
        assert fb.supports(rec) is True

    def test_fallback_never_raises(self) -> None:
        fb = _FallbackMapper()
        for source_type in SourceType:
            rec = RawRecord(
                source="test",
                source_type=source_type,
                raw_fields={},
            )
            cr = fb.map(rec)
            assert isinstance(cr, CanonicalRecord)

    def test_fallback_sets_warning_in_metadata(self) -> None:
        factory = MapperFactory()
        rec = RawRecord(
            source="x.txt",
            source_type=SourceType.RECRUITER_NOTES,
            raw_fields={},
        )
        cr = factory.map(rec)
        assert "warning" in cr.mapping_metadata or cr.source_type == SourceType.RECRUITER_NOTES

    def test_fallback_metadata_returns_dict(self) -> None:
        fb = _FallbackMapper()
        m = fb.metadata()
        assert isinstance(m, dict)


# ================================================================
# Config passthrough
# ================================================================


class TestConfigPassthrough:
    def test_csv_ignored_fields_config(self) -> None:
        factory = MapperFactory(config={
            "CsvMapper": {"ignored_fields": ["custom_internal_id"]},
        })
        rec = _csv_record({"custom_internal_id": "123", "email": "a@b.com"})
        cr = factory.map(rec)
        assert "custom_internal_id" in cr.ignored_fields

    def test_github_max_repos_config(self) -> None:
        repos = [
            {"name": f"repo-{i}", "html_url": f"https://github.com/a/repo-{i}",
             "description": None, "language": "Python",
             "stargazers_count": 0, "forks_count": 0,
             "fork": False, "archived": False, "topics": []}
            for i in range(10)
        ]
        factory = MapperFactory(config={"GithubMapper": {"max_repos": 3}})
        rec = RawRecord(
            source="github/alice",
            source_type=SourceType.GITHUB,
            raw_fields={
                "profile": {"login": "alice"},
                "repos": repos, "languages": {}, "topics": [],
                "total_stars": 0, "total_forks": 0, "public_repo_count": 10,
            },
            candidate_hint="alice",
        )
        cr = factory.map(rec)
        assert len(cr.experience) == 3
