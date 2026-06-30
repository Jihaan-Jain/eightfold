"""
tests/test_country_normalizer.py
==================================

Unit tests for src/normalization/country_normalizer.py.
"""

from __future__ import annotations

import pytest

from src.normalization.country_normalizer import (
    CountryNormalizer,
    country_to_alpha2,
    normalize_country,
)
from src.models import CanonicalRecord, SourceType


def _rec(location: str | None = None) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="test-id",
        source_type=SourceType.CSV,
        source_label="test.csv",
        location=location,
    )


class TestCountryToAlpha2:
    # ── Alias table hits ──────────────────────────────────────
    def test_india_full_name(self):
        assert country_to_alpha2("India") == "IN"

    def test_india_full_name_lowercase(self):
        assert country_to_alpha2("india") == "IN"

    def test_usa_abbreviation(self):
        assert country_to_alpha2("USA") == "US"

    def test_us_abbreviation(self):
        assert country_to_alpha2("US") == "US"

    def test_united_states(self):
        assert country_to_alpha2("United States") == "US"

    def test_united_states_of_america(self):
        assert country_to_alpha2("United States of America") == "US"

    def test_uk_abbreviation(self):
        assert country_to_alpha2("UK") == "GB"

    def test_united_kingdom(self):
        assert country_to_alpha2("United Kingdom") == "GB"

    def test_republic_of_india(self):
        assert country_to_alpha2("Republic of India") == "IN"

    def test_great_britain(self):
        assert country_to_alpha2("Great Britain") == "GB"

    def test_prc(self):
        assert country_to_alpha2("PRC") == "CN"

    def test_russian_federation(self):
        assert country_to_alpha2("Russian Federation") == "RU"

    def test_south_korea(self):
        assert country_to_alpha2("South Korea") == "KR"

    def test_uae(self):
        assert country_to_alpha2("UAE") == "AE"

    def test_singapore(self):
        assert country_to_alpha2("Singapore") == "SG"

    def test_australia(self):
        assert country_to_alpha2("Australia") == "AU"

    def test_canada(self):
        assert country_to_alpha2("Canada") == "CA"

    def test_germany(self):
        assert country_to_alpha2("Germany") == "DE"

    def test_japan(self):
        assert country_to_alpha2("Japan") == "JP"

    def test_brazil(self):
        assert country_to_alpha2("Brazil") == "BR"

    def test_brasil_variant(self):
        assert country_to_alpha2("Brasil") == "BR"

    def test_netherlands(self):
        assert country_to_alpha2("Netherlands") == "NL"

    def test_holland(self):
        assert country_to_alpha2("Holland") == "NL"

    def test_pakistan(self):
        assert country_to_alpha2("Pakistan") == "PK"

    def test_bangladesh(self):
        assert country_to_alpha2("Bangladesh") == "BD"

    def test_nigeria(self):
        assert country_to_alpha2("Nigeria") == "NG"

    # ── Alpha-2 pass-through ──────────────────────────────────
    def test_alpha2_passthrough_in(self):
        assert country_to_alpha2("IN") == "IN"

    def test_alpha2_passthrough_us(self):
        assert country_to_alpha2("US") == "US"

    def test_alpha2_lowercase_in(self):
        assert country_to_alpha2("in") == "IN"

    # ── pycountry fallback ────────────────────────────────────
    def test_france_via_pycountry(self):
        result = country_to_alpha2("France")
        assert result == "FR"

    def test_alpha3_ind(self):
        result = country_to_alpha2("IND")
        assert result == "IN"

    def test_alpha3_usa(self):
        result = country_to_alpha2("USA")
        assert result == "US"

    def test_alpha3_gbr(self):
        result = country_to_alpha2("GBR")
        assert result == "GB"

    # ── Invalid / empty ───────────────────────────────────────
    def test_empty_returns_none(self):
        assert country_to_alpha2("") is None

    def test_whitespace_returns_none(self):
        assert country_to_alpha2("   ") is None

    def test_garbage_returns_none(self):
        result = country_to_alpha2("xyzzy_invalid_country_name_1234")
        assert result is None

    def test_number_returns_none(self):
        result = country_to_alpha2("12345")
        assert result is None


class TestNormalizeCountryFunction:
    def test_india_normalized(self):
        r = normalize_country("India")
        assert r.normalized == "IN"
        assert r.confidence == 1.0

    def test_invalid_unchanged(self):
        r = normalize_country("xyzzy")
        assert r.normalized == "xyzzy"
        assert r.confidence == 0.0


class TestCountryNormalizerClass:
    @pytest.fixture
    def normalizer(self):
        return CountryNormalizer()

    def test_country_code_stored_in_metadata(self, normalizer):
        rec = _rec("Bangalore, India")
        out = normalizer.normalize(rec)
        assert out.mapping_metadata.get("country_code") == "IN"

    def test_city_state_country(self, normalizer):
        rec = _rec("San Francisco, California, United States")
        out = normalizer.normalize(rec)
        assert out.mapping_metadata.get("country_code") == "US"

    def test_unknown_country_no_crash(self, normalizer):
        rec = _rec("Some City, Narnia")
        out = normalizer.normalize(rec)
        assert out is not None

    def test_empty_location_no_crash(self, normalizer):
        rec = _rec(None)
        out = normalizer.normalize(rec)
        assert out is not None

    def test_supports_with_location(self, normalizer):
        rec = _rec("India")
        assert normalizer.supports(rec) is True

    def test_supports_false_without_location(self, normalizer):
        rec = _rec(None)
        assert normalizer.supports(rec) is False

    def test_provenance_written_on_resolution(self, normalizer):
        rec = _rec("Bangalore, India")
        out = normalizer.normalize(rec)
        assert any(p.field == "location" for p in out.provenance)

    def test_metadata_returns_dict(self, normalizer):
        m = normalizer.metadata()
        assert isinstance(m, dict)
        assert "method" in m
