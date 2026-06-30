"""
src/mapping/github_mapper.py
=============================

Mapper for GitHub API records extracted by
:class:`~src.extractors.GithubExtractor`.

RawRecord Structure
-------------------
::

    raw_fields = {
        "profile":           { GitHub user object },
        "repos":             [ list of repo dicts ],
        "languages":         { "Python": 8, "JavaScript": 3 },
        "topics":            [ sorted unique topic strings ],
        "total_stars":       int,
        "total_forks":       int,
        "public_repo_count": int,
    }

Mapping Strategy
----------------
1. Map scalar profile fields (name, bio, location, email, blog, company)
   directly from ``profile``.
2. Map contact URLs (blog → website, html_url → github_url, login → github_username).
3. Map repo-aggregated stats (stars, forks, public_repo_count, languages).
4. Map topics → skills (topics are effectively skill tags on GitHub).
5. Map individual repos → experience entries (each repo is a project the
   candidate built).
6. Map languages → skills (in addition to topics).
7. Record follower / following counts in mapping_metadata.
"""

from __future__ import annotations

from typing import Any

from src.mapping.base import BaseMapper
from src.mapping.utils import (
    clean_str,
    make_provenance,
    set_field,
)
from src.models import (
    CanonicalRecord,
    MappingMethod,
    RawRecord,
    SourceType,
)

# ── Fields to skip (internal GitHub API fields) ───────────────────

_IGNORED_PROFILE_KEYS: frozenset[str] = frozenset(
    {
        "id", "node_id", "url", "followers_url", "following_url",
        "gists_url", "starred_url", "subscriptions_url",
        "organizations_url", "repos_url", "events_url",
        "received_events_url", "type", "site_admin",
        "gravatar_id", "avatar_url", "updated_at", "created_at",
    }
)


