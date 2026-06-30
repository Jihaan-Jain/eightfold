"""
models.py
=========

Canonical Pydantic v2 data models for the Candidate Data Transformer.

This module is the **single source of truth** for every data shape
that flows through the pipeline.  No model is defined inside a logic
module.

Model Inventory
---------------

Enumerations
~~~~~~~~~~~~
- :class:`SourceType`          — input source type
- :class:`NormalizationMethod` — transformation applied to a field
- :class:`MergeStrategy`       — algorithm used during merge
- :class:`ConfidenceMethod`    — how a confidence score was computed
- :class:`ProjectionMode`      — consumer output projection mode
- :class:`ValidationMode`      — rule enforcement level
- :class:`MissingFieldStrategy`— what to do when a field is absent
- :class:`ProcessingStage`     — pipeline stage labels

Supporting Models
~~~~~~~~~~~~~~~~~
- :class:`Provenance`          — audit trail for one field transformation
- :class:`Skill`               — resolved skill with ontology & confidence
- :class:`Experience`          — one work-history entry
- :class:`Education`           — one educational qualification
- :class:`CandidateLink`       — a profile URL or portfolio link
- :class:`QualityMetrics`      — five-axis quality measurement
- :class:`ValidationIssue`     — one structured validation finding
- :class:`ValidationResult`    — full output of the validation stage

Primary Pipeline Models
~~~~~~~~~~~~~~~~~~~~~~~
- :class:`RawRecord`           — output of an extractor (pre-mapping)
- :class:`CanonicalRecord`     — output of the mapping stage (single source)
- :class:`CandidateProfile`    — canonical merged profile (primary artifact)

Design Principles
-----------------
- All models are ``frozen=True`` unless they are mutable staging
  objects (those are explicitly documented as mutable).
- All ``float`` confidence fields are bounded ``[0.0, 1.0]`` via
  :data:`ConfidenceScore`.
- All ``datetime`` fields are UTC-aware.
- Optional fields default to ``None``, not sentinel strings.
- Every ``Field(...)`` has a ``description`` for schema generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ================================================================
# Utility Types & Helpers
# ================================================================

#: Float bounded to [0.0, 1.0].  Every confidence / score field uses
#: this type so bound violations are caught by Pydantic at model
#: construction time rather than silently propagating.
ConfidenceScore = Annotated[
    float,
    Field(
        ge=0.0,
        le=1.0,
        description=(
            "Confidence score in the closed interval [0.0, 1.0]. "
            "1.0 = certain; 0.0 = no confidence."
        ),
    ),
]


def _utc_now() -> datetime:
    """Return the current instant as a timezone-aware UTC datetime."""
    return datetime.now(tz=timezone.utc)


def _new_uuid() -> str:
    """Return a new random UUID4 as a hyphenated string."""
    return str(uuid4())


# ================================================================
# Enumerations
# ================================================================


class SourceType(str, Enum):
    """
    Supported input source types for the extraction stage.

    Each extractor is associated with exactly one ``SourceType``.
    String values are lowercase so they can be used directly in
    YAML config files, log messages, and JSON output.

    Attributes
    ----------
    CSV:
        Recruiter-managed spreadsheet in CSV or TSV format.
    ATS:
        Applicant Tracking System export in JSON format.
    GITHUB:
        GitHub user profile fetched via the GitHub REST API.
    RESUME:
        Candidate résumé document in PDF format.
    RECRUITER_NOTES:
        Free-text notes entered by a recruiter (CSV column or plain
        text file).
    """

    CSV             = "csv"
    ATS             = "ats"
    GITHUB          = "github"
    RESUME          = "resume"
    RECRUITER_NOTES = "recruiter_notes"


class NormalizationMethod(str, Enum):
    """
    Describes the transformation applied to a field value during
    the normalisation stage.

    Stored in :attr:`Provenance.method` so the transformation chain
    is fully traceable field-by-field.

    Attributes
    ----------
    NONE:
        No transformation — raw value used as-is.
    EMAIL_LOWERCASE:
        Email lowercased and whitespace stripped.
    PHONE_E164:
        Phone normalised to E.164 international format.
    DATE_ISO8601:
        Date string parsed and serialised to ISO 8601.
    NAME_TITLE_CASE:
        Name converted to title case with whitespace normalised.
    SKILL_ALIAS:
        Skill resolved via the curated alias dictionary (Stage 1).
    SKILL_FUZZY:
        Skill resolved via RapidFuzz token-sort ratio (Stage 2).
    SKILL_SBERT:
        Skill resolved via SBERT cosine similarity (Stage 3).
    LOCATION_DECOMPOSE:
        Location string decomposed to city / state / country fields.
    URL_NORMALIZE:
        URL scheme normalised, trailing slash removed.
    COMPANY_STRIP_SUFFIX:
        Legal suffix (Inc., LLC, Ltd.) stripped for deduplication.
    """

    NONE                 = "none"
    EMAIL_LOWERCASE      = "email_lowercase"
    PHONE_E164           = "phone_e164"
    DATE_ISO8601         = "date_iso8601"
    NAME_TITLE_CASE      = "name_title_case"
    SKILL_ALIAS          = "skill_alias"
    SKILL_FUZZY          = "skill_fuzzy"
    SKILL_SBERT          = "skill_sbert"
    LOCATION_DECOMPOSE   = "location_decompose"
    URL_NORMALIZE        = "url_normalize"
    COMPANY_STRIP_SUFFIX = "company_strip_suffix"


class MappingMethod(str, Enum):
    """
    How a raw field was mapped to its canonical counterpart.

    Stored in the ``reason`` of a :class:`Provenance` record produced
    by the mapping stage.  Kept separate from :class:`NormalizationMethod`
    so the two pipeline stages remain independently traceable.

    Attributes
    ----------
    DIRECT:
        Raw field name exactly equals the canonical name (case-insensitive).
    ALIAS:
        Raw field name matched a registered alias in the
        :class:`~src.mapping.field_registry.FieldRegistry`.
    INFERRED:
        Canonical field derived by combining two or more raw fields
        (e.g. ``first_name`` + ``last_name`` → ``full_name``).
    NESTED:
        Field extracted from a nested dict path
        (e.g. ATS ``candidate.contact.email``).
    SECTION:
        Field extracted from a plain-text section in a PDF résumé
        (e.g. skills bullet list under the ``SKILLS`` header).
    DEFAULT:
        Canonical field assigned a hard-coded default value because the
        source provided no applicable raw field.
    UNKNOWN:
        Raw field could not be mapped to any canonical field and was
        stored in ``CanonicalRecord.unknown_fields`` for review.
    """

    DIRECT   = "direct"
    ALIAS    = "alias"
    INFERRED = "inferred"
    NESTED   = "nested"
    SECTION  = "section"
    DEFAULT  = "default"
    UNKNOWN  = "unknown"


class MergeStrategy(str, Enum):
    """
    High-level algorithm used by the merge stage.

    Configured in :class:`~src.config.MergeConfig` and determines
    how scalar field conflicts between multiple sources are decided.

    Attributes
    ----------
    SOURCE_PRIORITY:
        Resolve conflicts using the source trust hierarchy defined
        in ``constants.SOURCE_PRIORITY``.  Default strategy.
    MAJORITY_VOTE:
        When ≥ 2 of ≥ 3 sources agree on a value, that value wins
        regardless of source priority.
    MOST_RECENT:
        Always prefer the value from the most recently extracted source.
    MANUAL:
        All conflicts are sent to the Human Approval Queue; no
        automated resolution is attempted.
    """

    SOURCE_PRIORITY = "source_priority"
    MAJORITY_VOTE   = "majority_vote"
    MOST_RECENT     = "most_recent"
    MANUAL          = "manual"


class ConfidenceMethod(str, Enum):
    """
    Describes how a confidence score was computed.

    Attached to :class:`~src.models.Provenance` records and quality
    metric fields for full auditability.

    Attributes
    ----------
    MULTI_SOURCE_AGREEMENT:
        Multiple sources provided and agreed on this value.
    SINGLE_SOURCE:
        Only one source provided this value.
    FUZZY_RESOLUTION:
        Value resolved via RapidFuzz; confidence is penalised.
    SBERT_RESOLUTION:
        Value resolved via SBERT; confidence reflects cosine score.
    MAJORITY_OVERRIDE:
        Value won by majority vote; confidence reflects agreement ratio.
    MANUAL_OVERRIDE:
        Value set by a human reviewer; confidence is 1.0 by definition.
    """

    MULTI_SOURCE_AGREEMENT = "multi_source_agreement"
    SINGLE_SOURCE          = "single_source"
    FUZZY_RESOLUTION       = "fuzzy_resolution"
    SBERT_RESOLUTION       = "sbert_resolution"
    MAJORITY_OVERRIDE      = "majority_override"
    MANUAL_OVERRIDE        = "manual_override"


class ProjectionMode(str, Enum):
    """
    Controls how the projector transforms a :class:`CandidateProfile`
    field for the consumer-facing output.

    Each :class:`~src.config.ProjectionField` specifies one mode.

    Attributes
    ----------
    SELECT:
        Include the field at its canonical name (pass-through).
    RENAME:
        Expose the field under a consumer alias defined by
        :attr:`~src.config.ProjectionField.output_name`.
    FLATTEN:
        Extract a scalar attribute from each element of a list field
        (e.g. ``skills[].name`` → ``["Python", "Java"]``).
    TRANSFORM:
        Apply a named transformation function registered in the
        projector transform registry.
    AGGREGATE:
        Reduce a list field to a scalar (count, first, last, etc.).
    DEFAULT:
        Fill a missing / null field with a configured default value.
    CONDITIONAL:
        Include the field only when a boolean expression evaluates to
        ``True`` for the candidate being projected.
    """

    SELECT      = "select"
    RENAME      = "rename"
    FLATTEN     = "flatten"
    TRANSFORM   = "transform"
    AGGREGATE   = "aggregate"
    DEFAULT     = "default"
    CONDITIONAL = "conditional"


class ValidationMode(str, Enum):
    """
    Enforcement level for a validation rule.

    Configured per-rule in :class:`~src.config.ValidationRuleConfig`.

    Attributes
    ----------
    ERROR:
        Rule failure blocks the candidate from the main output.
        The candidate is written to the errors log instead.
    WARNING:
        Rule failure is noted but the candidate is still written to
        the main output.
    OFF:
        Rule is disabled entirely and never evaluated.
    """

    ERROR   = "error"
    WARNING = "warning"
    OFF     = "off"


class MissingFieldStrategy(str, Enum):
    """
    Behaviour when an expected field is absent from the projected output.

    Configured per-field in :class:`~src.config.ProjectionField`.

    Attributes
    ----------
    OMIT:
        Field is silently excluded from the output object.
    NULL:
        Field is included with a JSON ``null`` value.
    DEFAULT:
        Field is filled with the value specified by
        :attr:`~src.config.ProjectionField.default_value`.
    ERROR:
        Missing field triggers a :class:`~src.models.ValidationIssue`
        at ERROR severity.
    """

    OMIT    = "omit"
    NULL    = "null"
    DEFAULT = "default"
    ERROR   = "error"


class ProcessingStage(str, Enum):
    """
    Typed enumeration of pipeline stage labels.

    Used in :attr:`Provenance.processing_stage` and log context to
    identify which stage last touched a field value.  Prefer this
    enum over the raw ``STAGE_*`` string constants from
    :mod:`src.constants` in typed code.

    Attributes
    ----------
    EXTRACTION:
        Raw bytes / text read from source; no transformation applied.
    MAPPING:
        Source-specific field names translated to canonical names.
    NORMALIZATION:
        Field values transformed to canonical format.
    IDENTITY_RESOLUTION:
        Records clustered by composite identity score.
    MERGE:
        CandidateProfile assembled from a cluster of records.
    CONFLICT_RESOLUTION:
        Scalar field conflicts resolved to a single winner.
    CONFIDENCE_SCORING:
        Per-field and five-axis quality metrics computed.
    PROJECTION:
        CandidateProfile projected to consumer output schema.
    VALIDATION:
        Projected output validated against schema and business rules.
    OUTPUT:
        Final serialisation to JSON / JSONL files.
    """

    EXTRACTION          = "extraction"
    MAPPING             = "canonical_mapping"
    NORMALIZATION       = "normalization"
    IDENTITY_RESOLUTION = "identity_resolution"
    MERGE               = "merge"
    CONFLICT_RESOLUTION = "conflict_resolution"
    CONFIDENCE_SCORING  = "confidence_scoring"
    PROJECTION          = "projection"
    VALIDATION          = "validation"
    OUTPUT              = "output"


# ================================================================
# Supporting Models
# ================================================================


class Provenance(BaseModel):
    """
    Full audit record for one field value across the pipeline.

    A ``Provenance`` object is created every time a field value is
    first recorded, transformed, or involved in a conflict resolution
    decision.  The complete provenance trail for a field is a list of
    these objects in chronological order (oldest first).

    Stored at :attr:`CandidateProfile.provenance` as::

        {"email": [Provenance, Provenance, ...], ...}

    This design means every value in the final output can be traced
    back to its exact source record and every transformation it passed
    through.

    Attributes
    ----------
    field:
        Canonical field name this entry describes (e.g. ``"email"``).
    source:
        Source type that originally provided this value.
    method:
        Normalisation transformation that was applied.
    original_value:
        Exact value as it appeared in the raw source — never modified.
    normalized_value:
        Value after normalisation.  May equal ``original_value`` when
        ``method == NormalizationMethod.NONE``.
    processing_stage:
        Pipeline stage that last wrote to this provenance entry.
    confidence:
        Confidence that this is the correct value for this field.
    timestamp:
        UTC datetime when this provenance entry was recorded.
    reason:
        Optional human-readable explanation (e.g. why this value was
        chosen over a competing one during conflict resolution).
    """

    model_config = ConfigDict(frozen=True)

    field: str = Field(
        description="Canonical field name this provenance entry describes."
    )
    source: SourceType = Field(
        description="The source type that originally provided this value."
    )
    method: NormalizationMethod = Field(
        default=NormalizationMethod.NONE,
        description="Normalisation transformation that was applied to original_value.",
    )
    original_value: Any = Field(
        default=None,
        description=(
            "Exact value as it appeared in the raw source, before any "
            "transformation.  This field is immutable once set."
        ),
    )
    normalized_value: Any = Field(
        default=None,
        description=(
            "Value after the normalisation pipeline.  Used by identity "
            "resolution and merge stages."
        ),
    )
    processing_stage: ProcessingStage = Field(
        default=ProcessingStage.EXTRACTION,
        description="Pipeline stage that produced or last modified this entry.",
    )
    confidence: ConfidenceScore = Field(
        default=1.0,
        description="Confidence that normalized_value is the correct canonical value.",
    )
    timestamp: datetime = Field(
        default_factory=_utc_now,
        description="UTC datetime when this provenance entry was created.",
    )
    reason: str | None = Field(
        default=None,
        description=(
            "Optional explanation for why this value was chosen or discarded "
            "during conflict resolution (e.g. 'ATS outranks CSV (priority 1 vs 3)')."
        ),
    )


class Skill(BaseModel):
    """
    A single resolved skill with ontology, confidence, and source
    attribution.

    Skills are not plain strings — they are typed, hierarchical,
    sourced, and confidence-rated entities.  This enables semantic
    deduplication across sources and parent-domain queries.

    Ontology Example
    ----------------
    ::

        Skill(
            name="pytorch",
            normalized_name="PyTorch",
            aliases=["pt", "PyTorch Lightning"],
            category="Deep Learning Framework",
            parent_domain="Machine Learning",
            confidence=0.92,
            sources=[SourceType.GITHUB, SourceType.RESUME],
            embedding_score=0.94,
        )

    Attributes
    ----------
    name:
        Raw skill string as originally extracted from the source.
    normalized_name:
        Canonical skill name after alias / fuzzy / SBERT resolution.
    aliases:
        All raw strings from source records that resolved to this
        canonical skill (e.g. ``["pt", "pytorch"]`` → ``"PyTorch"``).
    category:
        Level-1 ontology category
        (e.g. ``"Deep Learning Framework"``).
    parent_domain:
        Level-2 ontology parent domain
        (e.g. ``"Machine Learning"``).
    confidence:
        Confidence that ``normalized_name`` is the correct canonical
        form for the original input string.
    sources:
        All source types that mentioned this skill.
    embedding_score:
        SBERT cosine similarity score from Stage 3 of the skill
        normalisation pipeline.  ``None`` when resolved by earlier
        stages (dictionary or RapidFuzz).
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(
        description="Raw skill string as originally extracted from the source."
    )
    normalized_name: str = Field(
        description=(
            "Canonical skill name after alias / fuzzy / SBERT resolution "
            "(e.g. 'PyTorch', 'JavaScript', 'Kubernetes')."
        )
    )
    aliases: list[str] = Field(
        default_factory=list,
        description=(
            "All raw input strings that mapped to this canonical skill, "
            "across all sources (e.g. ['pytorch', 'pt', 'PyTorch Lightning'])."
        ),
    )
    category: str | None = Field(
        default=None,
        description=(
            "Level-1 ontology category "
            "(e.g. 'Deep Learning Framework', 'Programming Language')."
        ),
    )
    parent_domain: str | None = Field(
        default=None,
        description=(
            "Level-2 ontology parent domain "
            "(e.g. 'Machine Learning', 'Web Development', 'Data Engineering')."
        ),
    )
    confidence: ConfidenceScore = Field(
        default=1.0,
        description=(
            "Confidence that normalized_name is the correct canonical form "
            "for the raw input string."
        ),
    )
    sources: list[SourceType] = Field(
        default_factory=list,
        description="All source types that mentioned this skill.",
    )
    embedding_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "SBERT cosine similarity score between the raw skill embedding and "
            "the canonical skill embedding.  None when resolved by dictionary "
            "or RapidFuzz (stages 1–2)."
        ),
    )


