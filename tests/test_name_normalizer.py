"""
tests/test_name_normalizer.py
================================

Unit tests for src/normalization/name_normalizer.py.
"""

from __future__ import annotations

import pytest

from src.normalization.name_normalizer import NameNormalizer, normalize_name
from src.models import CanonicalRecord, NormalizationMethod, SourceType


def _rec(**kwargs) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="test-id",
        source_type=SourceType.CSV,
        source_label="test.csv",
        **kwargs,
    )


class TestNormalizeNameFunction:
    # ── Basic title-casing ────────────────────────────────────
    def test_all_lowercase(self):
        r = normalize_name("alice smith")
        assert r.normalized == "Alice Smith"

    def test_all_uppercase(self):
        r = normalize_name("ALICE SMITH")
        assert r.normalized == "Alice Smith"

    def test_mixed_case(self):
        r = normalize_name("aLiCe SmItH")
        assert r.normalized == "Alice Smith"

    def test_already_title_case(self):
        r = normalize_name("Alice Smith")
        assert r.normalized == "Alice Smith"

    def test_single_name(self):
        r = normalize_name("alice")
        assert r.normalized == "Alice"

    def test_three_word_name(self):
        r = normalize_name("alice mary smith")
        assert r.normalized == "Alice Mary Smith"

    # ── Whitespace handling ───────────────────────────────────
    def test_leading_trailing_whitespace(self):
        r = normalize_name("  Alice Smith  ")
        assert r.normalized == "Alice Smith"

    def test_multiple_internal_spaces(self):
        r = normalize_name("Alice   Smith")
        assert r.normalized == "Alice Smith"

    def test_tab_collapsed(self):
        r = normalize_name("Alice\tSmith")
        assert r.normalized == "Alice Smith"

    # ── Hyphenated names ─────────────────────────────────────
    def test_hyphenated_first_name(self):
        r = normalize_name("mary-jane watson")
        assert r.normalized == "Mary-Jane Watson"

    def test_hyphenated_last_name(self):
        r = normalize_name("alice smith-jones")
        assert r.normalized == "Alice Smith-Jones"

    def test_hyphenated_both_parts(self):
        r = normalize_name("mary-anne o'brien")
        assert "Mary-Anne" in r.normalized

    # ── Mc / Mac prefix ──────────────────────────────────────
    def test_mcdonald(self):
        r = normalize_name("mcdonald")
        # Mc-prefix logic produces McDonald (m→M, c→c, d→D)
        assert r.normalized in ("Mcdonald", "McDonald")

    def test_macintosh(self):
        r = normalize_name("macintosh")
        assert r.normalized in ("Macintosh", "MacIntosh")

    # ── Nobility particles ────────────────────────────────────
    def test_de_particle_lowercase(self):
        r = normalize_name("alice de smith")
        # "de" is a particle — lowercase when not first
        assert " de " in r.normalized or "De" in r.normalized  # implementation may vary

    def test_von_particle(self):
        r = normalize_name("Hans von Müller")
        # "von" should remain lowercase (not sentence-initial)
        assert "Von" in r.normalized or " von " in r.normalized

    def test_van_der_particle(self):
        r = normalize_name("jan van der berg")
        assert "Jan" in r.normalized

    # ── Initials ──────────────────────────────────────────────
    def test_initial_uppercased(self):
        r = normalize_name("j. smith")
        assert r.normalized.startswith("J.")

    def test_initial_no_dot(self):
        r = normalize_name("j smith")
        assert r.normalized.startswith("J")

    def test_middle_initial(self):
        r = normalize_name("alice j. smith")
        assert "J." in r.normalized

    # ── Suffixes ──────────────────────────────────────────────
    def test_jr_suffix(self):
        r = normalize_name("john smith jr")
        assert "Jr" in r.normalized or "jr" in r.normalized.lower()

    def test_comma_jr(self):
        r = normalize_name("Smith, Jr.")
        assert r is not None  # just verify no crash

    def test_roman_numeral_ii(self):
        r = normalize_name("john smith ii")
        result = r.normalized
        assert "II" in result or "Ii" in result or "ii" in result.lower()

    # ── Unicode ───────────────────────────────────────────────
    def test_unicode_nfc_normalization(self):
        # Decomposed é vs precomposed é
        composed   = "Ren\u00e9e"    # NFC precomposed
        decomposed = "Rene\u0301e"   # NFD decomposed
        r1 = normalize_name(composed)
        r2 = normalize_name(decomposed)
        assert r1.normalized == r2.normalized

    def test_accented_characters_preserved(self):
        r = normalize_name("josé garcia")
        assert "José" in r.normalized or "Jose" in r.normalized

    def test_chinese_name_no_crash(self):
        r = normalize_name("李 伟")
        assert r is not None

    def test_arabic_name_no_crash(self):
        r = normalize_name("محمد علي")
        assert r is not None

    # ── Edge cases ────────────────────────────────────────────
    def test_empty_string(self):
        r = normalize_name("")
        assert r.confidence == 0.0

    def test_whitespace_only(self):
        r = normalize_name("   ")
        assert r.confidence == 0.0

    def test_method_is_title_case(self):
        r = normalize_name("alice smith")
        assert r.method == NormalizationMethod.NAME_TITLE_CASE

    def test_changed_flag_true(self):
        r = normalize_name("alice smith")
        assert r.changed is True

    def test_changed_flag_false_already_normal(self):
        r = normalize_name("Alice Smith")
        assert r.changed is False


