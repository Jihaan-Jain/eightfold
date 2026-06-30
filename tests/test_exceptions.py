"""
test_exceptions.py  (v2)
========================

Unit tests for the custom exception hierarchy in src/exceptions.py (v2).

The v2 hierarchy has 8 classes (ConfidenceScoringError and
ConflictResolutionError were merged into the architecture but the
v2 exceptions.py has 8 named classes).

Tests verify:
- All exceptions inherit from CandidateTransformerError
- Structured context fields are set correctly on each subclass
- stage attribute populated per exception type
- str(exc) returns the message
- details dict is always a dict (never None)
- All exceptions are catchable via the base class
"""

from __future__ import annotations

import pytest

from src.exceptions import (
    CandidateTransformerError,
    ConfigurationError,
    ExtractionError,
    IdentityResolutionError,
    MappingError,
    MergeError,
    NormalizationError,
    ProjectionError,
    ValidationError,
)

# All 8 non-base exception classes
EXCEPTION_CLASSES = [
    ConfigurationError,
    ExtractionError,
    MappingError,
    NormalizationError,
    IdentityResolutionError,
    MergeError,
    ProjectionError,
    ValidationError,
]


# ================================================================
# Base Exception Tests
# ================================================================


class TestCandidateTransformerError:
    """Tests for the base exception class."""

    def test_str_returns_message(self) -> None:
        exc = CandidateTransformerError("something went wrong")
        assert str(exc) == "something went wrong"

    def test_message_attribute(self) -> None:
        exc = CandidateTransformerError("test")
        assert exc.message == "test"

    def test_stage_defaults_to_none(self) -> None:
        exc = CandidateTransformerError("error")
        assert exc.stage is None

    def test_details_defaults_to_empty_dict(self) -> None:
        exc = CandidateTransformerError("error")
        assert exc.details == {}

    def test_details_none_becomes_empty_dict(self) -> None:
        exc = CandidateTransformerError("error", details=None)
        assert isinstance(exc.details, dict)
        assert exc.details == {}

    def test_with_stage_and_details(self) -> None:
        exc = CandidateTransformerError(
            "error",
            stage="extraction",
            details={"source": "csv", "record_id": "row-1"},
        )
        assert exc.stage == "extraction"
        assert exc.details["source"] == "csv"

    def test_repr_contains_class_name(self) -> None:
        exc = CandidateTransformerError("something failed")
        assert "CandidateTransformerError" in repr(exc)

    def test_repr_contains_message(self) -> None:
        exc = CandidateTransformerError("test message")
        assert "test message" in repr(exc)


# ================================================================
# Inheritance Tests
# ================================================================


class TestInheritance:
    """Every domain exception must inherit from CandidateTransformerError."""

    @pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
    def test_is_subclass_of_base(self, exc_class) -> None:
        assert issubclass(exc_class, CandidateTransformerError)

    @pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
    def test_instance_is_base(self, exc_class) -> None:
        exc = exc_class("test message")
        assert isinstance(exc, CandidateTransformerError)

    @pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
    def test_catchable_as_base(self, exc_class) -> None:
        with pytest.raises(CandidateTransformerError):
            raise exc_class("test")

    @pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
    def test_details_never_none(self, exc_class) -> None:
        exc = exc_class("test")
        assert isinstance(exc.details, dict)

    @pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
    def test_str_is_message(self, exc_class) -> None:
        exc = exc_class("my error message")
        assert str(exc) == "my error message"


# ================================================================
# ConfigurationError Tests
# ================================================================


class TestConfigurationError:
    """Tests for ConfigurationError."""

    def test_stage_is_configuration(self) -> None:
        exc = ConfigurationError("bad config")
        assert exc.stage == "configuration"

    def test_context_fields(self) -> None:
        exc = ConfigurationError(
            "missing key",
            config_path="configs/default_config.yaml",
            invalid_key="identity_resolution.email_weight",
        )
        assert exc.config_path == "configs/default_config.yaml"
        assert exc.invalid_key == "identity_resolution.email_weight"
        assert exc.details["config_path"] == "configs/default_config.yaml"
        assert exc.details["invalid_key"] == "identity_resolution.email_weight"

    def test_defaults_to_none(self) -> None:
        exc = ConfigurationError("error")
        assert exc.config_path is None
        assert exc.invalid_key is None


# ================================================================
# ExtractionError Tests
# ================================================================


class TestExtractionError:
    """Tests for ExtractionError."""

    def test_stage_is_extraction(self) -> None:
        exc = ExtractionError("parse failed")
        assert exc.stage == "extraction"

    def test_source_context(self) -> None:
        exc = ExtractionError(
            "GitHub 404",
            source_type="github",
            source_path="https://api.github.com/users/unknown",
            record_id="github-unknown",
        )
        assert exc.source_type == "github"
        assert exc.source_path == "https://api.github.com/users/unknown"
        assert exc.record_id == "github-unknown"
        assert exc.details["source_type"] == "github"

    def test_defaults_to_none(self) -> None:
        exc = ExtractionError("error")
        assert exc.source_type is None
        assert exc.source_path is None
        assert exc.record_id is None


