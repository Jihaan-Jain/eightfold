"""
src/merge/__init__.py
======================

Public API for the merge layer.

The merge layer transforms a flat list of normalised
:class:`~src.models.CanonicalRecord` objects into a list of
:class:`~src.models.CandidateProfile` objects — one per unique
real-world candidate.

Quick start
-----------
::

    from src.merge import MergeFactory

    pipeline = MergeFactory.build_default_pipeline()
    profiles, reports = pipeline.run(canonical_records)

    # Each profile is a CandidateProfile; each report is a MergeReport.
    for profile, report in zip(profiles, reports):
        print(profile.candidate_id, len(report.conflicts))

Custom configuration
--------------------
::

    pipeline = MergeFactory.build_default_pipeline(config={
        "strategy":         "majority_vote",
        "match_threshold":  0.80,
        "field_strategies": {"full_name": "most_recent"},
        "pipeline":         {"stop_on_error": True},
    })
"""

from src.merge.conflict_resolver import ConflictRecord, ConflictResolver
from src.merge.confidence_engine import ConfidenceEngine
from src.merge.factory import MergeFactory
from src.merge.identity_resolver import CandidateGroup, IdentityResolver
from src.merge.merge_engine import MergeEngine, MergeReport
from src.merge.pipeline import MergePipeline
from src.merge.provenance_aggregator import ProvenanceAggregator

__all__ = [
    "MergePipeline",
    "MergeFactory",
    "IdentityResolver",
    "MergeEngine",
    "ConflictResolver",
    "ConfidenceEngine",
    "ProvenanceAggregator",
    "CandidateGroup",
    "ConflictRecord",
    "MergeReport",
]