class Experience(BaseModel):
    """
    One position in a candidate's professional work history.

    Experience entries from multiple sources are deduplicated by
    :mod:`src.merge.experience_merger` using the key::

        (normalized_company, normalized_title, start_year_month)

    After deduplication, entries are sorted by ``start_date`` descending
    (most recent first).

    Attributes
    ----------
    company:
        Raw company name as extracted from the source.
    normalized_company:
        Company name after legal-suffix stripping and lowercasing,
        used as the deduplication key.
    title:
        Job title as extracted from the source.
    description:
        Free-text description of responsibilities and achievements.
    start_date:
        ISO 8601 start date.  May be year-only (``"2022"``),
        year-month (``"2022-06"``), or full date (``"2022-06-15"``).
    end_date:
        ISO 8601 end date.  ``None`` when the position is current.
        Raw ``"Present"`` / ``"Current"`` values are normalised to
        ``None`` with ``is_current=True``.
    is_current:
        ``True`` when this is an active / ongoing position.
    location:
        City, country, or ``"Remote"`` for this position.
    confidence:
        Confidence in the accuracy of this entry.  Penalised when
        parsed from unstructured PDF text.
    source:
        Which source type provided this entry.
    """

    model_config = ConfigDict(frozen=True)

    company: str = Field(
        description="Raw company name as extracted from the source."
    )
    normalized_company: str = Field(
        description=(
            "Company name after legal-suffix stripping and whitespace "
            "normalisation.  Used as the deduplication key across sources."
        )
    )
    title: str = Field(
        description="Job title as extracted from the source."
    )
    description: str | None = Field(
        default=None,
        description="Free-text description of responsibilities and achievements.",
    )
    start_date: str | None = Field(
        default=None,
        description=(
            "ISO 8601 start date.  May be year-only ('2022'), "
            "year-month ('2022-06'), or full date ('2022-06-15')."
        ),
    )
    end_date: str | None = Field(
        default=None,
        description=(
            "ISO 8601 end date.  None when the position is current. "
            "Raw 'Present'/'Current' values are normalised to None."
        ),
    )
    is_current: bool = Field(
        default=False,
        description="True when this is an active / ongoing position.",
    )
    location: str | None = Field(
        default=None,
        description="City, country, or 'Remote' for this position.",
    )
    confidence: ConfidenceScore = Field(
        default=1.0,
        description=(
            "Confidence in the accuracy of this entry. "
            "Penalised for PDF-parsed entries where the layout is ambiguous."
        ),
    )
    source: SourceType = Field(
        description="Source type that provided this experience entry."
    )


