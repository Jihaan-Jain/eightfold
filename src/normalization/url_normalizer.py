"""
src/normalization/url_normalizer.py
=====================================

Normalizes URL fields on a :class:`~src.models.CanonicalRecord`.

Operations (per URL)
---------------------
1. Strip whitespace.
2. Ensure ``https://`` scheme (upgrade ``http://``; add scheme when missing).
3. Remove well-known tracking query parameters
   (``utm_*``, ``ref``, ``source``, ``campaign``, ``fbclid``, ``gclid``,
   ``mc_cid``, ``mc_eid``, ``_hsenc``, ``_hsmi``).
4. Remove trailing slashes from paths (except root ``/``).
5. Lowercase scheme and host; preserve path case.
6. Normalize GitHub URLs to ``https://github.com/{login}`` format.
7. Normalize LinkedIn URLs to ``https://linkedin.com/in/{handle}`` format.

Fields affected
---------------
- ``github_url``
- ``linkedin_url``
- ``website``
- ``experience[].url``
- ``projects[].url``
- Keys in ``other_links``
"""

from __future__ import annotations

import re
from urllib.parse import (
    ParseResult,
    parse_qs,
    urlencode,
    urlparse,
    urlunparse,
)
from typing import Any

from src.models import CanonicalRecord, NormalizationMethod
from src.normalization.base import BaseNormalizer
from src.normalization.utils import NormalizationResult

# Tracking query parameters to strip
_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "utm_id", "utm_source_platform", "ref", "referer", "source",
        "campaign", "fbclid", "gclid", "dclid", "mc_cid", "mc_eid",
        "_hsenc", "_hsmi", "mkt_tok", "trk", "trkCampaign", "sc_channel",
        "sc_campaign", "sc_outcome",
    }
)

_GITHUB_RE  = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9\-]+)(?:/.*)?$",
    re.IGNORECASE,
)
_LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9\-_%]+)(?:/.*)?$",
    re.IGNORECASE,
)


def _ensure_scheme(url: str) -> str:
    """Add ``https://`` if the URL has no scheme."""
    if not url:
        return url
    if url.startswith("//"):
        return "https:" + url
    if "://" not in url:
        return "https://" + url
    return url


def _strip_tracking(parsed: ParseResult) -> ParseResult:
    """Remove tracking query parameters from a parsed URL."""
    qs = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
    new_query = urlencode(filtered, doseq=True)
    return parsed._replace(query=new_query)


def normalize_url(raw: str) -> NormalizationResult:
    """
    Normalize a single URL string.

    Parameters
    ----------
    raw:
        Raw URL as captured by the mapper.

    Returns
    -------
    NormalizationResult
        ``normalized`` is the cleaned HTTPS URL, or the original on failure.
    """
    if not raw or not raw.strip():
        return NormalizationResult(
            original=raw, normalized=raw,
            method=NormalizationMethod.URL_NORMALIZE, confidence=0.0,
            reason="Empty URL.",
        )

    url = raw.strip()

    # ── GitHub canonical form ─────────────────────────────────
    m = _GITHUB_RE.match(url)
    if m:
        login = m.group(1)
        normalized = f"https://github.com/{login}"
        return NormalizationResult(
            original=raw, normalized=normalized,
            method=NormalizationMethod.URL_NORMALIZE, confidence=1.0,
            reason=f"GitHub URL canonicalized for login={login!r}.",
        )

    # ── LinkedIn canonical form ───────────────────────────────
    m = _LINKEDIN_RE.match(url)
    if m:
        handle = m.group(1).lower()
        normalized = f"https://linkedin.com/in/{handle}"
        return NormalizationResult(
            original=raw, normalized=normalized,
            method=NormalizationMethod.URL_NORMALIZE, confidence=1.0,
            reason=f"LinkedIn URL canonicalized for handle={handle!r}.",
        )

    # ── Generic URL ───────────────────────────────────────────
    try:
        url = _ensure_scheme(url)
        parsed = urlparse(url)

        # Force https
        if parsed.scheme == "http":
            parsed = parsed._replace(scheme="https")

        # Lowercase scheme + host
        parsed = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
        )

        # Strip tracking params
        parsed = _strip_tracking(parsed)

        # Remove trailing slash from path (not root)
        path = parsed.path.rstrip("/") or "/"
        parsed = parsed._replace(path=path)

        normalized = urlunparse(parsed)
        return NormalizationResult(
            original=raw, normalized=normalized,
            method=NormalizationMethod.URL_NORMALIZE, confidence=0.95,
            reason="HTTPS enforced, tracking params stripped, trailing slash removed.",
        )
    except Exception as exc:
        return NormalizationResult(
            original=raw, normalized=raw,
            method=NormalizationMethod.NONE, confidence=0.0,
            reason=f"URL parse error: {exc}",
        )


class UrlNormalizer(BaseNormalizer):
    """
    Normalizes URL fields on a :class:`~src.models.CanonicalRecord`.

    Fields normalized:
    ``github_url``, ``linkedin_url``, ``website``,
    ``experience[].url``, ``projects[].url``, ``other_links`` values.

    Config Keys
    -----------
    ``force_https`` (bool):
        Upgrade ``http://`` to ``https://``.  Default ``True``.
    ``strip_tracking`` (bool):
        Remove tracking query parameters.  Default ``True``.
    """

    _URL_FIELDS = ("github_url", "linkedin_url", "website")

    def supports(self, record: CanonicalRecord) -> bool:
        return bool(
            record.github_url or record.linkedin_url or record.website
            or any(e.get("url") for e in record.experience)
            or any(p.get("url") for p in record.projects)
            or record.other_links
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "normalizer": self.__class__.__name__,
            "fields":     list(self._URL_FIELDS)
                          + ["experience[].url", "projects[].url", "other_links"],
            "method":     NormalizationMethod.URL_NORMALIZE.value,
            "version":    "1.0.0",
        }

    def normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        return self._timed_normalize(record, self._do_normalize)

    def _do_normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        # ── Scalar URL fields ─────────────────────────────────
        for field_name in self._URL_FIELDS:
            raw = getattr(record, field_name)
            if not raw:
                continue
            result = normalize_url(raw)
            if result.changed and result.confidence > 0.0:
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
            elif result.confidence == 0.0:
                self._log.warning(
                    "URL normalization failed",
                    extra={"field": field_name, "url": raw, "reason": result.reason},
                )

        # ── Experience entries ────────────────────────────────
        for entry in record.experience:
            raw = entry.get("url")
            if raw and isinstance(raw, str):
                result = normalize_url(raw)
                if result.changed and result.confidence > 0.0:
                    entry["url"] = result.normalized

        # ── Project entries ───────────────────────────────────
        for proj in record.projects:
            raw = proj.get("url")
            if raw and isinstance(raw, str):
                result = normalize_url(raw)
                if result.changed and result.confidence > 0.0:
                    proj["url"] = result.normalized

        # ── other_links ───────────────────────────────────────
        for platform, url in list(record.other_links.items()):
            if url:
                result = normalize_url(url)
                if result.changed and result.confidence > 0.0:
                    record.other_links[platform] = result.normalized

        return record
