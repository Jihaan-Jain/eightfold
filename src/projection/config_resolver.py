"""
src/projection/config_resolver.py
===================================

Reads and resolves projection configuration from YAML or JSON files.

Config Schema
-------------
::

    version: "1.0"
    include_confidence: false
    include_provenance: false
    include_quality_metrics: true
    missing_field_strategy: "omit"   # omit | null | error | default

    fields:
      - source: "full_name"
        output: "name"              # rename
        transform: "title"          # optional transform

      - source: "emails"
        output: "primary_email"
        transform: "first"          # take first element

      - source: "skills"
        output: "skill_names"
        array_path: "normalized_name"  # extract from each item

      - source: "location.city"    # nested path
        output: "city"

      - source: "years_experience"
        output: "years_exp"
        default: 0                  # default when null

      - source: "overall_confidence"
        output: "confidence_score"
        condition: "include_confidence == true"  # conditional

      - source: "experience"
        output: "work_history"
        flatten: true               # include all fields of each dict

    drop:
      - "candidate_id"              # always drop these
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.logging_config import get_logger

_log = get_logger(__name__)

# ── Default projection config (pass-through with quality metrics) ──

_DEFAULT_CONFIG: dict[str, Any] = {
    "version": "1.0",
    "include_confidence": True,
    "include_provenance": False,
    "include_quality_metrics": True,
    "missing_field_strategy": "omit",
    "fields": [],
    "drop": [],
}

_DEFAULT_PASS_THROUGH_FIELDS: list[str] = [
    "candidate_id", "full_name", "emails", "phones",
    "location", "headline", "years_experience", "skills",
    "experience", "education", "links",
    "overall_confidence", "quality_metrics",
]


class ProjectionConfig:
    """
    Resolved projection configuration.

    Attributes
    ----------
    include_confidence:
        Include per-field confidence values in output.
    include_provenance:
        Include the full provenance map in output.
    include_quality_metrics:
        Include the five-axis QualityMetrics in output.
    missing_field_strategy:
        How to handle missing fields: ``"omit"``, ``"null"``,
        ``"error"``, ``"default"``.
    fields:
        List of field projection specs.
    drop:
        Field names to always exclude from output.
    pass_through:
        When ``True`` and ``fields`` is empty, include all
        profile fields as-is.
    """

    def __init__(self, raw: dict[str, Any]) -> None:
        self.include_confidence:      bool = bool(raw.get("include_confidence", True))
        self.include_provenance:      bool = bool(raw.get("include_provenance", False))
        self.include_quality_metrics: bool = bool(raw.get("include_quality_metrics", True))
        self.missing_field_strategy:  str  = raw.get("missing_field_strategy", "omit")
        self.fields:  list[dict[str, Any]] = raw.get("fields", [])
        self.drop:    list[str]            = raw.get("drop", [])
        self.pass_through: bool            = len(self.fields) == 0

    @classmethod
    def default(cls) -> "ProjectionConfig":
        """Return a default pass-through config."""
        return cls(_DEFAULT_CONFIG)


class ConfigResolver:
    """
    Loads :class:`ProjectionConfig` from a YAML/JSON file or dict.

    Parameters
    ----------
    config_path:
        Path to a ``*.yaml`` or ``*.json`` config file.
        When ``None``, the default pass-through config is used.
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._path = Path(config_path) if config_path else None

    def resolve(self) -> ProjectionConfig:
        """
        Load and validate the projection config.

        Returns
        -------
        ProjectionConfig
        """
        if self._path is None:
            return ProjectionConfig.default()

        if not self._path.exists():
            _log.warning(
                "Projection config not found — using defaults",
                extra={"path": str(self._path)},
            )
            return ProjectionConfig.default()

        raw = self._load_file(self._path)
        self._validate(raw)
        cfg = ProjectionConfig(raw)
        _log.info(
            "Projection config loaded",
            extra={
                "path":   str(self._path),
                "fields": len(cfg.fields),
                "drop":   len(cfg.drop),
            },
        )
        return cfg

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ProjectionConfig:
        """Instantiate directly from a dict (for testing)."""
        return ProjectionConfig(raw)

    # ── Private ───────────────────────────────────────────────

    def _load_file(self, path: Path) -> dict[str, Any]:
        suffix = path.suffix.lower()
        content = path.read_text(encoding="utf-8")
        if suffix in (".yaml", ".yml"):
            try:
                import yaml
                return yaml.safe_load(content) or {}
            except ImportError:
                _log.warning("PyYAML not installed — treating YAML as JSON")
        if suffix in (".json", ".yaml", ".yml"):
            try:
                return json.loads(content)
            except json.JSONDecodeError as exc:
                _log.error(
                    "Config parse error",
                    extra={"path": str(path), "error": str(exc)},
                )
                return {}
        return {}

    def _validate(self, raw: dict[str, Any]) -> None:
        """Warn on unknown top-level keys."""
        known = {
            "version", "include_confidence", "include_provenance",
            "include_quality_metrics", "missing_field_strategy",
            "fields", "drop",
        }
        for key in raw:
            if key not in known:
                _log.warning(
                    "Unknown projection config key",
                    extra={"key": key},
                )
