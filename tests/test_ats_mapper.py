"""
tests/test_ats_mapper.py
=========================

Unit tests for src/mapping/ats_mapper.py.

Covers
------
- Schema detection (greenhouse / lever / workday / generic)
- Greenhouse: nested candidate object, email_addresses, phone_numbers,
  website_addresses, tags-as-skills
- Lever: flat emails[], phones[], links[], headline, location.name
- Workday: Worker.Personal_Data.Name_Data / Contact_Data hierarchy
- Generic: flat dict registry resolution, nested dict expansion
- Unknown fields logged as warnings
- Provenance entries created with NESTED method
- Name inference (first+last → full, full → first+last)
- Multiple schemas produce correct CanonicalRecord structure
"""

from __future__ import annotations

import pytest

from src.mapping.ats_mapper import ATSMapper, _detect_schema
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


def _make_record(fields: dict, hint: str | None = None) -> RawRecord:
    return RawRecord(
        source="ats_export.json",
        source_type=SourceType.ATS,
        raw_fields=fields,
        candidate_hint=hint,
    )


@pytest.fixture()
def mapper() -> ATSMapper:
    return ATSMapper()


# ================================================================
# Schema Detection
# ================================================================


class TestSchemaDetection:
    def test_greenhouse_detected(self) -> None:
        rf = {"candidate": {}, "applications": [], "attachments": []}
        assert _detect_schema(rf) == "greenhouse"

    def test_lever_detected(self) -> None:
        rf = {"applications": [], "stage": {}}
        assert _detect_schema(rf) == "lever"

    def test_workday_by_worker_key(self) -> None:
        rf = {"Worker": {}}
        assert _detect_schema(rf) == "workday"

    def test_workday_by_workdayid(self) -> None:
        rf = {"WorkdayID": "WD-001"}
        assert _detect_schema(rf) == "workday"

    def test_generic_fallback(self) -> None:
        rf = {"name": "Alice", "email": "a@b.com"}
        assert _detect_schema(rf) == "generic"

    def test_forced_schema_overrides(self, mapper) -> None:
        m = ATSMapper(config={"schema": "generic"})
        rf = {"candidate": {}, "applications": []}
        rec = _make_record(rf)
        cr = m.map(rec)
        assert cr.mapping_metadata["ats_schema"] == "generic"


# ================================================================
# Greenhouse Schema
# ================================================================