class Education(BaseModel):
    """
    One educational qualification in a candidate's background.

    Education entries are deduplicated by
    :mod:`src.merge.education_merger` using the key::

        (normalized_institution, normalized_degree, graduation_year)

    After deduplication, entries are sorted by ``end_date`` descending
    (most recent / highest qualification first).

    Attributes
    ----------
    institution:
        Raw institution name as extracted from the source.
    normalized_institution:
        Institution name lowercased and whitespace-normalised for
        deduplication (e.g. ``"iit bombay"``).
    degree:
        Degree type (e.g. ``"Bachelor of Technology"``,
        ``"Master of Science"``, ``"PhD"``).
    field_of_study:
        Subject area or major (e.g. ``"Computer Science"``).
    start_date:
        ISO 8601 start date of the programme.
    end_date:
        ISO 8601 graduation date.  ``None`` if the programme is
        ongoing.
    grade:
        Grade or GPA as a string
        (e.g. ``"3.8 / 4.0"``, ``"9.2 CGPA"``, ``"First Class"``).
    confidence:
        Confidence in the accuracy of this entry.
    source:
        Source type that provided this entry.
    """

    model_config = ConfigDict(frozen=True)

    institution: str = Field(
        description="Raw institution name as extracted from the source."
    )
    normalized_institution: str = Field(
        description=(
            "Institution name lowercased and whitespace-normalised, "
            "used as the deduplication key (e.g. 'iit bombay')."
        )
    )
    degree: str | None = Field(
        default=None,
        description=(
            "Degree type (e.g. 'Bachelor of Technology', "
            "'Master of Science', 'PhD', 'B.Tech')."
        ),
    )
    field_of_study: str | None = Field(
        default=None,
        description="Subject area or major (e.g. 'Computer Science', 'Data Science').",
    )
    start_date: str | None = Field(
        default=None,
        description="ISO 8601 start date of the programme.",
    )
    end_date: str | None = Field(
        default=None,
        description=(
            "ISO 8601 graduation / expected-graduation date.  "
            "None when the programme is ongoing."
        ),
    )
    grade: str | None = Field(
        default=None,
        description=(
            "Grade or GPA as a string "
            "(e.g. '3.8 / 4.0', '9.2 CGPA', 'First Class Honours')."
        ),
    )
    confidence: ConfidenceScore = Field(
        default=1.0,
        description="Confidence in the accuracy of this education entry.",
    )
    source: SourceType = Field(
        description="Source type that provided this education entry."
    )


