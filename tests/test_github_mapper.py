"""
tests/test_github_mapper.py
============================

Unit tests for src/mapping/github_mapper.py.

Covers
------
- Profile field mapping (name, bio, location, email, blog, company)
- URL mapping: html_url → github_url, blog → website
- GitHub username from login / candidate_hint
- Twitter handle → other_links
- Stats: github_stars, github_repos, primary_language
- Topics → skills
- Languages → skills
- Repos → experience entries (title, company, description, url)
- Fork filtering (include_forked=False by default)
- max_repos config
- Archived repo → is_current=False
- Metadata: followers, following, total_forks, languages_breakdown
- Provenance: stage, source_type
- Empty / null profile fields handled gracefully
"""

from __future__ import annotations

import pytest

from src.mapping.github_mapper import GithubMapper
from src.models import (
    ProcessingStage,
    RawRecord,
    SourceType,
)


# ================================================================
# Helpers / Fixtures
# ================================================================


_PROFILE: dict = {
    "login":             "alice",
    "name":              "Alice Smith",
    "html_url":          "https://github.com/alice",
    "bio":               "ML engineer & open source contributor.",
    "location":          "Bangalore, India",
    "email":             "alice@example.com",
    "blog":              "https://alice.dev",
    "company":           "@Eightfold",
    "twitter_username":  "alicecodes",
    "public_repos":      18,
    "followers":         234,
    "following":         56,
}

_REPOS: list[dict] = [
    {
        "name":             "ml-pipeline",
        "full_name":        "alice/ml-pipeline",
        "html_url":         "https://github.com/alice/ml-pipeline",
        "description":      "Production ML pipeline.",
        "language":         "Python",
        "stargazers_count": 120,
        "forks_count":      30,
        "fork":             False,
        "archived":         False,
        "topics":           ["ml", "pipeline", "python"],
    },
    {
        "name":             "react-ui",
        "full_name":        "alice/react-ui",
        "html_url":         "https://github.com/alice/react-ui",
        "description":      "Component library.",
        "language":         "JavaScript",
        "stargazers_count": 45,
        "forks_count":      10,
        "fork":             False,
        "archived":         False,
        "topics":           ["react", "ui"],
    },
    {
        "name":             "forked-repo",
        "html_url":         "https://github.com/alice/forked-repo",
        "description":      "A fork.",
        "language":         "Go",
        "stargazers_count": 0,
        "forks_count":      0,
        "fork":             True,
        "archived":         False,
        "topics":           [],
    },
]

_LANGUAGES: dict = {"Python": 8, "JavaScript": 3, "Shell": 1}
_TOPICS:    list  = ["ml", "pipeline", "python", "react", "ui"]
_TOTAL_STARS = 165
_TOTAL_FORKS = 40


def _make_record(
    profile: dict | None = None,
    repos: list | None = None,
    languages: dict | None = None,
    topics: list | None = None,
    total_stars: int = 0,
    total_forks: int = 0,
    pub_repo_count: int = 0,
    hint: str | None = "alice",
) -> RawRecord:
    return RawRecord(
        source="github/alice",
        source_type=SourceType.GITHUB,
        raw_fields={
            "profile":           profile or {},
            "repos":             repos or [],
            "languages":         languages or {},
            "topics":            topics or [],
            "total_stars":       total_stars,
            "total_forks":       total_forks,
            "public_repo_count": pub_repo_count,
        },
        candidate_hint=hint,
    )


@pytest.fixture()
def mapper() -> GithubMapper:
    return GithubMapper()


@pytest.fixture()
def full_record() -> RawRecord:
    return _make_record(
        profile=_PROFILE,
        repos=_REPOS,
        languages=_LANGUAGES,
        topics=_TOPICS,
        total_stars=_TOTAL_STARS,
        total_forks=_TOTAL_FORKS,
        pub_repo_count=18,
    )


# ================================================================
# Profile Field Mapping
# ================================================================


