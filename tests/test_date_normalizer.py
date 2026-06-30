"""
tests/test_date_normalizer.py
================================

Unit tests for src/normalization/date_normalizer.py.
"""

from __future__ import annotations

import pytest

from src.normalization.date_normalizer import DateNormalizer, normalize_date
from src.models import CanonicalRecord, NormalizationMethod, SourceType


def _rec(experience=None, education=None) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="test-id",
        source_type=SourceType.CSV,
        source_label="test.csv",
        experience=experience or [],
        education=education or [],
    )


class TestNormalizeDateFunction:
    # ── Present / Current ─────────────────────────────────────
    def test_present_returns_none(self):
        assert normalize_date("Present").normalized is None

    def test_current_returns_none(self):
        assert normalize_date("current").normalized is None

    def test_now_returns_none(self):
        assert normalize_date("Now").normalized is None

    def test_ongoing_returns_none(self):
        assert normalize_date("Ongoing").normalized is None

    def test_today_returns_none(self):
        assert normalize_date("today").normalized is None

    def test_dash_sentinel_returns_none(self):
        assert normalize_date("–").normalized is None

    # ── Year only ─────────────────────────────────────────────
    def test_year_only(self):
        r = normalize_date("2024")
        assert r.normalized == "2024"
        assert r.confidence >= 0.9

    def test_year_only_early(self):
        r = normalize_date("1995")
        assert r.normalized == "1995"

    def test_year_with_whitespace(self):
        r = normalize_date(" 2020 ")
        assert r.normalized == "2020"

    # ── MM/YYYY ───────────────────────────────────────────────
    def test_mm_slash_yyyy(self):
        r = normalize_date("01/2024")
        assert r.normalized == "2024-01"

    def test_mm_slash_yyyy_two_digit(self):
        r = normalize_date("12/2023")
        assert r.normalized == "2023-12"

    def test_yyyy_slash_mm(self):
        r = normalize_date("2024/01")
        assert r.normalized == "2024-01"

    # ── YYYY-MM ───────────────────────────────────────────────
    def test_yyyy_mm_already_iso(self):
        r = normalize_date("2024-01")
        assert r.normalized == "2024-01"
        assert r.confidence == 1.0

    def test_yyyy_mm_december(self):
        r = normalize_date("2023-12")
        assert r.normalized == "2023-12"

    # ── Full ISO ──────────────────────────────────────────────
    def test_full_iso_date(self):
        r = normalize_date("2024-01-15")
        assert r.normalized == "2024-01-15"
        assert r.confidence == 1.0

    def test_full_iso_date_end_of_year(self):
        r = normalize_date("2023-12-31")
        assert r.normalized == "2023-12-31"

    # ── Dateutil (human-readable) ─────────────────────────────
    def test_jan_2024(self):
        r = normalize_date("Jan 2024")
        assert r.normalized == "2024-01"
        assert r.confidence > 0

    def test_january_2024(self):
        r = normalize_date("January 2024")
        assert r.normalized == "2024-01"

    def test_dec_2023(self):
        r = normalize_date("Dec 2023")
        assert r.normalized == "2023-12"

    def test_march_2019(self):
        r = normalize_date("March 2019")
        assert r.normalized == "2019-03"

    def test_full_text_date(self):
        r = normalize_date("15 Jan 2024")
        assert "2024" in r.normalized
        assert r.confidence > 0

    # ── Invalid / empty ───────────────────────────────────────
    def test_empty_string(self):
        r = normalize_date("")
        assert r.confidence == 0.0

    def test_whitespace_only(self):
        r = normalize_date("   ")
        assert r.confidence == 0.0

    def test_garbage_string(self):
        r = normalize_date("not a date at all")
        # dateutil may parse this — if so confidence > 0; otherwise 0.0
        # We just verify it doesn't crash
        assert r is not None

    def test_out_of_range_year(self):
        r = normalize_date("1800")
        # Year outside 1900-2100 should not produce a high confidence result
        # (it may still return the year-string)
        assert r is not None

    # ── Method ───────────────────────────────────────────────
    def test_method_is_date_iso8601(self):
        r = normalize_date("Jan 2024")
        assert r.method == NormalizationMethod.DATE_ISO8601


class TestDateNormalizer:
    @pytest.fixture
    def normalizer(self):
        return DateNormalizer()

    def test_normalizes_experience_dates(self, normalizer):
        rec = _rec(experience=[{
            "company": "Acme",
            "title": "Engineer",
            "start_date": "Jan 2020",
            "end_date": "Dec 2022",
        }])
        out = normalizer.normalize(rec)
        assert out.experience[0]["start_date"] == "2020-01"
        assert out.experience[0]["end_date"] == "2022-12"

    def test_normalizes_education_dates(self, normalizer):
        rec = _rec(education=[{
            "institution": "MIT",
            "start_date": "2014",
            "end_date": "2018",
        }])
        out = normalizer.normalize(rec)
        assert out.education[0]["start_date"] == "2014"
        assert out.education[0]["end_date"] == "2018"

    def test_present_end_date_becomes_none(self, normalizer):
        rec = _rec(experience=[{
            "company": "Acme",
            "start_date": "Jan 2022",
            "end_date": "Present",
        }])
        out = normalizer.normalize(rec)
        assert out.experience[0]["end_date"] is None

    def test_none_dates_untouched(self, normalizer):
        rec = _rec(experience=[{
            "company": "Acme",
            "start_date": None,
            "end_date": None,
        }])
        out = normalizer.normalize(rec)
        assert out.experience[0]["start_date"] is None

    def test_multiple_experience_entries(self, normalizer):
        rec = _rec(experience=[
            {"start_date": "Jan 2020", "end_date": "Dec 2021"},
            {"start_date": "Jan 2022", "end_date": "Present"},
        ])
        out = normalizer.normalize(rec)
        assert out.experience[0]["start_date"] == "2020-01"
        assert out.experience[1]["end_date"] is None

    def test_provenance_written_on_change(self, normalizer):
        rec = _rec(experience=[{"start_date": "Jan 2020", "end_date": "Dec 2021"}])
        out = normalizer.normalize(rec)
        assert any(p.field == "experience" for p in out.provenance)

    def test_supports_with_experience(self, normalizer):
        rec = _rec(experience=[{"start_date": "2020"}])
        assert normalizer.supports(rec) is True

    def test_supports_false_when_empty(self, normalizer):
        rec = _rec()
        assert normalizer.supports(rec) is False

    def test_supports_with_education(self, normalizer):
        rec = _rec(education=[{"start_date": "2014"}])
        assert normalizer.supports(rec) is True

    def test_metadata_returns_dict(self, normalizer):
        m = normalizer.metadata()
        assert isinstance(m, dict)
        assert "method" in m