class CandidateLink(BaseModel):
    """
    A profile URL or portfolio link associated with a candidate.

    Links are extracted from all sources, deduplicated by normalised
    URL, and classified by ``platform``.

    Attributes
    ----------
    platform:
        Platform or link category (e.g. ``"github"``, ``"linkedin"``,
        ``"portfolio"``, ``"stackoverflow"``, ``"other"``).
    url:
        Fully-qualified, normalised URL (scheme always present,
        trailing slash removed, fragment removed).
    verified:
        ``True`` if the URL was retrieved from an authoritative API
        (e.g. directly from the GitHub API response field) rather
        than parsed from unstructured free text.
    """

    model_config = ConfigDict(frozen=True)

    platform: str = Field(
        description=(
            "Platform identifier for this link.  Well-known values: "
            "'github', 'linkedin', 'portfolio', 'stackoverflow', 'twitter', "
            "'personal', 'other'.  Not an enum so future platforms need no "
            "code changes."
        )
    )
    url: str = Field(
        description="Fully-qualified, normalised URL with scheme present."
    )
    verified: bool = Field(
        default=False,
        description=(
            "True when the URL came from an authoritative API response "
            "rather than being extracted from unstructured text."
        ),
    )


class QualityMetrics(BaseModel):
    """
    Five-axis quality measurement for a merged :class:`CandidateProfile`.

    A single ``overall_confidence`` score masks whether a profile is
    unreliable due to data sparsity or source disagreement.  These five
    axes give operators a precise diagnosis.

    Axes
    ----
    overall_confidence:
        Weighted average of per-field confidence scores, where weights
        are taken from ``constants.FIELD_IMPORTANCE_WEIGHTS``.
    completeness:
        Fraction of expected canonical fields that are non-null.
        A profile built only from GitHub will score low here.
    consistency:
        Intra-source coherence ratio.  Detects sources that
        contradict themselves (e.g. start_date after end_date).
    agreement:
        For fields present in more than one source, the fraction
        where all sources returned the same normalised value.
    freshness:
        Recency score based on the age of contributing source
        extractions.  1.0 = extracted today; decays to 0.0 over
        ``constants.FRESHNESS_HALF_LIFE_DAYS`` days.

    Attributes
    ----------
    overall_confidence:
        Weighted mean confidence across all fields.
    completeness:
        Fraction of expected canonical fields that are populated.
    consistency:
        Intra-source coherence score (1.0 = no self-contradictions).
    agreement:
        Inter-source agreement score (1.0 = full agreement).
    freshness:
        Source recency score (1.0 = all sources extracted today).
    """

    model_config = ConfigDict(frozen=True)

    overall_confidence: ConfidenceScore = Field(
        description="Weighted average confidence across all profile fields."
    )
    completeness: ConfidenceScore = Field(
        description=(
            "Fraction of expected canonical fields that are populated (non-null). "
            "Ranges from 0.0 (empty profile) to 1.0 (fully populated)."
        )
    )
    consistency: ConfidenceScore = Field(
        description=(
            "Intra-source coherence score.  1.0 = no source contradicts itself "
            "(e.g. no experience entry has start_date after end_date)."
        )
    )
    agreement: ConfidenceScore = Field(
        description=(
            "Inter-source agreement score for multi-source fields.  "
            "1.0 = all sources that provided a field agreed on the same value."
        )
    )
    freshness: ConfidenceScore = Field(
        description=(
            "Recency score based on extraction timestamps.  "
            "1.0 = all sources extracted today; decays to 0.0 over "
            "constants.FRESHNESS_HALF_LIFE_DAYS days."
        )
    )


