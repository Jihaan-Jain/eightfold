"""
src/normalization/country_normalizer.py
========================================

Converts country strings to ISO 3166-1 alpha-2 codes.

Supported input formats
------------------------
- Full name:   ``"India"``          → ``"IN"``
- Alpha-3:     ``"IND"``            → ``"IN"``
- Alpha-2:     ``"IN"``             → ``"IN"`` (pass-through)
- Common name: ``"Republic of India"``  → ``"IN"``
- Aliases:     ``"USA"`` / ``"US"`` / ``"United States"`` → ``"US"``

Uses ``pycountry`` as the primary lookup with a hand-maintained alias
table for high-frequency variants that pycountry may not map directly.
"""

from __future__ import annotations

from typing import Any

from src.models import CanonicalRecord, NormalizationMethod
from src.normalization.base import BaseNormalizer
from src.normalization.utils import NormalizationResult

# ── Hand-maintained alias table ───────────────────────────────────
# Maps lowercase aliases → ISO 3166-1 alpha-2
_ALIASES: dict[str, str] = {
    # USA variants
    "usa":                    "US",
    "united states":          "US",
    "united states of america": "US",
    "u.s.":                   "US",
    "u.s.a.":                 "US",
    "us":                     "US",
    # UK variants
    "uk":                     "GB",
    "united kingdom":         "GB",
    "great britain":          "GB",
    "england":                "GB",
    "britain":                "GB",
    # India
    "india":                  "IN",
    "republic of india":      "IN",
    "bharat":                 "IN",
    # China
    "china":                  "CN",
    "people's republic of china": "CN",
    "prc":                    "CN",
    # Russia
    "russia":                 "RU",
    "russian federation":     "RU",
    # South Korea
    "south korea":            "KR",
    "korea":                  "KR",
    "republic of korea":      "KR",
    # North Korea
    "north korea":            "KP",
    # UAE
    "uae":                    "AE",
    "united arab emirates":   "AE",
    # Other common
    "singapore":              "SG",
    "hong kong":              "HK",
    "taiwan":                 "TW",
    "vietnam":                "VN",
    "viet nam":               "VN",
    "iran":                   "IR",
    "south africa":           "ZA",
    "new zealand":            "NZ",
    "nz":                     "NZ",
    "au":                     "AU",
    "australia":              "AU",
    "ca":                     "CA",
    "canada":                 "CA",
    "de":                     "DE",
    "germany":                "DE",
    "fr":                     "FR",
    "france":                 "FR",
    "jp":                     "JP",
    "japan":                  "JP",
    "br":                     "BR",
    "brazil":                 "BR",
    "brasil":                 "BR",
    "mx":                     "MX",
    "mexico":                 "MX",
    "nl":                     "NL",
    "netherlands":            "NL",
    "holland":                "NL",
    "se":                     "SE",
    "sweden":                 "SE",
    "no":                     "NO",
    "norway":                 "NO",
    "fi":                     "FI",
    "finland":                "FI",
    "dk":                     "DK",
    "denmark":                "DK",
    "it":                     "IT",
    "italy":                  "IT",
    "es":                     "ES",
    "spain":                  "ES",
    "pt":                     "PT",
    "portugal":               "PT",
    "pl":                     "PL",
    "poland":                 "PL",
    "ch":                     "CH",
    "switzerland":            "CH",
    "be":                     "BE",
    "belgium":                "BE",
    "at":                     "AT",
    "austria":                "AT",
    "ie":                     "IE",
    "ireland":                "IE",
    "il":                     "IL",
    "israel":                 "IL",
    "pk":                     "PK",
    "pakistan":               "PK",
    "bd":                     "BD",
    "bangladesh":             "BD",
    "lk":                     "LK",
    "sri lanka":              "LK",
    "np":                     "NP",
    "nepal":                  "NP",
    "my":                     "MY",
    "malaysia":               "MY",
    "id":                     "ID",
    "indonesia":              "ID",
    "ph":                     "PH",
    "philippines":            "PH",
    "th":                     "TH",
    "thailand":               "TH",
    "ng":                     "NG",
    "nigeria":                "NG",
    "eg":                     "EG",
    "egypt":                  "EG",
    "ke":                     "KE",
    "kenya":                  "KE",
    "za":                     "ZA",
    "gh":                     "GH",
    "ghana":                  "GH",
    "ar":                     "AR",
    "argentina":              "AR",
    "co":                     "CO",
    "colombia":               "CO",
    "cl":                     "CL",
    "chile":                  "CL",
    "pe":                     "PE",
    "peru":                   "PE",
}