class TestGreenhouseMapper:
    def _greenhouse_record(self, candidate: dict, extra: dict | None = None) -> RawRecord:
        rf = {"candidate": candidate, "applications": [], "attachments": []}
        if extra:
            rf.update(extra)
        return _make_record(rf)

    def test_first_last_name_mapped(self, mapper) -> None:
        rec = self._greenhouse_record({"first_name": "Alice", "last_name": "Smith"})
        cr = mapper.map(rec)
        assert cr.first_name == "Alice"
        assert cr.last_name == "Smith"
        assert cr.full_name == "Alice Smith"  # inferred

    def test_email_addresses_list(self, mapper) -> None:
        rec = self._greenhouse_record({
            "first_name": "Alice",
            "email_addresses": [
                {"value": "alice@work.com", "type": "work"},
                {"value": "alice@home.com", "type": "personal"},
            ],
        })
        cr = mapper.map(rec)
        assert "alice@work.com" in cr.emails
        assert "alice@home.com" in cr.emails

    def test_phone_numbers_list(self, mapper) -> None:
        rec = self._greenhouse_record({
            "first_name": "Alice",
            "phone_numbers": [{"value": "+1-555-0001", "type": "mobile"}],
        })
        cr = mapper.map(rec)
        assert "+1-555-0001" in cr.phones

    def test_location_from_addresses(self, mapper) -> None:
        rec = self._greenhouse_record({
            "addresses": [{"value": "Bangalore, India", "type": "home"}],
        })
        cr = mapper.map(rec)
        assert cr.location == "Bangalore, India"

    def test_title_mapped_to_headline(self, mapper) -> None:
        rec = self._greenhouse_record({"title": "Senior Engineer"})
        cr = mapper.map(rec)
        assert cr.headline == "Senior Engineer"

    def test_company_mapped(self, mapper) -> None:
        rec = self._greenhouse_record({"company": "Acme Corp"})
        cr = mapper.map(rec)
        assert cr.current_company == "Acme Corp"

    def test_github_url_in_website_addresses(self, mapper) -> None:
        rec = self._greenhouse_record({
            "website_addresses": [
                {"value": "https://github.com/alice", "type": "other"},
            ],
        })
        cr = mapper.map(rec)
        assert cr.github_url == "https://github.com/alice"

    def test_linkedin_url_in_website_addresses(self, mapper) -> None:
        rec = self._greenhouse_record({
            "website_addresses": [
                {"value": "https://linkedin.com/in/alice", "type": "linkedin"},
            ],
        })
        cr = mapper.map(rec)
        assert cr.linkedin_url == "https://linkedin.com/in/alice"

    def test_tags_become_skills(self, mapper) -> None:
        rec = self._greenhouse_record({}, extra={"tags": ["Python", "Machine Learning"]})
        cr = mapper.map(rec)
        assert "Python" in cr.skills

    def test_provenance_processing_stage(self, mapper) -> None:
        rec = self._greenhouse_record({"first_name": "Alice", "last_name": "Smith"})
        cr = mapper.map(rec)
        for prov in cr.provenance:
            assert prov.processing_stage == ProcessingStage.MAPPING

    def test_provenance_method_nested(self, mapper) -> None:
        rec = self._greenhouse_record({"first_name": "Alice"})
        cr = mapper.map(rec)
        prov = next(p for p in cr.provenance if p.field == "first_name")
        assert "candidate.first_name" in prov.reason

    def test_schema_recorded_in_metadata(self, mapper) -> None:
        rec = self._greenhouse_record({})
        cr = mapper.map(rec)
        assert cr.mapping_metadata["ats_schema"] == "greenhouse"


# ================================================================
# Lever Schema
# ================================================================


class TestLeverMapper:
    def _lever_record(self, fields: dict) -> RawRecord:
        base = {"applications": [], "stage": {}}
        base.update(fields)
        return _make_record(base)

    def test_name_mapped(self, mapper) -> None:
        rec = self._lever_record({"name": "Bob Jones"})
        cr = mapper.map(rec)
        assert cr.full_name == "Bob Jones"
        assert cr.first_name == "Bob"
        assert cr.last_name == "Jones"

    def test_emails_list(self, mapper) -> None:
        rec = self._lever_record({"name": "Bob", "emails": ["bob@work.com"]})
        cr = mapper.map(rec)
        assert "bob@work.com" in cr.emails

    def test_phones_list_of_dicts(self, mapper) -> None:
        rec = self._lever_record({
            "name": "Bob",
            "phones": [{"value": "555-0002", "type": "mobile"}],
        })
        cr = mapper.map(rec)
        assert "555-0002" in cr.phones

    def test_phones_list_of_strings(self, mapper) -> None:
        rec = self._lever_record({
            "name": "Bob",
            "phones": ["555-0003"],
        })
        cr = mapper.map(rec)
        assert "555-0003" in cr.phones

    def test_headline_mapped(self, mapper) -> None:
        rec = self._lever_record({"headline": "Lead Engineer"})
        cr = mapper.map(rec)
        assert cr.headline == "Lead Engineer"

    def test_location_from_dict(self, mapper) -> None:
        rec = self._lever_record({"location": {"name": "New York, NY"}})
        cr = mapper.map(rec)
        assert cr.location == "New York, NY"

    def test_summary_mapped(self, mapper) -> None:
        rec = self._lever_record({"summary": "Experienced engineer."})
        cr = mapper.map(rec)
        assert cr.summary == "Experienced engineer."

    def test_links_github_classified(self, mapper) -> None:
        rec = self._lever_record({
            "links": [{"url": "https://github.com/bob"}],
        })
        cr = mapper.map(rec)
        assert cr.github_url == "https://github.com/bob"

    def test_links_list_of_strings(self, mapper) -> None:
        rec = self._lever_record({
            "links": ["https://linkedin.com/in/bob"],
        })
        cr = mapper.map(rec)
        assert cr.linkedin_url == "https://linkedin.com/in/bob"

    def test_tags_as_skills(self, mapper) -> None:
        rec = self._lever_record({"tags": ["Go", "Kubernetes"]})
        cr = mapper.map(rec)
        assert "Go" in cr.skills

    def test_schema_recorded(self, mapper) -> None:
        rec = self._lever_record({})
        cr = mapper.map(rec)
        assert cr.mapping_metadata["ats_schema"] == "lever"


