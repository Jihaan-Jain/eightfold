"""
src/merge/merge_engine.py
==========================

The core merge engine.  Accepts a :class:`~src.merge.identity_resolver.CandidateGroup`
(a cluster of normalised :class:`~src.models.CanonicalRecord` objects)
and produces:

- A merged :class:`~src.models.CandidateProfile`
- A :class:`MergeReport` containing all conflict records, quality metrics,
  and the full provenance map

Merge Field Strategies
----------------------
===================  =========================================================
Field type           Strategy
===================  =========================================================
Scalar strings       Conflict resolution (highest-priority source wins)
List fields          Union + dedup  (emails, phones, skills, certs, projects)
Experience           Union + dedup by (normalized_company, title, start_date)
Education            Union + dedup by (normalized_institution, degree, end_date)
Links                Union + dedup by normalised URL
GitHub stats         Max (stars, repos) — GitHub is most authoritative
===================  =========================================================

MergeReport
-----------
Produced for every merge (even single-record groups).  Contains:
- ``candidate_id``   — matches CandidateProfile.candidate_id
- ``merged_records`` — list of canonical_id strings
- ``source_types``   — unique SourceType values merged
- ``conflicts``      — list of :class:`~src.merge.conflict_resolver.ConflictRecord`
- ``quality_metrics``— :class:`~src.models.QualityMetrics`
- ``merge_strategy`` — effective strategy name
- ``needs_review``   — True when identity resolution was uncertain
- ``merged_at``      — UTC timestamp
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Any

from src.constants import SOURCE_PRIORITY
from src.logging_config import get_logger
from src.models import (
    CandidateLink,
    CandidateProfile,
    CanonicalRecord,
    Education,
    Experience,
    MergeStrategy,
    NormalizationMethod,
    ProcessingStage,
    Provenance,
    QualityMetrics,
    Skill,
    SourceType,
)
from src.merge.conflict_resolver import ConflictRecord, ConflictResolver
from src.merge.confidence_engine import ConfidenceEngine
from src.merge.identity_resolver import CandidateGroup
from src.merge.provenance_aggregator import ProvenanceAggregator
from src.merge.utils import (
    clean_lower,
    deduplicate_strings,
    email_key,
    normalize_key,
    phone_key,
    union_lists,
    url_key,
    github_login_from_url,
    linkedin_handle_from_url,
    experience_sort_key,
    education_sort_key,
)

_log = get_logger(__name__)


# ================================================================
# MergeReport
# ================================================================


@dataclass
class MergeReport:
    """
    Full audit trail for one merge operation.

    This is the ``MergeReport`` model suggested in the screenshot.

    Attributes
    ----------
    candidate_id:
        Matches :attr:`~src.models.CandidateProfile.candidate_id`.
    merged_records:
        ``canonical_id`` values of all source records.
    source_types:
        Unique source type values (e.g. ``["ats", "github"]``).
    conflicts:
        All :class:`~src.merge.conflict_resolver.ConflictRecord` objects
        produced during this merge.
    quality_metrics:
        Five-axis quality score.  ``None`` until confidence engine runs.
    merge_strategy:
        Effective :class:`~src.models.MergeStrategy` name.
    needs_review:
        ``True`` when identity resolution was uncertain.
    merged_at:
        UTC timestamp of merge completion.
    """

    candidate_id:    str
    merged_records:  list[str]  = dc_field(default_factory=list)
    source_types:    list[str]  = dc_field(default_factory=list)
    conflicts:       list[ConflictRecord] = dc_field(default_factory=list)
    quality_metrics: QualityMetrics | None = None
    merge_strategy:  str = MergeStrategy.SOURCE_PRIORITY.value
    needs_review:    bool = False
    merged_at:       datetime = dc_field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict[str, Any]:
        """Return a fully serialisable dictionary for logging / output."""
        return {
            "candidate_id":    self.candidate_id,
            "merged_records":  self.merged_records,
            "source_types":    self.source_types,
            "conflicts":       [c.to_dict() for c in self.conflicts],
            "quality_metrics": (
                self.quality_metrics.model_dump()
                if self.quality_metrics else None
            ),
            "merge_strategy":  self.merge_strategy,
            "needs_review":    self.needs_review,
            "merged_at":       self.merged_at.isoformat(),
            "conflict_count":  len(self.conflicts),
        }


# ================================================================
# Internal helpers
# ================================================================


def _pick_scalar(
    field_name: str,
    records: list[CanonicalRecord],
    resolver: ConflictResolver,
    conflicts_out: list[ConflictRecord],
    source_types_out: dict[str, list[SourceType]],
    agreement_out: dict[str, bool],
) -> Any:
    """
    Read ``field_name`` from every record, resolve conflicts, track metadata.
    """
    raw_values: list[tuple[Any, SourceType, datetime]] = []
    for rec in records:
        v = getattr(rec, field_name, None)
        if v is not None and v != "":
            raw_values.append((v, rec.source_type, rec.mapped_at))

    if not raw_values:
        return None

    source_types_out[field_name] = [s for _, s, _ in raw_values]

    # Detect agreement
    normalised_vals = [
        normalize_key(str(v)) if isinstance(v, str) else v
        for v, _, _ in raw_values
    ]
    all_agree = len(set(str(n) for n in normalised_vals)) == 1
    agreement_out[field_name] = all_agree

    winner, new_conflicts = resolver.resolve(field_name, raw_values)
    conflicts_out.extend(new_conflicts)
    return winner


def _sort_by_priority(records: list[CanonicalRecord]) -> list[CanonicalRecord]:
    """Sort records: lowest priority number (highest trust) first."""
    return sorted(records, key=lambda r: SOURCE_PRIORITY.get(r.source_type.value, 99))


# ── Experience deduplication ──────────────────────────────────────

def _exp_key(entry: dict[str, Any]) -> str:
    """Stable deduplication key for an experience entry."""
    company  = normalize_key(entry.get("company", "") or "")
    title    = normalize_key(entry.get("title", "") or "")
    start    = (entry.get("start_date") or "")[:7]  # YYYY-MM
    return f"{company}|{title}|{start}"


def _merge_experience(records: list[CanonicalRecord]) -> list[Experience]:
    """Union-dedup experience dicts across all records → typed Experience objects."""
    seen: dict[str, dict[str, Any]] = {}
    priority_sorted = _sort_by_priority(records)

    for rec in priority_sorted:
        src = rec.source_type
        for entry in rec.experience:
            if not isinstance(entry, dict):
                continue
            key = _exp_key(entry)
            if key not in seen:
                seen[key] = {**entry, "_source": src}
            else:
                # Enrich: fill missing fields from lower-priority sources
                existing = seen[key]
                for k, v in entry.items():
                    if k not in existing or existing[k] is None:
                        existing[k] = v

    result: list[Experience] = []
    for entry in seen.values():
        src = entry.pop("_source", SourceType.CSV)
        company = entry.get("company", "")
        if not company:
            continue
        try:
            exp = Experience(
                company=company,
                normalized_company=normalize_key(company),
                title=entry.get("title", ""),
                description=entry.get("description"),
                start_date=entry.get("start_date"),
                end_date=entry.get("end_date"),
                is_current=bool(entry.get("is_current", False)),
                location=entry.get("location"),
                confidence=float(entry.get("confidence", 0.85)),
                source=src,
            )
            result.append(exp)
        except Exception as exc:
            _log.warning(
                "Experience entry skipped",
                extra={"reason": str(exc), "entry": str(entry)[:120]},
            )

    result.sort(key=lambda e: experience_sort_key({
        "start_date": e.start_date,
        "end_date": e.end_date,
    }), reverse=True)
    return result


# ── Education deduplication ───────────────────────────────────────

def _edu_key(entry: dict[str, Any]) -> str:
    """Stable deduplication key for an education entry."""
    institution = normalize_key(entry.get("institution", "") or "")
    degree      = normalize_key(entry.get("degree", "") or "")
    end         = (entry.get("end_date") or "")[:4]  # YYYY
    return f"{institution}|{degree}|{end}"


def _merge_education(records: list[CanonicalRecord]) -> list[Education]:
    """Union-dedup education dicts across all records → typed Education objects."""
    seen: dict[str, dict[str, Any]] = {}
    priority_sorted = _sort_by_priority(records)

    for rec in priority_sorted:
        src = rec.source_type
        for entry in rec.education:
            if not isinstance(entry, dict):
                continue
            key = _edu_key(entry)
            if key not in seen:
                seen[key] = {**entry, "_source": src}
            else:
                existing = seen[key]
                for k, v in entry.items():
                    if k not in existing or existing[k] is None:
                        existing[k] = v

    result: list[Education] = []
    for entry in seen.values():
        src = entry.pop("_source", SourceType.CSV)
        institution = entry.get("institution", "")
        if not institution:
            continue
        try:
            edu = Education(
                institution=institution,
                normalized_institution=normalize_key(institution),
                degree=entry.get("degree"),
                field_of_study=entry.get("field") or entry.get("field_of_study"),
                start_date=entry.get("start_date"),
                end_date=entry.get("end_date"),
                grade=entry.get("gpa") or entry.get("grade"),
                confidence=float(entry.get("confidence", 0.85)),
                source=src,
            )
            result.append(edu)
        except Exception as exc:
            _log.warning(
                "Education entry skipped",
                extra={"reason": str(exc), "entry": str(entry)[:120]},
            )

    result.sort(key=lambda e: education_sort_key({
        "end_date": e.end_date,
    }), reverse=True)
    return result


# ── Skills deduplication ──────────────────────────────────────────

def _merge_skills(records: list[CanonicalRecord]) -> list[Skill]:
    """
    Union-merge normalised skill strings into typed :class:`~src.models.Skill`
    objects, tracking all aliases and sources.
    """
    # canonical_name → {aliases, sources}
    skill_map: dict[str, dict[str, Any]] = {}

    for rec in records:
        for raw_skill in rec.skills:
            key = clean_lower(raw_skill)
            if key not in skill_map:
                skill_map[key] = {
                    "name":     raw_skill,
                    "aliases":  [raw_skill],
                    "sources":  [rec.source_type],
                }
            else:
                existing = skill_map[key]
                if raw_skill not in existing["aliases"]:
                    existing["aliases"].append(raw_skill)
                if rec.source_type not in existing["sources"]:
                    existing["sources"].append(rec.source_type)

    result: list[Skill] = []
    for key, data in skill_map.items():
        # Use the version from the highest-priority source
        name = data["name"]
        conf = min(1.0, 0.8 + 0.05 * len(data["sources"]))  # more sources → higher conf
        try:
            skill = Skill(
                name=name,
                normalized_name=name,
                aliases=data["aliases"],
                sources=data["sources"],
                confidence=conf,
            )
            result.append(skill)
        except Exception as exc:
            _log.warning("Skill skipped", extra={"reason": str(exc), "skill": name})

    return result


# ── Links deduplication ───────────────────────────────────────────

def _merge_links(records: list[CanonicalRecord]) -> list[CandidateLink]:
    """Collect all links across sources, dedup by normalised URL."""
    seen: dict[str, CandidateLink] = {}

    for rec in records:
        if rec.github_url:
            k = url_key(rec.github_url)
            if k not in seen:
                seen[k] = CandidateLink(
                    platform="github", url=rec.github_url, verified=True
                )
        if rec.linkedin_url:
            k = url_key(rec.linkedin_url)
            if k not in seen:
                seen[k] = CandidateLink(
                    platform="linkedin", url=rec.linkedin_url, verified=True
                )
        if rec.website:
            k = url_key(rec.website)
            if k not in seen:
                seen[k] = CandidateLink(
                    platform="portfolio", url=rec.website, verified=False
                )
        for platform, url in rec.other_links.items():
            if url:
                k = url_key(url)
                if k not in seen:
                    seen[k] = CandidateLink(
                        platform=platform, url=url, verified=False
                    )

    # Sort: verified links first
    return sorted(seen.values(), key=lambda lk: (not lk.verified, lk.platform))


# ── Location structure ────────────────────────────────────────────

def _build_location_dict(records: list[CanonicalRecord]) -> dict[str, str | None]:
    """
    Build the structured location dict for CandidateProfile.

    Reads ``mapping_metadata["location_components"]`` from each record
    (written by LocationNormalizer) and takes the most complete version.
    """
    best: dict[str, str | None] = {
        "city": None, "state": None, "country": None, "country_code": None
    }
    best_score = -1

    for rec in _sort_by_priority(records):
        comps = rec.mapping_metadata.get("location_components") or {}
        score = sum(1 for v in comps.values() if v)
        if score > best_score:
            best_score = score
            best = {
                "city":         comps.get("city"),
                "state":        comps.get("state"),
                "country":      comps.get("country"),
                "country_code": rec.mapping_metadata.get("country_code")
                                or comps.get("country"),
            }

    return best


# ================================================================
# MergeEngine
# ================================================================


class MergeEngine:
    """
    Merges a :class:`~src.merge.identity_resolver.CandidateGroup` into a
    :class:`~src.models.CandidateProfile` + :class:`MergeReport`.

    Parameters
    ----------
    conflict_resolver:
        :class:`~src.merge.conflict_resolver.ConflictResolver` instance.
    confidence_engine:
        :class:`~src.merge.confidence_engine.ConfidenceEngine` instance.
    provenance_aggregator:
        :class:`~src.merge.provenance_aggregator.ProvenanceAggregator` instance.
    """

    def __init__(
        self,
        conflict_resolver:    ConflictResolver | None = None,
        confidence_engine:    ConfidenceEngine | None = None,
        provenance_aggregator: ProvenanceAggregator | None = None,
    ) -> None:
        self._resolver    = conflict_resolver    or ConflictResolver()
        self._confidence  = confidence_engine    or ConfidenceEngine()
        self._provenance  = provenance_aggregator or ProvenanceAggregator()

    def merge(self, group: CandidateGroup) -> tuple[CandidateProfile, MergeReport]:
        """
        Merge a candidate group into a profile + audit report.

        Parameters
        ----------
        group:
            One :class:`~src.merge.identity_resolver.CandidateGroup`.

        Returns
        -------
        tuple[CandidateProfile, MergeReport]
            The merged profile and its audit report.
        """
        records = group.records
        conflicts: list[ConflictRecord] = []
        source_types_per_field: dict[str, list[SourceType]] = {}
        agreement_per_field:    dict[str, bool] = {}

        # ── Scalar field resolution ───────────────────────────
        def _pick(name: str) -> Any:
            return _pick_scalar(
                name, records, self._resolver,
                conflicts, source_types_per_field, agreement_per_field
            )

        full_name        = _pick("full_name")
        headline         = _pick("headline")
        summary          = _pick("summary")
        current_company  = _pick("current_company")
        current_title    = _pick("current_title")
        location_raw     = _pick("location")
        github_username  = _pick("github_username")
        primary_language = _pick("primary_language")

        # Years of experience: take max across sources
        yoe_values = [
            (rec.years_of_experience, rec.source_type, rec.mapped_at)
            for rec in records
            if rec.years_of_experience is not None
        ]
        years_experience: float | None = None
        if yoe_values:
            years_experience = max(v for v, _, _ in yoe_values)
            source_types_per_field["years_experience"] = [s for _, s, _ in yoe_values]
            agreement_per_field["years_experience"] = len(set(v for v, _, _ in yoe_values)) == 1

        # GitHub stats: take max (most complete GitHub source)
        gh_stars = max(
            (rec.github_stars for rec in records if rec.github_stars is not None),
            default=None,
        )
        gh_repos = max(
            (rec.github_repos for rec in records if rec.github_repos is not None),
            default=None,
        )

        # ── List field union + dedup ──────────────────────────
        all_emails = union_lists(*[rec.emails for rec in records], key=email_key)
        all_phones = union_lists(*[rec.phones for rec in records], key=phone_key)
        all_certs  = union_lists(
            *[rec.certifications for rec in records],
            key=lambda s: clean_lower(s),
        )

        if all_emails:
            source_types_per_field["emails"] = [rec.source_type for rec in records if rec.emails]
            agreement_per_field["emails"] = True  # union — no conflict

        if all_phones:
            source_types_per_field["phones"] = [rec.source_type for rec in records if rec.phones]
            agreement_per_field["phones"] = True

        # ── Structured field merges ───────────────────────────
        merged_experience = _merge_experience(records)
        merged_education  = _merge_education(records)
        merged_skills     = _merge_skills(records)
        merged_links      = _merge_links(records)
        location_dict     = _build_location_dict(records)

        # Track structured field sources
        if merged_experience:
            source_types_per_field["experience"] = list({r.source_type for r in records if r.experience})
            agreement_per_field["experience"] = True
        if merged_education:
            source_types_per_field["education"] = list({r.source_type for r in records if r.education})
            agreement_per_field["education"] = True
        if merged_skills:
            source_types_per_field["skills"] = list({r.source_type for r in records if r.skills})
            agreement_per_field["skills"] = True
        if merged_links:
            source_types_per_field["links"] = list({r.source_type for r in records})
            agreement_per_field["links"] = True
        if any(v for v in location_dict.values()):
            source_types_per_field["location"] = list({r.source_type for r in records if r.location})
            agreement_per_field["location"] = True

        # ── Provenance aggregation ────────────────────────────
        winner_src: dict[str, SourceType] = {
            cr.field: cr.winner_source for cr in conflicts
        }
        prov_map = self._provenance.aggregate(
            records,
            conflict_records=conflicts,
            winner_source_per_field=winner_src,
        )

        # ── Confidence scoring ────────────────────────────────
        timestamps = [rec.mapped_at for rec in records]

        # Build a provisional profile for consistency checks
        # (we'll rebuild it with quality metrics after scoring)
        provisional_profile = CandidateProfile(
            full_name=full_name,
            emails=all_emails,
            phones=all_phones,
            location=location_dict,
            headline=headline,
            years_experience=years_experience,
            skills=merged_skills,
            experience=merged_experience,
            education=merged_education,
            links=merged_links,
            provenance=prov_map,
        )

        quality = self._confidence.score(
            provisional_profile,
            source_types_per_field,
            agreement_per_field,
            timestamps,
        )

        # ── Final CandidateProfile (frozen) ──────────────────
        profile = CandidateProfile(
            candidate_id=provisional_profile.candidate_id,
            full_name=full_name,
            emails=all_emails,
            phones=all_phones,
            location=location_dict,
            headline=headline,
            years_experience=years_experience,
            skills=merged_skills,
            experience=merged_experience,
            education=merged_education,
            links=merged_links,
            provenance=prov_map,
            quality_metrics=quality,
            overall_confidence=quality.overall_confidence,
        )

        # ── MergeReport ───────────────────────────────────────
        report = MergeReport(
            candidate_id=profile.candidate_id,
            merged_records=[rec.canonical_id for rec in records],
            source_types=list({rec.source_type.value for rec in records}),
            conflicts=conflicts,
            quality_metrics=quality,
            merge_strategy=self._resolver._strategy.value,
            needs_review=group.needs_review,
        )

        _log.info(
            "Merge complete",
            extra={
                "candidate_id":       profile.candidate_id,
                "sources":            report.source_types,
                "conflicts":          len(conflicts),
                "overall_confidence": quality.overall_confidence,
                "completeness":       quality.completeness,
                "needs_review":       group.needs_review,
            },
        )
        return profile, report
