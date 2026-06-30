"""
src/main.py
============

End-to-end pipeline orchestrator.

Stage Flow
----------
::

    Input files / args
        │
        ▼  Extraction
    list[RawRecord]
        │
        ▼  Mapping
    list[CanonicalRecord]
        │
        ▼  Normalization
    list[CanonicalRecord]   (normalised in-place)
        │
        ▼  Identity Resolution → Merge
    list[CandidateProfile] + list[MergeReport]
        │
        ▼  Projection
    list[dict]
        │
        ▼  Validation
    ValidationReport
        │
        ▼  Output
    JSON file / stdout

Usage (programmatic)
--------------------
::

    from src.main import run_pipeline, PipelineConfig

    result = run_pipeline(PipelineConfig(
        csv_paths=["data/candidates.csv"],
        output_path="output/candidates.json",
        verbose=True,
    ))
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.logging_config import get_logger
from src.models import CanonicalRecord, CandidateProfile

_log = get_logger(__name__)


# ================================================================
# PipelineConfig
# ================================================================


@dataclass
class PipelineConfig:
    """
    Configuration for a single pipeline run.

    All path lists accept strings or :class:`pathlib.Path` objects.
    """

    # ── Input sources ─────────────────────────────────────────
    csv_paths:    list[str] = field(default_factory=list)
    ats_paths:    list[str] = field(default_factory=list)
    resume_paths: list[str] = field(default_factory=list)
    github_users: list[str] = field(default_factory=list)

    # ── Configuration files ───────────────────────────────────
    pipeline_config_path:   str | None = None
    projection_config_path: str | None = None
    validation_config_path: str | None = None

    # ── Output ────────────────────────────────────────────────
    output_path:  str | None = None
    report_path:  str | None = None

    # ── Behaviour flags ───────────────────────────────────────
    verbose:         bool  = False
    merge_strategy:  str   = "source_priority"
    match_threshold: float = 0.85
    fail_on_error:   bool  = True


# ================================================================
# PipelineResult
# ================================================================


@dataclass
class PipelineResult:
    """Returned by :func:`run_pipeline`."""

    profiles:          list[CandidateProfile]
    outputs:           list[dict[str, Any]]
    validation_report: Any       # ValidationReport
    elapsed_ms:        float = 0.0

    @property
    def profile_count(self) -> int:
        return len(self.profiles)

    @property
    def valid_count(self) -> int:
        return self.validation_report.valid

    def to_output_list(self) -> list[dict[str, Any]]:
        return self.outputs


# ================================================================
# Stage helpers
# ================================================================


def _extract(cfg: PipelineConfig) -> list[Any]:
    """Stage 1: Extraction → list[RawRecord]."""
    from src.extractors.factory import ExtractorFactory

    factory      = ExtractorFactory()
    raw_records: list[Any] = []

    for path in cfg.csv_paths:
        p = Path(path)
        if not p.exists():
            _log.warning("CSV file not found — skipping", extra={"path": path})
            continue
        try:
            extractor = factory.get(p)
            records   = extractor.extract(p)
            raw_records.extend(records)
            _log.info("Extracted CSV", extra={"path": path, "count": len(records)})
        except Exception as exc:
            _log.error("CSV extraction failed", extra={"path": path, "error": str(exc)})

    for path in cfg.ats_paths:
        p = Path(path)
        if not p.exists():
            _log.warning("ATS file not found — skipping", extra={"path": path})
            continue
        try:
            extractor = factory.get(p)
            records   = extractor.extract(p)
            raw_records.extend(records)
            _log.info("Extracted ATS", extra={"path": path, "count": len(records)})
        except Exception as exc:
            _log.error("ATS extraction failed", extra={"path": path, "error": str(exc)})

    for path in cfg.resume_paths:
        p = Path(path)
        if not p.exists():
            _log.warning("Resume file not found — skipping", extra={"path": path})
            continue
        try:
            extractor = factory.get(p)
            records   = extractor.extract(p)
            raw_records.extend(records)
            _log.info("Extracted resume", extra={"path": path, "count": len(records)})
        except Exception as exc:
            _log.error("Resume extraction failed", extra={"path": path, "error": str(exc)})

    for username in cfg.github_users:
        try:
            extractor = factory.get(username, source_type="github")
            records   = extractor.extract(username)
            raw_records.extend(records)
            _log.info("Extracted GitHub", extra={"username": username, "count": len(records)})
        except Exception as exc:
            _log.error("GitHub extraction failed", extra={"username": username, "error": str(exc)})

    _log.info("Extraction complete", extra={"total_records": len(raw_records)})
    return raw_records


def _map(raw_records: list[Any]) -> list[CanonicalRecord]:
    """Stage 2: Mapping → list[CanonicalRecord]."""
    from src.mapping.factory import MapperFactory

    mapper    = MapperFactory()
    canonical = mapper.map_many(raw_records)
    _log.info("Mapping complete", extra={"mapped": len(canonical)})
    return canonical


def _normalise(canonical: list[CanonicalRecord]) -> list[CanonicalRecord]:
    """Stage 3: Normalization (each record processed individually)."""
    from src.normalization.factory import NormalizerFactory

    pipeline   = NormalizerFactory.build_default_pipeline()
    normalised = []
    for rec in canonical:
        try:
            normalised.append(pipeline.run(rec))
        except Exception as exc:
            _log.warning(
                "Normalization failed for record",
                extra={"canonical_id": rec.canonical_id, "error": str(exc)},
            )
            normalised.append(rec)

    _log.info("Normalization complete", extra={"normalised": len(normalised)})
    return normalised


def _merge(
    normalised: list[CanonicalRecord], cfg: PipelineConfig
) -> tuple[list[CandidateProfile], list[Any]]:
    """Stage 4: Identity Resolution + Merge → list[CandidateProfile]."""
    from src.merge.factory import MergeFactory

    pipeline = MergeFactory.build_default_pipeline(config={
        "strategy":        cfg.merge_strategy,
        "match_threshold": cfg.match_threshold,
    })
    profiles, reports = pipeline.run(normalised)
    _log.info(
        "Merge complete",
        extra={"profiles": len(profiles), "reports": len(reports)},
    )
    return profiles, reports


def _project(
    profiles: list[CandidateProfile], cfg: PipelineConfig
) -> list[dict[str, Any]]:
    """Stage 5: Projection → list[dict]."""
    from src.projection.factory import ProjectorFactory

    projector = ProjectorFactory.build(config_path=cfg.projection_config_path)
    outputs   = projector.project_many(profiles)
    _log.info("Projection complete", extra={"outputs": len(outputs)})
    return outputs


def _validate(
    profiles: list[CandidateProfile],
    outputs:  list[dict[str, Any]],
    cfg:      PipelineConfig,
) -> Any:
    """Stage 6: Validation → ValidationReport."""
    from src.validation.factory import ValidatorFactory

    validator = ValidatorFactory.build(config={
        "fail_on_error": cfg.fail_on_error,
    })
    report = validator.validate_batch(profiles, outputs)
    _log.info(
        "Validation complete",
        extra={
            "valid":    report.valid,
            "invalid":  report.invalid,
            "errors":   report.error_count,
            "warnings": report.warning_count,
        },
    )
    return report


def _write_output(outputs: list[dict[str, Any]], cfg: PipelineConfig) -> None:
    """Stage 7: Write JSON output."""
    payload = json.dumps(outputs, indent=2, default=str, ensure_ascii=False)
    if cfg.output_path:
        path = Path(cfg.output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        _log.info("Output written", extra={"path": str(path)})
    else:
        sys.stdout.write(payload + "\n")


def _write_report(report: Any, cfg: PipelineConfig) -> None:
    """Write validation report JSON if path is specified."""
    if not cfg.report_path:
        return
    path = Path(cfg.report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    _log.info("Validation report written", extra={"path": str(path)})


# ================================================================
# Public API
# ================================================================


def run_pipeline(cfg: PipelineConfig) -> PipelineResult:
    """
    Execute the full candidate transformation pipeline.

    Parameters
    ----------
    cfg:
        :class:`PipelineConfig` describing all inputs and options.

    Returns
    -------
    PipelineResult
    """
    t0 = time.perf_counter()

    if cfg.verbose:
        _log.info("Pipeline starting")

    raw_records = _extract(cfg)

    if not raw_records:
        _log.warning("No records extracted — producing empty output")
        from src.validation.report import ValidationReport
        empty_report = ValidationReport()
        _write_output([], cfg)
        _write_report(empty_report, cfg)
        return PipelineResult(
            profiles=[],
            outputs=[],
            validation_report=empty_report,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    canonical  = _map(raw_records)
    normalised = _normalise(canonical)
    profiles, _merge_reports = _merge(normalised, cfg)
    outputs    = _project(profiles, cfg)
    report     = _validate(profiles, outputs, cfg)

    _write_output(outputs, cfg)
    _write_report(report, cfg)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    _log.info(
        "Pipeline complete",
        extra={
            "raw_records": len(raw_records),
            "profiles":    len(profiles),
            "valid":       report.valid,
            "elapsed_ms":  round(elapsed_ms, 2),
        },
    )
    return PipelineResult(
        profiles=profiles,
        outputs=outputs,
        validation_report=report,
        elapsed_ms=elapsed_ms,
    )
