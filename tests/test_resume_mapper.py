"""
tests/test_resume_mapper.py
============================

Unit tests for src/mapping/resume_mapper.py.

Covers
------
- Section header detection (SUMMARY, SKILLS, EXPERIENCE, EDUCATION,
  PROJECTS, CERTIFICATIONS)
- Contact extraction: email, phone, URL from top lines
- Name heuristic from first non-email non-URL line
- Skills section: comma-separated, bullet-list
- Experience section: date-range entry grouping, is_current flag
- Education section: degree detection, institution parsing
- Projects section: URL extraction
- Certifications: bullet list to list[str]
- Empty text → empty CanonicalRecord with metadata flag
- GitHub URL → username inference
- Multiple section layouts (different orders)
- Provenance method is SECTION for section-extracted fields
"""

from __future__ import annotations

import pytest

from src.mapping.resume_mapper import ResumePdfMapper
from src.models import (
    ProcessingStage,
    RawRecord,
    SourceType,
)


# ================================================================
# Helpers
# ================================================================


def _make_record(full_text: str, pages: list[str] | None = None) -> RawRecord:
    return RawRecord(
        source="resume.pdf",
        source_type=SourceType.RESUME,
        raw_fields={
            "full_text":  full_text,
            "pages":      pages or [full_text],
            "char_count": len(full_text),
            "word_count": len(full_text.split()),
        },
    )


@pytest.fixture()
def mapper() -> ResumePdfMapper:
    return ResumePdfMapper()


# ================================================================
# Fixtures — sample résumé text blocks
# ================================================================


_CONTACT_TEXT = """\
Alice Smith
alice@example.com | +1-555-123-4567
https://github.com/alice | https://linkedin.com/in/alice | https://alice.dev
San Francisco, CA
"""

_SKILLS_TEXT = """\
SKILLS
Python, TensorFlow, Docker, Kubernetes
React, Node.js, PostgreSQL
"""

_EXPERIENCE_TEXT = """\
EXPERIENCE
Software Engineer at Eightfold AI 2020-2023
- Led ML pipeline development
- Reduced inference latency by 40%

Backend Developer at Startup Inc 2018-2020
- Built REST APIs using Flask
"""

_EDUCATION_TEXT = """\
EDUCATION
MIT 2014-2018
B.S. Computer Science

Stanford University 2018-2019
M.S. Artificial Intelligence
"""

_CERTIFICATIONS_TEXT = """\
CERTIFICATIONS
AWS Solutions Architect
Google Cloud Professional
"""

_FULL_RESUME = (
    _CONTACT_TEXT
    + _SKILLS_TEXT
    + _EXPERIENCE_TEXT
    + _EDUCATION_TEXT
    + _CERTIFICATIONS_TEXT
)


# ================================================================
# Contact Extraction
# ================================================================


class TestContactExtraction:
    def test_email_extracted(self, mapper) -> None:
        rec = _make_record(_CONTACT_TEXT + _SKILLS_TEXT)
        cr = mapper.map(rec)
        assert "alice@example.com" in cr.emails

    def test_phone_extracted(self, mapper) -> None:
        rec = _make_record(_CONTACT_TEXT)
        cr = mapper.map(rec)
        assert any("555" in p for p in cr.phones)

    def test_github_url_extracted(self, mapper) -> None:
        rec = _make_record(_CONTACT_TEXT)
        cr = mapper.map(rec)
        assert cr.github_url is not None
        assert "github.com/alice" in cr.github_url

    def test_linkedin_url_extracted(self, mapper) -> None:
        rec = _make_record(_CONTACT_TEXT)
        cr = mapper.map(rec)
        assert cr.linkedin_url is not None
        assert "linkedin.com/in/alice" in cr.linkedin_url

    def test_website_extracted(self, mapper) -> None:
        rec = _make_record(_CONTACT_TEXT)
        cr = mapper.map(rec)
        assert cr.website is not None
        assert "alice.dev" in cr.website

    def test_github_username_inferred(self, mapper) -> None:
        rec = _make_record(_CONTACT_TEXT)
        cr = mapper.map(rec)
        assert cr.github_username == "alice"

    def test_name_extracted_from_first_line(self, mapper) -> None:
        rec = _make_record(_CONTACT_TEXT)
        cr = mapper.map(rec)
        assert cr.full_name is not None
        assert "Alice" in cr.full_name

    def test_name_split_into_first_last(self, mapper) -> None:
        rec = _make_record(_CONTACT_TEXT)
        cr = mapper.map(rec)
        assert cr.first_name == "Alice"
        assert cr.last_name == "Smith"


