"""
src/normalization/factory.py
=============================

Factory for building pre-configured :class:`~src.normalization.pipeline.NormalizationPipeline`
instances.

Default Pipeline Order
----------------------
1. :class:`~src.normalization.email_normalizer.EmailNormalizer`
2. :class:`~src.normalization.name_normalizer.NameNormalizer`
3. :class:`~src.normalization.country_normalizer.CountryNormalizer`
4. :class:`~src.normalization.location_normalizer.LocationNormalizer`
5. :class:`~src.normalization.phone_normalizer.PhoneNormalizer`
6. :class:`~src.normalization.url_normalizer.UrlNormalizer`
7. :class:`~src.normalization.company_normalizer.CompanyNormalizer`
8. :class:`~src.normalization.date_normalizer.DateNormalizer`
9. :class:`~src.normalization.skill_normalizer.SkillNormalizer`

Country must run before Phone (region inference) and Location
(country code lookup).

Usage
-----
::

    from src.normalization.factory import NormalizerFactory

    # Default pipeline
    pipeline = NormalizerFactory.build_default_pipeline()

    # With config
    pipeline = NormalizerFactory.build_default_pipeline(config={
        "pipeline": {"disabled": ["SkillNormalizer"]},
        "SkillNormalizer": {"use_sbert": False},
        "PhoneNormalizer": {"default_region": "IN"},
    })
"""

from __future__ import annotations

from typing import Any

from src.normalization.company_normalizer import CompanyNormalizer
from src.normalization.country_normalizer import CountryNormalizer
from src.normalization.date_normalizer import DateNormalizer
from src.normalization.email_normalizer import EmailNormalizer
from src.normalization.location_normalizer import LocationNormalizer
from src.normalization.name_normalizer import NameNormalizer
from src.normalization.phone_normalizer import PhoneNormalizer
from src.normalization.pipeline import NormalizationPipeline
from src.normalization.skill_normalizer import SkillNormalizer
from src.normalization.url_normalizer import UrlNormalizer

# Canonical normalizer name → class mapping (for runtime lookup)
_NORMALIZER_REGISTRY: dict[str, type] = {
    "EmailNormalizer":    EmailNormalizer,
    "NameNormalizer":     NameNormalizer,
    "CountryNormalizer":  CountryNormalizer,
    "LocationNormalizer": LocationNormalizer,
    "PhoneNormalizer":    PhoneNormalizer,
    "UrlNormalizer":      UrlNormalizer,
    "CompanyNormalizer":  CompanyNormalizer,
    "DateNormalizer":     DateNormalizer,
    "SkillNormalizer":    SkillNormalizer,
}

# Default execution order (must respect dependency constraints)
_DEFAULT_ORDER: list[str] = [
    "EmailNormalizer",
    "NameNormalizer",
    "CountryNormalizer",    # sets country_code before Phone + Location
    "LocationNormalizer",
    "PhoneNormalizer",
    "UrlNormalizer",
    "CompanyNormalizer",
    "DateNormalizer",
    "SkillNormalizer",
]


class NormalizerFactory:
    """
    Factory that constructs :class:`~src.normalization.pipeline.NormalizationPipeline`
    instances.

    All methods are class-methods — no instantiation needed.
    """

    @classmethod
    def build_default_pipeline(
        cls,
        config: dict[str, Any] | None = None,
    ) -> NormalizationPipeline:
        """
        Build the default pipeline with all normalizers in dependency order.

        Parameters
        ----------
        config:
            Optional configuration dict.  Keys:

            - ``"pipeline"`` — pipeline-level config (``disabled``, etc.)
            - ``"<NormalizerName>"`` — per-normalizer config dict

            Example::

                config = {
                    "pipeline":          {"disabled": ["SkillNormalizer"]},
                    "SkillNormalizer":   {"use_sbert": False, "fuzzy_threshold": 0.85},
                    "PhoneNormalizer":   {"default_region": "IN"},
                    "EmailNormalizer":   {"drop_invalid": True},
                }

        Returns
        -------
        NormalizationPipeline
            Fully-configured pipeline ready to call ``.run(record)``.
        """
        config = config or {}
        pipeline_cfg = config.get("pipeline", {})
        pipeline = NormalizationPipeline(config=pipeline_cfg)

        for name in _DEFAULT_ORDER:
            normalizer_cls = _NORMALIZER_REGISTRY[name]
            normalizer_cfg = config.get(name, {})
            pipeline.add(normalizer_cls(config=normalizer_cfg))

        return pipeline

    @classmethod
    def build_custom_pipeline(
        cls,
        normalizer_names: list[str],
        config: dict[str, Any] | None = None,
    ) -> NormalizationPipeline:
        """
        Build a pipeline with a custom ordered subset of normalizers.

        Parameters
        ----------
        normalizer_names:
            Ordered list of normalizer class names to include.
            Must be keys in :data:`_NORMALIZER_REGISTRY`.
        config:
            Optional per-normalizer configuration dict.

        Returns
        -------
        NormalizationPipeline
            Custom pipeline.

        Raises
        ------
        ValueError
            When an unknown normalizer name is specified.
        """
        config = config or {}
        pipeline_cfg = config.get("pipeline", {})
        pipeline = NormalizationPipeline(config=pipeline_cfg)

        for name in normalizer_names:
            if name not in _NORMALIZER_REGISTRY:
                raise ValueError(
                    f"Unknown normalizer: {name!r}. "
                    f"Valid names: {sorted(_NORMALIZER_REGISTRY)}"
                )
            normalizer_cls = _NORMALIZER_REGISTRY[name]
            normalizer_cfg = config.get(name, {})
            pipeline.add(normalizer_cls(config=normalizer_cfg))

        return pipeline

    @classmethod
    def available_normalizers(cls) -> list[str]:
        """Return the names of all registered normalizers."""
        return list(_NORMALIZER_REGISTRY.keys())

    @classmethod
    def default_order(cls) -> list[str]:
        """Return the default normalizer execution order."""
        return list(_DEFAULT_ORDER)
