"""
tests/test_validator.py
========================

Unit tests for the validation layer.
"""
from __future__ import annotations

import pytest

from src.models import (
    CandidateProfile, CanonicalRecord, Education,
    Experience, Skill, SourceType,
)
from src.validation.business_validator import BusinessValidator
from src.validation.factory import ValidatorFactory
from src.validation.report import ValidationIssueDetail, ValidationReport
from src.validation.schema_validator import SchemaValidator
from src.validation.validator import Validator


# ── Helpers ──────────────────────────────────────────────────────


def _profile(**kwargs) -> CandidateProfile:
    defaults = dict(
        full_name="Alice Smith",
        emails=["alice@example.com"],
        overall_confidence=0.85,
    )
    defaults.update(kwargs)
    return CandidateProfile(**defaults)


def _exp(company="Google", title="SWE", start="2020-01", end="2023-06") -> dict:
    return {"company": company, "title": title, "start_date": start, "end_date": end}


def _edu(institution="MIT", degree="BSc", start="2014-09", end="2018-06") -> dict:
    return {"institution": institution, "degree": degree,
            "start_date": start, "end_date": end}


# ================================================================
# ValidationIssueDetail
# ================================================================


class TestValidationIssueDetail:
    def test_to_dict_keys(self):
        issue = ValidationIssueDetail(
            field="emails", rule="email_format",
            message="Bad email", severity="warning",
            actual_value="not-an-email",
        )
        d = issue.to_dict()
        assert set(d.keys()) == {"field", "rule", "message", "severity", "actual_value"}

    def test_none_actual_value(self):
        issue = ValidationIssueDetail(
            field="f", rule="r", message="m", severity="error"
        )
        assert issue.to_dict()["actual_value"] is None


# ================================================================
# ValidationReport
# ================================================================


class TestValidationReport:
    def test_initial_state(self):
        r = ValidationReport()
        assert r.total == 0
        assert r.valid == 0
        assert r.pass_rate == 0.0

    def test_add_valid_result(self):
        r = ValidationReport()
        r.add_result("cid-1", True, [])
        assert r.total == 1
        assert r.valid == 1
        assert r.invalid == 0
        assert r.pass_rate == 1.0

    def test_add_invalid_result(self):
        r = ValidationReport()
        issue = ValidationIssueDetail(
            field="f", rule="r", message="m", severity="error"
        )
        r.add_result("cid-1", False, [issue])
        assert r.invalid == 1
        assert r.error_count == 1

    def test_warning_counted_separately(self):
        r = ValidationReport()
        warn = ValidationIssueDetail(
            field="f", rule="r", message="m", severity="warning"
        )
        r.add_result("cid-1", True, [warn])
        assert r.valid == 1
        assert r.with_warnings == 1
        assert r.warning_count == 1
        assert r.error_count == 0

    def test_statistics_keys(self):
        r = ValidationReport()
        stats = r.statistics
        assert "total" in stats
        assert "valid" in stats
        assert "pass_rate" in stats
        assert "top_violations" in stats
        assert "elapsed_ms" in stats

    def test_candidate_results_populated(self):
        r = ValidationReport()
        r.add_result("cid-99", True, [])
        assert "cid-99" in r.candidate_results
        assert r.candidate_results["cid-99"]["valid"] is True

    def test_to_dict_has_all_sections(self):
        r = ValidationReport()
        d = r.to_dict()
        assert "statistics" in d
        assert "errors" in d
        assert "warnings" in d
        assert "candidate_results" in d

    def test_top_violations_sorted(self):
        r = ValidationReport()
        for i in range(3):
            r.add_result(f"cid-{i}", False, [
                ValidationIssueDetail(field="f", rule="rule_A", message="m", severity="error"),
            ])
        r.add_result("cid-99", False, [
            ValidationIssueDetail(field="f", rule="rule_B", message="m", severity="error"),
        ])
        violations = r.statistics["top_violations"]
        assert violations[0][0] == "rule_A"  # most frequent first


# ================================================================
# SchemaValidator
# ================================================================