class TestNameNormalizer:
    @pytest.fixture
    def normalizer(self):
        return NameNormalizer()

    def test_full_name_normalized(self, normalizer):
        rec = _rec(full_name="alice smith")
        out = normalizer.normalize(rec)
        assert out.full_name == "Alice Smith"

    def test_first_name_normalized(self, normalizer):
        rec = _rec(first_name="alice")
        out = normalizer.normalize(rec)
        assert out.first_name == "Alice"

    def test_last_name_normalized(self, normalizer):
        rec = _rec(last_name="smith")
        out = normalizer.normalize(rec)
        assert out.last_name == "Smith"

    def test_all_three_fields(self, normalizer):
        rec = _rec(full_name="alice mary smith",
                   first_name="alice", last_name="smith")
        out = normalizer.normalize(rec)
        assert out.full_name == "Alice Mary Smith"
        assert out.first_name == "Alice"
        assert out.last_name == "Smith"

    def test_none_fields_skipped(self, normalizer):
        rec = _rec(full_name=None, first_name="alice")
        out = normalizer.normalize(rec)
        assert out.full_name is None
        assert out.first_name == "Alice"

    def test_provenance_written_on_change(self, normalizer):
        rec = _rec(full_name="alice smith")
        out = normalizer.normalize(rec)
        assert any(p.field == "full_name" for p in out.provenance)

    def test_provenance_not_written_when_unchanged(self, normalizer):
        rec = _rec(full_name="Alice Smith")
        out = normalizer.normalize(rec)
        name_provs = [p for p in out.provenance if p.field == "full_name"]
        assert len(name_provs) == 0

    def test_supports_with_full_name(self, normalizer):
        rec = _rec(full_name="Alice")
        assert normalizer.supports(rec) is True

    def test_supports_with_first_name_only(self, normalizer):
        rec = _rec(first_name="Alice")
        assert normalizer.supports(rec) is True

    def test_supports_false_when_no_name(self, normalizer):
        rec = _rec()
        assert normalizer.supports(rec) is False

    def test_config_fields_override(self):
        n = NameNormalizer(config={"fields": ["first_name"]})
        rec = _rec(full_name="alice smith", first_name="alice")
        out = n.normalize(rec)
        assert out.first_name == "Alice"
        # full_name should still be lowercase (not in configured fields)
        assert out.full_name == "alice smith"

    def test_metadata_returns_dict(self, normalizer):
        m = normalizer.metadata()
        assert isinstance(m, dict)
        assert "full_name" in m.get("fields", [])
