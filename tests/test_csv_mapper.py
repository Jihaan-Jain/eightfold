"""
tests/test_csv_mapper.py
=========================

Unit tests for src/mapping/csv_mapper.py.

Covers
------
- Basic field mapping (email, phone, name)
- Alias mapping (First Name, Mobile, Company)
- Full name ↔ first+last inference
- Skills parsing (comma-separated, pipe-separated, list)
- URL classification (GitHub, LinkedIn, website)
- Unknown fields become warnings in unknown_fields list
- Internal fields (id, stage, recruiter) become ignored_fields
- Multiple schemas / CSV layouts
- Empty cells produce no mapped fields
- Provenance entries created for every mapped field
- MappingMethod.DIRECT vs ALIAS vs INFERRED in provenance
"""

from __future__ import annotations

import pytest

from src.mapping.csv_mapper import CsvMapper
from src.models import (
    CanonicalRecord,
    MappingMethod,
    ProcessingStage,
    RawRecord,
    SourceType,
)


# ================================================================
# Helpers
# ================================================================


def _make_record(fields: dict) -> RawRecord:
    """Create a CSV RawRecord from a dict of raw fields."""
    return RawRecord(
        source="test_recruiter.csv",
        source_type=SourceType.CSV,
        raw_fields=fields,
    )


@pytest.fixture()
def mapper() -> CsvMapper:
    return CsvMapper()


# ================================================================
# Basic Field Mapping
# ================================================================


class TestBasicFieldMapping:
    def test_email_direct(self, mapper) -> None:
        rec = _make_record({"email": "alice@example.com"})
        cr = mapper.map(rec)
        assert "alice@example.com" in cr.emails
        assert "emails" in cr.mapped_fields

    def test_email_alias(self, mapper) -> None:
        rec = _make_record({"Email Address": "alice@example.com"})
        cr = mapper.map(rec)
        assert "alice@example.com" in cr.emails

    def test_phone_alias_mobile(self, mapper) -> None:
        rec = _make_record({"Mobile": "+91-9876543210"})
        cr = mapper.map(rec)
        assert "+91-9876543210" in cr.phones

    def test_phone_alias_cell(self, mapper) -> None:
        rec = _make_record({"Cell Phone": "555-1234"})
        cr = mapper.map(rec)
        assert "555-1234" in cr.phones

    def test_location_alias_city(self, mapper) -> None:
        rec = _make_record({"City": "Bangalore"})
        cr = mapper.map(rec)
        assert cr.location == "Bangalore"

    def test_summary_alias_bio(self, mapper) -> None:
        rec = _make_record({"bio": "10 years ML engineer"})
        cr = mapper.map(rec)
        assert cr.summary == "10 years ML engineer"

    def test_company_alias(self, mapper) -> None:
        rec = _make_record({"Current Company": "Eightfold AI"})
        cr = mapper.map(rec)
        assert cr.current_company == "Eightfold AI"

    def test_headline_alias_job_title(self, mapper) -> None:
        rec = _make_record({"Job Title": "Senior ML Engineer"})
        cr = mapper.map(rec)
        assert cr.headline == "Senior ML Engineer"


# ================================================================
# Name Handling
# ================================================================


class TestNameHandling:
    def test_full_name_direct(self, mapper) -> None:
        rec = _make_record({"name": "Alice Smith"})
        cr = mapper.map(rec)
        assert cr.full_name == "Alice Smith"

    def test_full_name_alias(self, mapper) -> None:
        rec = _make_record({"Candidate Name": "Bob Jones"})
        cr = mapper.map(rec)
        assert cr.full_name == "Bob Jones"

    def test_first_last_infers_full_name(self, mapper) -> None:
        rec = _make_record({"First Name": "Alice", "Last Name": "Smith"})
        cr = mapper.map(rec)
        assert cr.full_name == "Alice Smith"
        assert cr.first_name == "Alice"
        assert cr.last_name == "Smith"

    def test_full_name_infers_first_last(self, mapper) -> None:
        rec = _make_record({"name": "Charlie Brown"})
        cr = mapper.map(rec)
        assert cr.first_name == "Charlie"
        assert cr.last_name == "Brown"

    def test_comma_separated_name(self, mapper) -> None:
        """Last, First format."""
        rec = _make_record({"name": "Smith, Alice"})
        cr = mapper.map(rec)
        assert cr.first_name == "Alice"
        assert cr.last_name == "Smith"

    def test_single_name_no_last(self, mapper) -> None:
        rec = _make_record({"name": "Cher"})
        cr = mapper.map(rec)
        assert cr.first_name == "Cher"
        assert cr.last_name is None