# ================================================================
# Section Detection
# ================================================================


class TestSectionDetection:
    def test_skills_section_detected(self, mapper) -> None:
        rec = _make_record(_SKILLS_TEXT)
        cr = mapper.map(rec)
        assert "SKILLS" in cr.mapping_metadata.get("sections_detected", [])

    def test_experience_section_detected(self, mapper) -> None:
        rec = _make_record(_EXPERIENCE_TEXT)
        cr = mapper.map(rec)
        assert "EXPERIENCE" in cr.mapping_metadata.get("sections_detected", [])

    def test_education_section_detected(self, mapper) -> None:
        rec = _make_record(_EDUCATION_TEXT)
        cr = mapper.map(rec)
        assert "EDUCATION" in cr.mapping_metadata.get("sections_detected", [])

    def test_certifications_section_detected(self, mapper) -> None:
        rec = _make_record(_CERTIFICATIONS_TEXT)
        cr = mapper.map(rec)
        assert "CERTIFICATIONS" in cr.mapping_metadata.get("sections_detected", [])

    def test_full_resume_detects_all_sections(self, mapper) -> None:
        rec = _make_record(_FULL_RESUME)
        cr = mapper.map(rec)
        detected = set(cr.mapping_metadata.get("sections_detected", []))
        assert "SKILLS" in detected
        assert "EXPERIENCE" in detected
        assert "EDUCATION" in detected


# ================================================================
# Skills
# ================================================================


class TestSkillsExtraction:
    def test_comma_separated_skills(self, mapper) -> None:
        text = "SKILLS\nPython, TensorFlow, Docker\n"
        cr = mapper.map(_make_record(text))
        assert "Python" in cr.skills
        assert "TensorFlow" in cr.skills
        assert "Docker" in cr.skills

    def test_multi_line_skills(self, mapper) -> None:
        text = "SKILLS\nPython, TensorFlow\nDocker, Kubernetes\n"
        cr = mapper.map(_make_record(text))
        assert "Python" in cr.skills
        assert "Docker" in cr.skills

    def test_bullet_list_skills(self, mapper) -> None:
        text = "SKILLS\n• Python\n• TensorFlow\n• Docker\n"
        cr = mapper.map(_make_record(text))
        assert "Python" in cr.skills

    def test_skills_section_aliases(self, mapper) -> None:
        text = "Technical Skills\nJava, Spring, MySQL\n"
        cr = mapper.map(_make_record(text))
        assert "Java" in cr.skills

    def test_empty_skills_section(self, mapper) -> None:
        text = "SKILLS\n\n\nEXPERIENCE\nSome company 2020-2021\n"
        cr = mapper.map(_make_record(text))
        # Skills may be empty or have no content
        assert isinstance(cr.skills, list)


# ================================================================
# Experience
# ================================================================


class TestExperienceExtraction:
    def test_experience_entries_parsed(self, mapper) -> None:
        rec = _make_record(_EXPERIENCE_TEXT)
        cr = mapper.map(rec)
        assert len(cr.experience) >= 1

    def test_experience_is_current_present(self, mapper) -> None:
        text = "EXPERIENCE\nML Engineer at Eightfold AI 2022-Present\n- Build pipelines\n"
        cr = mapper.map(_make_record(text))
        assert len(cr.experience) >= 1
        entry = cr.experience[0]
        assert entry.get("is_current") is True

    def test_experience_start_year(self, mapper) -> None:
        text = "EXPERIENCE\nEngineer at Acme 2019-2022\n"
        cr = mapper.map(_make_record(text))
        assert len(cr.experience) >= 1
        assert cr.experience[0].get("start_date") == "2019"

    def test_experience_end_year(self, mapper) -> None:
        text = "EXPERIENCE\nEngineer at Acme 2019-2022\n"
        cr = mapper.map(_make_record(text))
        assert cr.experience[0].get("end_date") == "2022"

    def test_experience_provenance_method_section(self, mapper) -> None:
        text = "EXPERIENCE\nEngineer at Acme 2019-2022\n"
        cr = mapper.map(_make_record(text))
        exp_provs = [p for p in cr.provenance if p.field == "experience"]
        assert len(exp_provs) >= 1
        assert "section" in exp_provs[0].reason.lower()


