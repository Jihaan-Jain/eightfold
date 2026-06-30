"""
config.py
=========

Runtime configuration models for the Candidate Data Transformer.

All pipeline behaviour that varies between deployments, consumers, or
environments is expressed as configuration data rather than code.
This module defines the Pydantic models that validate and represent
that configuration.

Loading Flow
------------
1. ``config/loader.py`` reads a YAML file into a plain dict.
2. That dict is passed to ``ApplicationConfig(**data)``.
3. Pydantic v2 validates every field and runs all model validators.
4. If any validation fails, a :class:`~src.exceptions.ConfigurationError`
   is raised **before** any extraction begins (fail-fast).
5. The validated ``ApplicationConfig`` is injected into every pipeline
   stage via dependency injection — no stage reads the YAML file directly.

Configuration Hierarchy
-----------------------
::

    ApplicationConfig                   ← top-level; injected into pipeline
    ├── LoggingConfig                   ← logging handler configuration
    ├── NormalizationConfig             ← normaliser behaviour
    ├── IdentityResolutionConfig        ← identity scoring thresholds & weights
    ├── MergeConfig                     ← conflict resolution strategy
    ├── ConfidenceConfig                ← scoring weights
    ├── ProjectionConfig                ← output schema definition
    │   └── list[ProjectionField]       ← per-field projection rules
    └── ValidationConfig                ← rule enforcement settings
        └── list[ValidationRuleConfig]  ← per-rule modes

Design Principles
-----------------
- All config models are ``frozen=True`` — they are constructed once and
  never mutated.
- Sensible defaults are provided for every field so the system works
  with a minimal (or even empty) config file.
- ``model_validator`` decorators enforce cross-field constraints at load
  time (weight sums, threshold ordering, etc.).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models import (
    ConfidenceMethod,
    MergeStrategy,
    MissingFieldStrategy,
    NormalizationMethod,
    ProjectionMode,
    ValidationMode,
)


# ================================================================
# LoggingConfig
# ================================================================


class LoggingConfig(BaseModel):
    """
    Configuration for the logging sub-system.

    Drives :func:`~src.logging_config.configure_logging` at startup.
    All parameters map directly to that function's arguments.

    Attributes
    ----------
    log_level:
        Minimum severity level.
        One of ``"DEBUG"``, ``"INFO"``, ``"WARNING"``, ``"ERROR"``,
        ``"CRITICAL"``.  Validated by a field validator.
    log_file:
        Path to the rotating log file.  ``None`` disables file logging.
        Parent directories are created automatically.
    max_bytes:
        Maximum log file size before rotation.  Default: 10 MB.
    backup_count:
        Number of rotated backup files to retain.  Default: 5.
    debug_mode:
        When ``True``, every log record includes source file, line,
        and function name.  Use in development only.
    json_console:
        When ``True``, console handler outputs JSON instead of
        human-readable text.  Useful inside containers.
    """

    model_config = ConfigDict(frozen=True)

    log_level: str = Field(
        default="INFO",
        description=(
            "Minimum severity level: 'DEBUG', 'INFO', 'WARNING', "
            "'ERROR', or 'CRITICAL'."
        ),
    )
    log_file: str | None = Field(
        default=None,
        description=(
            "Path to the rotating JSON log file.  None disables file logging.  "
            "Parent directories are created automatically."
        ),
    )
    max_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
        description=(
            "Maximum log file size in bytes before rotation occurs.  "
            "Default: 10 MB (10 * 1024 * 1024)."
        ),
    )
    backup_count: int = Field(
        default=5,
        ge=0,
        description="Number of rotated backup log files to retain.  Default: 5.",
    )
    debug_mode: bool = Field(
        default=False,
        description=(
            "When True, every log record includes source file, line number, "
            "and function name.  Do not enable in production."
        ),
    )
    json_console: bool = Field(
        default=False,
        description=(
            "When True, the console handler outputs JSON instead of "
            "human-readable text.  Enable when stdout is ingested by a log "
            "aggregator inside a container."
        ),
    )

    @field_validator("log_level")
    @classmethod
    def log_level_must_be_valid(cls, value: str) -> str:
        """
        Validate and normalise the log level string.

        Raises
        ------
        ValueError
            If the value is not a recognised severity string.
        """
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in valid:
            raise ValueError(
                f"log_level must be one of {sorted(valid)}, got {value!r}."
            )
        return upper


# ================================================================
# NormalizationConfig
# ================================================================


class NormalizationConfig(BaseModel):
    """
    Controls the behaviour of the normalisation stage.

    All settings have safe defaults covering the common case.
    Override only what your deployment requires.

    Attributes
    ----------
    default_country_code:
        ISO 3166-1 alpha-2 fallback country code used by the phone
        normaliser when no country can be inferred from location data.
    preferred_date_format:
        strftime format for output date serialisation.  The normaliser
        always *parses* all formats in ``constants.DATE_FORMATS`` but
        always *serialises* in this format.
    sbert_enabled:
        When ``False``, Stage 3 (SBERT cosine similarity) of the skill
        pipeline is skipped.  Reduces accuracy but improves throughput.
    rapidfuzz_threshold:
        Minimum RapidFuzz token-sort ratio to accept a fuzzy skill
        match (Stage 2).  Range: [0.0, 1.0].
    sbert_threshold:
        Minimum SBERT cosine similarity to accept a semantic skill
        match (Stage 3).  Range: [0.0, 1.0].
    normalise_company_suffixes:
        When ``True``, legal suffixes (Inc., LLC, Ltd.) are stripped
        from company names before experience deduplication.
    name_title_case:
        When ``True``, full_name values are converted to title case
        during normalisation.
    """

    model_config = ConfigDict(frozen=True)

    default_country_code: str = Field(
        default="IN",
        min_length=2,
        max_length=2,
        description=(
            "ISO 3166-1 alpha-2 country code used by the phone normaliser "
            "when no country can be inferred from the candidate's location."
        ),
    )
    preferred_date_format: str = Field(
        default="%Y-%m-%d",
        description=(
            "strftime format string for output date serialisation.  "
            "Always parses all formats in constants.DATE_FORMATS; "
            "serialises in this format."
        ),
    )
    sbert_enabled: bool = Field(
        default=True,
        description=(
            "When False, Stage 3 (SBERT cosine similarity) of the semantic "
            "skill pipeline is skipped.  Reduces accuracy but improves "
            "throughput for high-volume runs."
        ),
    )
    rapidfuzz_threshold: float = Field(
        default=0.88,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum RapidFuzz token-sort ratio to accept a fuzzy skill match "
            "(Stage 2 of the skill normalisation pipeline)."
        ),
    )
    sbert_threshold: float = Field(
        default=0.82,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum SBERT cosine similarity to accept a semantic skill match "
            "(Stage 3 of the skill normalisation pipeline)."
        ),
    )
    normalise_company_suffixes: bool = Field(
        default=True,
        description=(
            "When True, legal suffixes (Inc., LLC, Ltd., Corp.) are stripped "
            "from company names before experience entry deduplication."
        ),
    )
    name_title_case: bool = Field(
        default=True,
        description=(
            "When True, full_name values are converted to title case during "
            "the normalisation stage."
        ),
    )

    @model_validator(mode="after")
    def sbert_threshold_must_be_less_than_or_equal_rapidfuzz(
        self,
    ) -> "NormalizationConfig":
        """
        Validate threshold ordering.

        SBERT is Stage 3 (most expensive, used as last resort).
        It should have a lower or equal threshold than RapidFuzz —
        if SBERT needs a higher bar than RapidFuzz, the stages would
        never trigger in the correct order.

        Note: This is a soft advisory.  Admins may intentionally set
        SBERT threshold higher for precision-focused deployments.
        """
        # Intentionally not raising; SBERT threshold > rapidfuzz threshold
        # is allowed for precision-focused deployments.
        return self


# ================================================================
# IdentityResolutionConfig
# ================================================================


class IdentityResolutionConfig(BaseModel):
    """
    Controls the weighted composite identity scoring model.

    The five signal weights **must sum to exactly 1.0** — enforced by
    a ``model_validator`` at construction time.

    Composite Score Formula
    -----------------------
    ::

        score = email_weight    * email_score
              + phone_weight    * phone_score
              + name_weight     * sbert_name_score
              + company_weight  * company_score
              + location_weight * location_score

    Threshold Guidance
    ------------------
    - ``≥ 0.90`` — very strict; fewer merges, lower false-positive rate
    - ``= 0.85`` — recommended default; balanced
    - ``≤ 0.75`` — aggressive; more merges, higher false-positive risk

    Attributes
    ----------
    match_threshold:
        Composite score at or above which two records are merged into
        the same candidate cluster.
    review_threshold:
        Composite score below which a merge decision is escalated to
        the Human Approval Queue.  Must be < ``match_threshold``.
    email_weight:
        Weight for the exact normalised-email match signal.
    phone_weight:
        Weight for the exact E.164 phone match signal.
    name_weight:
        Weight for the SBERT cosine similarity of full names.
    company_weight:
        Weight for the Jaccard similarity of employer name sets.
    location_weight:
        Weight for the city/country location match signal.
    """

    model_config = ConfigDict(frozen=True)

    match_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description=(
            "Composite identity score at or above which two records are "
            "merged into one CandidateGroup."
        ),
    )
    review_threshold: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description=(
            "Composite score below which the merge decision is escalated "
            "to the Human Approval Queue.  Must be strictly less than "
            "match_threshold."
        ),
    )
    email_weight: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        description="Weight for the exact normalised-email match signal.",
    )
    phone_weight: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="Weight for the exact E.164 phone match signal.",
    )
    name_weight: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Weight for the SBERT cosine similarity of full names.",
    )
    company_weight: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description="Weight for the Jaccard similarity of normalised employer sets.",
    )
    location_weight: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description="Weight for the city / country location match signal.",
    )

    @model_validator(mode="after")
    def weights_must_sum_to_one(self) -> "IdentityResolutionConfig":
        """
        Validate that the five signal weights sum to 1.0.

        Raises
        ------
        ValueError
            If the weights do not sum to 1.0 ± 1e-6.
        """
        total = (
            self.email_weight
            + self.phone_weight
            + self.name_weight
            + self.company_weight
            + self.location_weight
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Identity signal weights must sum to 1.0; got {total:.8f}.  "
                "Adjust email_weight, phone_weight, name_weight, "
                "company_weight, or location_weight."
            )
        return self

    @model_validator(mode="after")
    def review_threshold_must_be_less_than_match_threshold(
        self,
    ) -> "IdentityResolutionConfig":
        """
        Validate that ``review_threshold < match_threshold``.

        If ``review_threshold >= match_threshold``, every match would
        be sent to the approval queue, defeating the purpose of the
        match threshold.

        Raises
        ------
        ValueError
            If ``review_threshold >= match_threshold``.
        """
        if self.review_threshold >= self.match_threshold:
            raise ValueError(
                f"review_threshold ({self.review_threshold}) must be strictly "
                f"less than match_threshold ({self.match_threshold})."
            )
        return self


# ================================================================
# MergeConfig
# ================================================================


class MergeConfig(BaseModel):
    """
    Controls the merge and conflict resolution stage.

    Attributes
    ----------
    strategy:
        High-level algorithm for resolving scalar field conflicts.
    store_merge_decisions:
        When ``True``, every conflict resolution decision is stored
        as a structured record in the candidate's provenance map.
    human_approval_enabled:
        When ``True``, candidates with an identity confidence below
        ``IdentityResolutionConfig.review_threshold`` are sent to
        the Human Approval Queue instead of being auto-merged.
    """

    model_config = ConfigDict(frozen=True)

    strategy: MergeStrategy = Field(
        default=MergeStrategy.SOURCE_PRIORITY,
        description=(
            "High-level strategy for resolving scalar field conflicts: "
            "'source_priority' (default), 'majority_vote', "
            "'most_recent', or 'manual'."
        ),
    )
    store_merge_decisions: bool = Field(
        default=True,
        description=(
            "When True, every conflict resolution decision is stored in "
            "the candidate's provenance map for full auditability."
        ),
    )
    human_approval_enabled: bool = Field(
        default=False,
        description=(
            "When True, candidates with identity confidence below "
            "IdentityResolutionConfig.review_threshold are escalated to "
            "the Human Approval Queue instead of being auto-merged."
        ),
    )


# ================================================================
# ConfidenceConfig
# ================================================================


class ConfidenceConfig(BaseModel):
    """
    Controls the confidence scoring and quality metrics stage.

    Attributes
    ----------
    method:
        Primary method used to compute per-field confidence scores.
    freshness_half_life_days:
        Number of days over which the freshness score decays from 1.0
        to 0.0.  Sources extracted today score 1.0.
    compute_quality_metrics:
        When ``True``, all five quality-axis metrics (completeness,
        consistency, agreement, freshness, overall_confidence) are
        computed and attached to every profile.
    min_profile_confidence:
        Profiles with ``overall_confidence`` below this threshold are
        written to the errors log rather than the main output.
    """

    model_config = ConfigDict(frozen=True)

    method: ConfidenceMethod = Field(
        default=ConfidenceMethod.MULTI_SOURCE_AGREEMENT,
        description="Primary method used to compute per-field confidence scores.",
    )
    freshness_half_life_days: int = Field(
        default=180,
        gt=0,
        description=(
            "Number of days over which the freshness score decays from "
            "1.0 to 0.0.  Sources extracted today = 1.0; sources extracted "
            "freshness_half_life_days ago = 0.0."
        ),
    )
    compute_quality_metrics: bool = Field(
        default=True,
        description=(
            "When True, all five quality-axis metrics are computed and attached "
            "to every CandidateProfile."
        ),
    )
    min_profile_confidence: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description=(
            "Profiles with overall_confidence below this value are written to "
            "the errors log instead of the main output."
        ),
    )


# ================================================================
# Projection Configuration
# ================================================================


class ProjectionField(BaseModel):
    """
    Projection rule for one field in the consumer output schema.

    Supported Modes
    ---------------
    ``SELECT``
        Include the field at its canonical name.
    ``RENAME``
        Expose the field under ``output_name``.
    ``FLATTEN``
        Extract a scalar attribute from each list element via
        ``flatten_path`` (e.g. ``skills[].name`` → list of str).
    ``TRANSFORM``
        Apply the named function from ``transform`` (registered in
        the projector transform registry).
    ``AGGREGATE``
        Reduce a list to a scalar via ``aggregate``
        (``"count"``, ``"first"``, ``"last"``, ``"max"``, ``"min"``).
    ``DEFAULT``
        Fill a missing / null field with ``default_value``.
    ``CONDITIONAL``
        Include the field only when ``condition`` evaluates ``True``.

    Attributes
    ----------
    canonical_name:
        Dotted path to the field on CandidateProfile.
        Supports nested access (``"quality_metrics.completeness"``)
        and list-element access (``"skills[].name"``).
    output_name:
        Consumer-facing field name in the output object.
        Defaults to ``canonical_name`` when ``None``.
    mode:
        Projection mode controlling how the field is transformed.
    required:
        When ``True`` and the field is missing or null, the
        ``missing_strategy`` is applied.
    missing_strategy:
        What to do when the field is absent or null:
        ``"omit"``, ``"null"``, ``"default"``, or ``"error"``.
    default_value:
        Value to use when ``missing_strategy="default"``.
    flatten_path:
        Attribute name to extract from each list element.
        Only meaningful for list-typed fields.
    transform:
        Name of a registered transform function.
        Only used when ``mode=TRANSFORM``.
    aggregate:
        Aggregation to apply to a list field.
        Only used when ``mode=AGGREGATE``.
    condition:
        Python expression evaluated against the candidate dict.
        The field is included only when the expression is truthy.
        Only used when ``mode=CONDITIONAL``.
    """

    model_config = ConfigDict(frozen=True)

    canonical_name: str = Field(
        description=(
            "Dotted path to the field on CandidateProfile.  Supports nested "
            "access ('quality_metrics.completeness') and list-element access "
            "('skills[].name')."
        )
    )
    output_name: str | None = Field(
        default=None,
        description=(
            "Consumer-facing name in the output.  Uses canonical_name when None."
        ),
    )
    mode: ProjectionMode = Field(
        default=ProjectionMode.SELECT,
        description="Projection mode controlling how the field is transformed.",
    )
    required: bool = Field(
        default=False,
        description=(
            "When True and the field is absent or null, missing_strategy "
            "is applied (and may raise if set to 'error')."
        ),
    )
    missing_strategy: MissingFieldStrategy = Field(
        default=MissingFieldStrategy.NULL,
        description=(
            "Behaviour for absent / null fields: "
            "'omit', 'null', 'default', or 'error'."
        ),
    )
    default_value: Any = Field(
        default=None,
        description=(
            "Value used when missing_strategy='default' and the field is absent. "
            "Must be JSON-serialisable."
        ),
    )
    flatten_path: str | None = Field(
        default=None,
        description=(
            "Attribute to extract from each list element.  "
            "Only meaningful for list-typed fields.  "
            "Example: flatten_path='name' on skills → ['Python', 'Java']."
        ),
    )
    transform: str | None = Field(
        default=None,
        description=(
            "Name of a registered projector transform function.  "
            "Only used when mode=TRANSFORM.  "
            "Example: 'join_comma', 'to_uppercase', 'count'."
        ),
    )
    aggregate: str | None = Field(
        default=None,
        description=(
            "Aggregation to apply to a list field.  "
            "Only used when mode=AGGREGATE.  "
            "Supported values: 'count', 'first', 'last', 'max', 'min'."
        ),
    )
    condition: str | None = Field(
        default=None,
        description=(
            "Python expression evaluated against the candidate dict.  "
            "The field is included only when the expression is truthy.  "
            "Only used when mode=CONDITIONAL.  "
            "Example: \"quality_metrics['completeness'] > 0.8\"."
        ),
    )

    @field_validator("canonical_name")
    @classmethod
    def canonical_name_must_not_be_blank(cls, value: str) -> str:
        """Reject blank canonical_name strings."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("canonical_name must not be blank or whitespace-only.")
        return stripped

    @model_validator(mode="after")
    def validate_mode_dependencies(self) -> "ProjectionField":
        """
        Validate that mode-specific fields are present when required.

        Rules
        -----
        - ``FLATTEN`` requires ``flatten_path``.
        - ``TRANSFORM`` requires ``transform``.
        - ``AGGREGATE`` requires ``aggregate``.
        - ``DEFAULT`` requires ``default_value`` is not None.

        Raises
        ------
        ValueError
            If a required mode-specific field is absent.
        """
        if self.mode == ProjectionMode.FLATTEN and not self.flatten_path:
            raise ValueError(
                "ProjectionField with mode=FLATTEN must specify flatten_path."
            )
        if self.mode == ProjectionMode.TRANSFORM and not self.transform:
            raise ValueError(
                "ProjectionField with mode=TRANSFORM must specify transform."
            )
        if self.mode == ProjectionMode.AGGREGATE and not self.aggregate:
            raise ValueError(
                "ProjectionField with mode=AGGREGATE must specify aggregate."
            )
        valid_aggregates = {"count", "first", "last", "max", "min"}
        if self.aggregate and self.aggregate not in valid_aggregates:
            raise ValueError(
                f"aggregate must be one of {sorted(valid_aggregates)}, "
                f"got {self.aggregate!r}."
            )
        return self