# ================================================================
# Skills Parsing
# ================================================================


class TestSkillsParsing:
    def test_comma_separated_skills(self, mapper) -> None:
        rec = _make_record({"Skills": "Python, TensorFlow, Docker"})
        cr = mapper.map(rec)
        assert "Python" in cr.skills
        assert "TensorFlow" in cr.skills
        assert "Docker" in cr.skills

    def test_semicolon_separated_skills(self, mapper) -> None:
        rec = _make_record({"skills": "Java;Spring;MySQL"})
        cr = mapper.map(rec)
        assert "Java" in cr.skills
        assert "Spring" in cr.skills

    def test_pipe_separated_skills(self, mapper) -> None:
        rec = _make_record({"Technologies": "React|Redux|TypeScript"})
        cr = mapper.map(rec)
        assert "React" in cr.skills

    def test_skills_alias_tech_stack(self, mapper) -> None:
        rec = _make_record({"Tech Stack": "Go, Kubernetes"})
        cr = mapper.map(rec)
        assert "Go" in cr.skills

    def test_empty_skills_not_mapped(self, mapper) -> None:
        rec = _make_record({"skills": ""})
        cr = mapper.map(rec)
        assert cr.skills == []

    def test_skills_deduplication(self, mapper) -> None:
        rec = _make_record({"skills": "Python, python, PYTHON"})
        cr = mapper.map(rec)
        # Deduplicated by parse_skill_list (case-insensitive)
        assert len([s for s in cr.skills if s.lower() == "python"]) == 1


# ================================================================
# URL Classification
# ================================================================


class TestUrlClassification:
    def test_github_url_classified(self, mapper) -> None:
        rec = _make_record({"github": "https://github.com/alice"})
        cr = mapper.map(rec)
        assert cr.github_url == "https://github.com/alice"

    def test_github_url_extracts_username(self, mapper) -> None:
        rec = _make_record({"github": "https://github.com/alice"})
        cr = mapper.map(rec)
        assert cr.github_username == "alice"

    def test_linkedin_url_classified(self, mapper) -> None:
        rec = _make_record({"linkedin": "https://linkedin.com/in/alice-smith"})
        cr = mapper.map(rec)
        assert cr.linkedin_url == "https://linkedin.com/in/alice-smith"

    def test_website_classified(self, mapper) -> None:
        rec = _make_record({"website": "https://alice.dev"})
        cr = mapper.map(rec)
        assert cr.website == "https://alice.dev"

    def test_blog_classified_as_website(self, mapper) -> None:
        rec = _make_record({"blog": "https://myblog.com"})
        cr = mapper.map(rec)
        assert cr.website == "https://myblog.com"

    def test_github_url_in_website_field_reclassified(self, mapper) -> None:
        """A GitHub URL stored under 'website' is re-routed to github_url."""
        rec = _make_record({"website": "https://github.com/bob"})
        cr = mapper.map(rec)
        assert cr.github_url == "https://github.com/bob"
        assert cr.website is None


# ================================================================
# Unknown / Ignored Fields
# ================================================================


class TestUnknownIgnoredFields:
    def test_unknown_field_logged(self, mapper) -> None:
        rec = _make_record({"completely_novel_field_xyz": "value"})
        cr = mapper.map(rec)
        assert "completely_novel_field_xyz" in cr.unknown_fields

    def test_unknown_field_not_in_mapped(self, mapper) -> None:
        rec = _make_record({"foobar_xyz": "value"})
        cr = mapper.map(rec)
        assert "foobar_xyz" not in cr.mapped_fields

    def test_internal_id_ignored(self, mapper) -> None:
        rec = _make_record({"id": "12345", "email": "a@b.com"})
        cr = mapper.map(rec)
        assert "id" in cr.ignored_fields
        assert "12345" not in str(cr.emails)

    def test_stage_ignored(self, mapper) -> None:
        rec = _make_record({"stage": "Phone Screen", "name": "Alice"})
        cr = mapper.map(rec)
        assert "stage" in cr.ignored_fields

    def test_recruiter_ignored(self, mapper) -> None:
        rec = _make_record({"recruiter": "Bob", "email": "a@b.com"})
        cr = mapper.map(rec)
        assert "recruiter" in cr.ignored_fields

    def test_empty_cell_not_mapped(self, mapper) -> None:
        rec = _make_record({"name": "", "email": "a@b.com"})
        cr = mapper.map(rec)
        assert cr.full_name is None
        assert "alice@b.com" not in cr.emails  # only email mapped


