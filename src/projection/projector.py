"""
src/projection/projector.py
=============================

Transforms a :class:`~src.models.CandidateProfile` into a consumer-facing
output dict using a :class:`~src.projection.config_resolver.ProjectionConfig`.

Pipeline
--------
::

    CandidateProfile
        │
        ▼  model_to_dict
    profile_dict
        │
        ▼  pass-through OR field-by-field specs
    raw_output
        │
        ▼  drop listed fields
        │  strip provenance (unless include_provenance=True)
        │  strip quality_metrics (unless include_quality_metrics=True)
        │  strip confidence (unless include_confidence=True)
        ▼
    projected_dict
"""

from __future__ import annotations

from typing import Any

from src.logging_config import get_logger
from src.models import CandidateProfile
from src.projection.config_resolver import ProjectionConfig
from src.projection.field_selector import FieldSelector
from src.projection.utils import model_to_dict

_log = get_logger(__name__)

# Fields excluded from the default pass-through when their config flag is off
_CONFIDENCE_FIELDS    = {"overall_confidence"}
_PROVENANCE_FIELDS    = {"provenance"}
_QUALITY_FIELDS       = {"quality_metrics"}


class Projector:
    """
    Projects a :class:`~src.models.CandidateProfile` to a plain dict
    suitable for JSON serialisation.

    Parameters
    ----------
    config:
        Resolved :class:`~src.projection.config_resolver.ProjectionConfig`.
    """

    def __init__(self, config: ProjectionConfig) -> None:
        self._config = config
        self._selectors: list[FieldSelector] = [
            FieldSelector(spec) for spec in config.fields
        ]

    # ── Public API ────────────────────────────────────────────

    def project(self, profile: CandidateProfile) -> dict[str, Any]:
        """
        Project one :class:`~src.models.CandidateProfile` to a plain dict.

        Parameters
        ----------
        profile:
            Fully merged and confidence-scored profile.

        Returns
        -------
        dict[str, Any]
            Consumer-facing output dictionary.
        """
        # Serialise to plain dict (handles nested Pydantic models)
        profile_dict = model_to_dict(profile.model_dump())

        if self._config.pass_through:
            output = self._pass_through(profile_dict)
        else:
            output = self._apply_specs(profile_dict)

        # Apply drop list
        for key in self._config.drop:
            output.pop(key, None)

        # Apply flag-based suppression
        if not self._config.include_confidence:
            for k in list(_CONFIDENCE_FIELDS):
                output.pop(k, None)

        if not self._config.include_provenance:
            for k in list(_PROVENANCE_FIELDS):
                output.pop(k, None)

        if not self._config.include_quality_metrics:
            for k in list(_QUALITY_FIELDS):
                output.pop(k, None)

        return output

    def project_many(
        self, profiles: list[CandidateProfile]
    ) -> list[dict[str, Any]]:
        """Project a batch of profiles."""
        return [self.project(p) for p in profiles]

    # ── Private ───────────────────────────────────────────────

    def _pass_through(self, profile_dict: dict[str, Any]) -> dict[str, Any]:
        """
        Default mode: include all fields from the profile dict.

        Skips internal/None fields based on config flags.
        """
        output: dict[str, Any] = {}
        strategy = self._config.missing_field_strategy

        for key, value in profile_dict.items():
            # Skip None/empty unless strategy = null
            if (value is None or value == [] or value == {}) and strategy == "omit":
                continue
            output[key] = value

        return output

    def _apply_specs(self, profile_dict: dict[str, Any]) -> dict[str, Any]:
        """Apply explicit field projection specs."""
        output: dict[str, Any] = {}
        strategy = self._config.missing_field_strategy

        for selector in self._selectors:
            try:
                out_key, value, include = selector.apply(profile_dict, strategy)
                if include:
                    output[out_key] = value
                elif strategy == "null" and value is None:
                    output[out_key] = None
            except Exception as exc:
                _log.warning(
                    "Field selector error",
                    extra={
                        "field": selector.source_key,
                        "error": str(exc),
                    },
                )

        return output