class ValidationIssue(BaseModel):
    """
    One structured validation finding (error or warning) for a candidate.

    Distinct from :class:`~src.exceptions.ValidationError` (the
    exception class, which signals that the *validator machinery*
    crashed).  This model describes *what* rule failed in the output.

    Attributes
    ----------
    field:
        Canonical field name where the violation was detected.
    rule:
        Unique identifier of the validation rule that was violated
        (e.g. ``"email_format"``, ``"graduation_not_future"``).
    message:
        Human-readable description of the violation.
    severity:
        ``ValidationMode.ERROR`` blocks the candidate from the main
        output; ``ValidationMode.WARNING`` is advisory.
    actual_value:
        The actual field value that failed the rule, for debugging.
    """

    model_config = ConfigDict(frozen=True)

    field: str = Field(
        description="Canonical field name where the validation violation was detected."
    )
    rule: str = Field(
        description=(
            "Unique rule identifier "
            "(e.g. 'email_format', 'graduation_not_future', "
            "'experience_dates_ordered')."
        )
    )
    message: str = Field(
        description="Human-readable description of the validation violation."
    )
    severity: ValidationMode = Field(
        description=(
            "Enforcement level: 'error' (blocks output) or 'warning' (advisory)."
        )
    )
    actual_value: Any = Field(
        default=None,
        description="The actual value that triggered the rule violation.",
    )


