"""
src/mapping/__init__.py
========================

Public API for the mapping layer.

The mapping layer converts a :class:`~src.models.RawRecord` (raw bytes
from an extractor) into a :class:`~src.models.CanonicalRecord`
(canonical field names, structured values, per-field provenance).

Quick start
-----------
::

    from src.mapping import MapperFactory

    factory = MapperFactory()
    canonical = factory.map(raw_record)         # single record
    results   = factory.map_many(raw_records)   # batch

Alternatively, use a specific mapper directly::

    from src.mapping import CsvMapper, ATSMapper, GithubMapper, ResumePdfMapper

    mapper    = CsvMapper()
    canonical = mapper.map(record)

Or query the field registry::

    from src.mapping import REGISTRY

    canonical_name = REGISTRY.resolve("First Name")   # "first_name"
    field_def      = REGISTRY.get("emails")
"""

from src.mapping.ats_mapper import ATSMapper
from src.mapping.base import BaseMapper
from src.mapping.csv_mapper import CsvMapper
from src.mapping.factory import MapperFactory
from src.mapping.field_registry import REGISTRY, FieldDefinition, FieldRegistry
from src.mapping.github_mapper import GithubMapper
from src.mapping.resume_mapper import ResumePdfMapper
from src.mapping.utils import (
    classify_url,
    clean_str,
    flatten_dict,
    make_provenance,
    parse_skill_list,
    safe_get,
    set_field,
    split_name,
)

__all__ = [
    # Mappers
    "BaseMapper",
    "CsvMapper",
    "ATSMapper",
    "GithubMapper",
    "ResumePdfMapper",
    # Factory
    "MapperFactory",
    # Registry
    "REGISTRY",
    "FieldRegistry",
    "FieldDefinition",
    # Utilities
    "safe_get",
    "flatten_dict",
    "clean_str",
    "split_name",
    "parse_skill_list",
    "classify_url",
    "make_provenance",
    "set_field",
]