def country_to_alpha2(raw: str) -> str | None:
    """
    Convert a country string to its ISO 3166-1 alpha-2 code.

    Parameters
    ----------
    raw:
        Country name, alpha-2, or alpha-3 code (any case).

    Returns
    -------
    str | None
        Two-letter ISO code (uppercase) or ``None`` when unresolvable.
    """
    if not raw or not raw.strip():
        return None

    normalized = raw.strip().lower()

    # 1. Alias table (fastest)
    if normalized in _ALIASES:
        return _ALIASES[normalized]

    # 2. Already a valid alpha-2?
    if len(raw.strip()) == 2 and raw.strip().isalpha():
        return raw.strip().upper()

    # 3. pycountry lookup
    try:
        import pycountry
        # By alpha-2
        country = pycountry.countries.get(alpha_2=raw.strip().upper())
        if country:
            return country.alpha_2

        # By alpha-3
        country = pycountry.countries.get(alpha_3=raw.strip().upper())
        if country:
            return country.alpha_2

        # By name (exact)
        country = pycountry.countries.get(name=raw.strip())
        if country:
            return country.alpha_2

        # By common name
        country = pycountry.countries.get(common_name=raw.strip())
        if country:
            return country.alpha_2

        # Fuzzy search
        results = pycountry.countries.search_fuzzy(raw.strip())
        if results:
            return results[0].alpha_2

    except (ImportError, LookupError):
        pass

    return None


def normalize_country(raw: str) -> NormalizationResult:
    """
    Normalize a country string to its ISO 3166-1 alpha-2 code.

    Parameters
    ----------
    raw:
        Country string in any format.

    Returns
    -------
    NormalizationResult
        ``normalized`` is the alpha-2 code or the original on failure.
    """
    code = country_to_alpha2(raw)
    if code is None:
        return NormalizationResult(
            original=raw, normalized=raw,
            method=NormalizationMethod.NONE, confidence=0.0,
            reason=f"Could not resolve country: {raw!r}",
        )
    return NormalizationResult(
        original=raw, normalized=code,
        method=NormalizationMethod.NONE,  # reuse NONE; no dedicated enum
        confidence=1.0,
        reason=f"{raw!r} → ISO 3166-1 alpha-2 {code!r}",
    )


class CountryNormalizer(BaseNormalizer):
    """
    Normalizes the country component inside ``record.location``.

    This normalizer **does not** modify ``record.location`` directly —
    it is consumed by :class:`~src.normalization.location_normalizer.LocationNormalizer`
    and :class:`~src.normalization.phone_normalizer.PhoneNormalizer`.

    When used in the pipeline it stores the resolved alpha-2 code in
    ``record.mapping_metadata["country_code"]`` for downstream use.
    """

    def supports(self, record: CanonicalRecord) -> bool:
        return bool(record.location)

    def metadata(self) -> dict[str, Any]:
        return {
            "normalizer": self.__class__.__name__,
            "fields":     ["location (country component)"],
            "method":     "ISO 3166-1 alpha-2",
            "version":    "1.0.0",
        }

    def normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        return self._timed_normalize(record, self._do_normalize)

    def _do_normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        if not record.location:
            return record

        # Extract last comma-separated part as probable country
        parts = [p.strip() for p in record.location.split(",")]
        country_candidate = parts[-1] if parts else record.location

        code = country_to_alpha2(country_candidate)
        if code:
            record.mapping_metadata["country_code"] = code
            self._add_provenance(
                record,
                field="location",
                original_value=country_candidate,
                normalized_value=code,
                method=NormalizationMethod.NONE,
                confidence=1.0,
                reason=f"Country component resolved to ISO alpha-2: {code!r}",
            )
        else:
            self._log.warning(
                "Country not resolved",
                extra={"candidate": country_candidate, "location": record.location},
            )
        return record