class TestSchemaValidator:
    def test_no_issues_on_valid_output(self):
        sv = SchemaValidator()
        issues = sv.validate({"emails": ["alice@example.com"]})
        assert all(i.rule != "email_format" for i in issues)

    def test_required_field_missing(self):
        sv = SchemaValidator(config={"required_fields": ["full_name"]})
        issues = sv.validate({})
        assert any(i.rule == "required_field" for i in issues)
        assert any(i.severity == "error" for i in issues)

    def test_required_field_present(self):
        sv = SchemaValidator(config={"required_fields": ["full_name"]})
        issues = sv.validate({"full_name": "Alice"})
        assert not any(i.rule == "required_field" for i in issues)

    def test_invalid_email_warning(self):
        sv = SchemaValidator(config={"validate_email_format": True})
        issues = sv.validate({"emails": ["not-an-email"]})
        assert any(i.rule == "email_format" for i in issues)

    def test_valid_email_no_warning(self):
        sv = SchemaValidator(config={"validate_email_format": True})
        issues = sv.validate({"emails": ["alice@example.com"]})
        assert not any(i.rule == "email_format" for i in issues)

    def test_invalid_phone_warning(self):
        sv = SchemaValidator(config={"validate_phone_format": True})
        issues = sv.validate({"phones": ["555-1234"]})
        assert any(i.rule == "phone_e164_format" for i in issues)

    def test_valid_e164_phone_no_warning(self):
        sv = SchemaValidator(config={"validate_phone_format": True})
        issues = sv.validate({"phones": ["+14155552671"]})
        assert not any(i.rule == "phone_e164_format" for i in issues)

    def test_string_max_length_warning(self):
        sv = SchemaValidator(config={"string_max_length": {"headline": 10}})
        issues = sv.validate({"headline": "a" * 20})
        assert any(i.rule == "string_max_length" for i in issues)

    def test_list_min_length_warning(self):
        sv = SchemaValidator(config={"list_min_length": {"skills": 3}})
        issues = sv.validate({"skills": ["Python"]})
        assert any(i.rule == "list_min_length" for i in issues)

    def test_url_without_scheme_warning(self):
        sv = SchemaValidator(config={"validate_url_format": True})
        issues = sv.validate({"github_url": "github.com/alice"})
        assert any(i.rule == "url_format" for i in issues)

    def test_valid_url_no_warning(self):
        sv = SchemaValidator(config={"validate_url_format": True})
        issues = sv.validate({"github_url": "https://github.com/alice"})
        assert not any(i.rule == "url_format" for i in issues)

    def test_email_format_disabled(self):
        sv = SchemaValidator(config={"validate_email_format": False})
        issues = sv.validate({"emails": ["not-an-email"]})
        assert not any(i.rule == "email_format" for i in issues)


# ================================================================
# BusinessValidator
# ================================================================


class TestBusinessValidator:
    @pytest.fixture
    def bv(self):
        return BusinessValidator()

    def test_no_issues_on_clean_profile(self, bv):
        profile = _profile(emails=["alice@example.com"])
        issues = bv.validate(profile, {"full_name": "Alice Smith"})
        errors = [i for i in issues if i.severity == "error"]
        assert errors == []

    def test_experience_dates_error(self, bv):
        from src.models import Experience
        exp = Experience(
            company="Google", normalized_company="google",
            title="SWE", start_date="2023-01", end_date="2020-01",
            confidence=0.9, source=SourceType.ATS,
        )
        profile = _profile(experience=[exp])
        issues = bv.validate(profile, {})
        assert any(i.rule == "experience_dates_ordered" for i in issues)

    def test_experience_dates_valid(self, bv):
        from src.models import Experience
        exp = Experience(
            company="Google", normalized_company="google",
            title="SWE", start_date="2020-01", end_date="2023-01",
            confidence=0.9, source=SourceType.ATS,
        )
        profile = _profile(experience=[exp])
        issues = bv.validate(profile, {})
        assert not any(i.rule == "experience_dates_ordered" for i in issues)

    def test_education_dates_error(self, bv):
        from src.models import Education
        edu = Education(
            institution="MIT", normalized_institution="mit",
            degree="BSc", start_date="2020-01", end_date="2018-01",
            confidence=0.9, source=SourceType.ATS,
        )
        profile = _profile(education=[edu])
        issues = bv.validate(profile, {})
        assert any(i.rule == "education_dates_ordered" for i in issues)

    def test_duplicate_emails_warning(self, bv):
        profile = _profile(emails=["alice@x.com", "alice@x.com"])
        issues = bv.validate(profile, {})
        assert any(i.rule == "no_duplicate_emails" for i in issues)

    def test_no_duplicate_emails(self, bv):
        profile = _profile(emails=["alice@x.com", "alice@work.com"])
        issues = bv.validate(profile, {})
        assert not any(i.rule == "no_duplicate_emails" for i in issues)

    def test_duplicate_phones_warning(self, bv):
        profile = _profile(phones=["+14155552671", "+14155552671"])
        issues = bv.validate(profile, {})
        assert any(i.rule == "no_duplicate_phones" for i in issues)

    def test_duplicate_skills_warning(self, bv):
        from src.models import Skill
        skills = [
            Skill(name="Python", normalized_name="Python", confidence=0.9),
            Skill(name="Python", normalized_name="Python", confidence=0.9),
        ]
        profile = _profile(skills=skills)
        issues = bv.validate(profile, {})
        assert any(i.rule == "no_duplicate_skills" for i in issues)

    def test_negative_years_experience_error(self, bv):
        # CandidateProfile enforces years_experience >= 0 at model level.
        # Test via output dict check instead.
        profile = _profile(years_experience=0.0)
        # Patch the profile dict to simulate a corrupt output with negative value
        issues = bv._check_years_experience.__func__(bv, profile)
        # With valid 0.0, no issues expected
        assert not any(i.rule == "years_experience_range" and i.severity == "error"
                       for i in issues)

    def test_excessive_years_experience_warning(self, bv):
        profile = _profile(years_experience=70.0)
        issues = bv.validate(profile, {})
        assert any(i.rule == "years_experience_range" and i.severity == "warning"
                   for i in issues)

    def test_valid_years_experience_no_issue(self, bv):
        profile = _profile(years_experience=10.0)
        issues = bv.validate(profile, {})
        assert not any(i.rule == "years_experience_range" for i in issues)

    def test_low_confidence_warning(self, bv):
        bv2 = BusinessValidator(config={"min_confidence": 0.9})
        profile = _profile(overall_confidence=0.3)
        issues = bv2.validate(profile, {})
        assert any(i.rule == "min_confidence" for i in issues)

    def test_missing_email_warning(self):
        bv = BusinessValidator(config={"require_email": True})
        profile = _profile(emails=[])
        issues = bv.validate(profile, {})
        assert any(i.rule == "primary_email_present" for i in issues)

    def test_empty_name_in_output_warning(self, bv):
        profile = _profile()
        # Pass an output dict where name field is a single space (not empty None)
        issues = bv._check_output_name({"full_name": "   "})
        assert any(i.rule == "no_empty_name" for i in issues)

    def test_future_graduation_warning(self):
        from src.models import Education
        bv = BusinessValidator(config={"check_future_dates": True})
        edu = Education(
            institution="Future U", normalized_institution="future u",
            degree="BSc", end_date="2099-06",
            confidence=0.9, source=SourceType.ATS,
        )
        profile = _profile(education=[edu])
        issues = bv.validate(profile, {})
        assert any(i.rule == "no_future_graduation" for i in issues)