# ================================================================
# MappingError Tests
# ================================================================


class TestMappingError:
    """Tests for MappingError."""

    def test_stage_is_canonical_mapping(self) -> None:
        exc = MappingError("unknown field")
        assert exc.stage == "canonical_mapping"

    def test_context_fields(self) -> None:
        exc = MappingError(
            "no mapping for field",
            source_type="csv",
            raw_field_name="LinkedInProfileURL",
            record_id="csv-row-42",
        )
        assert exc.source_type == "csv"
        assert exc.raw_field_name == "LinkedInProfileURL"
        assert exc.record_id == "csv-row-42"


# ================================================================
# NormalizationError Tests
# ================================================================


class TestNormalizationError:
    """Tests for NormalizationError."""

    def test_stage_is_normalization(self) -> None:
        exc = NormalizationError("invalid phone")
        assert exc.stage == "normalization"

    def test_context_fields(self) -> None:
        exc = NormalizationError(
            "cannot parse date",
            field_name="start_date",
            raw_value="not-a-date",
            normalizer="date_normalizer",
            record_id="ats-row-5",
        )
        assert exc.field_name == "start_date"
        assert exc.raw_value == "not-a-date"
        assert exc.normalizer == "date_normalizer"
        assert exc.record_id == "ats-row-5"

    def test_raw_value_stored_on_exc(self) -> None:
        exc = NormalizationError("error", raw_value=12345)
        assert exc.raw_value == 12345

    def test_long_raw_value_truncated_in_details(self) -> None:
        long_value = "x" * 500
        exc = NormalizationError("error", raw_value=long_value)
        # details stores truncated version
        stored = exc.details.get("raw_value", "")
        assert len(stored) <= 200

    def test_none_raw_value(self) -> None:
        exc = NormalizationError("error", raw_value=None)
        assert exc.raw_value is None
        assert exc.details["raw_value"] is None


# ================================================================
# IdentityResolutionError Tests
# ================================================================


class TestIdentityResolutionError:
    """Tests for IdentityResolutionError."""

    def test_stage_is_identity_resolution(self) -> None:
        exc = IdentityResolutionError("scoring failed")
        assert exc.stage == "identity_resolution"

    def test_record_ids_default_empty(self) -> None:
        exc = IdentityResolutionError("error")
        assert exc.record_ids == []

    def test_with_record_ids_and_strategy(self) -> None:
        exc = IdentityResolutionError(
            "SBERT model not loaded",
            record_ids=["csv-row-1", "ats-row-5"],
            strategy="sbert_name_similarity",
        )
        assert len(exc.record_ids) == 2
        assert exc.strategy == "sbert_name_similarity"
        assert exc.details["record_ids"] == ["csv-row-1", "ats-row-5"]


# ================================================================
# MergeError Tests
# ================================================================


class TestMergeError:
    """Tests for MergeError."""

    def test_stage_is_merge(self) -> None:
        exc = MergeError("assembly failed")
        assert exc.stage == "merge"

    def test_context_fields(self) -> None:
        exc = MergeError(
            "all records missing full_name",
            group_id="grp-001",
            record_ids=["r1", "r2", "r3"],
        )
        assert exc.group_id == "grp-001"
        assert exc.record_ids == ["r1", "r2", "r3"]
        assert exc.details["group_id"] == "grp-001"

    def test_record_ids_default_empty(self) -> None:
        exc = MergeError("error")
        assert exc.record_ids == []


# ================================================================
# ProjectionError Tests
# ================================================================


class TestProjectionError:
    """Tests for ProjectionError."""

    def test_stage_is_projection(self) -> None:
        exc = ProjectionError("unknown field")
        assert exc.stage == "projection"

    def test_context_fields(self) -> None:
        exc = ProjectionError(
            "transform not registered",
            schema_name="recruiter_view",
            field_name="skills",
            candidate_id="cand-001",
        )
        assert exc.schema_name == "recruiter_view"
        assert exc.field_name == "skills"
        assert exc.candidate_id == "cand-001"


# ================================================================
# ValidationError Tests
# ================================================================


class TestValidationError:
    """Tests for ValidationError (the exception, not the model)."""

    def test_stage_is_validation(self) -> None:
        exc = ValidationError("validator crashed")
        assert exc.stage == "validation"

    def test_context_fields(self) -> None:
        exc = ValidationError(
            "unexpected error in rule",
            candidate_id="cand-007",
            rule_name="graduation_not_future",
        )
        assert exc.candidate_id == "cand-007"
        assert exc.rule_name == "graduation_not_future"
        assert exc.details["candidate_id"] == "cand-007"