class TestProfileMapping:
    def test_full_name_mapped(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert cr.full_name == "Alice Smith"

    def test_github_url_from_html_url(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert cr.github_url == "https://github.com/alice"

    def test_github_username_from_login(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert cr.github_username == "alice"

    def test_github_username_from_hint_fallback(self, mapper) -> None:
        rec = _make_record(profile={}, hint="bob")
        cr = mapper.map(rec)
        assert cr.github_username == "bob"

    def test_bio_mapped_to_summary(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert cr.summary == "ML engineer & open source contributor."

    def test_location_mapped(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert cr.location == "Bangalore, India"

    def test_email_mapped(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert "alice@example.com" in cr.emails

    def test_blog_mapped_to_website(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert cr.website == "https://alice.dev"

    def test_blog_without_scheme_prefixed(self, mapper) -> None:
        rec = _make_record(profile={"login": "alice", "blog": "alice.dev"})
        cr = mapper.map(rec)
        assert cr.website is not None
        assert cr.website.startswith("https://")

    def test_company_mapped_at_stripped(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        # "@Eightfold" → "Eightfold"
        assert cr.current_company == "Eightfold"

    def test_twitter_in_other_links(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert "twitter" in cr.other_links
        assert "alicecodes" in cr.other_links["twitter"]


# ================================================================
# Statistics
# ================================================================


class TestStats:
    def test_github_stars_mapped(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert cr.github_stars == _TOTAL_STARS

    def test_github_repos_mapped(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert cr.github_repos == 18

    def test_primary_language_is_python(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert cr.primary_language == "Python"

    def test_followers_in_metadata(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert cr.mapping_metadata.get("followers") == 234

    def test_total_forks_in_metadata(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert cr.mapping_metadata.get("total_forks") == _TOTAL_FORKS

    def test_languages_breakdown_in_metadata(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        breakdown = cr.mapping_metadata.get("languages_breakdown", {})
        assert "Python" in breakdown


# ================================================================
# Skills
# ================================================================


class TestSkillsMapping:
    def test_topics_become_skills(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        for topic in _TOPICS:
            assert topic in cr.skills

    def test_languages_become_skills(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        assert "Python" in cr.skills
        assert "JavaScript" in cr.skills

    def test_topics_as_skills_false(self, mapper) -> None:
        m = GithubMapper(config={"topics_as_skills": False})
        rec = _make_record(
            profile=_PROFILE, topics=["ml"], languages={"Python": 5}
        )
        cr = m.map(rec)
        # Topics should NOT be in skills
        assert "ml" not in cr.skills
        # Languages should still be
        assert "Python" in cr.skills

    def test_languages_as_skills_false(self, mapper) -> None:
        m = GithubMapper(config={"languages_as_skills": False})
        rec = _make_record(
            profile=_PROFILE, topics=["ml"], languages={"Python": 5}
        )
        cr = m.map(rec)
        # Languages should NOT be in skills
        assert "Python" not in cr.skills
        # Topics should still be
        assert "ml" in cr.skills


# ================================================================
# Repos → Experience
# ================================================================


class TestRepoExperience:
    def test_non_forked_repos_become_experience(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        # 2 non-forked repos in fixture
        assert len(cr.experience) == 2

    def test_forked_repo_excluded_by_default(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        titles = [e.get("title") for e in cr.experience]
        assert "forked-repo" not in titles

    def test_include_forked_config(self, mapper) -> None:
        m = GithubMapper(config={"include_forked": True})
        rec = _make_record(profile=_PROFILE, repos=_REPOS, hint="alice")
        cr = m.map(rec)
        assert len(cr.experience) == 3

    def test_max_repos_config(self, mapper) -> None:
        m = GithubMapper(config={"max_repos": 1})
        rec = _make_record(profile=_PROFILE, repos=_REPOS, hint="alice")
        cr = m.map(rec)
        assert len(cr.experience) == 1

    def test_experience_entry_has_title(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        for entry in cr.experience:
            assert entry.get("title") is not None

    def test_experience_entry_has_url(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        for entry in cr.experience:
            assert entry.get("url") is not None

    def test_experience_entry_has_language(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        langs = [e.get("language") for e in cr.experience]
        assert "Python" in langs

    def test_archived_repo_is_not_current(self, mapper) -> None:
        archived_repos = [
            {"name": "old-proj", "html_url": "https://github.com/a/old-proj",
             "description": "Old project.", "language": "Python",
             "stargazers_count": 0, "forks_count": 0,
             "fork": False, "archived": True, "topics": []},
        ]
        rec = _make_record(profile=_PROFILE, repos=archived_repos, hint="alice")
        cr = mapper.map(rec)
        assert cr.experience[0]["is_current"] is False


# ================================================================
# Provenance
# ================================================================


class TestProvenance:
    def test_provenance_stage_is_mapping(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        for prov in cr.provenance:
            assert prov.processing_stage == ProcessingStage.MAPPING

    def test_provenance_source_type(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        for prov in cr.provenance:
            assert prov.source == SourceType.GITHUB

    def test_provenance_for_full_name(self, mapper, full_record) -> None:
        cr = mapper.map(full_record)
        prov_fields = [p.field for p in cr.provenance]
        assert "full_name" in prov_fields


# ================================================================
# Edge Cases
# ================================================================


class TestEdgeCases:
    def test_empty_profile_no_crash(self, mapper) -> None:
        rec = _make_record(profile={}, hint="alice")
        cr = mapper.map(rec)
        assert cr.github_username == "alice"  # from hint

    def test_no_repos_no_experience(self, mapper) -> None:
        rec = _make_record(profile=_PROFILE, repos=[], hint="alice")
        cr = mapper.map(rec)
        assert cr.experience == []

    def test_no_languages_no_primary_language(self, mapper) -> None:
        rec = _make_record(profile=_PROFILE, languages={}, hint="alice")
        cr = mapper.map(rec)
        assert cr.primary_language is None

    def test_null_profile_fields_skipped(self, mapper) -> None:
        rec = _make_record(
            profile={"login": "alice", "name": None, "bio": None},
            hint="alice",
        )
        cr = mapper.map(rec)
        assert cr.full_name is None
        assert cr.summary is None


# ================================================================
# supports()
# ================================================================


class TestSupports:
    def test_supports_github(self, mapper) -> None:
        rec = _make_record()
        assert mapper.supports(rec) is True

    def test_does_not_support_csv(self, mapper) -> None:
        rec = RawRecord(
            source="x.csv",
            source_type=SourceType.CSV,
            raw_fields={},
        )
        assert mapper.supports(rec) is False

    def test_metadata_returns_dict(self, mapper) -> None:
        m = mapper.metadata()
        assert isinstance(m, dict)
        assert m["source_type"] == "github"