# ================================================================
# Multiple Schema Layouts
# ================================================================


class TestMultipleSchemas:
    def test_greenhouse_like_csv(self, mapper) -> None:
        """CSV export from Greenhouse-style system."""
        rec = _make_record({
            "Candidate Name": "Priya Sharma",
            "Email Address":  "priya@example.com",
            "Phone":          "+91-9000000000",
            "Current Company":"Google",
            "Job Title":      "SWE",
            "Location":       "Bangalore, India",
            "Skills":         "Python, Go, Kubernetes",
            "LinkedIn":       "https://linkedin.com/in/priya",
            "GitHub":         "https://github.com/priya",
        })
        cr = mapper.map(rec)
        assert cr.full_name == "Priya Sharma"
        assert "priya@example.com" in cr.emails
        assert cr.current_company == "Google"
        assert cr.headline == "SWE"
        assert "Python" in cr.skills
        assert cr.linkedin_url is not None
        assert cr.github_url is not None

    def test_lever_like_csv(self, mapper) -> None:
        """CSV export from Lever-style system."""
        rec = _make_record({
            "Name":     "Alice Smith",
            "Email":    "alice@example.com",
            "Mobile":   "555-0001",
            "Company":  "Startup Inc",
            "Position": "Backend Engineer",
            "City":     "San Francisco",
        })
        cr = mapper.map(rec)
        assert cr.full_name == "Alice Smith"
        assert cr.current_company == "Startup Inc"
        assert "555-0001" in cr.phones

    def test_minimal_record_maps_without_error(self, mapper) -> None:
        rec = _make_record({"email": "x@y.com"})
        cr = mapper.map(rec)
        assert "x@y.com" in cr.emails


# ================================================================
# Provenance
# ================================================================


class TestProvenance:
    def test_provenance_created_for_mapped_field(self, mapper) -> None:
        rec = _make_record({"email": "alice@example.com"})
        cr = mapper.map(rec)
        prov_fields = [p.field for p in cr.provenance]
        assert "emails" in prov_fields

    def test_provenance_processing_stage_is_mapping(self, mapper) -> None:
        rec = _make_record({"name": "Alice"})
        cr = mapper.map(rec)
        for prov in cr.provenance:
            assert prov.processing_stage == ProcessingStage.MAPPING

    def test_alias_provenance_reason_contains_alias(self, mapper) -> None:
        rec = _make_record({"First Name": "Alice"})
        cr = mapper.map(rec)
        prov = next(p for p in cr.provenance if p.field == "first_name")
        assert "First Name" in prov.reason or "alias" in prov.reason.lower()

    def test_inferred_name_provenance(self, mapper) -> None:
        rec = _make_record({"First Name": "Alice", "Last Name": "Smith"})
        cr = mapper.map(rec)
        prov_map = {p.field: p for p in cr.provenance}
        assert "full_name" in prov_map
        assert "inferred" in prov_map["full_name"].reason.lower()

    def test_provenance_source_type(self, mapper) -> None:
        rec = _make_record({"email": "x@y.com"})
        cr = mapper.map(rec)
        for prov in cr.provenance:
            assert prov.source == SourceType.CSV

    def test_original_value_preserved_in_provenance(self, mapper) -> None:
        rec = _make_record({"Email Address": "Alice@Example.COM"})
        cr = mapper.map(rec)
        prov = next(p for p in cr.provenance if p.field == "emails")
        # Original value is the raw cell value, not normalised
        assert prov.original_value == "Alice@Example.COM"


# ================================================================
# supports()
# ================================================================


class TestSupports:
    def test_supports_csv(self, mapper) -> None:
        rec = _make_record({})
        assert mapper.supports(rec) is True

    def test_does_not_support_ats(self, mapper) -> None:
        rec = RawRecord(
            source="ats.json",
            source_type=SourceType.ATS,
            raw_fields={},
        )
        assert mapper.supports(rec) is False

    def test_metadata_returns_dict(self, mapper) -> None:
        m = mapper.metadata()
        assert isinstance(m, dict)
        assert m["source_type"] == "csv"
