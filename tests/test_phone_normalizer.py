"""
tests/test_phone_normalizer.py
================================

Unit tests for src/normalization/phone_normalizer.py.
"""

from __future__ import annotations

import pytest

from src.normalization.phone_normalizer import PhoneNormalizer, normalize_phone
from src.models import CanonicalRecord, NormalizationMethod, SourceType


def _rec(phones: list[str], location: str | None = None) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="test-id",
        source_type=SourceType.CSV,
        source_label="test.csv",
        phones=phones,
        location=location,
    )


class TestNormalizePhoneFunction:
    def test_us_e164(self):
        r = normalize_phone("+14155552671")
        assert r.normalized == "+14155552671"
        assert r.confidence == 1.0

    def test_us_with_region(self):
        r = normalize_phone("(415) 555-2671", default_region="US")
        assert r.normalized == "+14155552671"
        assert r.method == NormalizationMethod.PHONE_E164

    def test_us_dashes(self):
        r = normalize_phone("415-555-2671", default_region="US")
        assert r.normalized == "+14155552671"

    def test_us_dots(self):
        r = normalize_phone("415.555.2671", default_region="US")
        assert r.normalized == "+14155552671"

    def test_international_plus(self):
        r = normalize_phone("+919876543210")
        assert r.normalized == "+919876543210"
        assert r.confidence == 1.0

    def test_uk_number(self):
        r = normalize_phone("+447911123456")
        assert r.normalized == "+447911123456"

    def test_india_number_with_region(self):
        r = normalize_phone("09876543210", default_region="IN")
        assert r.normalized == "+919876543210"

    def test_empty_returns_unchanged(self):
        r = normalize_phone("")
        assert r.confidence == 0.0
        assert r.normalized == ""

    def test_garbage_string(self):
        r = normalize_phone("not a phone number at all")
        assert r.confidence == 0.0

    def test_too_short(self):
        r = normalize_phone("123", default_region="US")
        assert r.confidence == 0.0

    def test_changed_flag_true(self):
        r = normalize_phone("(415) 555-2671", default_region="US")
        assert r.changed is True

    def test_changed_flag_false_on_already_e164(self):
        r = normalize_phone("+14155552671")
        assert r.changed is False


class TestPhoneNormalizer:
    @pytest.fixture
    def normalizer(self):
        return PhoneNormalizer()

    def test_basic_e164_conversion(self, normalizer):
        rec = _rec(["(415) 555-2671"], location="San Francisco, California, US")
        out = normalizer.normalize(rec)
        assert "+14155552671" in out.phones

    def test_location_infers_region(self):
        n = PhoneNormalizer()
        rec = _rec(["09876543210"], location="Bangalore, India")
        out = n.normalize(rec)
        # Should infer IN region
        assert any("91" in p for p in out.phones)

    def test_config_default_region(self):
        n = PhoneNormalizer(config={"default_region": "US"})
        rec = _rec(["4155552671"])
        out = n.normalize(rec)
        assert "+14155552671" in out.phones

    def test_invalid_kept_by_default(self, normalizer):
        rec = _rec(["not-a-phone"])
        out = normalizer.normalize(rec)
        assert "not-a-phone" in out.phones

    def test_invalid_dropped_when_configured(self):
        n = PhoneNormalizer(config={"drop_invalid": True})
        rec = _rec(["not-a-phone", "+14155552671"])
        out = n.normalize(rec)
        assert "not-a-phone" not in out.phones
        assert "+14155552671" in out.phones

    def test_duplicate_phones_deduplicated(self, normalizer):
        rec = _rec(["+14155552671", "+14155552671"])
        out = normalizer.normalize(rec)
        assert out.phones.count("+14155552671") == 1

    def test_multiple_phones(self, normalizer):
        rec = _rec(["+14155552671", "+447911123456"])
        out = normalizer.normalize(rec)
        assert "+14155552671" in out.phones
        assert "+447911123456" in out.phones

    def test_empty_list_no_change(self, normalizer):
        rec = _rec([])
        out = normalizer.normalize(rec)
        assert out.phones == []

    def test_provenance_written_for_changed(self, normalizer):
        rec = _rec(["(415) 555-2671"], location="US")
        out = normalizer.normalize(rec)
        prov_fields = [p.field for p in out.provenance]
        assert "phones" in prov_fields

    def test_supports_true_with_phones(self, normalizer):
        rec = _rec(["+14155552671"])
        assert normalizer.supports(rec) is True

    def test_supports_false_without_phones(self, normalizer):
        rec = _rec([])
        assert normalizer.supports(rec) is False

    def test_metadata_returns_dict(self, normalizer):
        m = normalizer.metadata()
        assert isinstance(m, dict)
        assert "phones" in m.get("fields", [])

    def test_already_e164_no_change(self, normalizer):
        rec = _rec(["+14155552671"])
        out = normalizer.normalize(rec)
        assert "+14155552671" in out.phones
