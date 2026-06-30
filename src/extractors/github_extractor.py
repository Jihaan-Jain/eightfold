"""
src/extractors/github_extractor.py
====================================

Extractor for GitHub user profiles via the GitHub REST API v3.

Accepts any of these ``source`` formats::

    "priya-sharma"                           # plain username
    "https://github.com/priya-sharma"        # profile URL
    "https://github.com/priya-sharma/"       # with trailing slash
    "https://api.github.com/users/priya-sharma"  # API URL

Collects
--------
- User profile (name, bio, location, email, blog, company, etc.)
- Up to 100 most-recently-updated public repositories
- Primary language per repository (aggregated into a language map)
- Repository topics
- Aggregate statistics: total stars, total forks, repo count, etc.

Returns **one** :class:`~src.models.RawRecord` per GitHub username.

Error Handling
--------------
==================  ==================================================
HTTP Status         Behaviour
==================  ==================================================
200                 Normal extraction
403 / 429           Rate limit — backs off and retries (configurable)
404                 Raises ExtractionError (username does not exist)
5xx                 Raises ExtractionError after retries exhausted
Network timeout     Raises ExtractionError after retries exhausted
==================  ==================================================

RawRecord layout
----------------
``raw_fields``
    +--------------------------+--------------------------------------+
    | Key                      | Value                                |
    +==========================+======================================+
    | ``profile``              | GitHub user object dict              |
    | ``repos``                | List of repository dicts             |
    | ``languages``            | ``{language: repo_count}`` mapping   |
    | ``topics``               | Sorted list of unique topic strings  |
    | ``total_stars``          | Sum of stargazer_count across repos  |
    | ``total_forks``          | Sum of forks_count across repos      |
    | ``public_repo_count``    | ``profile["public_repos"]``          |
    +--------------------------+--------------------------------------+

``metadata`` — standard block
    +--------------------------+--------------------------------------+
    | Key                      | Value                                |
    +==========================+======================================+
    | ``checksum``             | ``None`` (API source; no local file) |
    | ``file_size``            | ``None`` (API source)                |
    | ``mime``                 | ``"application/json"`` (wire format) |
    | ``encoding``             | ``"utf-8"`` (GitHub API always UTF-8)|
    | ``pages``                | ``None`` (N/A for GitHub)            |
    | ``language``             | Most-used language across repos      |
    +--------------------------+--------------------------------------+

``metadata`` — GitHub-specific keys
    +--------------------------+--------------------------------------+
    | Key                      | Value                                |
    +==========================+======================================+
    | ``api_base_url``         | GitHub API base URL used             |
    | ``username``             | Resolved GitHub username             |
    | ``repos_fetched``        | Actual number of repos in ``repos``  |
    | ``rate_limit_remaining`` | ``X-RateLimit-Remaining`` header     |
    | ``rate_limit_reset``     | ``X-RateLimit-Reset`` header (epoch) |
    | ``http_status``          | Final HTTP status for profile call   |
    +--------------------------+--------------------------------------+
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.exceptions import ExtractionError
from src.extractors.base import BaseExtractor
from src.extractors.utils import build_standard_metadata, normalise_source_label, retry
from src.models import RawRecord, SourceType

# Public GitHub API base URL.
_GITHUB_API_BASE: str = "https://api.github.com"

# Maximum repos fetched per user (GitHub caps per_page at 100).
_MAX_REPOS: int = 100

# Default HTTP timeout in seconds.
_DEFAULT_TIMEOUT: float = 15.0

# Regex to extract a username from a github.com profile URL.
_GITHUB_PROFILE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9\-]+)/?$",
    re.IGNORECASE,
)

# Regex to extract a username from a GitHub API URL.
_GITHUB_API_RE = re.compile(
    r"(?:https?://)?api\.github\.com/users/([a-zA-Z0-9\-]+)/?",
    re.IGNORECASE,
)

# HTTP status codes worth retrying on.
_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class GithubExtractor(BaseExtractor):
    """
    Extractor for GitHub user profile data via the REST API.

    Config Keys
    -----------
    ``api_token`` (str | None)
        GitHub Personal Access Token (classic or fine-grained).
        When set, the rate limit rises from 60 to 5 000 requests/hour.
    ``api_base_url`` (str)
        Override the API base URL.  Default: ``"https://api.github.com"``.
    ``timeout`` (float)
        HTTP request timeout in seconds.  Default: ``15.0``.
    ``max_retries`` (int)
        Number of retry attempts on transient failures.  Default: ``3``.
    ``retry_delay`` (float)
        Initial back-off delay in seconds.  Default: ``1.0``.
    ``fetch_repos`` (bool)
        When ``False``, skip repo fetching (faster; profile only).
        Default: ``True``.

    Examples
    --------
    ::

        extractor = GithubExtractor(config={"api_token": "ghp_..."})
        records = extractor.extract("priya-sharma")
        profile = records[0].raw_fields["profile"]
        print(profile["name"])
    """

    @property
    def source_type(self) -> SourceType:
        """Returns :attr:`~src.models.SourceType.GITHUB`."""
        return SourceType.GITHUB

    def supports(self, source: str | Path) -> bool:
        """
        Return ``True`` for GitHub usernames, profile URLs, and API URLs.

        A bare string without slashes or dots is treated as a username.
        """
        s = str(source)
        if _GITHUB_PROFILE_RE.search(s):
            return True
        if _GITHUB_API_RE.search(s):
            return True
        # Plain username: alphanumeric + hyphens, no dots or slashes.
        if re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,37}[a-zA-Z0-9])?", s):
            return True
        return False

    def validate_source(self, source: str | Path) -> None:
        """
        Validate that ``source`` resolves to a GitHub username string.

        Raises
        ------
        src.exceptions.ExtractionError
            If the username cannot be parsed from ``source``.
        """
        username = self._resolve_username(str(source))
        if not username:
            raise ExtractionError(
                f"Cannot resolve a GitHub username from source: {source!r}",
                source_type=self.source_type.value,
            )

    def extract(self, source: str | Path) -> list[RawRecord]:
        """
        Fetch GitHub profile and repository data for a user.

        Returns a **single-element list** containing one
        :class:`~src.models.RawRecord`.

        Parameters
        ----------
        source:
            GitHub username, profile URL, or API URL.

        Returns
        -------
        list[RawRecord]
            Always a list with exactly one element.

        Raises
        ------
        src.exceptions.ExtractionError
            On 404 (user not found), exhausted retries, or network errors.
        """
        self.validate_source(source)
        return self._timed_extract(source, self._do_extract)

    def metadata(self) -> dict[str, Any]:
        """Return static metadata about this extractor."""
        return {
            "extractor":   self.__class__.__name__,
            "source_type": self.source_type.value,
            "version":     "1.0.0",
            "api_base":    self._config.get("api_base_url", _GITHUB_API_BASE),
            "max_repos":   _MAX_REPOS,
        }

    # ── Internal implementation ───────────────────────────────

    def _do_extract(self, source: str | Path) -> list[RawRecord]:
        """Core extraction: resolve username → fetch profile → fetch repos."""
        import requests  # imported here so library is optional at import time

        username = self._resolve_username(str(source))
        source_label = f"github/{username}"
        api_base = self._config.get("api_base_url", _GITHUB_API_BASE).rstrip("/")
        timeout: float = float(self._config.get("timeout", _DEFAULT_TIMEOUT))
        fetch_repos: bool = bool(self._config.get("fetch_repos", True))

        session = self._build_session()

        # ── Fetch profile ─────────────────────────────────────
        profile_url = f"{api_base}/users/{username}"
        profile_resp = self._get_with_retry(
            session, profile_url, timeout, username
        )
        profile: dict[str, Any] = profile_resp.json()

        rate_remaining = profile_resp.headers.get("X-RateLimit-Remaining", "")
        rate_reset = profile_resp.headers.get("X-RateLimit-Reset", "")

        # ── Fetch repos ───────────────────────────────────────
        repos: list[dict[str, Any]] = []
        if fetch_repos:
            repos_url = (
                f"{api_base}/users/{username}/repos"
                f"?per_page={_MAX_REPOS}&sort=updated&type=owner"
            )
            repos_resp = self._get_with_retry(
                session, repos_url, timeout, username
            )
            repos = repos_resp.json() if isinstance(repos_resp.json(), list) else []

        # ── Aggregate statistics ──────────────────────────────
        languages: dict[str, int] = {}
        topics: list[str] = []
        total_stars: int = 0
        total_forks: int = 0

        for repo in repos:
            lang = repo.get("language")
            if lang:
                languages[lang] = languages.get(lang, 0) + 1
            total_stars += repo.get("stargazers_count", 0)
            total_forks += repo.get("forks_count", 0)
            for topic in repo.get("topics", []):
                if topic not in topics:
                    topics.append(topic)

        topics.sort()

        top_lang = self._top_language(languages)

        record = RawRecord(
            source=source_label,
            source_type=self.source_type,
            raw_fields={
                "profile":           profile,
                "repos":             repos,
                "languages":         languages,
                "topics":            topics,
                "total_stars":       total_stars,
                "total_forks":       total_forks,
                "public_repo_count": profile.get("public_repos", 0),
            },
            candidate_hint=username,
            metadata={
                # ── Standard block ────────────────────────────────
                **build_standard_metadata(
                    checksum=None,          # API source — no local file
                    file_size=None,         # API source
                    mime="application/json",# GitHub API wire format
                    encoding="utf-8",       # GitHub API always UTF-8
                    pages=None,
                    language=top_lang,      # most-used language across repos
                ),
                # ── GitHub-specific ─────────────────────────────
                "api_base_url":         api_base,
                "username":             username,
                "repos_fetched":        len(repos),
                "rate_limit_remaining": rate_remaining,
                "rate_limit_reset":     rate_reset,
                "http_status":          profile_resp.status_code,
            },
        )
        return [record]

    # ── HTTP helpers ──────────────────────────────────────────

    def _build_session(self) -> Any:
        """
        Build a ``requests.Session`` with authentication headers.

        Returns
        -------
        requests.Session
            Session with ``Accept``, ``User-Agent``, and optional
            ``Authorization`` headers pre-configured.
        """
        import requests

        session = requests.Session()
        session.headers.update(
            {
                "Accept":     "application/vnd.github+json",
                "User-Agent": "candidate-transformer/1.0.0",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        token = self._config.get("api_token")
        if token:
            session.headers["Authorization"] = f"Bearer {token}"
        return session

    def _get_with_retry(
        self,
        session: Any,
        url: str,
        timeout: float,
        username: str,
    ) -> Any:
        """
        Perform a GET request with exponential back-off retry.

        Retries on network errors and :attr:`_RETRYABLE_STATUSES`.
        Raises immediately on 404 and 403 (non-rate-limit).

        Parameters
        ----------
        session:
            ``requests.Session`` instance.
        url:
            Fully-qualified URL to GET.
        timeout:
            Request timeout in seconds.
        username:
            GitHub username (for error messages).

        Returns
        -------
        requests.Response
            Successful response object.

        Raises
        ------
        src.exceptions.ExtractionError
            On 404, permanent 403, or exhausted retries.
        """
        import requests

        max_retries: int = int(self._config.get("max_retries", 3))
        delay: float = float(self._config.get("retry_delay", 1.0))
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                resp = session.get(url, timeout=timeout)
            except requests.Timeout as exc:
                last_exc = exc
                self._log.warning(
                    "GitHub request timed out",
                    extra={"url": url, "attempt": attempt, "max": max_retries},
                )
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2.0
                continue
            except requests.ConnectionError as exc:
                last_exc = exc
                self._log.warning(
                    "GitHub connection error",
                    extra={"url": url, "attempt": attempt, "error": str(exc)},
                )
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2.0
                continue

            # ── Handle specific HTTP status codes ─────────────
            if resp.status_code == 200:
                return resp

            if resp.status_code == 404:
                raise ExtractionError(
                    f"GitHub user not found: '{username}'",
                    source_type=self.source_type.value,
                    source_path=url,
                )

            if resp.status_code == 403:
                # Check if this is a rate limit (has Retry-After or reset header).
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    sleep_secs = float(retry_after)
                    self._log.warning(
                        "GitHub rate limit (403); sleeping",
                        extra={"retry_after": sleep_secs, "url": url},
                    )
                    time.sleep(min(sleep_secs, 60.0))
                    continue
                raise ExtractionError(
                    f"GitHub API returned 403 Forbidden for '{username}'. "
                    "Check API token permissions.",
                    source_type=self.source_type.value,
                    source_path=url,
                )

            if resp.status_code == 429:
                # True rate limit response.
                retry_after = resp.headers.get("Retry-After", "5")
                sleep_secs = float(retry_after)
                self._log.warning(
                    "GitHub rate limit (429); sleeping",
                    extra={"retry_after": sleep_secs, "attempt": attempt},
                )
                time.sleep(min(sleep_secs, 60.0))
                continue

            if resp.status_code in _RETRYABLE_STATUSES or resp.status_code >= 500:
                self._log.warning(
                    "GitHub transient error",
                    extra={"status": resp.status_code, "url": url, "attempt": attempt},
                )
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2.0
                last_exc = ExtractionError(
                    f"GitHub API returned HTTP {resp.status_code} for {url}",
                    source_type=self.source_type.value,
                    source_path=url,
                )
                continue

            # Unexpected status code — raise immediately.
            raise ExtractionError(
                f"GitHub API returned unexpected HTTP {resp.status_code} for {url}",
                source_type=self.source_type.value,
                source_path=url,
            )

        # All retries exhausted.
        if last_exc is not None:
            if isinstance(last_exc, ExtractionError):
                raise last_exc
            raise ExtractionError(
                f"GitHub request failed after {max_retries} attempts: {last_exc}",
                source_type=self.source_type.value,
                source_path=url,
            ) from last_exc

        raise ExtractionError(
            f"GitHub request failed after {max_retries} attempts for {url}",
            source_type=self.source_type.value,
            source_path=url,
        )

    # ── Username resolution ───────────────────────────────────

    def _resolve_username(self, source: str) -> str:
        """
        Extract a GitHub username from any supported source format.

        Tries, in order:

        1. GitHub profile URL regex
        2. GitHub API URL regex
        3. Plain username (alphanumeric + hyphens, no slashes)

        Parameters
        ----------
        source:
            Raw source string.

        Returns
        -------
        str
            Resolved username, or empty string if unresolvable.
        """
        m = _GITHUB_PROFILE_RE.search(source)
        if m:
            return m.group(1)

        m = _GITHUB_API_RE.search(source)
        if m:
            return m.group(1)

        # Plain username: alphanumeric and hyphens, no slashes.
        stripped = source.strip().rstrip("/")
        if re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,37}[a-zA-Z0-9])?", stripped):
            return stripped

        return ""

    # ── Language helpers ──────────────────────────────────────

    @staticmethod
    def _top_language(languages: dict[str, int]) -> str | None:
        """
        Return the programming language with the highest repo count.

        Used to populate ``metadata["language"]`` in the standard block
        so downstream stages can read the dominant language without
        inspecting the full ``raw_fields["languages"]`` map.

        Parameters
        ----------
        languages:
            ``{language_name: repo_count}`` mapping built during
            repo aggregation.

        Returns
        -------
        str | None
            The language name with the highest count, or ``None``
            when ``languages`` is empty (no repos fetched, or all repos
            have ``null`` language).

        Examples
        --------
        ::

            _top_language({"Python": 8, "JavaScript": 3, "Shell": 1})
            # "Python"

            _top_language({})
            # None
        """
        if not languages:
            return None
        return max(languages, key=lambda lang: languages[lang])
