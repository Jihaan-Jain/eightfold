"""
src/mapping/csv_mapper.py
==========================

Mapper for recruiter CSV exports.

Handles multiple CSV export schemas from different recruiters — the
field registry drives alias resolution so no schema needs hardcoding.

Mapping Strategy
----------------
1. For every raw field in ``RawRecord.raw_fields``:
   a. Query the registry for a canonical name.
   b. If found → map to :class:`~src.models.CanonicalRecord` with
      :data:`~src.models.MappingMethod.ALIAS` or
      :data:`~src.models.MappingMethod.DIRECT` provenance.
   c. If not found → record as unknown (warning logged).
2. After iterating all fields:
   - If ``first_name`` and ``last_name`` are mapped but ``full_name``
     is not → infer ``full_name`` by concatenation.
   - If ``full_name`` is mapped but ``first_name`` / ``last_name``
     are not → infer them via :func:`~src.mapping.utils.split_name`.
   - Classify any URL fields (GitHub, LinkedIn, Website).

Known CSV Field Aliases (handled via registry)
-----------------------------------------------
Name variants:
  Name, Full Name, Candidate Name, First Name, Last Name

Contact:
  Email, Email Address, Phone, Mobile, Cell

Company / Role:
  Company, Current Company, Employer, Job Title, Position

Skills:
  Skills, Skill Set, Technologies, Tech Stack

Online:
  Github, LinkedIn, Website, URL, Blog
"""

from __future__ import annotations

from typing import Any

from src.mapping.base import BaseMapper
from src.mapping.utils import (
    classify_url,
    clean_str,
    make_provenance,
    parse_skill_list,
    set_field,
    split_name,
)
from src.models import (
    CanonicalRecord,
    MappingMethod,
    RawRecord,
    SourceType,
)


# Fields intentionally skipped (internal recruiter IDs, etc.)
_IGNORED_FIELDS: frozenset[str] = frozenset(
    {
        "id", "candidate id", "candidate_id", "applicant id",
        "applicant_id", "record id", "record_id", "row id", "row_id",
        "internal id", "internal_id", "ats id", "ats_id",
        "created at", "created_at", "updated at", "updated_at",
        "modified at", "modified_at", "stage", "pipeline stage",
        "recruiter", "recruiter name", "recruiter_name", "owner",
        "source", "source name", "source_name", "referral",
        "rejection reason", "rejection_reason", "status", "notes",
    }
)