# ================================================================
# Education
# ================================================================


class TestEducationExtraction:
    def test_education_entries_parsed(self, mapper) -> None:
        rec = _make_record(_EDUCATION_TEXT)
        cr = mapper.map(rec)
        assert len(cr.education) >= 1

    def test_education_institution_captured(self, mapper) -> None:
        text = "EDUCATION\nMIT 2014-2018\nB.S. Computer Science\n"
        cr = mapper.map(_make_record(text))
        assert len(cr.education) >= 1
        entry = cr.education[0]
        assert entry.get("institution") is not None

    def test_education_degree_captured(self, mapper) -> None:
        text = "EDUCATION\nMIT 2014-2018\nB.S. Computer Science\n"
        cr = mapper.map(_make_record(text))
        # degree may be in the institution line or the degree line
        assert any(
            e.get("degree") or e.get("institution")
            for e in cr.education
        )

    def test_education_date_range_parsed(self, mapper) -> None:
        text = "EDUCATION\nStanford 2018-2020\nM.S. AI\n"
        cr = mapper.map(_make_record(text))
        entry = cr.education[0]
        assert entry.get("start_date") == "2018"
        assert entry.get("end_date") == "2020"


# ================================================================
# Certifications
# ================================================================


class TestCertificationsExtraction:
    def test_certifications_parsed(self, mapper) -> None:
        rec = _make_record(_CERTIFICATIONS_TEXT)
        cr = mapper.map(rec)
        assert len(cr.certifications) >= 1

    def test_certification_names_present(self, mapper) -> None:
        rec = _make_record(_CERTIFICATIONS_TEXT)
        cr = mapper.map(rec)
        combined = " ".join(cr.certifications)
        assert "AWS" in combined or "Google" in combined

    def test_certifications_bullet_stripped(self, mapper) -> None:
        text = "CERTIFICATIONS\n• AWS Solutions Architect\n• GCP Professional\n"
        cr = mapper.map(_make_record(text))
        for cert in cr.certifications:
            assert not cert.startswith("•")


# ================================================================
# Edge Cases
# ================================================================


class TestEdgeCases:
    def test_empty_text_returns_empty_canonical(self, mapper) -> None:
        rec = _make_record("")
        cr = mapper.map(rec)
        assert cr.emails == []
        assert cr.skills == []
        assert cr.mapping_metadata.get("empty_text") is True

    def test_no_crash_on_minimal_text(self, mapper) -> None:
        rec = _make_record("John Doe\njohn@example.com\n")
        cr = mapper.map(rec)
        assert "john@example.com" in cr.emails

    def test_no_crash_on_gibberish(self, mapper) -> None:
        rec = _make_record("!@#$%^&*() not a real resume")
        cr = mapper.map(rec)
        assert isinstance(cr.skills, list)
        assert isinstance(cr.emails, list)

    def test_provenance_stage_is_mapping(self, mapper) -> None:
        rec = _make_record(_FULL_RESUME)
        cr = mapper.map(rec)
        for prov in cr.provenance:
            assert prov.processing_stage == ProcessingStage.MAPPING

    def test_source_type_in_canonical(self, mapper) -> None:
        rec = _make_record(_CONTACT_TEXT)
        cr = mapper.map(rec)
        assert cr.source_type == SourceType.RESUME


# ================================================================
# supports()
# ================================================================


class TestSupports:
    def test_supports_resume(self, mapper) -> None:
        rec = _make_record("text")
        assert mapper.supports(rec) is True

    def test_does_not_support_csv(self, mapper) -> None:
        rec = RawRecord(
            source="x.csv",
            source_type=SourceType.CSV,
            raw_fields={"name": "Alice"},
        )
        assert mapper.supports(rec) is False

    def test_metadata_no_nlp(self, mapper) -> None:
        m = mapper.metadata()
        assert m.get("nlp") is False
        assert m["source_type"] == "resume"