class ValidationResult(BaseModel):
    """
    The complete outcome of running one candidate through the validation
    stage.

    Consumers should inspect this object before trusting the projected
    output.

    Outcomes
    --------
    - ``is_valid=True, errors=[], warnings=[]``  — clean output
    - ``is_valid=True, errors=[], warnings=[…]`` — passed with advisories
    - ``is_valid=False, errors=[…]``             — blocked; see errors log

    Attributes
    ----------
    candidate_id:
        The :attr:`CandidateProfile.candidate_id` this result applies to.
    is_valid:
        ``True`` when all ERROR-mode rules passed.  A candidate with
        ``is_valid=False`` is written to the errors log rather than the
        main output.
    errors:
        Validation rules that failed at ERROR severity.
        Non-empty implies ``is_valid=False``.
    warnings:
        Validation rules that failed at WARNING severity.
        The candidate is still written to output despite these.
    validated_at:
        UTC datetime when validation was performed.
    """

    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(
        description="CandidateProfile.candidate_id this result applies to."
    )
    is_valid: bool = Field(
        description=(
            "True when all ERROR-mode validation rules passed.  "
            "False candidates are written to the errors log."
        )
    )
    errors: list[ValidationIssue] = Field(
        default_factory=list,
        description=(
            "Validation rules that failed at ERROR severity.  "
            "Non-empty implies is_valid=False."
        ),
    )
    warnings: list[ValidationIssue] = Field(
        default_factory=list,
        description=(
            "Validation rules that failed at WARNING severity.  "
            "Candidate is still included in main output."
        ),
    )
    validated_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC datetime when validation was run.",
    )


# ================================================================
# Primary Pipeline Models
# ================================================================


class RawRecord(BaseModel):
    """
    The first object produced by any extractor.

    Represents one row / document / API response from a single source,
    *exactly as it was received* — no field mapping, no normalisation.

    The extractor's job is only to convert raw bytes/text to
    Python-native types.  All downstream stages are guaranteed that
    ``raw_fields`` contains only JSON-serialisable Python values.

    Immutability
    ------------
    ``RawRecord`` is frozen.  Once an extractor creates it, no
    downstream stage may mutate it.  Provenance correctness depends on
    ``original_value`` remaining stable across the full pipeline run.

    Attributes
    ----------
    record_id:
        System-generated UUID uniquely identifying this raw record.
        Used as the primary key in all provenance entries.
    source:
        Human-readable source label (e.g. ``"data/recruiter_q3.csv"``
        or ``"github/priya-sharma"``).  Used in log messages.
    source_type:
        The type of source this record was extracted from.
    raw_fields:
        Key-value pairs exactly as they appeared in the source.
        Keys are source-specific field names (NOT canonical names).
        Values are Python-native types only.
    metadata:
        Source-specific metadata not suitable for ``raw_fields``
        (e.g. HTTP response headers, CSV dialect, PDF page count,
        GitHub API rate-limit remaining).
    candidate_hint:
        Optional candidate identifier extracted directly from the
        source (e.g. ATS ``candidate_id``, GitHub username).  Used to
        seed identity resolution when the source already knows its key.
    created_at:
        UTC datetime when this record was produced by the extractor.
    """

    model_config = ConfigDict(frozen=True)

    record_id: str = Field(
        default_factory=_new_uuid,
        description=(
            "System-generated UUID4 uniquely identifying this raw record. "
            "Used as the primary key in all Provenance entries."
        ),
    )
    source: str = Field(
        description=(
            "Human-readable source label used in log messages "
            "(e.g. 'data/recruiter_q3.csv', 'github/priya-sharma')."
        )
    )
    source_type: SourceType = Field(
        description="The enumerated type of source this record was extracted from."
    )
    raw_fields: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Key-value pairs exactly as they appeared in the raw source. "
            "Keys are source-specific names (NOT canonical names). "
            "Values must be JSON-serialisable Python types."
        ),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Source-specific metadata not in raw_fields "
            "(e.g. HTTP headers, CSV dialect, PDF page count, "
            "API rate-limit remaining, file hash)."
        ),
    )
    candidate_hint: str | None = Field(
        default=None,
        description=(
            "Optional identifier from the source itself used to seed "
            "identity resolution (e.g. ATS candidate_id, GitHub username)."
        ),
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC datetime when this record was produced by the extractor.",
    )