class CsvMapper(BaseMapper):
    """
    Maps a CSV-sourced :class:`~src.models.RawRecord` to a
    :class:`~src.models.CanonicalRecord`.

    Supports any recruiter CSV export format because all field
    resolution is driven by the :class:`~src.mapping.field_registry.FieldRegistry`.

    Config Keys
    -----------
    ``ignored_fields`` (list[str])
        Additional raw field names to silently skip.
    """

    @property
    def source_type(self) -> SourceType:
        return SourceType.CSV

    def supports(self, record: RawRecord) -> bool:
        return record.source_type == SourceType.CSV

    def metadata(self) -> dict[str, Any]:
        return {
            "mapper":        self.__class__.__name__,
            "source_type":   self.source_type.value,
            "version":       "1.0.0",
            "field_registry_size": len(self._registry),
        }

    def map(self, record: RawRecord) -> CanonicalRecord:
        """Map a CSV RawRecord to a CanonicalRecord."""
        return self._timed_map(record, self._do_map)

    # ── Internal implementation ───────────────────────────────

    def _do_map(self, record: RawRecord) -> CanonicalRecord:
        canonical = self._make_canonical(record)
        canonical.mapping_metadata["mapper"] = "CsvMapper"
        canonical.mapping_metadata["source"] = record.source

        extra_ignored = {
            s.lower() for s in self._config.get("ignored_fields", [])
        }

        for raw_key, raw_value in record.raw_fields.items():
            low_key = raw_key.strip().lower()

            # ── Skip known-internal fields ────────────────────
            if low_key in _IGNORED_FIELDS or low_key in extra_ignored:
                self._record_ignored(canonical, raw_key)
                continue

            # ── Resolve via registry ──────────────────────────
            canon_name = self._registry.resolve(raw_key)
            if canon_name is None:
                self._record_unknown(canonical, raw_key)
                continue

            value = clean_str(raw_value)
            if value is None:
                continue  # empty cell — skip

            # Determine method: DIRECT when raw == canonical
            method = (
                MappingMethod.DIRECT
                if low_key == canon_name
                else MappingMethod.ALIAS
            )

            self._apply(canonical, canon_name, raw_key, value, method, record)

        # ── Post-processing inferences ────────────────────────
        self._infer_names(canonical, record)
        self._infer_links(canonical, record)

        return canonical

    def _apply(
        self,
        canonical: CanonicalRecord,
        canon_name: str,
        raw_key: str,
        raw_value: Any,
        method: MappingMethod,
        record: RawRecord,
    ) -> None:
        """Map one raw field to its canonical field on the record."""
        # Skills require special parsing
        if canon_name == "skills":
            skill_list = parse_skill_list(raw_value)
            if skill_list:
                prov = make_provenance(
                    field=canon_name,
                    source=record.source_type,
                    method=method,
                    original_value=raw_value,
                    mapped_value=skill_list,
                    raw_field_name=raw_key,
                )
                set_field(canonical, canon_name, skill_list, prov)
            return

        # URL fields: classify and route
        if canon_name in ("github_url", "linkedin_url", "website"):
            platform, url = classify_url(raw_value)
            actual_canon = {
                "github":   "github_url",
                "linkedin": "linkedin_url",
                "website":  "website",
            }.get(platform, "website")
            prov = make_provenance(
                field=actual_canon,
                source=record.source_type,
                method=method,
                original_value=raw_value,
                mapped_value=url,
                raw_field_name=raw_key,
            )
            set_field(canonical, actual_canon, url, prov)
            return

        # Default scalar set
        prov = make_provenance(
            field=canon_name,
            source=record.source_type,
            method=method,
            original_value=raw_value,
            mapped_value=raw_value,
            raw_field_name=raw_key,
        )
        set_field(canonical, canon_name, raw_value, prov)

    def _infer_names(
        self,
        canonical: CanonicalRecord,
        record: RawRecord,
    ) -> None:
        """
        Infer ``full_name`` from first+last, or split full into parts.
        """
        has_full  = canonical.full_name is not None
        has_first = canonical.first_name is not None
        has_last  = canonical.last_name is not None

        if has_first and has_last and not has_full:
            inferred = f"{canonical.first_name} {canonical.last_name}"
            prov = make_provenance(
                field="full_name",
                source=record.source_type,
                method=MappingMethod.INFERRED,
                original_value=f"{canonical.first_name} + {canonical.last_name}",
                mapped_value=inferred,
                confidence=0.9,
            )
            set_field(canonical, "full_name", inferred, prov)

        elif has_full and not has_first and not has_last:
            first, last = split_name(canonical.full_name)
            if first:
                prov = make_provenance(
                    field="first_name",
                    source=record.source_type,
                    method=MappingMethod.INFERRED,
                    original_value=canonical.full_name,
                    mapped_value=first,
                    confidence=0.9,
                )
                set_field(canonical, "first_name", first, prov)
            if last:
                prov = make_provenance(
                    field="last_name",
                    source=record.source_type,
                    method=MappingMethod.INFERRED,
                    original_value=canonical.full_name,
                    mapped_value=last,
                    confidence=0.9,
                )
                set_field(canonical, "last_name", last, prov)

    def _infer_links(
        self,
        canonical: CanonicalRecord,
        record: RawRecord,
    ) -> None:
        """
        Extract GitHub username from github_url if not already set.
        """
        if canonical.github_url and not canonical.github_username:
            from src.mapping.utils import _GITHUB_URL_RE
            m = _GITHUB_URL_RE.search(canonical.github_url)
            if m:
                username = m.group(1)
                prov = make_provenance(
                    field="github_username",
                    source=record.source_type,
                    method=MappingMethod.INFERRED,
                    original_value=canonical.github_url,
                    mapped_value=username,
                    confidence=0.95,
                )
                set_field(canonical, "github_username", username, prov)
