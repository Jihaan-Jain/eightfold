"""
tests/test_company_normalizer.py
==================================

Unit tests for src/normalization/company_normalizer.py.
"""

from __future__ import annotations

import pytest

from src.normalization.company_normalizer import CompanyNormalizer, normalize_company
from src.models import CanonicalRecord, NormalizationMethod, SourceType


def _rec(current_company: str | None = None, experience=None) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="test-id",
        source_type=SourceType.CSV,
        source_label="test.csv",
        current_company=current_company,
        experience=experience or [],
    )


class TestNormalizeCompanyFunction:
    # ── Legal suffix stripping ────────────────────────────────
    def test_llc_stripped(self):
        r = normalize_company("Acme LLC")
        assert "LLC" not in r.normalized
        assert "Acme" in r.normalized

    def test_inc_stripped(self):
        r = normalize_company("Apple Inc.")
        assert "Inc" not in r.normalized
        assert "Apple" in r.normalized

    def test_inc_dot_stripped(self):
        r = normalize_company("Apple Inc.")
        assert "Apple" in r.normalized

    def test_corp_stripped(self):
        r = normalize_company("Eightfold Corp")
        assert "Corp" not in r.normalized
        assert "Eightfold" in r.normalized

    def test_ltd_stripped(self):
        r = normalize_company("Widget Ltd")
        assert "Ltd" not in r.normalized
        assert "Widget" in r.normalized

    def test_limited_stripped(self):
        r = normalize_company("Widget Limited")
        assert "Limited" not in r.normalized

    def test_incorporated_stripped(self):
        r = normalize_company("Acme Incorporated")
        assert "Incorporated" not in r.normalized

    def test_corporation_stripped(self):
        r = normalize_company("Acme Corporation")
        assert "Corporation" not in r.normalized

    def test_gmbh_stripped(self):
        r = normalize_company("Muster GmbH")
        assert "GmbH" not in r.normalized
        assert "Muster" in r.normalized

    def test_ag_stripped(self):
        r = normalize_company("Siemens AG")
        assert "AG" not in r.normalized
        assert "Siemens" in r.normalized

    def test_pvt_ltd_stripped(self):
        r = normalize_company("Infosys Pvt. Ltd.")
        assert "Pvt" not in r.normalized
        assert "Infosys" in r.normalized

    def test_private_limited_stripped(self):
        r = normalize_company("Infosys Private Limited")
        assert "Limited" not in r.normalized

    def test_comma_suffix(self):
        r = normalize_company("Google, Inc.")
        assert "Inc" not in r.normalized
        assert "Google" in r.normalized

    def test_llp_stripped(self):
        r = normalize_company("Law Firm LLP")
        assert "LLP" not in r.normalized

    def test_plc_stripped(self):
        r = normalize_company("Barclays PLC")
        assert "PLC" not in r.normalized

    # ── @ prefix ─────────────────────────────────────────────
    def test_at_prefix_stripped(self):
        r = normalize_company("@Eightfold")
        assert r.normalized == "Eightfold"

    def test_at_prefix_with_suffix(self):
        r = normalize_company("@Acme Inc.")
        assert "@" not in r.normalized
        assert "Acme" in r.normalized

    # ── Title casing ──────────────────────────────────────────
    def test_all_lowercase_title_cased(self):
        r = normalize_company("google")
        assert r.normalized == "Google"

    def test_all_uppercase_title_cased(self):
        r = normalize_company("GOOGLE")
        assert r.normalized == "Google"

    # ── Idempotency ───────────────────────────────────────────
    def test_clean_name_passes_through(self):
        r = normalize_company("Google")
        assert r.normalized == "Google"

    def test_multiple_variants_same_result(self):
        r1 = normalize_company("Google LLC")
        r2 = normalize_company("Google Inc.")
        r3 = normalize_company("Google Corp")
        # All three should normalize to "Google"
        assert r1.normalized == r2.normalized == r3.normalized

    # ── Edge cases ────────────────────────────────────────────
    def test_empty_string(self):
        r = normalize_company("")
        assert r.confidence == 0.0

    def test_whitespace_only(self):
        r = normalize_company("   ")
        assert r.confidence == 0.0

    def test_does_not_strip_sole_short_name(self):
        # "Co" alone should not be stripped
        r = normalize_company("Co")
        assert r.normalized  # result is not empty

    def test_method_is_company_strip_suffix(self):
        r = normalize_company("Acme LLC")
        assert r.method == NormalizationMethod.COMPANY_STRIP_SUFFIX

    def test_changed_flag_true_on_suffix(self):
        r = normalize_company("Acme LLC")
        assert r.changed is True

    def test_changed_flag_false_on_clean(self):
        r = normalize_company("Google")
        assert r.changed is False


class TestCompanyNormalizer:
    @pytest.fixture
    def normalizer(self):
        return CompanyNormalizer()

    def test_current_company_normalized(self, normalizer):
        rec = _rec(current_company="Google LLC")
        out = normalizer.normalize(rec)
        assert "LLC" not in out.current_company
        assert "Google" in out.current_company

    def test_at_prefix_in_current_company(self, normalizer):
        rec = _rec(current_company="@Eightfold")
        out = normalizer.normalize(rec)
        assert out.current_company == "Eightfold"

    def test_experience_company_normalized(self, normalizer):
        rec = _rec(experience=[
            {"company": "Apple Inc.", "title": "Engineer"},
            {"company": "@Startup Ltd", "title": "Developer"},
        ])
        out = normalizer.normalize(rec)
        assert "Inc" not in out.experience[0].get("company", "")
        assert "@" not in out.experience[1].get("company", "")

    def test_strip_suffixes_disabled(self):
        n = CompanyNormalizer(config={"strip_suffixes": False})
        rec = _rec(current_company="Google LLC")
        out = n.normalize(rec)
        # LLC should still be present (in some case form, since title-case applies)
        assert "llc" in out.current_company.lower()

    def test_none_company_no_crash(self, normalizer):
        rec = _rec(current_company=None)
        out = normalizer.normalize(rec)
        assert out.current_company is None

    def test_provenance_written_on_change(self, normalizer):
        rec = _rec(current_company="Google LLC")
        out = normalizer.normalize(rec)
        assert any(p.field == "current_company" for p in out.provenance)

    def test_provenance_not_written_on_unchanged(self, normalizer):
        rec = _rec(current_company="Google")
        out = normalizer.normalize(rec)
        co_provs = [p for p in out.provenance if p.field == "current_company"]
        assert len(co_provs) == 0

    def test_supports_with_company(self, normalizer):
        rec = _rec(current_company="Google")
        assert normalizer.supports(rec) is True

    def test_supports_with_experience_company(self, normalizer):
        rec = _rec(experience=[{"company": "Apple"}])
        assert normalizer.supports(rec) is True

    def test_supports_false_when_empty(self, normalizer):
        rec = _rec()
        assert normalizer.supports(rec) is False

    def test_metadata_returns_dict(self, normalizer):
        m = normalizer.metadata()
        assert isinstance(m, dict)
        assert "current_company" in m.get("fields", [])
