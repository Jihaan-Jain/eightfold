"""
exceptions.py
=============

Custom domain exception hierarchy for the Candidate Data Transformer.

Design Principles
-----------------
- **Single root** — every exception inherits from
  :class:`CandidateTransformerError` so callers can catch the entire
  domain with one ``except`` clause.
- **Structured context** — each subclass carries typed fields
  (``stage``, ``source_type``, ``record_id``, etc.) so log aggregators
  can group failures without parsing message strings.
- **Fail-fast** — :class:`ConfigurationError` is designed to be raised
  at startup, before any extraction begins.
- **Recoverable vs fatal** — extraction / mapping errors are
  *per-source* (the pipeline continues); merge / projection errors are
  *per-candidate* (that candidate goes to the error log).

Hierarchy
---------
::

    CandidateTransformerError
    ├── ConfigurationError
    ├── ExtractionError
    ├── MappingError
    ├── NormalizationError
    ├── IdentityResolutionError
    ├── MergeError
    ├── ProjectionError
    └── ValidationError
"""

from __future__ import annotations

from typing import Any


# ================================================================
# Base Exception
# ================================================================


class CandidateTransformerError(Exception):
    """
    Root of the candidate-transformer exception hierarchy.

    All pipeline components raise subclasses of this exception so
    callers can implement a single top-level handler::

        try:
            pipeline.run(sources)
        except CandidateTransformerError as exc:
            log.error(
                "pipeline failure",
                stage=exc.stage,
                details=exc.details,
                error=str(exc),
            )

    Parameters
    ----------
    message:
        Human-readable description of the failure.
    stage:
        Pipeline stage where the error originated.  Use the
        ``STAGE_*`` constants from :mod:`src.constants` for
        consistency with provenance records and log context.
    details:
        Free-form dict of structured context (source type, record id,
        field name, raw value, etc.) for log aggregation.

    Attributes
    ----------
    message:
        The original message string (same as ``str(exc)``).
    stage:
        The pipeline stage name, or ``None`` if not applicable.
    details:
        Structured context dictionary.  Always a ``dict`` — never
        ``None`` — so callers can safely do ``exc.details.get(...)``.
    """

    def __init__(
        self,
        message: str,
        stage: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.stage: str | None = stage
        self.details: dict[str, Any] = details or {}

    def __repr__(self) -> str:
        """Return a developer-friendly string showing all fields."""
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"stage={self.stage!r}, "
            f"details={self.details!r})"
        )


# ================================================================
# ConfigurationError
# ================================================================


class ConfigurationError(CandidateTransformerError):
    """
    Raised when the application configuration is missing, malformed,
    or logically inconsistent.

    This exception is **always fatal** — it is raised at startup before
    any source extraction begins so that bad configuration is caught
    immediately rather than mid-run.

    Common causes
    -------------
    - Required YAML key is absent
    - Output schema references a canonical field that does not exist
    - Identity signal weights do not sum to 1.0
    - YAML file has a syntax error
    - ``log_level`` is not a recognised severity string
    - ``review_threshold >= match_threshold`` in identity config

    Parameters
    ----------
    message:
        Description of what is wrong with the configuration.
    config_path:
        Filesystem path to the offending configuration file.
    invalid_key:
        The specific YAML key or field name that triggered the error.

    Examples
    --------
    ::

        raise ConfigurationError(
            "Identity signal weights sum to 1.10 instead of 1.0.",
            config_path="configs/default_config.yaml",
            invalid_key="identity_resolution.email_weight",
        )
    """

    def __init__(
        self,
        message: str,
        config_path: str | None = None,
        invalid_key: str | None = None,
    ) -> None:
        super().__init__(
            message,
            stage="configuration",
            details={
                "config_path": config_path,
                "invalid_key": invalid_key,
            },
        )
        self.config_path: str | None = config_path
        self.invalid_key: str | None = invalid_key


# ================================================================
# ExtractionError
# ================================================================


