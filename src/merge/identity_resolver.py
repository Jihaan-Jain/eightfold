"""
src/merge/identity_resolver.py
================================

Groups :class:`~src.models.CanonicalRecord` objects that belong to the
same real-world candidate using Union-Find (disjoint-set) clustering.

Identity Signals (descending strength)
---------------------------------------
1. **Email match**       — exact, case-insensitive  (weight from constants)
2. **Phone match**       — E.164 normalised         (weight from constants)
3. **GitHub username**   — extracted from URL       (weight 0.95 × email)
4. **LinkedIn handle**   — extracted from URL       (weight 0.85 × email)
5. **Name + Company**    — fuzzy RapidFuzz          (weight from constants)
6. **Name + Location**   — fuzzy RapidFuzz          (weight from constants)

Thresholds
----------
``IDENTITY_MATCH_THRESHOLD`` (default 0.85):
    Two records must reach this combined signal score to be merged.

``IDENTITY_REVIEW_THRESHOLD`` (default 0.70):
    Below match threshold but above this → flagged for human review
    (stored in ``CandidateGroup.needs_review``).

Output
------
Returns a list of :class:`CandidateGroup` objects.  Each group contains
one or more ``CanonicalRecord`` objects representing the same person.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from src.constants import (
    IDENTITY_MATCH_THRESHOLD,
    IDENTITY_REVIEW_THRESHOLD,
    IDENTITY_WEIGHT_COMPANY,
    IDENTITY_WEIGHT_EMAIL,
    IDENTITY_WEIGHT_LOCATION,
    IDENTITY_WEIGHT_NAME,
    IDENTITY_WEIGHT_PHONE,
)
from src.logging_config import get_logger
from src.models import CanonicalRecord
from src.merge.utils import (
    clean_lower,
    email_key,
    github_login_from_url,
    linkedin_handle_from_url,
    normalize_key,
    phone_key,
)

_log = get_logger(__name__)

# GitHub/LinkedIn signal weights relative to email weight
_GITHUB_WEIGHT:   float = IDENTITY_WEIGHT_EMAIL * 0.95
_LINKEDIN_WEIGHT: float = IDENTITY_WEIGHT_EMAIL * 0.85


# ================================================================
# CandidateGroup
# ================================================================


@dataclass
class CandidateGroup:
    """
    A cluster of :class:`~src.models.CanonicalRecord` objects believed
    to represent the same real-world candidate.

    Attributes
    ----------
    group_id:
        Stable identifier for this group (UUID of the primary record).
    records:
        All ``CanonicalRecord`` objects in this cluster.
    primary_record_id:
        ``canonical_id`` of the most-complete record in the group.
    identity_signals:
        Human-readable list of signals that caused these records to
        be grouped (e.g. ``["email_match", "github_match"]``).
    match_score:
        Highest pairwise identity score that triggered grouping.
        ``1.0`` for single-record groups.
    needs_review:
        ``True`` when the group was formed on a weak signal
        (score between ``IDENTITY_REVIEW_THRESHOLD`` and
        ``IDENTITY_MATCH_THRESHOLD``).
    source_types:
        Unique source types represented in this group.
    """

    group_id:         str
    records:          list[CanonicalRecord] = field(default_factory=list)
    primary_record_id: str = ""
    identity_signals: list[str] = field(default_factory=list)
    match_score:      float = 1.0
    needs_review:     bool = False
    source_types:     list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.records and not self.primary_record_id:
            self.primary_record_id = self._elect_primary()
        if self.records and not self.source_types:
            self.source_types = list({r.source_type.value for r in self.records})

    def _elect_primary(self) -> str:
        """Return the canonical_id of the record with the most mapped fields."""
        return max(self.records, key=lambda r: len(r.mapped_fields)).canonical_id

    def add(self, record: CanonicalRecord) -> None:
        """Append a record to this group and refresh derived fields."""
        self.records.append(record)
        self.source_types = list({r.source_type.value for r in self.records})
        self.primary_record_id = self._elect_primary()

    @property
    def size(self) -> int:
        return len(self.records)


# ================================================================
# Union-Find
# ================================================================


class _UnionFind:
    """Simple path-compressed union-find over integer indices."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank   = [0] * n

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path compression
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> bool:
        """Merge sets containing x and y.  Returns True if they were distinct."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1
        return True

    def groups(self, n: int) -> dict[int, list[int]]:
        """Return {root: [members]} mapping."""
        clusters: dict[int, list[int]] = {}
        for i in range(n):
            root = self.find(i)
            clusters.setdefault(root, []).append(i)
        return clusters


# ================================================================
# Identity Scorer
# ================================================================


def _score_pair(a: CanonicalRecord, b: CanonicalRecord) -> tuple[float, list[str]]:
    """
    Compute a composite identity score for records ``a`` and ``b``.

    Hard signals (deterministic identity proof)
    -------------------------------------------
    - Exact email match   → score immediately >= IDENTITY_MATCH_THRESHOLD
    - Exact phone match   → score immediately >= IDENTITY_MATCH_THRESHOLD
    - GitHub login match  → score immediately >= IDENTITY_MATCH_THRESHOLD
    - LinkedIn match      → score immediately >= IDENTITY_MATCH_THRESHOLD

    Soft signals (probabilistic, additive)
    ----------------------------------------
    - Name + Company fuzzy
    - Name + Location fuzzy

    Returns
    -------
    tuple[float, list[str]]
        ``(score, signals)`` where ``score ∈ [0.0, 1.0]`` and
        ``signals`` lists the matches that contributed.
    """
    score: float = 0.0
    signals: list[str] = []

    # ── Hard signals — any single match is sufficient to merge ──

    # 1. Email exact match (emails are globally unique → definitive proof)
    emails_a = {email_key(e) for e in a.emails}
    emails_b = {email_key(e) for e in b.emails}
    if emails_a and emails_b and emails_a & emails_b:
        score = max(score, IDENTITY_MATCH_THRESHOLD)
        signals.append("email_match")

    # 2. Phone exact match (E.164 — globally unique)
    phones_a = {phone_key(p) for p in a.phones}
    phones_b = {phone_key(p) for p in b.phones}
    if phones_a and phones_b and phones_a & phones_b:
        score = max(score, IDENTITY_MATCH_THRESHOLD)
        signals.append("phone_match")

    # 3. GitHub username match (unique per platform)
    login_a = github_login_from_url(a.github_url) or (
        a.github_username.lower() if a.github_username else None
    )
    login_b = github_login_from_url(b.github_url) or (
        b.github_username.lower() if b.github_username else None
    )
    if login_a and login_b and login_a == login_b:
        score = max(score, IDENTITY_MATCH_THRESHOLD)
        signals.append("github_match")

    # 4. LinkedIn handle match (unique per platform)
    li_a = linkedin_handle_from_url(a.linkedin_url)
    li_b = linkedin_handle_from_url(b.linkedin_url)
    if li_a and li_b and li_a == li_b:
        score = max(score, IDENTITY_MATCH_THRESHOLD)
        signals.append("linkedin_match")

    # ── Soft signals — additive, need combination to reach threshold ──

    name_a   = normalize_key(a.full_name or "")
    name_b   = normalize_key(b.full_name or "")
    name_sim = 0.0

    if name_a and name_b:
        try:
            from rapidfuzz import fuzz
            name_sim = fuzz.token_sort_ratio(name_a, name_b) / 100.0
        except ImportError:
            name_sim = float(name_a == name_b)

        if name_sim >= 0.85:
            co_a = normalize_key(a.current_company or "")
            co_b = normalize_key(b.current_company or "")
            if co_a and co_b:
                try:
                    from rapidfuzz import fuzz as _fuzz
                    co_sim = _fuzz.token_sort_ratio(co_a, co_b) / 100.0
                except ImportError:
                    co_sim = float(co_a == co_b)
                if co_sim >= 0.80:
                    combined = IDENTITY_WEIGHT_NAME * name_sim + IDENTITY_WEIGHT_COMPANY * co_sim
                    score = min(1.0, score + combined)
                    signals.append("name_company_match")
            else:
                score = min(1.0, score + IDENTITY_WEIGHT_NAME * name_sim * 0.6)
                signals.append("name_only_match")

    # 6. Name + Location
    if name_a and name_b and "name_company_match" not in signals:
        loc_a = clean_lower(a.location or "")
        loc_b = clean_lower(b.location or "")
        if loc_a and loc_b and loc_a == loc_b and name_sim >= 0.85:
            score = min(1.0, score + IDENTITY_WEIGHT_NAME * 0.4 + IDENTITY_WEIGHT_LOCATION * 0.6)
            signals.append("name_location_match")

    return score, signals


# ================================================================
# IdentityResolver
# ================================================================


class IdentityResolver:
    """
    Clusters :class:`~src.models.CanonicalRecord` objects into
    :class:`CandidateGroup` objects using Union-Find.

    Parameters
    ----------
    match_threshold:
        Minimum composite score to merge two records.
        Default: ``IDENTITY_MATCH_THRESHOLD`` (0.85).
    review_threshold:
        Minimum score to flag a group for human review.
        Default: ``IDENTITY_REVIEW_THRESHOLD`` (0.70).
    config:
        Optional config dict.  Reserved for future per-signal
        weight overrides.
    """

    def __init__(
        self,
        match_threshold: float = IDENTITY_MATCH_THRESHOLD,
        review_threshold: float = IDENTITY_REVIEW_THRESHOLD,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._match_threshold  = match_threshold
        self._review_threshold = review_threshold
        self._config = config or {}

    def resolve(self, records: list[CanonicalRecord]) -> list[CandidateGroup]:
        """
        Cluster ``records`` into groups of the same candidate.

        Parameters
        ----------
        records:
            All :class:`~src.models.CanonicalRecord` objects from the
            normalisation stage.

        Returns
        -------
        list[CandidateGroup]
            One group per unique candidate.  Single-record groups are
            valid (candidate with only one source).

        Notes
        -----
        Time complexity: O(n² · α(n)) where α is the inverse Ackermann
        function (effectively constant).  For n ≤ 10,000 records this
        is fast enough for an offline batch pipeline.
        """
        n = len(records)
        if n == 0:
            return []

        uf = _UnionFind(n)
        pair_scores: dict[tuple[int, int], tuple[float, list[str]]] = {}

        for i in range(n):
            for j in range(i + 1, n):
                score, signals = _score_pair(records[i], records[j])
                if score >= self._review_threshold:
                    pair_scores[(i, j)] = (score, signals)
                if score >= self._match_threshold:
                    uf.union(i, j)
                    _log.debug(
                        "Records merged",
                        extra={
                            "record_a": records[i].canonical_id,
                            "record_b": records[j].canonical_id,
                            "score":    round(score, 4),
                            "signals":  signals,
                        },
                    )

        # Build CandidateGroup objects from clusters
        groups: list[CandidateGroup] = []
        for root, members in uf.groups(n).items():
            cluster_records = [records[i] for i in members]

            # Aggregate signals and best score for this cluster
            all_signals: list[str] = []
            best_score: float = 1.0 if len(members) == 1 else 0.0
            needs_review = False

            for i in members:
                for j in members:
                    if i >= j:
                        continue
                    key = (min(i, j), max(i, j))
                    if key in pair_scores:
                        s, sigs = pair_scores[key]
                        best_score = max(best_score, s)
                        for sig in sigs:
                            if sig not in all_signals:
                                all_signals.append(sig)
                        if s < self._match_threshold:
                            needs_review = True

            primary_id = max(
                cluster_records, key=lambda r: len(r.mapped_fields)
            ).canonical_id

            group = CandidateGroup(
                group_id=primary_id,
                records=cluster_records,
                primary_record_id=primary_id,
                identity_signals=all_signals,
                match_score=best_score,
                needs_review=needs_review,
                source_types=list({r.source_type.value for r in cluster_records}),
            )
            groups.append(group)

        _log.info(
            "Identity resolution complete",
            extra={
                "input_records": n,
                "output_groups": len(groups),
                "multi_source":  sum(1 for g in groups if g.size > 1),
            },
        )
        return groups

    def metadata(self) -> dict[str, Any]:
        return {
            "resolver":          self.__class__.__name__,
            "match_threshold":   self._match_threshold,
            "review_threshold":  self._review_threshold,
            "algorithm":         "union-find",
            "signals":           [
                "email_match", "phone_match", "github_match",
                "linkedin_match", "name_company_match", "name_location_match",
            ],
        }