class ProjectionConfig(BaseModel):
    """
    Output schema configuration — defines which fields to project and
    how to transform them for one named consumer output schema.

    Multiple named schemas can co-exist (e.g. ``"recruiter_view"``,
    ``"ats_export"``, ``"full_profile"``).

    Attributes
    ----------
    name:
        Unique schema identifier (e.g. ``"recruiter_view"``).
    description:
        Human-readable description of this schema's purpose.
    fields:
        Ordered list of :class:`ProjectionField` rules.
        Output field order matches this list order.
    include_confidence:
        When ``True``, the :class:`~src.models.QualityMetrics` object
        is included in the output under the key ``"quality_metrics"``
        (or an alias if configured).
    include_provenance:
        When ``True``, the full provenance map is included.
        **Warning:** significantly increases output payload size.
    include_merge_decisions:
        When ``True``, the conflict resolution audit map is included.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(
        description=(
            "Unique schema identifier "
            "(e.g. 'recruiter_view', 'ats_export', 'full_profile')."
        )
    )
    description: str | None = Field(
        default=None,
        description="Optional human-readable description of this schema's purpose.",
    )
    fields: list[ProjectionField] = Field(
        default_factory=list,
        description=(
            "Ordered list of field projection rules.  "
            "Output object field order matches this list order."
        ),
    )
    include_confidence: bool = Field(
        default=False,
        description=(
            "When True, quality_metrics is included in the output under "
            "the key 'quality_metrics' (or a configured alias)."
        ),
    )
    include_provenance: bool = Field(
        default=False,
        description=(
            "When True, the full provenance map is included in the output.  "
            "WARNING: significantly increases output payload size."
        ),
    )
    include_merge_decisions: bool = Field(
        default=False,
        description=(
            "When True, the conflict resolution audit map is included "
            "in the output under the key 'merge_decisions'."
        ),
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        """Reject blank schema names."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("ProjectionConfig.name must not be blank.")
        return stripped


