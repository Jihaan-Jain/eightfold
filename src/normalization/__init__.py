"""
src/normalization/__init__.py
==============================

Public API for the normalization layer.

The normalization layer transforms a :class:`~src.models.CanonicalRecord`
(output of the mapping stage) by normalizing each field to a canonical,
machine-comparable form.

Quick start
-----------
::

    from src.normalization import NormalizerFactory

    pipeline = NormalizerFactory.build_default_pipeline()
    normalized = pipeline.run(canonical_record)

    # With configuration:
    pipeline = NormalizerFactory.build_default_pipeline(config={
        "pipeline":        {"disabled": ["SkillNormalizer"]},
        "PhoneNormalizer": {"default_region": "IN"},
    })

    # Standalone field-level functions:
    from src.normalization import normalize_email, normalize_skill

    result = normalize_email("  Alice@EXAMPLE.COM  ")
    result = normalize_skill("py", use_sbert=False)
"""

from src.normalization.base import BaseNormalizer
from src.normalization.company_normalizer import CompanyNormalizer, normalize_company
from src.normalization.country_normalizer import CountryNormalizer, country_to_alpha2, normalize_country
from src.normalization.date_normalizer import DateNormalizer, normalize_date
from src.normalization.email_normalizer import EmailNormalizer, normalize_email
from src.normalization.factory import NormalizerFactory
from src.normalization.location_normalizer import LocationNormalizer, normalize_location
from src.normalization.name_normalizer import NameNormalizer, normalize_name
from src.normalization.phone_normalizer import PhoneNormalizer, normalize_phone
from src.normalization.pipeline import NormalizationPipeline
from src.normalization.skill_normalizer import (
    CANONICAL_SKILLS,
    SkillNormalizationResult,
    SkillNormalizer,
    normalize_skill,
)
from src.normalization.url_normalizer import UrlNormalizer, normalize_url
from src.normalization.utils import (
    NormalizationResult,
    ascii_normalize,
    clean_text,
    deduplicate,
    similarity,
)

__all__ = [
    "BaseNormalizer",
    "EmailNormalizer",
    "PhoneNormalizer",
    "DateNormalizer",
    "CountryNormalizer",
    "LocationNormalizer",
    "UrlNormalizer",
    "NameNormalizer",
    "CompanyNormalizer",
    "SkillNormalizer",
    "NormalizationPipeline",
    "NormalizerFactory",
    "normalize_email",
    "normalize_phone",
    "normalize_date",
    "normalize_country",
    "country_to_alpha2",
    "normalize_location",
    "normalize_url",
    "normalize_name",
    "normalize_company",
    "normalize_skill",
    "CANONICAL_SKILLS",
    "NormalizationResult",
    "SkillNormalizationResult",
    "clean_text",
    "ascii_normalize",
    "deduplicate",
    "similarity",
]
