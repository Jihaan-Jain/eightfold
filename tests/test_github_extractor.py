"""
tests/test_github_extractor.py
================================

Unit tests for GithubExtractor.

All HTTP calls are mocked via unittest.mock — no real network requests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.extractors.github_extractor import GithubExtractor
from src.exceptions import ExtractionError
from src.models import SourceType


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def extractor() -> GithubExtractor:
    return GithubExtractor()


def _mock_response(
    status_code: int = 200,
    json_data: object = None,
    headers: dict | None = None,
) -> MagicMock:
    """Build a mock requests.Response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.headers = headers or {
        "X-RateLimit-Remaining": "59",
        "X-RateLimit-Reset": "1700000000",
    }
    return resp


_PROFILE_DATA = {
    "login":       "priya-sharma",
    "name":        "Priya Sharma",
    "bio":         "ML Engineer",
    "email":       "priya@example.com",
    "location":    "Bangalore, India",
    "company":     "Eightfold AI",
    "blog":        "https://priya.dev",
    "public_repos": 12,
    "followers":   400,
    "following":   50,
}

_REPOS_DATA = [
    {
        "name":             "ml-project",
        "language":         "Python",
        "stargazers_count": 150,
        "forks_count":      30,
        "topics":           ["machine-learning", "pytorch"],
    },
    {
        "name":             "data-pipeline",
        "language":         "Python",
        "stargazers_count": 80,
        "forks_count":      10,
        "topics":           ["data-engineering", "apache-airflow"],
    },
    {
        "name":             "frontend-demo",
        "language":         "JavaScript",
        "stargazers_count": 20,
        "forks_count":      5,
        "topics":           [],
    },
]


# ── supports() ────────────────────────────────────────────────


class TestSupports:
    def test_plain_username(self, extractor) -> None:
        assert extractor.supports("priya-sharma") is True

    def test_github_profile_url(self, extractor) -> None:
        assert extractor.supports("https://github.com/priya-sharma") is True

    def test_github_profile_url_with_slash(self, extractor) -> None:
        assert extractor.supports("https://github.com/priya-sharma/") is True

    def test_github_api_url(self, extractor) -> None:
        assert extractor.supports("https://api.github.com/users/priya-sharma") is True

    def test_csv_file_not_supported(self, extractor) -> None:
        assert extractor.supports("data/file.csv") is False

    def test_pdf_not_supported(self, extractor) -> None:
        assert extractor.supports("resume.pdf") is False


# ── _resolve_username() ───────────────────────────────────────


class TestResolveUsername:
    def test_plain_username(self, extractor) -> None:
        assert extractor._resolve_username("priya-sharma") == "priya-sharma"

    def test_profile_url(self, extractor) -> None:
        assert extractor._resolve_username(
            "https://github.com/priya-sharma"
        ) == "priya-sharma"

    def test_api_url(self, extractor) -> None:
        assert extractor._resolve_username(
            "https://api.github.com/users/priya-sharma"
        ) == "priya-sharma"

    def test_url_with_trailing_slash(self, extractor) -> None:
        assert extractor._resolve_username(
            "https://github.com/priya-sharma/"
        ) == "priya-sharma"

    def test_invalid_returns_empty(self, extractor) -> None:
        assert extractor._resolve_username("not/a/valid/source/string") == ""


# ── validate_source() ─────────────────────────────────────────


class TestValidateSource:
    def test_valid_username_passes(self, extractor) -> None:
        extractor.validate_source("priya-sharma")  # Must not raise

    def test_invalid_source_raises(self, extractor) -> None:
        with pytest.raises(ExtractionError, match="Cannot resolve"):
            extractor.validate_source("not/a/valid/source/string")


# ── extract() — Happy Path ────────────────────────────────────


