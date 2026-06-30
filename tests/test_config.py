"""
test_config.py  (v2)
====================

Unit tests for config models in src/config.py (v2).

Updated to use ApplicationConfig (top-level), LoggingConfig,
and ProjectionField with ProjectionMode.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.config import (
    ApplicationConfig,
    ConfidenceConfig,
    IdentityResolutionConfig,
    LoggingConfig,
    MergeConfig,
    NormalizationConfig,
    ProjectionConfig,
    ProjectionField,
    ValidationConfig,
    ValidationRuleConfig,
)
from src.models import (
    ConfidenceMethod,
    MergeStrategy,
    MissingFieldStrategy,
    ProjectionMode,
    ValidationMode,
)


# ================================================================
# LoggingConfig Tests
# ================================================================


class TestLoggingConfig:
    """Tests for the logging configuration model."""

    def test_defaults(self) -> None:
        cfg = LoggingConfig()
        assert cfg.log_level == "INFO"
        assert cfg.log_file is None
        assert cfg.debug_mode is False
        assert cfg.json_console is False
        assert cfg.max_bytes == 10 * 1024 * 1024
        assert cfg.backup_count == 5

    def test_log_level_upcased(self) -> None:
        cfg = LoggingConfig(log_level="debug")
        assert cfg.log_level == "DEBUG"

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            LoggingConfig(log_level="VERBOSE")

    def test_all_valid_levels(self) -> None:
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            cfg = LoggingConfig(log_level=level)
            assert cfg.log_level == level

    def test_log_file_path(self) -> None:
        cfg = LoggingConfig(log_file="logs/pipeline.log")
        assert cfg.log_file == "logs/pipeline.log"

    def test_frozen(self) -> None:
        cfg = LoggingConfig()
        with pytest.raises(Exception):
            cfg.log_level = "DEBUG"  # type: ignore[misc]


# ================================================================
# NormalizationConfig Tests
# ================================================================


class TestNormalizationConfig:
    """Tests for the normalisation configuration model."""

    def test_defaults(self) -> None:
        cfg = NormalizationConfig()
        assert cfg.default_country_code == "IN"
        assert cfg.sbert_enabled is True
        assert cfg.rapidfuzz_threshold == 0.88
        assert cfg.sbert_threshold == 0.82
        assert cfg.normalise_company_suffixes is True
        assert cfg.name_title_case is True

    def test_rapidfuzz_threshold_upper_bound(self) -> None:
        with pytest.raises(PydanticValidationError):
            NormalizationConfig(rapidfuzz_threshold=1.5)

    def test_rapidfuzz_threshold_lower_bound(self) -> None:
        with pytest.raises(PydanticValidationError):
            NormalizationConfig(rapidfuzz_threshold=-0.1)

    def test_sbert_disabled(self) -> None:
        cfg = NormalizationConfig(sbert_enabled=False)
        assert cfg.sbert_enabled is False

    def test_country_code_min_length(self) -> None:
        with pytest.raises(PydanticValidationError):
            NormalizationConfig(default_country_code="I")  # too short

    def test_country_code_max_length(self) -> None:
        with pytest.raises(PydanticValidationError):
            NormalizationConfig(default_country_code="IND")  # too long


# ================================================================
# IdentityResolutionConfig Tests
# ================================================================


class TestIdentityResolutionConfig:
    """Tests for the identity resolution config with model validators."""

    def test_default_weights_sum_to_one(self) -> None:
        cfg = IdentityResolutionConfig()
        total = (
            cfg.email_weight + cfg.phone_weight + cfg.name_weight
            + cfg.company_weight + cfg.location_weight
        )
        assert abs(total - 1.0) < 1e-9

    def test_weights_not_summing_to_one_raises(self) -> None:
        with pytest.raises(PydanticValidationError) as exc_info:
            IdentityResolutionConfig(
                email_weight=0.50,
                phone_weight=0.20,
                name_weight=0.15,
                company_weight=0.15,
                location_weight=0.10,  # sum = 1.10
            )
        assert "1.0" in str(exc_info.value)

    def test_review_threshold_equal_to_match_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            IdentityResolutionConfig(
                match_threshold=0.80,
                review_threshold=0.80,
            )

    def test_review_threshold_greater_than_match_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            IdentityResolutionConfig(
                match_threshold=0.70,
                review_threshold=0.90,
            )

    def test_valid_thresholds_accepted(self) -> None:
        cfg = IdentityResolutionConfig(
            match_threshold=0.90,
            review_threshold=0.75,
        )
        assert cfg.match_threshold == 0.90

    def test_custom_weights_summing_to_one(self) -> None:
        cfg = IdentityResolutionConfig(
            email_weight=0.50,
            phone_weight=0.20,
            name_weight=0.10,
            company_weight=0.10,
            location_weight=0.10,
        )
        total = (
            cfg.email_weight + cfg.phone_weight + cfg.name_weight
            + cfg.company_weight + cfg.location_weight
        )
        assert abs(total - 1.0) < 1e-9


# ================================================================
# MergeConfig Tests
# ================================================================


class TestMergeConfig:
    """Tests for the merge stage configuration model."""

    def test_defaults(self) -> None:
        cfg = MergeConfig()
        assert cfg.strategy == MergeStrategy.SOURCE_PRIORITY
        assert cfg.store_merge_decisions is True
        assert cfg.human_approval_enabled is False

    def test_manual_strategy(self) -> None:
        cfg = MergeConfig(strategy=MergeStrategy.MANUAL, human_approval_enabled=True)
        assert cfg.strategy == MergeStrategy.MANUAL
        assert cfg.human_approval_enabled is True


# ================================================================
# ConfidenceConfig Tests
# ================================================================


class TestConfidenceConfig:
    """Tests for the confidence scoring configuration model."""

    def test_defaults(self) -> None:
        cfg = ConfidenceConfig()
        assert cfg.method == ConfidenceMethod.MULTI_SOURCE_AGREEMENT
        assert cfg.freshness_half_life_days == 180
        assert cfg.compute_quality_metrics is True
        assert cfg.min_profile_confidence == 0.20

    def test_freshness_days_must_be_positive(self) -> None:
        with pytest.raises(PydanticValidationError):
            ConfidenceConfig(freshness_half_life_days=0)

    def test_min_confidence_bounds(self) -> None:
        with pytest.raises(PydanticValidationError):
            ConfidenceConfig(min_profile_confidence=1.5)


# ================================================================
# ProjectionField Tests
# ================================================================


class TestProjectionField:
    """Tests for the per-field projection rule model (v2)."""

    def test_minimal_select_field(self) -> None:
        field = ProjectionField(canonical_name="full_name")
        assert field.mode == ProjectionMode.SELECT
        assert field.output_name is None
        assert field.required is False
        assert field.missing_strategy == MissingFieldStrategy.NULL

    def test_blank_canonical_name_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            ProjectionField(canonical_name="  ")

    def test_empty_canonical_name_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            ProjectionField(canonical_name="")

    def test_rename_mode(self) -> None:
        field = ProjectionField(
            canonical_name="full_name",
            output_name="name",
            mode=ProjectionMode.RENAME,
        )
        assert field.output_name == "name"

    def test_flatten_requires_flatten_path(self) -> None:
        with pytest.raises(PydanticValidationError):
            ProjectionField(
                canonical_name="skills",
                mode=ProjectionMode.FLATTEN,
                # flatten_path missing → should raise
            )

    def test_flatten_with_path(self) -> None:
        field = ProjectionField(
            canonical_name="skills",
            mode=ProjectionMode.FLATTEN,
            flatten_path="name",
        )
        assert field.flatten_path == "name"

    def test_transform_requires_transform(self) -> None:
        with pytest.raises(PydanticValidationError):
            ProjectionField(
                canonical_name="skills",
                mode=ProjectionMode.TRANSFORM,
                # transform missing → should raise
            )

    def test_transform_with_function(self) -> None:
        field = ProjectionField(
            canonical_name="skills",
            mode=ProjectionMode.TRANSFORM,
            transform="join_comma",
        )
        assert field.transform == "join_comma"

    def test_aggregate_requires_aggregate(self) -> None:
        with pytest.raises(PydanticValidationError):
            ProjectionField(
                canonical_name="emails",
                mode=ProjectionMode.AGGREGATE,
                # aggregate missing → should raise
            )

    def test_aggregate_valid_values(self) -> None:
        for agg in ("count", "first", "last", "max", "min"):
            field = ProjectionField(
                canonical_name="emails",
                mode=ProjectionMode.AGGREGATE,
                aggregate=agg,
            )
            assert field.aggregate == agg

    def test_aggregate_invalid_value_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            ProjectionField(
                canonical_name="emails",
                mode=ProjectionMode.AGGREGATE,
                aggregate="median",  # not in valid set
            )

    def test_default_mode_with_default_value(self) -> None:
        field = ProjectionField(
            canonical_name="headline",
            mode=ProjectionMode.DEFAULT,
            missing_strategy=MissingFieldStrategy.DEFAULT,
            default_value="No headline provided",
        )
        assert field.default_value == "No headline provided"

    def test_conditional_mode(self) -> None:
        field = ProjectionField(
            canonical_name="quality_metrics",
            mode=ProjectionMode.CONDITIONAL,
            condition="overall_confidence > 0.8",
        )
        assert field.condition == "overall_confidence > 0.8"


# ================================================================
# ProjectionConfig Tests
# ================================================================


class TestProjectionConfig:
    """Tests for the output schema configuration model."""

    def test_minimal_schema(self) -> None:
        schema = ProjectionConfig(name="test_schema")
        assert schema.name == "test_schema"
        assert schema.fields == []
        assert schema.include_confidence is False

    def test_blank_name_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            ProjectionConfig(name="  ")

    def test_schema_with_fields(self) -> None:
        schema = ProjectionConfig(
            name="recruiter_view",
            include_confidence=True,
            fields=[
                ProjectionField(canonical_name="full_name", output_name="name"),
                ProjectionField(canonical_name="emails"),
            ],
        )
        assert len(schema.fields) == 2
        assert schema.include_confidence is True


# ================================================================
# ValidationConfig Tests
# ================================================================


class TestValidationConfig:
    """Tests for the validation configuration model."""

    def test_defaults(self) -> None:
        cfg = ValidationConfig()
        assert cfg.max_string_length == 2048
        assert cfg.max_skills_count == 200
        assert cfg.max_experience_count == 50
        assert cfg.max_education_count == 20
        assert cfg.rules == []

    def test_with_rules(self) -> None:
        cfg = ValidationConfig(
            rules=[
                ValidationRuleConfig(rule_id="email_format", mode=ValidationMode.ERROR),
                ValidationRuleConfig(rule_id="graduation_not_future", mode=ValidationMode.WARNING),
            ]
        )
        assert len(cfg.rules) == 2

    def test_max_skills_must_be_positive(self) -> None:
        with pytest.raises(PydanticValidationError):
            ValidationConfig(max_skills_count=0)


# ================================================================
# ApplicationConfig Tests
# ================================================================


class TestApplicationConfig:
    """Tests for the top-level ApplicationConfig model."""

    def test_default_construction(self) -> None:
        cfg = ApplicationConfig()
        assert cfg.logging.log_level == "INFO"
        assert cfg.output_format == "json"
        assert cfg.pretty_print is False
        assert cfg.projection is None
        assert isinstance(cfg.normalization, NormalizationConfig)
        assert isinstance(cfg.identity_resolution, IdentityResolutionConfig)

    def test_invalid_output_format_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            ApplicationConfig(output_format="xml")

    def test_output_format_normalised_to_lowercase(self) -> None:
        cfg = ApplicationConfig(output_format="JSON")
        assert cfg.output_format == "json"

    def test_jsonl_format(self) -> None:
        cfg = ApplicationConfig(output_format="jsonl")
        assert cfg.output_format == "jsonl"

    def test_errors_directory_must_differ_from_output(self) -> None:
        with pytest.raises(PydanticValidationError):
            ApplicationConfig(
                output_directory="data/output",
                errors_directory="data/output",  # same → should raise
            )

    def test_valid_different_directories(self) -> None:
        cfg = ApplicationConfig(
            output_directory="data/output",
            errors_directory="data/output/errors",
        )
        assert cfg.output_directory == "data/output"
        assert cfg.errors_directory == "data/output/errors"

    def test_frozen(self) -> None:
        cfg = ApplicationConfig()
        with pytest.raises(Exception):
            cfg.output_format = "xml"  # type: ignore[misc]

    def test_sub_configs_accessible(self) -> None:
        cfg = ApplicationConfig()
        assert cfg.merge.strategy == MergeStrategy.SOURCE_PRIORITY
        assert cfg.confidence.compute_quality_metrics is True