class GithubMapper(BaseMapper):
    """
    Maps a GitHub-sourced :class:`~src.models.RawRecord` to a
    :class:`~src.models.CanonicalRecord`.

    Config Keys
    -----------
    ``max_repos`` (int)
        Maximum number of repos to convert to experience entries.
        Default: ``20``.
    ``include_forked`` (bool)
        Whether to include forked repos in skills/experience.
        Default: ``False``.
    ``topics_as_skills`` (bool)
        Map GitHub topics to the skills field.  Default: ``True``.
    ``languages_as_skills`` (bool)
        Map GitHub language names to the skills field.  Default: ``True``.
    """

    @property
    def source_type(self) -> SourceType:
        return SourceType.GITHUB

    def supports(self, record: RawRecord) -> bool:
        return record.source_type == SourceType.GITHUB

    def metadata(self) -> dict[str, Any]:
        return {
            "mapper":       self.__class__.__name__,
            "source_type":  self.source_type.value,
            "version":      "1.0.0",
        }

    def map(self, record: RawRecord) -> CanonicalRecord:
        """Map a GitHub RawRecord to a CanonicalRecord."""
        return self._timed_map(record, self._do_map)

    # ── Internal implementation ───────────────────────────────

    def _do_map(self, record: RawRecord) -> CanonicalRecord:
        canonical = self._make_canonical(record)
        rf = record.raw_fields

        profile: dict[str, Any]  = rf.get("profile", {}) or {}
        repos:   list[dict]       = rf.get("repos", [])   or []
        languages: dict[str, int] = rf.get("languages", {}) or {}
        topics:    list[str]      = rf.get("topics", [])   or []
        total_stars: int          = rf.get("total_stars", 0)   or 0
        total_forks: int          = rf.get("total_forks", 0)   or 0
        pub_repo_count: int       = rf.get("public_repo_count", 0) or 0

        canonical.mapping_metadata["mapper"] = "GithubMapper"
        canonical.mapping_metadata["username"] = record.candidate_hint

        # ── Profile fields ────────────────────────────────────
        self._map_profile(canonical, profile, record)

        # ── Stats ─────────────────────────────────────────────
        self._map_stats(canonical, total_stars, total_forks,
                        pub_repo_count, languages, record)

        # ── Skills from topics ────────────────────────────────
        if self._config.get("topics_as_skills", True) and topics:
            prov = make_provenance(
                field="skills", source=record.source_type,
                method=MappingMethod.DIRECT,
                original_value=topics, mapped_value=topics,
                raw_field_name="topics",
            )
            set_field(canonical, "skills", topics, prov)

        # ── Skills from languages ─────────────────────────────
        if self._config.get("languages_as_skills", True) and languages:
            lang_skills = list(languages.keys())
            prov = make_provenance(
                field="skills", source=record.source_type,
                method=MappingMethod.DIRECT,
                original_value=lang_skills, mapped_value=lang_skills,
                raw_field_name="languages",
            )
            set_field(canonical, "skills", lang_skills, prov)

        # ── Repos → experience ────────────────────────────────
        self._map_repos(canonical, repos, record)

        return canonical

    def _map_profile(
        self,
        canonical: CanonicalRecord,
        profile: dict[str, Any],
        record: RawRecord,
    ) -> None:
        """Map GitHub user profile fields to canonical fields."""

        def _prov(field: str, raw_key: str, orig: Any, mapped: Any,
                  method: MappingMethod = MappingMethod.DIRECT) -> None:
            prov = make_provenance(
                field=field, source=record.source_type,
                method=method, original_value=orig,
                mapped_value=mapped, raw_field_name=f"profile.{raw_key}",
            )
            set_field(canonical, field, mapped, prov)

        # Name
        name = clean_str(profile.get("name"))
        if name:
            _prov("full_name", "name", profile.get("name"), name)

        # GitHub URL
        html_url = clean_str(profile.get("html_url"))
        if html_url:
            _prov("github_url", "html_url", html_url, html_url)

        # GitHub username (login)
        login = clean_str(profile.get("login")) or clean_str(record.candidate_hint)
        if login:
            _prov("github_username", "login", profile.get("login"), login)

        # Bio → summary
        bio = clean_str(profile.get("bio"))
        if bio:
            _prov("summary", "bio", bio, bio)

        # Location
        loc = clean_str(profile.get("location"))
        if loc:
            _prov("location", "location", loc, loc)

        # Email
        email = clean_str(profile.get("email"))
        if email:
            _prov("emails", "email", email, email)

        # Blog → website
        blog = clean_str(profile.get("blog"))
        if blog:
            # Ensure scheme
            if blog and not blog.startswith("http"):
                blog = f"https://{blog}"
            _prov("website", "blog", profile.get("blog"), blog)

        # Company → current_company
        company = clean_str(profile.get("company"))
        if company:
            # Strip leading @ (GitHub convention: "@Eightfold")
            company = company.lstrip("@").strip()
            _prov("current_company", "company", profile.get("company"), company)

        # Twitter handle → other_links
        twitter = clean_str(profile.get("twitter_username"))
        if twitter:
            canonical.other_links["twitter"] = f"https://twitter.com/{twitter}"
            if "other_links" not in canonical.mapped_fields:
                canonical.mapped_fields.append("other_links")

        # Record ignored keys
        for key in profile:
            if key in _IGNORED_PROFILE_KEYS:
                self._record_ignored(canonical, f"profile.{key}")

    def _map_stats(
        self,
        canonical: CanonicalRecord,
        total_stars: int,
        total_forks: int,
        pub_repo_count: int,
        languages: dict[str, int],
        record: RawRecord,
    ) -> None:
        """Map GitHub statistics to canonical stat fields."""

        def _prov(field: str, raw_key: str, orig: Any, mapped: Any) -> None:
            prov = make_provenance(
                field=field, source=record.source_type,
                method=MappingMethod.DIRECT,
                original_value=orig, mapped_value=mapped,
                raw_field_name=raw_key,
            )
            set_field(canonical, field, mapped, prov)

        if total_stars:
            _prov("github_stars", "total_stars", total_stars, total_stars)

        if pub_repo_count:
            _prov("github_repos", "public_repo_count", pub_repo_count, pub_repo_count)

        # Primary language
        if languages:
            top_lang = max(languages, key=lambda lang: languages[lang])
            _prov("primary_language", "languages", languages, top_lang)

        # Store followers / following in metadata
        profile = record.raw_fields.get("profile", {}) or {}
        canonical.mapping_metadata["followers"] = profile.get("followers", 0)
        canonical.mapping_metadata["following"] = profile.get("following", 0)
        canonical.mapping_metadata["total_forks"] = total_forks
        canonical.mapping_metadata["languages_breakdown"] = languages

    def _map_repos(
        self,
        canonical: CanonicalRecord,
        repos: list[dict[str, Any]],
        record: RawRecord,
    ) -> None:
        """
        Map GitHub repos to experience entries.

        Each non-forked public repo becomes an experience entry:
        ``company`` = GitHub username, ``title`` = repo name,
        ``description`` = repo description, ``technologies`` = topics.
        """
        max_repos      = self._config.get("max_repos", 20)
        include_forked = self._config.get("include_forked", False)
        username       = clean_str(record.candidate_hint) or "github"

        count = 0
        for repo in repos:
            if count >= max_repos:
                break
            if not include_forked and repo.get("fork"):
                continue

            entry: dict[str, Any] = {
                "company":     f"github/{username}",
                "title":       clean_str(repo.get("name")),
                "description": clean_str(repo.get("description")),
                "start_date":  None,
                "end_date":    None,
                "is_current":  not repo.get("archived", False),
                "location":    "Remote / Open Source",
                "url":         clean_str(repo.get("html_url")),
                "stars":       repo.get("stargazers_count", 0),
                "forks":       repo.get("forks_count", 0),
                "technologies": repo.get("topics", []),
                "language":    clean_str(repo.get("language")),
            }

            prov = make_provenance(
                field="experience", source=record.source_type,
                method=MappingMethod.DIRECT,
                original_value=repo, mapped_value=entry,
                raw_field_name=f"repos[{count}]",
                confidence=0.9,
            )
            set_field(canonical, "experience", entry, prov)
            count += 1