# ================================================================
# ValidationConfig
# ================================================================


class ValidationRuleConfig(BaseModel):
    """
    Per-rule enforcement settings for one validation rule.

    Rules not listed in :attr:`ValidationConfig.rules` use their
    built-in default enforcement mode (typically ``WARNING``).

    Attributes
    ----------
    rule_id:
        Unique identifier of the validation rule
        (e.g. ``"email_format"``, ``"graduation_not_future"``).
    mode:
        Enforcement level: ``"error"`` (blocks output),
        ``"warning"`` (advisory), or ``"off"`` (disabled).
    message_override:
        Optional custom error message to use instead of the rule's
        built-in default.  Useful for consumer-facing feedback.
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(
        description=(
            "Unique identifier of the validation rule "
            "(e.g. 'email_format', 'graduation_not_future', "
            "'experience_dates_ordered')."
        )
    )
    mode: ValidationMode = Field(
        description=(
            "Enforcement level: 'error' (blocks output to main file), "
            "'warning' (advisory, candidate still written), or 'off' (disabled)."
        )
    )
    message_override: str | None = Field(
        default=None,
        description=(
            "Optional custom error message.  When set, replaces the rule's "
            "built-in default message in ValidationResult output."
        ),
    )


class ValidationConfig(BaseModel):
    """
    Controls the validation stage — which rules are enforced and how.

    Attributes
    ----------
    rules:
        Per-rule enforcement overrides.  Rules not listed here use
        their built-in default mode.
    max_string_length:
        Maximum character length for any string field in the output.
    max_skills_count:
        Maximum number of skills per candidate in the output.
    max_experience_count:
        Maximum number of experience entries per candidate.
    max_education_count:
        Maximum number of education entries per candidate.
    """

    model_config = ConfigDict(frozen=True)

    rules: list[ValidationRuleConfig] = Field(
        default_factory=list,
        description=(
            "Per-rule enforcement overrides.  Rules absent from this list "
            "use their built-in default enforcement mode."
        ),
    )
    max_string_length: int = Field(
        default=2048,
        gt=0,
        description="Maximum character length for any string field in the output.",
    )
    max_skills_count: int = Field(
        default=200,
        gt=0,
        description="Maximum number of skill entries per candidate in the output.",
    )
    max_experience_count: int = Field(
        default=50,
        gt=0,
        description="Maximum number of experience entries per candidate.",
    )
    max_education_count: int = Field(
        default=20,
        gt=0,
        description="Maximum number of education entries per candidate.",
    )


# ================================================================
# ApplicationConfig  (top-level)
# ================================================================


class ApplicationConfig(BaseModel):
    """
    Top-level runtime configuration for the entire pipeline.

    This is the **single object** constructed at startup and injected
    into every pipeline stage.  No stage reads a config file directly.

    Attributes
    ----------
    logging:
        Logging handler configuration.
    normalization:
        Normaliser behaviour configuration.
    identity_resolution:
        Identity scoring thresholds and signal weights.
    merge:
        Conflict resolution strategy configuration.
    confidence:
        Confidence scoring configuration.
    projection:
        Output schema definition.  ``None`` means the full canonical
        profile is written without any field projection.
    validation:
        Validation rule enforcement configuration.
    input_directory:
        Directory from which extractors read source files.
    output_directory:
        Directory to which the output stage writes result files.
    errors_directory:
        Directory for candidates that failed validation.
    output_format:
        Serialisation format: ``"json"`` (one file per candidate)
        or ``"jsonl"`` (all candidates in one file).
    pretty_print:
        When ``True``, JSON output is indented for human readability.

    Example YAML
    ------------
    .. code-block:: yaml

        logging:
          log_level: INFO
          log_file: logs/pipeline.log
          debug_mode: false

        normalization:
          default_country_code: IN
          sbert_enabled: true

        identity_resolution:
          match_threshold: 0.85
          review_threshold: 0.70
          email_weight: 0.45
          phone_weight: 0.20
          name_weight: 0.15
          company_weight: 0.10
          location_weight: 0.10

        merge:
          strategy: source_priority
          store_merge_decisions: true

        output_directory: data/output
        errors_directory: data/output/errors
        output_format: json
        pretty_print: false
    """

    model_config = ConfigDict(frozen=True)

    logging: LoggingConfig = Field(
        default_factory=LoggingConfig,
        description="Logging handler configuration.",
    )
    normalization: NormalizationConfig = Field(
        default_factory=NormalizationConfig,
        description="Normaliser behaviour configuration.",
    )
    identity_resolution: IdentityResolutionConfig = Field(
        default_factory=IdentityResolutionConfig,
        description="Identity resolution thresholds and signal weights.",
    )
    merge: MergeConfig = Field(
        default_factory=MergeConfig,
        description="Merge and conflict resolution strategy configuration.",
    )
    confidence: ConfidenceConfig = Field(
        default_factory=ConfidenceConfig,
        description="Confidence scoring and quality metrics configuration.",
    )
    projection: ProjectionConfig | None = Field(
        default=None,
        description=(
            "Output schema configuration.  None = write full canonical profile "
            "without field projection."
        ),
    )
    validation: ValidationConfig = Field(
        default_factory=ValidationConfig,
        description="Validation rule enforcement configuration.",
    )
    input_directory: str = Field(
        default="data/input",
        description=(
            "Directory from which extractors read source files "
            "(relative to project root)."
        ),
    )
    output_directory: str = Field(
        default="data/output",
        description=(
            "Directory to which the output stage writes result files "
            "(relative to project root)."
        ),
    )
    errors_directory: str = Field(
        default="data/output/errors",
        description=(
            "Directory for candidates that failed ERROR-mode validation rules "
            "(relative to project root)."
        ),
    )
    output_format: str = Field(
        default="json",
        description=(
            "Output serialisation format: "
            "'json' (one file per candidate, named {candidate_id}.json) or "
            "'jsonl' (all candidates in pipeline_output.jsonl)."
        ),
    )
    pretty_print: bool = Field(
        default=False,
        description=(
            "When True, output JSON is indented for human readability.  "
            "Increases file size; disable for production."
        ),
    )

    @field_validator("output_format")
    @classmethod
    def output_format_must_be_valid(cls, value: str) -> str:
        """Validate that output_format is 'json' or 'jsonl'."""
        valid = {"json", "jsonl"}
        lower = value.lower()
        if lower not in valid:
            raise ValueError(
                f"output_format must be one of {sorted(valid)}, got {value!r}."
            )
        return lower

    @model_validator(mode="after")
    def errors_directory_must_differ_from_output_directory(
        self,
    ) -> "ApplicationConfig":
        """
        Validate that the errors directory is not the same as the main
        output directory to prevent valid and invalid candidates from
        being mixed in the same folder.

        Raises
        ------
        ValueError
            If ``errors_directory == output_directory``.
        """
        if Path(self.errors_directory).resolve() == Path(self.output_directory).resolve():
            raise ValueError(
                f"errors_directory ({self.errors_directory!r}) must differ from "
                f"output_directory ({self.output_directory!r}).  "
                "Mixing valid and invalid candidates in the same folder is not allowed."
            )
        return self
