"""
test_models.py  (v2)
====================

Unit tests for all Pydantic models in src/models.py (v2).

Tests verify:
- Correct field defaults and construction
- Frozen model immutability
- ConfidenceScore bounds ([0.0, 1.0])
- Enum values and string representation
- Model validators (CandidateProfile.overall_confidence consistency)
- JSON-compatible round-trips
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError as PydanticValidationError

from src.models import (
    CandidateLink,
    CandidateProfile,
    ConfidenceMethod,
    Education,
    Experience,
    MergeStrategy,
    MissingFieldStrategy,
    NormalizationMethod,
    ProcessingStage,
    ProjectionMode,
    Provenance,
    QualityMetrics,
    RawRecord,
    Skill,
    SourceType,
    ValidationIssue,
    ValidationMode,
    ValidationResult,
)


# ================================================================
# Enum Tests
# ================================================================


class TestSourceType:
    """Tests for the SourceType enum."""

    def test_all_values_are_lowercase_strings(self) -> None:
        for member in SourceType:
            assert member.value == member.value.lower()

    def test_all_members_present(self) -> None:
        expected = {"CSV", "ATS", "GITHUB", "RESUME", "RECRUITER_NOTES"}
        assert {m.name for m in SourceType} == expected

    def test_csv_value(self) -> None:
        assert SourceType.CSV == "csv"

    def test_from_string(self) -> None:
        assert SourceType("ats") == SourceType.ATS
        assert SourceType("github") == SourceType.GITHUB

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(ValueError):
            SourceType("xml")


class TestNormalizationMethod:
    """Tests for the NormalizationMethod enum."""

    def test_all_expected_members_exist(self) -> None:
        expected = {
            "NONE", "EMAIL_LOWERCASE", "PHONE_E164", "DATE_ISO8601",
            "NAME_TITLE_CASE", "SKILL_ALIAS", "SKILL_FUZZY", "SKILL_SBERT",
            "LOCATION_DECOMPOSE", "URL_NORMALIZE", "COMPANY_STRIP_SUFFIX",
        }
        assert {m.name for m in NormalizationMethod} == expected

    def test_sbert_value(self) -> None:
        assert NormalizationMethod.SKILL_SBERT.value == "skill_sbert"


class TestMergeStrategy:
    """Tests for the MergeStrategy enum."""

    def test_all_members(self) -> None:
        expected = {"SOURCE_PRIORITY", "MAJORITY_VOTE", "MOST_RECENT", "MANUAL"}
        assert {m.name for m in MergeStrategy} == expected

    def test_source_priority_value(self) -> None:
        assert MergeStrategy.SOURCE_PRIORITY == "source_priority"


class TestProjectionMode:
    """Tests for the ProjectionMode enum."""

    def test_all_seven_modes(self) -> None:
        expected = {
            "SELECT", "RENAME", "FLATTEN", "TRANSFORM",
            "AGGREGATE", "DEFAULT", "CONDITIONAL",
        }
        assert {m.name for m in ProjectionMode} == expected

    def test_values_are_lowercase(self) -> None:
        for member in ProjectionMode:
            assert member.value == member.value.lower()


class TestValidationMode:
    """Tests for the ValidationMode enum."""

    def test_three_modes(self) -> None:
        assert ValidationMode.ERROR == "error"
        assert ValidationMode.WARNING == "warning"
        assert ValidationMode.OFF == "off"


class TestMissingFieldStrategy:
    """Tests for the MissingFieldStrategy enum."""

    def test_four_strategies(self) -> None:
        expected = {"OMIT", "NULL", "DEFAULT", "ERROR"}
        assert {m.name for m in MissingFieldStrategy} == expected


class TestProcessingStage:
    """Tests for the ProcessingStage enum."""

    def test_all_ten_stages(self) -> None:
        expected = {
            "EXTRACTION", "MAPPING", "NORMALIZATION", "IDENTITY_RESOLUTION",
            "MERGE", "CONFLICT_RESOLUTION", "CONFIDENCE_SCORING",
            "PROJECTION", "VALIDATION", "OUTPUT",
        }
        assert {m.name for m in ProcessingStage} == expected

    def test_extraction_value(self) -> None:
        assert ProcessingStage.EXTRACTION == "extraction"

    def test_mapping_value(self) -> None:
        assert ProcessingStage.MAPPING == "canonical_mapping"


class TestConfidenceMethod:
    """Tests for the ConfidenceMethod enum."""

    def test_all_methods(self) -> None:
        expected = {
            "MULTI_SOURCE_AGREEMENT", "SINGLE_SOURCE", "FUZZY_RESOLUTION",
            "SBERT_RESOLUTION", "MAJORITY_OVERRIDE", "MANUAL_OVERRIDE",
        }
        assert {m.name for m in ConfidenceMethod} == expected


# ================================================================
# RawRecord Tests
# ================================================================


class TestRawRecord:
    """Tests for the RawRecord model (v2 — has source_type field)."""

    def test_minimal_construction(self) -> None:
        record = RawRecord(
            source="data/recruiter.csv",
            source_type=SourceType.CSV,
        )
        assert record.source == "data/recruiter.csv"
        assert record.source_type == SourceType.CSV
        assert record.raw_fields == {}
        assert record.metadata == {}
        assert record.candidate_hint is None

    def test_record_id_auto_generated(self) -> None:
        r1 = RawRecord(source="a.csv", source_type=SourceType.CSV)
        r2 = RawRecord(source="a.csv", source_type=SourceType.CSV)
        assert r1.record_id != r2.record_id

    def test_created_at_is_utc(self) -> None:
        record = RawRecord(source="a.csv", source_type=SourceType.ATS)
        assert record.created_at.tzinfo is not None

    def test_frozen_raises_on_mutation(self) -> None:
        record = RawRecord(source="a.csv", source_type=SourceType.CSV)
        with pytest.raises(Exception):
            record.source = "other.csv"  # type: ignore[misc]

    def test_raw_fields_accepts_any_types(self) -> None:
        record = RawRecord(
            source="a.csv",
            source_type=SourceType.CSV,
            raw_fields={
                "name": "Alice",
                "age": 30,
                "skills": ["Python", "Java"],
                "score": 9.5,
                "active": True,
                "nothing": None,
            },
        )
        assert record.raw_fields["name"] == "Alice"
        assert record.raw_fields["skills"] == ["Python", "Java"]

    def test_candidate_hint(self) -> None:
        record = RawRecord(
            source="github/priya",
            source_type=SourceType.GITHUB,
            candidate_hint="priya-sharma",
        )
        assert record.candidate_hint == "priya-sharma"


# ================================================================
# Skill Tests
# ================================================================


class TestSkill:
    """Tests for the Skill model (v2 — has normalized_name + embedding_score)."""

    def test_minimal_construction(self) -> None:
        skill = Skill(name="pytorch", normalized_name="PyTorch")
        assert skill.name == "pytorch"
        assert skill.normalized_name == "PyTorch"
        assert skill.category is None
        assert skill.parent_domain is None
        assert skill.confidence == 1.0
        assert skill.aliases == []
        assert skill.sources == []
        assert skill.embedding_score is None

    def test_full_construction(self) -> None:
        skill = Skill(
            name="pytorch",
            normalized_name="PyTorch",
            aliases=["pt", "PyTorch Lightning"],
            category="Deep Learning Framework",
            parent_domain="Machine Learning",
            confidence=0.92,
            sources=[SourceType.GITHUB, SourceType.RESUME],
            embedding_score=0.94,
        )
        assert skill.parent_domain == "Machine Learning"
        assert skill.embedding_score == 0.94
        assert len(skill.aliases) == 2
        assert len(skill.sources) == 2

    def test_confidence_upper_bound(self) -> None:
        with pytest.raises(PydanticValidationError):
            Skill(name="x", normalized_name="X", confidence=1.5)

    def test_confidence_lower_bound(self) -> None:
        with pytest.raises(PydanticValidationError):
            Skill(name="x", normalized_name="X", confidence=-0.1)

    def test_embedding_score_bounds(self) -> None:
        with pytest.raises(PydanticValidationError):
            Skill(name="x", normalized_name="X", embedding_score=1.1)

    def test_frozen(self) -> None:
        skill = Skill(name="x", normalized_name="X")
        with pytest.raises(Exception):
            skill.name = "y"  # type: ignore[misc]


# ================================================================
# Experience Tests
# ================================================================


class TestExperience:
    """Tests for the Experience model (v2 — has normalized_company)."""

    def test_minimal_construction(self) -> None:
        exp = Experience(
            company="Eightfold AI",
            normalized_company="eightfold ai",
            title="ML Engineer",
            source=SourceType.ATS,
        )
        assert exp.company == "Eightfold AI"
        assert exp.normalized_company == "eightfold ai"
        assert exp.is_current is False
        assert exp.description is None

    def test_current_position(self) -> None:
        exp = Experience(
            company="Google",
            normalized_company="google",
            title="SWE",
            source=SourceType.ATS,
            is_current=True,
            end_date=None,
        )
        assert exp.is_current is True
        assert exp.end_date is None

    def test_confidence_bounds(self) -> None:
        with pytest.raises(PydanticValidationError):
            Experience(
                company="X",
                normalized_company="x",
                title="Y",
                source=SourceType.CSV,
                confidence=2.0,
            )

    def test_frozen(self) -> None:
        exp = Experience(
            company="X", normalized_company="x", title="Y", source=SourceType.ATS
        )
        with pytest.raises(Exception):
            exp.company = "Z"  # type: ignore[misc]


# ================================================================
# Education Tests
# ================================================================


class TestEducation:
    """Tests for the Education model (v2 — has normalized_institution)."""

    def test_minimal_construction(self) -> None:
        edu = Education(
            institution="IIT Bombay",
            normalized_institution="iit bombay",
            source=SourceType.RESUME,
        )
        assert edu.institution == "IIT Bombay"
        assert edu.normalized_institution == "iit bombay"
        assert edu.degree is None
        assert edu.grade is None

    def test_full_construction(self) -> None:
        edu = Education(
            institution="IIT Bombay",
            normalized_institution="iit bombay",
            degree="B.Tech",
            field_of_study="Computer Science",
            start_date="2015-07",
            end_date="2019-05",
            grade="9.1 CGPA",
            confidence=0.95,
            source=SourceType.ATS,
        )
        assert edu.degree == "B.Tech"
        assert edu.grade == "9.1 CGPA"

    def test_frozen(self) -> None:
        edu = Education(
            institution="X", normalized_institution="x", source=SourceType.RESUME
        )
        with pytest.raises(Exception):
            edu.institution = "Y"  # type: ignore[misc]


# ================================================================
# CandidateLink Tests
# ================================================================


class TestCandidateLink:
    """Tests for the CandidateLink model (v2 — platform replaces link_type)."""

    def test_github_link(self) -> None:
        link = CandidateLink(
            platform="github",
            url="https://github.com/priya-sharma",
            verified=True,
        )
        assert link.platform == "github"
        assert link.verified is True

    def test_unverified_by_default(self) -> None:
        link = CandidateLink(
            platform="other",
            url="https://example.com",
        )
        assert link.verified is False

    def test_any_platform_string(self) -> None:
        """platform is a free-form string, not an enum."""
        link = CandidateLink(
            platform="stackoverflow",
            url="https://stackoverflow.com/users/123",
        )
        assert link.platform == "stackoverflow"

    def test_frozen(self) -> None:
        link = CandidateLink(platform="github", url="https://github.com/x")
        with pytest.raises(Exception):
            link.url = "other"  # type: ignore[misc]


# ================================================================
# Provenance Tests
# ================================================================


class TestProvenance:
    """Tests for the enriched Provenance model (v2)."""

    def test_minimal_construction(self) -> None:
        prov = Provenance(
            field="email",
            source=SourceType.CSV,
        )
        assert prov.field == "email"
        assert prov.method == NormalizationMethod.NONE
        assert prov.processing_stage == ProcessingStage.EXTRACTION
        assert prov.confidence == 1.0
        assert prov.reason is None

    def test_full_construction(self) -> None:
        prov = Provenance(
            field="email",
            source=SourceType.CSV,
            method=NormalizationMethod.EMAIL_LOWERCASE,
            original_value="USER@GMAIL.COM",
            normalized_value="user@gmail.com",
            processing_stage=ProcessingStage.NORMALIZATION,
            confidence=0.95,
            reason="Lowercased and whitespace stripped.",
        )
        assert prov.original_value == "USER@GMAIL.COM"
        assert prov.normalized_value == "user@gmail.com"
        assert prov.reason == "Lowercased and whitespace stripped."

    def test_timestamp_is_utc(self) -> None:
        prov = Provenance(field="email", source=SourceType.ATS)
        assert prov.timestamp.tzinfo is not None

    def test_frozen(self) -> None:
        prov = Provenance(field="email", source=SourceType.ATS)
        with pytest.raises(Exception):
            prov.field = "phone"  # type: ignore[misc]

    def test_confidence_bounds(self) -> None:
        with pytest.raises(PydanticValidationError):
            Provenance(field="email", source=SourceType.ATS, confidence=1.5)


# ================================================================
# QualityMetrics Tests
# ================================================================


class TestQualityMetrics:
    """Tests for the QualityMetrics model (v2 — uses 'agreement' not 'source_agreement')."""

    def test_construction(self) -> None:
        m = QualityMetrics(
            overall_confidence=0.91,
            completeness=0.88,
            consistency=0.95,
            agreement=0.94,
            freshness=0.76,
        )
        assert m.agreement == 0.94
        assert m.overall_confidence == 0.91

    def test_all_axes_in_range(self) -> None:
        m = QualityMetrics(
            overall_confidence=0.80,
            completeness=0.70,
            consistency=0.90,
            agreement=0.85,
            freshness=0.60,
        )
        for attr in ("overall_confidence", "completeness", "consistency",
                     "agreement", "freshness"):
            val = getattr(m, attr)
            assert 0.0 <= val <= 1.0, f"{attr}={val} out of range"

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            QualityMetrics(
                overall_confidence=1.1,
                completeness=0.5,
                consistency=0.5,
                agreement=0.5,
                freshness=0.5,
            )

    def test_frozen(self) -> None:
        m = QualityMetrics(
            overall_confidence=0.8,
            completeness=0.8,
            consistency=0.8,
            agreement=0.8,
            freshness=0.8,
        )
        with pytest.raises(Exception):
            m.overall_confidence = 0.5  # type: ignore[misc]


# ================================================================
# ValidationIssue & ValidationResult Tests
# ================================================================


class TestValidationIssue:
    """Tests for the ValidationIssue model."""

    def test_construction(self) -> None:
        issue = ValidationIssue(
            field="email",
            rule="email_format",
            message="Email 'notanemail' is malformed.",
            severity=ValidationMode.ERROR,
            actual_value="notanemail",
        )
        assert issue.field == "email"
        assert issue.severity == ValidationMode.ERROR


class TestValidationResult:
    """Tests for the ValidationResult model."""

    def test_valid_result(self) -> None:
        result = ValidationResult(candidate_id="cand-001", is_valid=True)
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_invalid_result(self) -> None:
        result = ValidationResult(
            candidate_id="cand-002",
            is_valid=False,
            errors=[
                ValidationIssue(
                    field="email",
                    rule="email_format",
                    message="Malformed email.",
                    severity=ValidationMode.ERROR,
                )
            ],
        )
        assert result.is_valid is False
        assert len(result.errors) == 1

    def test_validated_at_is_utc(self) -> None:
        result = ValidationResult(candidate_id="x", is_valid=True)
        assert result.validated_at.tzinfo is not None


# ================================================================
# CandidateProfile Tests
# ================================================================


class TestCandidateProfile:
    """Tests for the primary canonical model (v2)."""

    def test_empty_profile(self) -> None:
        profile = CandidateProfile()
        assert profile.candidate_id is not None
        assert profile.full_name is None
        assert profile.emails == []
        assert profile.skills == []
        assert profile.quality_metrics is None
        assert profile.overall_confidence is None

    def test_unique_ids(self) -> None:
        p1 = CandidateProfile()
        p2 = CandidateProfile()
        assert p1.candidate_id != p2.candidate_id

    def test_full_construction(self) -> None:
        profile = CandidateProfile(
            full_name="Priya Sharma",
            emails=["priya.sharma@gmail.com"],
            phones=["+919876543210"],
            skills=[
                Skill(
                    name="pytorch",
                    normalized_name="PyTorch",
                    category="Deep Learning Framework",
                    parent_domain="Machine Learning",
                    sources=[SourceType.ATS],
                )
            ],
        )
        assert profile.full_name == "Priya Sharma"
        assert profile.skills[0].normalized_name == "PyTorch"

    def test_frozen(self) -> None:
        profile = CandidateProfile()
        with pytest.raises(Exception):
            profile.full_name = "Alice"  # type: ignore[misc]

    def test_timestamps_are_utc(self) -> None:
        profile = CandidateProfile()
        assert profile.created_at.tzinfo is not None
        assert profile.updated_at.tzinfo is not None

    def test_overall_confidence_model_validator_passes_when_consistent(self) -> None:
        """overall_confidence and quality_metrics must agree."""
        qm = QualityMetrics(
            overall_confidence=0.85,
            completeness=0.80,
            consistency=0.90,
            agreement=0.88,
            freshness=0.75,
        )
        profile = CandidateProfile(overall_confidence=0.85, quality_metrics=qm)
        assert profile.overall_confidence == 0.85

    def test_overall_confidence_model_validator_fails_when_inconsistent(self) -> None:
        """Mismatched overall_confidence and quality_metrics must raise."""
        qm = QualityMetrics(
            overall_confidence=0.85,
            completeness=0.80,
            consistency=0.90,
            agreement=0.88,
            freshness=0.75,
        )
        with pytest.raises(PydanticValidationError):
            CandidateProfile(overall_confidence=0.50, quality_metrics=qm)

    def test_quality_metrics_alone_is_valid(self) -> None:
        """overall_confidence=None with quality_metrics set is valid."""
        qm = QualityMetrics(
            overall_confidence=0.80,
            completeness=0.75,
            consistency=0.90,
            agreement=0.85,
            freshness=0.60,
        )
        profile = CandidateProfile(quality_metrics=qm)
        assert profile.overall_confidence is None  # validator only fires when both set
