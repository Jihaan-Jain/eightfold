"""
src/normalization/name_normalizer.py
=====================================

Normalizes name fields on a :class:`~src.models.CanonicalRecord`.

Operations (applied in order)
------------------------------
1. Unicode NFC normalization.
2. Strip leading/trailing whitespace.
3. Collapse internal whitespace runs to single spaces.
4. Title-case each word, with special handling for:
   - Hyphenated names: ``"mary-jane"`` → ``"Mary-Jane"``
   - Irish/Scottish prefixes: ``"mc"``, ``"mac"`` → ``"Mc"`` / ``"Mac"``
   - Nobility particles: ``"de"``, ``"von"``, ``"van"``, ``"del"``,
     ``"della"``, ``"di"`` — kept lowercase when not sentence-initial.
   - Initials: ``"j."`` → ``"J."``
   - Suffixes: ``"Jr."``, ``"Sr."``, ``"II"``, ``"III"``, ``"IV"`` — preserved.

Fields normalized
-----------------
- ``full_name``
- ``first_name``
- ``last_name``
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from src.models import CanonicalRecord, NormalizationMethod
from src.normalization.base import BaseNormalizer
from src.normalization.utils import NormalizationResult, clean_text

# ── Special tokens ────────────────────────────────────────────────

# Suffixes that should remain exactly as-is (case-insensitive match)
_SUFFIXES: frozenset[str] = frozenset(
    {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v", "esq", "esq.",
     "phd", "ph.d", "ph.d.", "md", "m.d.", "dds", "jd", "j.d."}
)

# Nobility / preposition particles (lowercase unless sentence-initial)
_PARTICLES: frozenset[str] = frozenset(
    {"de", "del", "della", "delle", "di", "du", "da", "das", "dos",
     "von", "van", "van den", "van der", "ten", "ter", "af", "av",
     "zu", "zum", "zur", "le", "la", "les", "el", "al", "bin", "binti",
     "ap", "ab", "ferch", "nic", "uí", "ui"}
)

# Prefixes that get special casing: "mcdonald" → "McDonald"
_MC_RE  = re.compile(r"^(mc)(.)", re.IGNORECASE)
_MAC_RE = re.compile(r"^(mac)([a-z])", re.IGNORECASE)

# Hyphen-split pattern
_HYPHEN_RE = re.compile(r"[-\u2010\u2011\u2012\u2013\u2014]")

# Initial detection: single letter followed by dot
_INITIAL_RE = re.compile(r"^([a-z])\.?$", re.IGNORECASE)

# Suffix detection pattern
_SUFFIX_COMMA_RE = re.compile(r",\s*(jr\.?|sr\.?|ii|iii|iv|v|esq\.?|phd|md)$", re.IGNORECASE)


def _title_case_word(word: str, *, is_first: bool = True) -> str:
    """
    Apply intelligent title-casing to a single name word.

    Parameters
    ----------
    word:
        A single name token (no spaces).
    is_first:
        ``True`` when this is the first or only word in the name.
        Particles are NOT lowercased when they are sentence-initial.

    Returns
    -------
    str
        Title-cased word.
    """
    if not word:
        return word

    low = word.lower()

    # Preserve suffixes verbatim (already correct casing from source or title-cased)
    if low in _SUFFIXES:
        return word.upper() if low in {"ii", "iii", "iv", "v"} else word.title()

    # Particle: lowercase unless first
    if low in _PARTICLES and not is_first:
        return low

    # Single initial: "j." → "J."
    m = _INITIAL_RE.match(word)
    if m:
        return word.upper() if len(word) == 1 else word[0].upper() + "."

    # Mc / Mac prefix
    m = _MC_RE.match(word)
    if m:
        return m.group(1).title() + m.group(2).upper() + word[len(m.group(0)):].lower()

    m = _MAC_RE.match(word)
    if m:
        rest = word[len(m.group(0)):]
        return m.group(1).title() + m.group(2).upper() + rest.lower()

    # Hyphenated
    if _HYPHEN_RE.search(word):
        parts = _HYPHEN_RE.split(word)
        sep   = _HYPHEN_RE.search(word).group(0)
        return sep.join(_title_case_word(p, is_first=True) for p in parts)

    return word.capitalize()


def normalize_name(raw: str) -> NormalizationResult:
    """
    Normalize a single name string.

    Parameters
    ----------
    raw:
        Raw name string.

    Returns
    -------
    NormalizationResult
        ``normalized`` is the title-cased, whitespace-collapsed name.
    """
    if not raw or not raw.strip():
        return NormalizationResult(
            original=raw, normalized=raw,
            method=NormalizationMethod.NAME_TITLE_CASE, confidence=0.0,
            reason="Empty name string.",
        )

    # NFC Unicode normalization
    nfc = unicodedata.normalize("NFC", raw)
    # Collapse whitespace
    cleaned = clean_text(nfc)

    # Strip trailing suffix (e.g. "Smith, Jr." → handled below)
    suffix_match = _SUFFIX_COMMA_RE.search(cleaned)
    suffix_part  = ""
    base_name    = cleaned
    if suffix_match:
        suffix_part = " " + suffix_match.group(1).title()
        base_name   = cleaned[: suffix_match.start()]

    # Title-case each word
    words = base_name.split()
    result_words = [
        _title_case_word(w, is_first=(i == 0))
        for i, w in enumerate(words)
    ]
    normalized = " ".join(result_words) + suffix_part

    return NormalizationResult(
        original=raw,
        normalized=normalized,
        method=NormalizationMethod.NAME_TITLE_CASE,
        confidence=1.0,
        reason="Unicode NFC + whitespace collapse + title case applied.",
    )


class NameNormalizer(BaseNormalizer):
    """
    Normalizes :attr:`~src.models.CanonicalRecord.full_name`,
    :attr:`~src.models.CanonicalRecord.first_name`, and
    :attr:`~src.models.CanonicalRecord.last_name`.

    Config Keys
    -----------
    ``fields`` (list[str]):
        Name fields to normalize.
        Default: ``["full_name", "first_name", "last_name"]``.
    """

    _DEFAULT_FIELDS = ("full_name", "first_name", "last_name")

    def supports(self, record: CanonicalRecord) -> bool:
        return bool(record.full_name or record.first_name or record.last_name)

    def metadata(self) -> dict[str, Any]:
        return {
            "normalizer": self.__class__.__name__,
            "fields":     list(self._DEFAULT_FIELDS),
            "method":     NormalizationMethod.NAME_TITLE_CASE.value,
            "version":    "1.0.0",
        }

    def normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        return self._timed_normalize(record, self._do_normalize)

    def _do_normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        fields = self._config.get("fields", list(self._DEFAULT_FIELDS))
        for field_name in fields:
            raw = getattr(record, field_name, None)
            if not raw:
                continue
            result = normalize_name(raw)
            if result.changed:
                setattr(record, field_name, result.normalized)
                self._add_provenance(
                    record,
                    field=field_name,
                    original_value=result.original,
                    normalized_value=result.normalized,
                    method=result.method,
                    confidence=result.confidence,
                    reason=result.reason,
                )
        return record
