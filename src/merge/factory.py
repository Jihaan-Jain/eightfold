"""
src/merge/factory.py
=====================

Factory for constructing fully-configured
:class:`~src.merge.pipeline.MergePipeline` instances.

Usage
-----
::

    from src.merge.factory import MergeFactory

    # Default pipeline (SOURCE_PRIORITY strategy)
    pipeline = MergeFactory.build_default_pipeline()

    # Custom strategy
    pipeline = MergeFactory.build_default_pipeline(config={
        "strategy":         "majority_vote",
        "match_threshold":  0.80,
        "field_strategies": {"full_name": "most_recent"},
    })

    # Run it
    profiles, reports = pipeline.run(canonical_records)
"""

from __future__ import annotations

from typing import Any

from src.constants import IDENTITY_MATCH_THRESHOLD, IDENTITY_REVIEW_THRESHOLD
from src.models import MergeStrategy
from src.merge.confidence_engine import ConfidenceEngine
from src.merge.conflict_resolver import ConflictResolver
from src.merge.identity_resolver import IdentityResolver
from src.merge.merge_engine import MergeEngine
from src.merge.pipeline import MergePipeline
from src.merge.provenance_aggregator import ProvenanceAggregator


class MergeFactory:
    """
    Factory for :class:`~src.merge.pipeline.MergePipeline` instances.

    All methods are class-level — no instantiation needed.
    """

    @classmethod
    def build_default_pipeline(
        cls,
        config: dict[str, Any] | None = None,
    ) -> MergePipeline:
        """
        Build a fully-configured merge pipeline with sensible defaults.

        Parameters
        ----------
        config:
            Optional configuration dict.  Supported keys:

            ``strategy`` (str):
                Default merge strategy.  One of:
                ``"source_priority"`` (default), ``"majority_vote"``,
                ``"most_recent"``, ``"manual"``.

            ``field_strategies`` (dict[str, str]):
                Per-field strategy overrides.
                e.g. ``{"full_name": "most_recent"}``.

            ``match_threshold`` (float, default 0.85):
                Identity resolution: minimum score to merge two records.

            ``review_threshold`` (float, default 0.70):
                Identity resolution: minimum score to flag for review.

            ``expected_fields`` (list[str]):
                Fields counted in completeness scoring.

            ``pipeline`` (dict):
                Pipeline-level options:
                - ``stop_on_error`` (bool, default ``False``)
                - ``emit_single_source`` (bool, default ``True``)

        Returns
        -------
        MergePipeline
            Ready to call ``.run(records)``.
        """
        config = config or {}

        # ── Strategy ──────────────────────────────────────────
        strategy_str = config.get("strategy", "source_priority")
        strategy = MergeStrategy(strategy_str)

        field_strat_raw: dict[str, str] = config.get("field_strategies", {})
        field_strategies = {
            field: MergeStrategy(strat)
            for field, strat in field_strat_raw.items()
        }

        # ── Identity resolver ─────────────────────────────────
        resolver = IdentityResolver(
            match_threshold=float(config.get("match_threshold", IDENTITY_MATCH_THRESHOLD)),
            review_threshold=float(config.get("review_threshold", IDENTITY_REVIEW_THRESHOLD)),
        )

        # ── Sub-components ────────────────────────────────────
        conflict_resolver = ConflictResolver(
            strategy=strategy,
            field_strategies=field_strategies,
        )
        confidence_engine = ConfidenceEngine(
            expected_fields=config.get("expected_fields"),
            field_weights=config.get("field_weights"),
        )
        prov_aggregator = ProvenanceAggregator()

        engine = MergeEngine(
            conflict_resolver=conflict_resolver,
            confidence_engine=confidence_engine,
            provenance_aggregator=prov_aggregator,
        )

        pipeline_config = config.get("pipeline", {})
        return MergePipeline(
            resolver=resolver,
            engine=engine,
            config=pipeline_config,
        )

    @classmethod
    def build_strict_pipeline(cls) -> MergePipeline:
        """
        Pipeline that requires strong identity signals (threshold = 0.90)
        and stops on any merge error.
        """
        return cls.build_default_pipeline(config={
            "match_threshold":  0.90,
            "review_threshold": 0.80,
            "pipeline":         {"stop_on_error": True},
        })

    @classmethod
    def build_lenient_pipeline(cls) -> MergePipeline:
        """
        Pipeline that accepts weaker identity signals (threshold = 0.70).
        Useful for data with low field coverage.
        """
        return cls.build_default_pipeline(config={
            "match_threshold":  0.70,
            "review_threshold": 0.55,
        })

    @classmethod
    def build_majority_vote_pipeline(cls) -> MergePipeline:
        """
        Pipeline that uses MAJORITY_VOTE as the default conflict
        resolution strategy.
        """
        return cls.build_default_pipeline(config={"strategy": "majority_vote"})

    @classmethod
    def build_most_recent_pipeline(cls) -> MergePipeline:
        """
        Pipeline that always favours the most recently extracted source.
        """
        return cls.build_default_pipeline(config={"strategy": "most_recent"})
