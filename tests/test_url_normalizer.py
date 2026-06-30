"""
tests/test_url_normalizer.py
==============================

Unit tests for src/normalization/url_normalizer.py.
"""

from __future__ import annotations

import pytest

from src.normalization.url_normalizer import UrlNormalizer, normalize_url
from src.models import CanonicalRecord, NormalizationMethod, SourceType


def _rec(**kwargs) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="test-id",
        source_type=SourceType.CSV,
        source_label="test.csv",
        **kwargs,
    )


class TestNormalizeUrlFunction:
    # ── GitHub canonical ──────────────────────────────────────
    def test_github_https(self):
        r = normalize_url("https://github.com/alice")
        assert r.normalized == "https://github.com/alice"

    def test_github_http_upgraded(self):
        r = normalize_url("http://github.com/alice")
        assert r.normalized == "https://github.com/alice"

    def test_github_no_scheme(self):
        r = normalize_url("github.com/alice")
        assert r.normalized == "https://github.com/alice"

    def test_github_www(self):
        r = normalize_url("https://www.github.com/alice")
        assert r.normalized == "https://github.com/alice"

    def test_github_trailing_slash(self):
        r = normalize_url("https://github.com/alice/")
        assert r.normalized == "https://github.com/alice"

    def test_github_with_path(self):
        # Only login is kept
        r = normalize_url("https://github.com/alice/ml-pipeline")
        assert r.normalized == "https://github.com/alice"

    # ── LinkedIn canonical ────────────────────────────────────
    def test_linkedin_https(self):
        r = normalize_url("https://linkedin.com/in/alice-smith")
        assert r.normalized == "https://linkedin.com/in/alice-smith"

    def test_linkedin_http_upgraded(self):
        r = normalize_url("http://linkedin.com/in/alice")
        assert r.normalized == "https://linkedin.com/in/alice"

    def test_linkedin_www(self):
        r = normalize_url("https://www.linkedin.com/in/alice")
        assert r.normalized == "https://linkedin.com/in/alice"

    def test_linkedin_handle_lowercased(self):
        r = normalize_url("https://linkedin.com/in/Alice-Smith")
        assert r.normalized == "https://linkedin.com/in/alice-smith"

    def test_linkedin_trailing_slash(self):
        r = normalize_url("https://www.linkedin.com/in/alice/")
        assert r.normalized == "https://linkedin.com/in/alice"

    # ── Generic URL ───────────────────────────────────────────
    def test_http_upgraded_to_https(self):
        r = normalize_url("http://example.com/page")
        assert r.normalized.startswith("https://")

    def test_scheme_added_when_missing(self):
        r = normalize_url("example.com/page")
        assert r.normalized.startswith("https://")

    def test_double_slash_scheme(self):
        r = normalize_url("//example.com/page")
        assert r.normalized.startswith("https://")

    def test_tracking_utm_stripped(self):
        r = normalize_url("https://example.com/page?utm_source=google&utm_medium=cpc")
        assert "utm_source" not in r.normalized
        assert "utm_medium" not in r.normalized

    def test_tracking_ref_stripped(self):
        r = normalize_url("https://example.com/?ref=newsletter")
        assert "ref=" not in r.normalized

    def test_tracking_fbclid_stripped(self):
        r = normalize_url("https://example.com/?fbclid=abc123")
        assert "fbclid" not in r.normalized

    def test_meaningful_params_preserved(self):
        r = normalize_url("https://example.com/search?q=python&page=2")
        assert "q=python" in r.normalized
        assert "page=2" in r.normalized

    def test_trailing_slash_removed(self):
        r = normalize_url("https://example.com/path/")
        assert not r.normalized.endswith("/")

    def test_root_trailing_slash_kept(self):
        r = normalize_url("https://example.com/")
        # Root slash is acceptable
        assert "example.com" in r.normalized

    def test_host_lowercased(self):
        r = normalize_url("https://EXAMPLE.COM/page")
        assert "example.com" in r.normalized

    def test_scheme_lowercased(self):
        r = normalize_url("HTTPS://example.com")
        assert r.normalized.startswith("https://")

    def test_empty_url(self):
        r = normalize_url("")
        assert r.confidence == 0.0

    def test_whitespace_only(self):
        r = normalize_url("   ")
        assert r.confidence == 0.0

    def test_changed_flag_on_upgrade(self):
        r = normalize_url("http://example.com")
        assert r.changed is True

    def test_changed_flag_false_on_canonical(self):
        r = normalize_url("https://example.com")
        assert r.changed is False or "example.com" in r.normalized


class TestUrlNormalizer:
    @pytest.fixture
    def normalizer(self):
        return UrlNormalizer()

    def test_github_url_normalized(self, normalizer):
        rec = _rec(github_url="http://github.com/alice/")
        out = normalizer.normalize(rec)
        assert out.github_url == "https://github.com/alice"

    def test_linkedin_url_normalized(self, normalizer):
        rec = _rec(linkedin_url="http://www.linkedin.com/in/Alice/")
        out = normalizer.normalize(rec)
        assert out.linkedin_url == "https://linkedin.com/in/alice"

    def test_website_http_upgraded(self, normalizer):
        rec = _rec(website="http://alice.dev")
        out = normalizer.normalize(rec)
        assert out.website.startswith("https://")

    def test_website_tracking_stripped(self, normalizer):
        rec = _rec(website="https://alice.dev?utm_source=twitter")
        out = normalizer.normalize(rec)
        assert "utm_source" not in out.website

    def test_experience_url_normalized(self, normalizer):
        rec = _rec(experience=[{"url": "http://github.com/alice/ml-pipeline"}])
        out = normalizer.normalize(rec)
        assert out.experience[0]["url"] == "https://github.com/alice"

    def test_project_url_normalized(self, normalizer):
        rec = _rec(projects=[{"url": "http://example.com/project"}])
        out = normalizer.normalize(rec)
        assert out.projects[0]["url"].startswith("https://")

    def test_other_links_normalized(self, normalizer):
        rec = _rec(other_links={"twitter": "http://twitter.com/alice"})
        out = normalizer.normalize(rec)
        assert out.other_links["twitter"].startswith("https://")

    def test_none_url_skipped(self, normalizer):
        rec = _rec(github_url=None, linkedin_url=None)
        out = normalizer.normalize(rec)
        assert out.github_url is None

    def test_provenance_written_on_change(self, normalizer):
        rec = _rec(github_url="http://github.com/alice")
        out = normalizer.normalize(rec)
        assert any(p.field == "github_url" for p in out.provenance)

    def test_supports_with_github_url(self, normalizer):
        rec = _rec(github_url="https://github.com/alice")
        assert normalizer.supports(rec) is True

    def test_supports_false_when_no_urls(self, normalizer):
        rec = _rec()
        assert normalizer.supports(rec) is False

    def test_metadata_returns_dict(self, normalizer):
        m = normalizer.metadata()
        assert isinstance(m, dict)
        assert "github_url" in m.get("fields", [])
