"""
tests/test_email_normalizer.py
================================

Unit tests for src/normalization/email_normalizer.py.
"""

from __future__ import annotations

import pytest

from src.normalization.email_normalizer import EmailNormalizer, normalize_email
from src.models import CanonicalRecord, NormalizationMethod, SourceType


def _rec(emails: list[str]) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="test-id",
        source_type=SourceType.CSV,
        source_label="test.csv",
        emails=emails,
    )


class TestNormalizeEmailFunction:
    def test_already_lowercase_valid(self):
        r = normalize_email("alice@example.com")
        assert r.normalized == "alice@example.com"
        assert r.confidence == 1.0

    def test_uppercase_lowercased(self):
        r = normalize_email("Alice@EXAMPLE.COM")
        assert r.normalized == "alice@example.com"
        assert r.method == NormalizationMethod.EMAIL_LOWERCASE

    def test_whitespace_stripped(self):
        r = normalize_email("  bob@example.com  ")
        assert r.normalized == "bob@example.com"

    def test_mixed_case_lowercased(self):
        r = normalize_email("TeSt.UsEr@DoMaIn.ORG")
        assert r.normalized == "test.user@domain.org"

    def test_invalid_no_at(self):
        r = normalize_email("notanemail")
        assert r.confidence == 0.0
        assert r.normalized == "notanemail"

    def test_invalid_no_domain(self):
        r = normalize_email("user@")
        assert r.confidence == 0.0

    def test_invalid_no_tld(self):
        r = normalize_email("user@domain")
        assert r.confidence == 0.0

    def test_empty_string(self):
        r = normalize_email("")
        assert r.confidence == 0.0

    def test_whitespace_only(self):
        r = normalize_email("   ")
        assert r.confidence == 0.0

    def test_plus_addressing_valid(self):
        r = normalize_email("alice+tag@example.com")
        assert r.confidence == 1.0
        assert r.normalized == "alice+tag@example.com"

    def test_subdomain_email(self):
        r = normalize_email("user@mail.company.co.uk")
        assert r.confidence == 1.0

    def test_numeric_local_part(self):
        r = normalize_email("12345@example.com")
        assert r.confidence == 1.0

    def test_dot_in_local_part(self):
        r = normalize_email("first.last@example.com")
        assert r.confidence == 1.0
        assert r.normalized == "first.last@example.com"

    def test_hyphen_in_domain(self):
        r = normalize_email("user@my-company.com")
        assert r.confidence == 1.0

    def test_changed_flag_true_on_uppercase(self):
        r = normalize_email("USER@EXAMPLE.COM")
        assert r.changed is True

    def test_changed_flag_false_on_already_normal(self):
        r = normalize_email("user@example.com")
        assert r.changed is False


class TestEmailNormalizer:
    @pytest.fixture
    def normalizer(self):
        return EmailNormalizer()

    def test_basic_lowercase(self, normalizer):
        rec = _rec(["ALICE@EXAMPLE.COM"])
        out = normalizer.normalize(rec)
        assert "alice@example.com" in out.emails

    def test_multiple_emails(self, normalizer):
        rec = _rec(["Alice@X.COM", "BOB@Y.COM"])
        out = normalizer.normalize(rec)
        assert "alice@x.com" in out.emails
        assert "bob@y.com" in out.emails

    def test_invalid_dropped_by_default(self, normalizer):
        rec = _rec(["notanemail", "valid@example.com"])
        out = normalizer.normalize(rec)
        assert "valid@example.com" in out.emails
        assert "notanemail" not in out.emails

    def test_invalid_kept_when_drop_false(self):
        n = EmailNormalizer(config={"drop_invalid": False})
        rec = _rec(["notanemail", "valid@example.com"])
        out = n.normalize(rec)
        assert "notanemail" in out.emails

    def test_deduplication(self, normalizer):
        rec = _rec(["Alice@X.COM", "alice@x.com", "ALICE@X.COM"])
        out = normalizer.normalize(rec)
        assert out.emails.count("alice@x.com") == 1

    def test_case_insensitive_deduplication(self, normalizer):
        rec = _rec(["User@Example.COM", "user@example.com"])
        out = normalizer.normalize(rec)
        assert len(out.emails) == 1

    def test_empty_list_no_change(self, normalizer):
        rec = _rec([])
        out = normalizer.normalize(rec)
        assert out.emails == []

    def test_provenance_written_for_changed(self, normalizer):
        rec = _rec(["ALICE@EXAMPLE.COM"])
        out = normalizer.normalize(rec)
        prov_fields = [p.field for p in out.provenance]
        assert "emails" in prov_fields

    def test_provenance_not_written_when_unchanged(self, normalizer):
        rec = _rec(["alice@example.com"])
        out = normalizer.normalize(rec)
        norm_provs = [p for p in out.provenance
                      if p.field == "emails" and "normalized" in (p.reason or "").lower()]
        assert len(norm_provs) == 0

    def test_supports_true_with_emails(self, normalizer):
        rec = _rec(["a@b.com"])
        assert normalizer.supports(rec) is True

    def test_supports_false_without_emails(self, normalizer):
        rec = _rec([])
        assert normalizer.supports(rec) is False

    def test_metadata_returns_dict(self, normalizer):
        m = normalizer.metadata()
        assert isinstance(m, dict)
        assert "emails" in m.get("fields", [])

    def test_whitespace_in_list_entry(self, normalizer):
        rec = _rec(["  alice@example.com  "])
        out = normalizer.normalize(rec)
        assert "alice@example.com" in out.emails

    def test_all_invalid_results_in_empty_list(self, normalizer):
        rec = _rec(["notanemail", "alsobad", "@"])
        out = normalizer.normalize(rec)
        assert out.emails == []

    def test_preserves_valid_complex_email(self, normalizer):
        rec = _rec(["alice.B+tag@my-company.co.uk"])
        out = normalizer.normalize(rec)
        assert "alice.b+tag@my-company.co.uk" in out.emails