class CanonicalRecord(BaseModel):
    """
    The output of the mapping stage for a **single** :class:`RawRecord`.

    ``CanonicalRecord`` is the intermediate object between raw extraction
    and the final merged :class:`CandidateProfile`.  It represents one
    source's view of a candidate in canonical field names, with every
    mapped field carrying a :class:`Provenance` entry.

    Mutability
    ----------
    Unlike :class:`RawRecord` and :class:`CandidateProfile`, this model
    is **not frozen**.  Mappers build it incrementally — appending to
    ``provenance``, ``mapped_fields``, etc. — before returning the
    completed instance.

    Attributes
    ----------
    canonical_id:
        System-generated UUID for this canonical record instance.
    source_record_id:
        The :attr:`RawRecord.record_id` this was produced from.
    source_type:
        The :attr:`RawRecord.source_type` of the originating record.
    source_label:
        The :attr:`RawRecord.source` label for log messages.
    full_name:
        Candidate's full name as mapped from the source.
    first_name / last_name:
        Split first / last name when the source provides them separately.
    emails:
        All email addresses found in the source record.
    phones:
        All phone numbers found in the source record.
    location:
        Location string as-is from the source (not decomposed).
    headline:
        Professional headline or one-line summary.
    summary:
        Longer free-text professional summary or bio.
    current_company:
        Most recent / current employer name.
    current_title:
        Most recent / current job title.
    years_of_experience:
        Estimated total years of experience (``None`` when not inferable).
    skills:
        Raw skill strings exactly as extracted (not normalised).
    experience:
        List of raw experience dicts with keys:
        ``company``, ``title``, ``start_date``, ``end_date``,
        ``is_current``, ``description``, ``location``.
    education:
        List of raw education dicts with keys:
        ``institution``, ``degree``, ``field``, ``start_date``,
        ``end_date``, ``gpa``.
    certifications:
        Raw certification / award strings.
    projects:
        List of raw project dicts with keys:
        ``name``, ``description``, ``url``, ``technologies``.
    github_url:
        Full GitHub profile URL.
    github_username:
        GitHub login (username) extracted from the source.
    linkedin_url:
        Full LinkedIn profile URL.
    website:
        Personal or portfolio website URL.
    other_links:
        Any additional URLs keyed by platform / label.
    github_stars:
        Total public stars across GitHub repositories.
    github_repos:
        Total public repository count.
    primary_language:
        Most-used programming language (GitHub source only).
    provenance:
        One :class:`Provenance` entry per successfully mapped field.
    mapped_fields:
        Canonical field names that were populated by this mapper.
    ignored_fields:
        Raw field names that were recognised but intentionally skipped
        (e.g. internal ATS IDs).
    unknown_fields:
        Raw field names that could not be mapped to any canonical field.
    mapping_metadata:
        Mapper-specific metadata (e.g. ATS schema variant, resume section
        detection hits, delimiter used).
    mapped_at:
        UTC datetime when mapping completed.
    """

    # ── Mutable — built incrementally by mapper ────────────────
    model_config = ConfigDict(frozen=False)

    # Identity
    canonical_id: str = Field(
        default_factory=_new_uuid,
        description="System-generated UUID4 for this canonical record.",
    )
    source_record_id: str = Field(
        description="RawRecord.record_id this was produced from."
    )
    source_type: SourceType = Field(
        description="SourceType of the originating RawRecord."
    )
    source_label: str = Field(
        description="Human-readable source label for log messages."
    )

    # Core scalar fields
    full_name: str | None = Field(default=None, description="Candidate full name.")
    first_name: str | None = Field(default=None, description="First name.")
    last_name: str | None = Field(default=None, description="Last name.")
    emails: list[str] = Field(default_factory=list, description="Email addresses.")
    phones: list[str] = Field(default_factory=list, description="Phone numbers.")
    location: str | None = Field(default=None, description="Location string.")
    headline: str | None = Field(default=None, description="Professional headline.")
    summary: str | None = Field(default=None, description="Free-text bio / summary.")
    current_company: str | None = Field(default=None, description="Current employer.")
    current_title: str | None = Field(default=None, description="Current job title.")
    years_of_experience: float | None = Field(
        default=None, description="Estimated total years of experience."
    )

    # Structured lists
    skills: list[str] = Field(
        default_factory=list,
        description="Raw skill strings — not yet normalised.",
    )
    experience: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Raw experience entries.",
    )
    education: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Raw education entries.",
    )
    certifications: list[str] = Field(
        default_factory=list,
        description="Raw certification strings.",
    )
    projects: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Raw project entries.",
    )

    # Online presence
    github_url: str | None = Field(default=None, description="GitHub profile URL.")
    github_username: str | None = Field(default=None, description="GitHub username.")
    linkedin_url: str | None = Field(default=None, description="LinkedIn profile URL.")
    website: str | None = Field(default=None, description="Personal website URL.")
    other_links: dict[str, str] = Field(
        default_factory=dict,
        description="Additional URLs keyed by platform or label.",
    )

    # GitHub-specific stats
    github_stars: int | None = Field(
        default=None, description="Total stars across public repos."
    )
    github_repos: int | None = Field(
        default=None, description="Public repo count."
    )
    primary_language: str | None = Field(
        default=None, description="Most-used programming language (GitHub only)."
    )

    # Provenance and diagnostics
    provenance: list[Provenance] = Field(
        default_factory=list,
        description="One Provenance entry per successfully mapped field.",
    )
    mapped_fields: list[str] = Field(
        default_factory=list,
        description="Canonical field names populated by this mapper.",
    )
    ignored_fields: list[str] = Field(
        default_factory=list,
        description="Raw field names recognised but intentionally skipped.",
    )
    unknown_fields: list[str] = Field(
        default_factory=list,
        description="Raw field names that could not be mapped.",
    )
    mapping_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Mapper-specific metadata (schema variant, section hits, etc.).",
    )
    mapped_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC datetime when mapping completed.",
    )


