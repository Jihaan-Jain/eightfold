"""
src/validation/report.py
=========================

:class:`ValidationReport` and related types for the validation stage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ValidationIssueDetail:
    """One structured validation finding."""
    field:        str
    rule:         str
    message:      str
    severity:     str           # "error" | "warning"
    actual_value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field":        self.field,
            "rule":         self.rule,
            "message":      self.message,
            "severity":     self.severity,
            "actual_value": str(self.actual_value)[:200] if self.actual_value is not None else None,
        }


@dataclass
class ValidationReport:
    """
    Complete validation outcome for all candidates in a pipeline run.

    Attributes
    ----------
    total:         Total profiles validated.
    valid:         Count of fully valid profiles.
    invalid:       Count of profiles that failed at least one ERROR rule.
    with_warnings: Count of profiles with at least one WARNING.
    errors:        All error issues across all candidates.
    warnings:      All warning issues across all candidates.
    candidate_results: Per-candidate map of ``{candidate_id: {"valid": bool, "issues": [...]}}``.
    validated_at:  UTC timestamp.
    elapsed_ms:    Validation wall-clock time.
    """

    total:           int = 0
    valid:           int = 0
    invalid:         int = 0
    with_warnings:   int = 0
    errors:   list[ValidationIssueDetail] = field(default_factory=list)
    warnings: list[ValidationIssueDetail] = field(default_factory=list)
    candidate_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    validated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    elapsed_ms:   float = 0.0

    # ── Aggregated statistics ─────────────────────────────────

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def pass_rate(self) -> float:
        return self.valid / self.total if self.total else 0.0

    @property
    def statistics(self) -> dict[str, Any]:
        """Aggregated statistics dict."""
        rule_error_counts: dict[str, int] = {}
        for issue in self.errors + self.warnings:
            rule_error_counts[issue.rule] = rule_error_counts.get(issue.rule, 0) + 1

        return {
            "total":           self.total,
            "valid":           self.valid,
            "invalid":         self.invalid,
            "with_warnings":   self.with_warnings,
            "pass_rate":       round(self.pass_rate, 4),
            "error_count":     self.error_count,
            "warning_count":   self.warning_count,
            "top_violations":  sorted(
                rule_error_counts.items(), key=lambda x: x[1], reverse=True
            )[:10],
            "elapsed_ms":      round(self.elapsed_ms, 2),
        }

    def to_dict(self) -> dict[str, Any]:
        """Full serialisable representation."""
        return {
            "statistics":        self.statistics,
            "validated_at":      self.validated_at.isoformat(),
            "candidate_results": self.candidate_results,
            "errors":  [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }

    def add_result(
        self,
        candidate_id: str,
        is_valid: bool,
        issues: list[ValidationIssueDetail],
    ) -> None:
        """Record results for one candidate."""
        self.total += 1
        if is_valid:
            self.valid += 1
        else:
            self.invalid += 1

        if any(i.severity == "warning" for i in issues):
            self.with_warnings += 1

        self.errors.extend(i for i in issues if i.severity == "error")
        self.warnings.extend(i for i in issues if i.severity == "warning")

        self.candidate_results[candidate_id] = {
            "valid":  is_valid,
            "issues": [i.to_dict() for i in issues],
        }