class ExtractionError(CandidateTransformerError):
    """
    Raised when a source extractor fails to read or parse its input.

    Extraction errors are **isolated per source** — a failure in the
    PDF extractor must not prevent the CSV or ATS extractors from
    running.  The pipeline logs this error and continues.

    Common causes
    -------------
    - CSV file not found or permission denied
    - ATS JSON is syntactically invalid
    - GitHub API returns 403 (rate limit) or 404 (user not found)
    - PDF is a scanned image with no extractable text layer
    - Network timeout when fetching a remote source

    Parameters
    ----------
    message:
        Description of the extraction failure.
    source_type:
        The source type that failed (``"csv"``, ``"ats"``,
        ``"github"``, ``"resume"``, ``"recruiter_notes"``).
    source_path:
        File path or API endpoint URL that caused the failure.
    record_id:
        Identifier of the specific record that could not be extracted,
        if it is available at the point of failure.

    Examples
    --------
    ::

        raise ExtractionError(
            "GitHub API returned 403 Forbidden.",
            source_type="github",
            source_path="https://api.github.com/users/priya-sharma",
            record_id=None,
        )
    """

    def __init__(
        self,
        message: str,
        source_type: str | None = None,
        source_path: str | None = None,
        record_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            stage="extraction",
            details={
                "source_type": source_type,
                "source_path": source_path,
                "record_id": record_id,
            },
        )
        self.source_type: str | None = source_type
        self.source_path: str | None = source_path
        self.record_id: str | None = record_id


# ================================================================
# MappingError
# ================================================================


class MappingError(CandidateTransformerError):
    """
    Raised when a source mapper cannot translate a raw field name to
    its canonical equivalent.

    Mapping errors surface **schema drift** — the upstream source
    changed a field name without notice.  The pipeline skips the
    offending field, logs this error, and continues mapping the
    remaining fields of the same record.

    Common causes
    -------------
    - ATS system renamed ``"candidateEmail"`` to ``"email_address"``
    - CSV header changed from ``"GitHub"`` to ``"github_profile"``
    - A required field is completely absent from the source schema

    Parameters
    ----------
    message:
        Description of the mapping failure.
    source_type:
        Source type whose mapper raised this error.
    raw_field_name:
        The source-specific field name that could not be mapped.
    record_id:
        The record identifier, if available.

    Examples
    --------
    ::

        raise MappingError(
            "Field 'LinkedInProfileURL' has no canonical mapping for source 'csv'.",
            source_type="csv",
            raw_field_name="LinkedInProfileURL",
            record_id="csv-row-42",
        )
    """

    def __init__(
        self,
        message: str,
        source_type: str | None = None,
        raw_field_name: str | None = None,
        record_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            stage="canonical_mapping",
            details={
                "source_type": source_type,
                "raw_field_name": raw_field_name,
                "record_id": record_id,
            },
        )
        self.source_type: str | None = source_type
        self.raw_field_name: str | None = raw_field_name
        self.record_id: str | None = record_id


# ================================================================
# NormalizationError
# ================================================================


class NormalizationError(CandidateTransformerError):
    """
    Raised when a normaliser fails to transform a field value and the
    failure is unrecoverable.

    Most normalisation failures are *soft* — the raw value is stored
    with a warning and a low confidence score.  This exception is
    reserved for cases where the input is so malformed that even
    storing it would corrupt the canonical model (e.g., a phone field
    containing a 500-character essay).

    Parameters
    ----------
    message:
        Description of the normalisation failure.
    field_name:
        Canonical field name being normalised.
    raw_value:
        The raw value that could not be normalised.  May be truncated
        in the exception message if very long.
    normalizer:
        Name of the normaliser module that raised the error
        (e.g. ``"phone_normalizer"``, ``"date_normalizer"``).
    record_id:
        Source record identifier, for provenance tracing.

    Examples
    --------
    ::

        raise NormalizationError(
            "Date string '32nd of Octember' could not be parsed by any format.",
            field_name="start_date",
            raw_value="32nd of Octember",
            normalizer="date_normalizer",
        )
    """

    def __init__(
        self,
        message: str,
        field_name: str | None = None,
        raw_value: Any = None,
        normalizer: str | None = None,
        record_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            stage="normalization",
            details={
                "field_name": field_name,
                "raw_value": str(raw_value)[:200] if raw_value is not None else None,
                "normalizer": normalizer,
                "record_id": record_id,
            },
        )
        self.field_name: str | None = field_name
        self.raw_value: Any = raw_value
        self.normalizer: str | None = normalizer
        self.record_id: str | None = record_id


# ================================================================
# IdentityResolutionError
# ================================================================