class TestExtractHappyPath:
    def test_returns_single_record(self, extractor) -> None:
        profile_resp = _mock_response(200, _PROFILE_DATA)
        repos_resp   = _mock_response(200, _REPOS_DATA)

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.side_effect = [profile_resp, repos_resp]
            mock_session_factory.return_value = session

            records = extractor.extract("priya-sharma")

        assert len(records) == 1

    def test_source_type_is_github(self, extractor) -> None:
        profile_resp = _mock_response(200, _PROFILE_DATA)
        repos_resp   = _mock_response(200, _REPOS_DATA)

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.side_effect = [profile_resp, repos_resp]
            mock_session_factory.return_value = session
            records = extractor.extract("priya-sharma")

        assert records[0].source_type == SourceType.GITHUB

    def test_candidate_hint_is_username(self, extractor) -> None:
        profile_resp = _mock_response(200, _PROFILE_DATA)
        repos_resp   = _mock_response(200, _REPOS_DATA)

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.side_effect = [profile_resp, repos_resp]
            mock_session_factory.return_value = session
            records = extractor.extract("priya-sharma")

        assert records[0].candidate_hint == "priya-sharma"

    def test_raw_fields_keys(self, extractor) -> None:
        profile_resp = _mock_response(200, _PROFILE_DATA)
        repos_resp   = _mock_response(200, _REPOS_DATA)

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.side_effect = [profile_resp, repos_resp]
            mock_session_factory.return_value = session
            records = extractor.extract("priya-sharma")

        rf = records[0].raw_fields
        for key in ("profile", "repos", "languages", "topics",
                    "total_stars", "total_forks", "public_repo_count"):
            assert key in rf, f"Missing raw_field: {key}"

    def test_language_aggregation(self, extractor) -> None:
        profile_resp = _mock_response(200, _PROFILE_DATA)
        repos_resp   = _mock_response(200, _REPOS_DATA)

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.side_effect = [profile_resp, repos_resp]
            mock_session_factory.return_value = session
            records = extractor.extract("priya-sharma")

        langs = records[0].raw_fields["languages"]
        # 2 Python repos, 1 JavaScript repo
        assert langs.get("Python") == 2
        assert langs.get("JavaScript") == 1

    def test_total_stars(self, extractor) -> None:
        profile_resp = _mock_response(200, _PROFILE_DATA)
        repos_resp   = _mock_response(200, _REPOS_DATA)

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.side_effect = [profile_resp, repos_resp]
            mock_session_factory.return_value = session
            records = extractor.extract("priya-sharma")

        assert records[0].raw_fields["total_stars"] == 150 + 80 + 20

    def test_topics_aggregated_and_sorted(self, extractor) -> None:
        profile_resp = _mock_response(200, _PROFILE_DATA)
        repos_resp   = _mock_response(200, _REPOS_DATA)

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.side_effect = [profile_resp, repos_resp]
            mock_session_factory.return_value = session
            records = extractor.extract("priya-sharma")

        topics = records[0].raw_fields["topics"]
        assert "machine-learning" in topics
        assert "data-engineering" in topics
        # Should be sorted
        assert topics == sorted(topics)

    def test_metadata_keys(self, extractor) -> None:
        profile_resp = _mock_response(200, _PROFILE_DATA)
        repos_resp   = _mock_response(200, _REPOS_DATA)

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.side_effect = [profile_resp, repos_resp]
            mock_session_factory.return_value = session
            records = extractor.extract("priya-sharma")

        meta = records[0].metadata
        # Standard block
        for key in ("checksum", "file_size", "mime", "encoding", "pages", "language"):
            assert key in meta, f"Missing standard key: {key}"
        # GitHub-specific
        for key in ("api_base_url", "username", "repos_fetched",
                    "rate_limit_remaining", "http_status"):
            assert key in meta, f"Missing GitHub key: {key}"
        # Standard block values for API source
        assert meta["checksum"] is None
        assert meta["file_size"] is None
        assert meta["mime"] == "application/json"
        assert meta["encoding"] == "utf-8"
        assert meta["pages"] is None

    def test_url_source_format_works(self, extractor) -> None:
        profile_resp = _mock_response(200, _PROFILE_DATA)
        repos_resp   = _mock_response(200, _REPOS_DATA)

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.side_effect = [profile_resp, repos_resp]
            mock_session_factory.return_value = session
            records = extractor.extract("https://github.com/priya-sharma")

        assert len(records) == 1
        assert records[0].metadata["username"] == "priya-sharma"

    def test_language_in_standard_block(self, extractor) -> None:
        """metadata['language'] = most-used programming language."""
        profile_resp = _mock_response(200, _PROFILE_DATA)
        repos_resp   = _mock_response(200, _REPOS_DATA)

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.side_effect = [profile_resp, repos_resp]
            mock_session_factory.return_value = session
            records = extractor.extract("priya-sharma")

        # _REPOS_DATA: Python×2, JavaScript×1 → top = Python
        assert records[0].metadata["language"] == "Python"


# ── extract() — Error Handling ────────────────────────────────


class TestExtractErrorHandling:
    def test_404_raises_extraction_error(self, extractor) -> None:
        not_found_resp = _mock_response(404, {"message": "Not Found"})

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.return_value = not_found_resp
            mock_session_factory.return_value = session

            with pytest.raises(ExtractionError, match="not found"):
                extractor.extract("nonexistent-user-xyz")

    def test_403_without_retry_after_raises(self, extractor) -> None:
        forbidden_resp = _mock_response(
            403,
            {"message": "Forbidden"},
            headers={"X-RateLimit-Remaining": "0"},
        )

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.return_value = forbidden_resp
            mock_session_factory.return_value = session

            with pytest.raises(ExtractionError, match="403"):
                extractor.extract("priya-sharma")

    def test_network_timeout_raises_after_retries(self) -> None:
        import requests as req_lib

        extractor = GithubExtractor(config={"max_retries": 2, "retry_delay": 0.01})

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.side_effect = req_lib.Timeout("timeout")
            mock_session_factory.return_value = session

            with pytest.raises(ExtractionError):
                extractor.extract("priya-sharma")

    def test_fetch_repos_false_skips_repos_call(self) -> None:
        extractor = GithubExtractor(config={"fetch_repos": False})
        profile_resp = _mock_response(200, _PROFILE_DATA)

        with patch.object(extractor, "_build_session") as mock_session_factory:
            session = MagicMock()
            session.get.return_value = profile_resp
            mock_session_factory.return_value = session
            records = extractor.extract("priya-sharma")

        # Only one GET call (profile), no repos call.
        assert session.get.call_count == 1
        assert records[0].raw_fields["repos"] == []

    def test_metadata_method(self, extractor) -> None:
        m = extractor.metadata()
        assert m["source_type"] == "github"
