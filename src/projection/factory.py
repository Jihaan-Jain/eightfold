"""
src/projection/factory.py
==========================

Factory for building configured :class:`~src.projection.projector.Projector`
instances.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.projection.config_resolver import ConfigResolver, ProjectionConfig
from src.projection.projector import Projector


class ProjectorFactory:
    """Factory for :class:`~src.projection.projector.Projector` instances."""

    @classmethod
    def build(
        cls,
        config_path: str | Path | None = None,
        config_dict: dict[str, Any] | None = None,
    ) -> Projector:
        """
        Build a :class:`~src.projection.projector.Projector`.

        Parameters
        ----------
        config_path:
            Path to a YAML/JSON projection config file.
        config_dict:
            Raw config dict (takes precedence over ``config_path``).

        Returns
        -------
        Projector
        """
        if config_dict is not None:
            cfg = ConfigResolver.from_dict(config_dict)
        else:
            cfg = ConfigResolver(config_path).resolve()
        return Projector(cfg)

    @classmethod
    def build_pass_through(cls) -> Projector:
        """Build a projector that passes all fields through unchanged."""
        return Projector(ProjectionConfig.default())

    @classmethod
    def build_minimal(cls) -> Projector:
        """Build a projector with only essential fields."""
        return cls.build(config_dict={
            "include_confidence":      True,
            "include_provenance":      False,
            "include_quality_metrics": False,
            "missing_field_strategy":  "omit",
            "fields": [
                {"source": "candidate_id",    "output": "id"},
                {"source": "full_name",        "output": "name"},
                {"source": "emails",           "output": "email",  "transform": "first"},
                {"source": "phones",           "output": "phone",  "transform": "first"},
                {"source": "location.city",    "output": "city"},
                {"source": "location.country", "output": "country"},
                {"source": "headline",         "output": "headline"},
                {"source": "years_experience", "output": "years_exp"},
                {"source": "skills",           "output": "skills",
                 "array_path": "normalized_name"},
                {"source": "overall_confidence", "output": "confidence"},
            ],
        })
