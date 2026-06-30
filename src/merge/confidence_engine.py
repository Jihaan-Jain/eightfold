"""
src/merge/confidence_engine.py
================================

Computes per-field and five-axis quality scores for a merged
:class:`~src.models.CandidateProfile`.

Five Quality Axes
-----------------
1. **overall_confidence**  — weighted average of per-field confidence scores
2. **completeness**        — fraction of expected fields that are non-null
3. **consistency**         — intra-source coherence (no contradictory dates, etc.)
4. **agreement**           — fraction of multi-source fields where sources agreed
5. **freshness**           — recency of source extraction timestamps

Design
------
- All computations are **deterministic** given the same inputs.
- No ML models.  Pure arithmetic.
- Field importance weights come from ``constants.FIELD_IMPORTANCE_WEIGHTS``.
- Source reliability weights come from ``constants.SOURCE_CONFIDENCE_WEIGHTS``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.constants import (
    FIELD_IMPORTANCE_WEIGHTS,
    SOURCE_CONFIDENCE_WEIGHTS,
    FRESHNESS_HALF_LIFE_DAYS,
)
from src.logging_config import get_logger
from src.models import (
    CandidateProfile,
    ConfidenceMethod,
    QualityMetrics,
    SourceType,
)
from src.merge.utils import freshness_score, completeness_score

_log = get_logger(__name__)

# Fields considered "expected" for completeness scoring
_EXPECTED_FIELDS: list[str] = [
    "full_name", "emails", "phones", "location",
    "headline", "years_experience", "skills",
    "experience", "education", "links",
]

# Per-field baseline confidence by source type
# (values from SOURCE_CONFIDENCE_WEIGHTS)
_SOURCE_WEIGHT: dict[str, float] = dict(SOURCE_CONFIDENCE_WEIGHTS)


# ================================================================
# Per-field confidence helpers
# ================================================================


def _field_confidence(
    field_name: str,
    value: Any,
    source_types: list[SourceType],
    agreed: bool,
) -> float:
    """
    Compute confidence for a single merged field value.

    Parameters
    ----------
    field_name:
        Canonical field name.
    value:
        The merged value.
    source_types:
        Source types that contributed a non-null value for this field.
    agreed:
        Whether all contributing sources agreed on the same value.

    Returns
    -------
    float
        Confidence in ``[0.0, 1.0]``.
    """
    if value is None or value == "" or value == [] or value == {}:
        return 0.0

    # Base: mean of contributing source weights
    source_weights = [_SOURCE_WEIGHT.get(st.value, 0.5) for st in source_types]
    base = sum(source_weights) / len(source_weights) if source_weights else 0.5

    # Bonus: multiple sources provided this field
    count_bonus = min(0.1 * (len(source_types) - 1), 0.15)

    # Agreement bonus / penalty
    agreement_delta = 0.05 if agreed else -0.10

    # Importance weight (not applied to the score itself, used in aggregate)
    score = base + count_bonus + agreement_delta
    return min(1.0, max(0.0, score))


# ================================================================
# Agreement tracker
# ================================================================


class _AgreementTracker:
    """Tracks which multi-source fields had full agreement."""

    def __init__(self) -> None:
        self._multi:   int = 0  # fields present in 2+ sources
        self._agreed:  int = 0  # fields where all sources agreed

    def record(self, agreed: bool) -> None:
        self._multi += 1
        if agreed:
            self._agreed += 1

    @property
    def score(self) -> float:
        if self._multi == 0:
            return 1.0
        return self._agreed / self._multi


# ================================================================
# Consistency checker
# ================================================================


def _consistency_score(profile: CandidateProfile) -> float:
    """
    Check for intra-profile contradictions.

    Checks performed:
    - Experience: start_date < end_date for each entry.
    - Education: start_date < end_date for each entry.
    - years_experience: not negative, not > 60.

    Returns
    -------
    float
        1.0 = no contradictions; reduced by 0.15 per violation.
    """
    violations = 0
    checks = 0

    from src.merge.utils import parse_year_month

    for exp in profile.experience:
        checks += 1
        sd = parse_year_month(exp.start_date)
        ed = parse_year_month(exp.end_date)
        if sd and ed and sd > ed:
            violations += 1
            _log.debug(
                "Consistency violation: start_date > end_date in experience",
                extra={"company": exp.company},
            )

    for edu in profile.education:
        checks += 1
        sd = parse_year_month(edu.start_date)
        ed = parse_year_month(edu.end_date)
        if sd and ed and sd > ed:
            violations += 1

    if profile.years_experience is not None:
        checks += 1
        if profile.years_experience < 0 or profile.years_experience > 60:
            violations += 1

    if checks == 0:
        return 1.0
    penalty = min(1.0, violations * 0.15)
    return max(0.0, 1.0 - penalty)


# ================================================================
# ConfidenceEngine
# ================================================================


class ConfidenceEngine:
    """
    Computes five-axis quality metrics for a merged
    :class:`~src.models.CandidateProfile`.

    The engine is stateless — call :meth:`score` with any profile.

    Parameters
    ----------
    expected_fields:
        Fields counted in the completeness score.
        Default: :data:`_EXPECTED_FIELDS`.
    field_weights:
        Overrides ``constants.FIELD_IMPORTANCE_WEIGHTS`` for the
        overall confidence weighted average.
    """

    def __init__(
        self,
        expected_fields: list[str] | None = None,
        field_weights: dict[str, float] | None = None,
    ) -> None:
        self._expected = expected_fields or _EXPECTED_FIELDS
        self._weights  = field_weights or dict(FIELD_IMPORTANCE_WEIGHTS)

    def score(
        self,
        profile: CandidateProfile,
        source_types_per_field: dict[str, list[SourceType]],
        agreement_per_field: dict[str, bool],
        source_timestamps: list[datetime],
    ) -> QualityMetrics:
        """
        Compute all five quality axes and return a :class:`~src.models.QualityMetrics`.

        Parameters
        ----------
        profile:
            The merged :class:`~src.models.CandidateProfile`.
        source_types_per_field:
            Mapping of canonical field name → list of source types that
            provided a non-null value for that field.
        agreement_per_field:
            Mapping of canonical field name → ``True`` when all sources agreed.
        source_timestamps:
            ``mapped_at`` timestamps from all contributing
            :class:`~src.models.CanonicalRecord` objects.

        Returns
        -------
        QualityMetrics
        """
        tracker = _AgreementTracker()

        # ── 1. Per-field confidence → overall_confidence ──────
        weighted_sum = 0.0
        weight_total = 0.0

        profile_dict = {
            "full_name":       profile.full_name,
            "emails":          profile.emails,
            "phones":          profile.phones,
            "location":        profile.location,
            "headline":        profile.headline,
            "years_experience": profile.years_experience,
            "skills":          profile.skills,
            "experience":      profile.experience,
            "education":       profile.education,
            "links":           profile.links,
        }

        for field_name, value in profile_dict.items():
            src_types = source_types_per_field.get(field_name, [])
            agreed    = agreement_per_field.get(field_name, True)

            if len(src_types) > 1:
                tracker.record(agreed)

            fc = _field_confidence(field_name, value, src_types, agreed)
            w  = self._weights.get(field_name, 0.5)
            weighted_sum += fc * w
            weight_total += w

        overall = weighted_sum / weight_total if weight_total > 0 else 0.0

        # ── 2. Completeness ────────────────────────────────────
        complete = completeness_score(profile_dict, self._expected)

        # ── 3. Consistency ─────────────────────────────────────
        consist = _consistency_score(profile)

        # ── 4. Agreement ───────────────────────────────────────
        agree = tracker.score

        # ── 5. Freshness ───────────────────────────────────────
        fresh = freshness_score(source_timestamps)

        metrics = QualityMetrics(
            overall_confidence=round(min(1.0, max(0.0, overall)), 4),
            completeness=round(complete, 4),
            consistency=round(consist, 4),
            agreement=round(agree, 4),
            freshness=round(fresh, 4),
        )

        _log.info(
            "Confidence scoring complete",
            extra={
                "candidate_id":       profile.candidate_id,
                "overall_confidence": metrics.overall_confidence,
                "completeness":       metrics.completeness,
                "consistency":        metrics.consistency,
                "agreement":          metrics.agreement,
                "freshness":          metrics.freshness,
            },
        )
        return metrics