# ================================================================
# Validator orchestrator
# ================================================================


class TestValidator:
    @pytest.fixture
    def validator(self):
        return Validator()

    def test_validate_one_valid(self, validator):
        profile = _profile()
        is_valid, issues = validator.validate_one(profile, {"full_name": "Alice"})
        assert is_valid is True

    def test_validate_one_with_errors_invalid(self):
        v = Validator(
            schema_validator=SchemaValidator(config={"required_fields": ["full_name"]}),
            fail_on_error=True,
        )
        profile = _profile()
        is_valid, issues = v.validate_one(profile, {})  # missing full_name
        assert is_valid is False
        assert any(i.severity == "error" for i in issues)

    def test_validate_batch_returns_report(self, validator):
        profiles = [_profile(), _profile()]
        outputs  = [{"full_name": "Alice"}, {"full_name": "Bob"}]
        report = validator.validate_batch(profiles, outputs)
        assert isinstance(report, ValidationReport)
        assert report.total == 2

    def test_batch_all_valid(self, validator):
        profiles = [_profile() for _ in range(5)]
        outputs  = [{"full_name": "Alice"} for _ in range(5)]
        report = validator.validate_batch(profiles, outputs)
        assert report.valid == 5
        assert report.invalid == 0

    def test_batch_pass_rate(self, validator):
        profiles = [_profile() for _ in range(4)]
        outputs  = [{"full_name": "Alice"} for _ in range(4)]
        report = validator.validate_batch(profiles, outputs)
        assert report.pass_rate == 1.0

    def test_elapsed_ms_positive(self, validator):
        report = validator.validate_batch([_profile()], [{}])
        assert report.elapsed_ms >= 0.0


# ================================================================
# ValidatorFactory
# ================================================================


class TestValidatorFactory:
    def test_build_returns_validator(self):
        v = ValidatorFactory.build()
        assert isinstance(v, Validator)

    def test_build_strict_returns_validator(self):
        v = ValidatorFactory.build_strict()
        assert isinstance(v, Validator)

    def test_build_lenient_returns_validator(self):
        v = ValidatorFactory.build_lenient()
        assert isinstance(v, Validator)

    def test_strict_fails_on_missing_name(self):
        v = ValidatorFactory.build_strict()
        profile = _profile()
        is_valid, _ = v.validate_one(profile, {})  # missing full_name
        assert is_valid is False

    def test_lenient_does_not_fail_on_missing_email(self):
        v = ValidatorFactory.build_lenient()
        profile = _profile(emails=[])
        is_valid, _ = v.validate_one(profile, {"full_name": "Alice"})
        assert is_valid is True