# ================================================================
# Workday Schema
# ================================================================


class TestWorkdayMapper:
    def _workday_record(self, personal_data: dict) -> RawRecord:
        return _make_record({
            "Worker": {
                "Personal_Data": personal_data,
            }
        })

    def test_first_last_name(self, mapper) -> None:
        rec = self._workday_record({
            "Name_Data": {"First_Name": "Carol", "Last_Name": "White"},
        })
        cr = mapper.map(rec)
        assert cr.first_name == "Carol"
        assert cr.last_name == "White"

    def test_email_from_contact_data(self, mapper) -> None:
        rec = self._workday_record({
            "Contact_Data": {"Email_Address": "carol@corp.com"},
        })
        cr = mapper.map(rec)
        assert "carol@corp.com" in cr.emails

    def test_phone_from_contact_data(self, mapper) -> None:
        rec = self._workday_record({
            "Contact_Data": {"Phone_Number": "+1-800-555-0000"},
        })
        cr = mapper.map(rec)
        assert "+1-800-555-0000" in cr.phones

    def test_location_from_address_data(self, mapper) -> None:
        rec = self._workday_record({
            "Contact_Data": {
                "Address_Data": {"City": "Austin", "Country": "USA"},
            },
        })
        cr = mapper.map(rec)
        assert cr.location in ("Austin, USA", "Austin")

    def test_schema_recorded(self, mapper) -> None:
        rec = self._workday_record({})
        cr = mapper.map(rec)
        assert cr.mapping_metadata["ats_schema"] == "workday"


# ================================================================
# Generic Schema
# ================================================================


class TestGenericMapper:
    def test_flat_email_resolved(self, mapper) -> None:
        rec = _make_record({"email": "gen@example.com"})
        cr = mapper.map(rec)
        assert "gen@example.com" in cr.emails

    def test_flat_name_resolved(self, mapper) -> None:
        rec = _make_record({"full_name": "Dana West"})
        cr = mapper.map(rec)
        assert cr.full_name == "Dana West"

    def test_nested_dict_expanded(self, mapper) -> None:
        """Unknown top-level key whose value is a dict triggers recursion."""
        rec = _make_record({
            "contact": {"email": "nested@example.com"},
        })
        cr = mapper.map(rec)
        # "contact.email" resolved to emails via registry
        assert "nested@example.com" in cr.emails

    def test_unknown_field_logged(self, mapper) -> None:
        rec = _make_record({"completely_novel_ats_key": "val"})
        cr = mapper.map(rec)
        assert "completely_novel_ats_key" in cr.unknown_fields

    def test_skills_parsed(self, mapper) -> None:
        rec = _make_record({"skills": "Python, Java, Scala"})
        cr = mapper.map(rec)
        assert "Python" in cr.skills

    def test_url_classified(self, mapper) -> None:
        rec = _make_record({"github": "https://github.com/dana"})
        cr = mapper.map(rec)
        assert cr.github_url == "https://github.com/dana"


# ================================================================
# supports()
# ================================================================


class TestSupports:
    def test_supports_ats(self, mapper) -> None:
        rec = _make_record({})
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
        assert m["source_type"] == "ats"
        assert "schemas" in m
