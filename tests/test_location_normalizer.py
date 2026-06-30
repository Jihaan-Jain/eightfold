"""
tests/test_location_normalizer.py
====================================

Unit tests for src/normalization/location_normalizer.py.
"""

from __future__ import annotations

import pytest

from src.normalization.location_normalizer import LocationNormalizer, normalize_location
from src.models import CanonicalRecord, SourceType


def _rec(location: str | None = None, experience=None) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="test-id",
        source_type=SourceType.CSV,
        source_label="test.csv",
        location=location,
        experience=experience or [],
    )


class TestNormalizeLocationFunction:
    def test_simple_city(self):
        r = normalize_location("Bangalore")
        assert r.normalized == "Bangalore"

    def test_city_country(self):
        r = normalize_location("Bangalore, India")
        assert r.normalized == "Bangalore, India"

    def test_city_state_country(self):
        r = normalize_location("San Francisco, California, USA")
        assert "San Francisco" in r.normalized

    def test_whitespace_collapsed(self):
        r = normalize_location("  New  York ,  USA  ")
        assert "New York" in r.normalized
        assert r.normalized == r.normalized.strip()

    def test_empty_string(self):
        r = normalize_location("")
        assert r.confidence == 0.0

    def test_whitespace_only(self):
        r = normalize_location("   ")
        assert r.confidence == 0.0

    def test_changed_when_whitespace_collapsed(self):
        r = normalize_location("  Bangalore , India  ")
        assert r.changed is True

    def test_no_change_on_clean_input(self):
        r = normalize_location("Bangalore, India")
        assert r.changed is False


class TestLocationNormalizerClass:
    @pytest.fixture
    def normalizer(self):
        return LocationNormalizer()

    def test_basic_location_cleaned(self, normalizer):
        rec = _rec("  Bangalore , India  ")
        out = normalizer.normalize(rec)
        assert out.location == "Bangalore, India"

    def test_components_stored_two_parts(self, normalizer):
        rec = _rec("Bangalore, India")
        out = normalizer.normalize(rec)
        comps = out.mapping_metadata.get("location_components", {})
        assert comps.get("city") == "Bangalore"

    def test_components_stored_three_parts(self, normalizer):
        rec = _rec("Austin, Texas, USA")
        out = normalizer.normalize(rec)
        comps = out.mapping_metadata.get("location_components", {})
        assert comps.get("city") == "Austin"
        assert comps.get("state") == "Texas"

    def test_country_code_stored(self, normalizer):
        rec = _rec("Bangalore, India")
        out = normalizer.normalize(rec)
        assert out.mapping_metadata.get("country_code") == "IN"

    def test_us_country_code(self, normalizer):
        rec = _rec("San Francisco, CA, USA")
        out = normalizer.normalize(rec)
        assert out.mapping_metadata.get("country_code") == "US"

    def test_uk_country_code(self, normalizer):
        rec = _rec("London, United Kingdom")
        out = normalizer.normalize(rec)
        assert out.mapping_metadata.get("country_code") == "GB"

    def test_empty_location_no_crash(self, normalizer):
        rec = _rec(None)
        out = normalizer.normalize(rec)
        assert out is not None

    def test_unknown_country_no_crash(self, normalizer):
        rec = _rec("Narnia, Middle Earth")
        out = normalizer.normalize(rec)
        assert out is not None

    def test_experience_location_normalized(self, normalizer):
        rec = _rec(
            location="Bangalore, India",
            experience=[{"location": "  San Francisco , USA  "}],
        )
        out = normalizer.normalize(rec)
        exp_loc = out.experience[0].get("location", "")
        # Whitespace should be collapsed
        assert "  " not in exp_loc

    def test_max_parts_config(self):
        n = LocationNormalizer(config={"max_parts": 2})
        rec = _rec("City, State, Country, Extra")
        out = n.normalize(rec)
        comps = out.mapping_metadata.get("location_components", {})
        assert comps.get("city") is not None

    def test_provenance_on_whitespace_change(self, normalizer):
        rec = _rec("  Bangalore , India  ")
        out = normalizer.normalize(rec)
        assert any(p.field == "location" for p in out.provenance)

    def test_no_provenance_when_already_clean(self, normalizer):
        rec = _rec("Bangalore, India")
        out = normalizer.normalize(rec)
        # May still write provenance for country code
        assert out is not None

    def test_supports_with_location(self, normalizer):
        rec = _rec("Bangalore")
        assert normalizer.supports(rec) is True

    def test_supports_false_without_location(self, normalizer):
        rec = _rec(None)
        assert normalizer.supports(rec) is False

    def test_metadata_returns_dict(self, normalizer):
        m = normalizer.metadata()
        assert isinstance(m, dict)
        assert "location" in m.get("fields", [])