class IdentityResolutionError(CandidateTransformerError):
    """
    Raised when the identity resolver encounters an unrecoverable
    internal error while computing composite scores or building
    candidate clusters.

    **Important:** a *low* identity score is not an error — it simply
    means two records did not match and each forms its own singleton
    group.  This exception signals an *unexpected failure in the
    resolver machinery itself* (e.g., SBERT model not loaded,
    union-find data structure corrupted).

    Parameters
    ----------
    message:
        Description of the identity resolution failure.
    record_ids:
        List of record identifiers involved in the failing comparison.
    strategy:
        The matching strategy that failed
        (e.g. ``"composite_scorer"``, ``"email_exact"``).

    Examples
    --------
    ::

        raise IdentityResolutionError(
            "SBERT model is not loaded; call EmbedderService.load() first.",
            record_ids=["csv-row-1", "ats-row-5"],
            strategy="sbert_name_similarity",
        )
    """

    def __init__(
        self,
        message: str,
        record_ids: list[str] | None = None,
        strategy: str | None = None,
    ) -> None:
        super().__init__(
            message,
            stage="identity_resolution",
            details={
                "record_ids": record_ids or [],
                "strategy": strategy,
            },
        )
        self.record_ids: list[str] = record_ids or []
        self.strategy: str | None = strategy


# ================================================================
# MergeError
# ================================================================


class MergeError(CandidateTransformerError):
    """
    Raised when the merger fails to assemble a
    :class:`~src.models.CandidateProfile` from a resolved candidate
    cluster.

    Common causes
    -------------
    - All records in the group are missing the minimum required fields
    - Conflict resolver exhausts all strategies without selecting a winner
    - An unexpected exception inside a field-level merger sub-routine

    Parameters
    ----------
    message:
        Description of the merge failure.
    group_id:
        Identifier of the candidate cluster that could not be merged.
    record_ids:
        Identifiers of the individual records in the failing group.

    Examples
    --------
    ::

        raise MergeError(
            "All 3 records in group are missing 'full_name'.",
            group_id="grp-abc123",
            record_ids=["csv-row-1", "ats-row-2", "resume-1"],
        )
    """

    def __init__(
        self,
        message: str,
        group_id: str | None = None,
        record_ids: list[str] | None = None,
    ) -> None:
        super().__init__(
            message,
            stage="merge",
            details={
                "group_id": group_id,
                "record_ids": record_ids or [],
            },
        )
        self.group_id: str | None = group_id
        self.record_ids: list[str] = record_ids or []


# ================================================================
# ProjectionError
# ================================================================


class ProjectionError(CandidateTransformerError):
    """
    Raised when the projector cannot apply an output schema to a
    :class:`~src.models.CandidateProfile`.

    Common causes
    -------------
    - Output schema references a canonical field that does not exist
      (should be caught at startup by the config loader, but may
      surface at runtime if the schema was hot-reloaded)
    - A ``transform`` function registered in the schema is not found
      in the projector's transform registry
    - A ``conditional`` expression in the schema raises an exception
      when evaluated against the candidate

    Parameters
    ----------
    message:
        Description of the projection failure.
    schema_name:
        Name of the output schema (from config) that caused the error.
    field_name:
        The specific field operation that failed.
    candidate_id:
        Identifier of the candidate being projected.

    Examples
    --------
    ::

        raise ProjectionError(
            "Transform function 'join_comma_sorted' is not registered.",
            schema_name="recruiter_view",
            field_name="skills",
            candidate_id="cand-001",
        )
    """

    def __init__(
        self,
        message: str,
        schema_name: str | None = None,
        field_name: str | None = None,
        candidate_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            stage="projection",
            details={
                "schema_name": schema_name,
                "field_name": field_name,
                "candidate_id": candidate_id,
            },
        )
        self.schema_name: str | None = schema_name
        self.field_name: str | None = field_name
        self.candidate_id: str | None = candidate_id


# ================================================================
# ValidationError
# ================================================================


class ValidationError(CandidateTransformerError):
    """
    Raised when the validator encounters an **internal error** during
    the validation process itself — not a validation rule failure.

    A candidate that *fails a rule* produces a
    :class:`~src.models.ValidationResult` with ``is_valid=False``.
    This exception is reserved for unexpected failures in the validator
    machinery (e.g., a rule implementation has a bug, a required
    sub-module is not initialised).

    Parameters
    ----------
    message:
        Description of the internal validator failure.
    candidate_id:
        Identifier of the candidate being validated.
    rule_name:
        The validation rule implementation that caused the failure.

    Examples
    --------
    ::

        raise ValidationError(
            "Rule 'graduation_not_future' raised AttributeError: "
            "'NoneType' object has no attribute 'year'.",
            candidate_id="cand-007",
            rule_name="graduation_not_future",
        )
    """

    def __init__(
        self,
        message: str,
        candidate_id: str | None = None,
        rule_name: str | None = None,
    ) -> None:
        super().__init__(
            message,
            stage="validation",
            details={
                "candidate_id": candidate_id,
                "rule_name": rule_name,
            },
        )
        self.candidate_id: str | None = candidate_id
        self.rule_name: str | None = rule_name