class CandidateProfile(BaseModel):
    """
    The fully merged, conflict-resolved canonical candidate profile.

    This is the system's **primary internal artifact** — the single
    ground-truth representation of everything the pipeline knows about
    one unique person.  All upstream heterogeneity collapses here.

    Consumers never receive this object directly.  They receive a
    projected dict shaped to their declared output schema.

    Immutability
    ------------
    ``CandidateProfile`` is frozen after creation.  The merger
    constructs one instance; all downstream stages (confidence scoring,
    projection, validation) treat it as read-only.

    Relationship to Other Models
    ----------------------------
    - Built from one ``CandidateGroup`` by the merge stage.
    - ``provenance`` maps every canonical field to its full
      :class:`Provenance` history.
    - ``quality_metrics`` holds all five quality-axis scores.

    Attributes
    ----------
    candidate_id:
        System-generated UUID stable within one pipeline run.
    full_name:
        Canonical full name (title-cased, whitespace-normalised).
    emails:
        Deduplicated list of lowercase email addresses.
        Primary email is always first.
    phones:
        Deduplicated list of E.164-formatted phone numbers.
        Primary phone is always first.
    location:
        Structured location dict with keys:
        ``city``, ``state``, ``country``, ``country_code``.
    headline:
        Professional headline or one-line summary.
    years_experience:
        Estimated total years of professional experience.
    skills:
        Union-merged, semantically deduplicated skill list.
    experience:
        Deduplicated work history, sorted by start_date descending.
    education:
        Deduplicated educational history, sorted by end_date descending.
    links:
        Deduplicated profile and portfolio links.
    provenance:
        Field-level provenance map.
        Key: canonical field name.
        Value: ordered list of :class:`Provenance` objects.
    quality_metrics:
        Five-axis quality measurement.  ``None`` until the confidence
        scoring stage runs.
    overall_confidence:
        Convenience scalar — mirrors
        ``quality_metrics.overall_confidence``.  ``None`` until scored.
    created_at:
        UTC datetime when this profile was first created by the merger.
    updated_at:
        UTC datetime of the most recent modification.
    """

    model_config = ConfigDict(frozen=True)

    # ── Identity ────────────────────────────────────────────
    candidate_id: str = Field(
        default_factory=_new_uuid,
        description=(
            "System-generated UUID4 stable within one pipeline run. "
            "Use an external stable key (e.g. primary email) for "
            "cross-run deduplication."
        ),
    )

    # ── Core identity fields ────────────────────────────────
    full_name: str | None = Field(
        default=None,
        description=(
            "Canonical full name (title-cased, whitespace-normalised). "
            "Resolved via conflict resolution when sources disagree."
        ),
    )
    emails: list[str] = Field(
        default_factory=list,
        description=(
            "Deduplicated list of lowercase normalised email addresses. "
            "Primary (highest-confidence) email is always first."
        ),
    )
    phones: list[str] = Field(
        default_factory=list,
        description=(
            "Deduplicated list of E.164-formatted phone numbers. "
            "Primary phone is always first."
        ),
    )

    # ── Location ────────────────────────────────────────────
    location: dict[str, str | None] = Field(
        default_factory=lambda: {
            "city": None,
            "state": None,
            "country": None,
            "country_code": None,
        },
        description=(
            "Structured location with keys: city, state, country, country_code. "
            "Decomposed from raw location strings by the location normaliser."
        ),
    )

    # ── Professional summary ────────────────────────────────
    headline: str | None = Field(
        default=None,
        description=(
            "Professional headline or one-line summary "
            "(e.g. 'Senior ML Engineer | PyTorch | Distributed Systems')."
        ),
    )
    years_experience: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Estimated total years of professional experience.  "
            "Computed from experience entries when not explicitly stated."
        ),
    )

    # ── Skills ──────────────────────────────────────────────
    skills: list[Skill] = Field(
        default_factory=list,
        description=(
            "Union-merged, semantically deduplicated skill list.  "
            "Each entry is a typed Skill with ontology, confidence, "
            "and full source attribution."
        ),
    )

    # ── Work history ────────────────────────────────────────
    experience: list[Experience] = Field(
        default_factory=list,
        description=(
            "Deduplicated work history sorted by start_date descending.  "
            "Dedup key: (normalized_company, normalized_title, start_year_month)."
        ),
    )

    # ── Education ───────────────────────────────────────────
    education: list[Education] = Field(
        default_factory=list,
        description=(
            "Deduplicated educational history sorted by end_date descending.  "
            "Dedup key: (normalized_institution, degree, graduation_year)."
        ),
    )

    # ── Links ───────────────────────────────────────────────
    links: list[CandidateLink] = Field(
        default_factory=list,
        description=(
            "Deduplicated profile and portfolio links.  "
            "Verified links (from authoritative APIs) appear first."
        ),
    )

    # ── Provenance ──────────────────────────────────────────
    provenance: dict[str, list[Provenance]] = Field(
        default_factory=dict,
        description=(
            "Field-level provenance map.  "
            "Key: canonical field name.  "
            "Value: list of Provenance objects in chronological order "
            "(oldest first, newest last)."
        ),
    )

    # ── Quality ─────────────────────────────────────────────
    quality_metrics: QualityMetrics | None = Field(
        default=None,
        description=(
            "Five-axis quality measurement: overall_confidence, completeness, "
            "consistency, agreement, freshness.  Populated by the confidence "
            "scoring stage; None until that stage runs."
        ),
    )
    overall_confidence: ConfidenceScore | None = Field(
        default=None,
        description=(
            "Convenience scalar mirroring quality_metrics.overall_confidence.  "
            "None until the confidence scoring stage runs."
        ),
    )

    # ── Timestamps ──────────────────────────────────────────
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC datetime when this profile was first created by the merger.",
    )
    updated_at: datetime = Field(
        default_factory=_utc_now,
        description=(
            "UTC datetime of the most recent modification.  "
            "Updated by the confidence scoring stage and any post-merge stages."
        ),
    )

    @model_validator(mode="after")
    def overall_confidence_matches_quality_metrics(self) -> "CandidateProfile":
        """
        Validate that ``overall_confidence`` is consistent with
        ``quality_metrics.overall_confidence`` when both are set.

        Raises
        ------
        ValueError
            If both fields are set but differ by more than 1e-6.
        """
        if (
            self.overall_confidence is not None
            and self.quality_metrics is not None
        ):
            delta = abs(
                self.overall_confidence - self.quality_metrics.overall_confidence
            )
            if delta > 1e-6:
                raise ValueError(
                    f"overall_confidence ({self.overall_confidence}) must match "
                    f"quality_metrics.overall_confidence "
                    f"({self.quality_metrics.overall_confidence}). "
                    f"Delta: {delta:.10f}"
                )
        return self
