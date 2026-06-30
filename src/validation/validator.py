"""
src/validation/validator.py
=============================

Orchestrates schema + business validation for a batch of profiles.
"""

from __future__ import annotations

import time
from typing import Any

from src.logging_config import get_logger
from src.models import CandidateProfile
from src.validation.business_validator import BusinessValidator
from src.validation.report import ValidationIssueDetail, ValidationReport
from src.validation.schema_validator import SchemaValidator

_log = get_logger(__name__)


class Validator:
    """
    Runs schema + business validation over all projected profiles.

    Parameters
    ----------
    schema_validator:
        Configured :class:`~src.validation.schema_validator.SchemaValidator`.
    business_validator:
        Configured :class:`~src.validation.business_validator.BusinessValidator`.
    fail_on_error:
        When ``True``, a profile with any ERROR-severity issue is counted
        as invalid.  Default ``True``.
    """

    def __init__(
        self,
        schema_validator:   SchemaValidator | None = None,
        business_validator: BusinessValidator | None = None,
        fail_on_error:      bool = True,
    ) -> None:
        self._schema   = schema_validator   or SchemaValidator()
        self._business = business_validator or BusinessValidator()
        self._fail     = fail_on_error

    def validate_one(
        self,
        profile: CandidateProfile,
        output:  dict[str, Any],
    ) -> tuple[bool, list[ValidationIssueDetail]]:
        """
        Validate one profile+output pair.

        Returns
        -------
        tuple[bool, list[ValidationIssueDetail]]
            ``(is_valid, issues)``
        """
        issues: list[ValidationIssueDetail] = []
        issues.extend(self._schema.validate(output))
        issues.extend(self._business.validate(profile, output))

        has_errors = any(i.severity == "error" for i in issues)
        is_valid   = not (self._fail and has_errors)
        return is_valid, issues

    def validate_batch(
        self,
        profiles: list[CandidateProfile],
        outputs:  list[dict[str, Any]],
    ) -> ValidationReport:
        """
        Validate a batch of profile/output pairs.

        Parameters
        ----------
        profiles:
            All merged :class:`~src.models.CandidateProfile` objects.
        outputs:
            Corresponding projected output dicts (same order/length).

        Returns
        -------
        ValidationReport
        """
        report = ValidationReport()
        t0     = time.perf_counter()

        for profile, output in zip(profiles, outputs):
            try:
                is_valid, issues = self.validate_one(profile, output)
            except Exception as exc:
                _log.error(
                    "Validation error for candidate",
                    extra={
                        "candidate_id": profile.candidate_id,
                        "error":        str(exc),
                    },
                    exc_info=True,
                )
                issues = [ValidationIssueDetail(
                    field="__validator__",
                    rule="internal_error",
                    message=f"Validation raised an exception: {exc}",
                    severity="error",
                )]
                is_valid = False

            report.add_result(profile.candidate_id, is_valid, issues)

        report.elapsed_ms = (time.perf_counter() - t0) * 1000

        _log.info(
            "Validation complete",
            extra={
                "total":        report.total,
                "valid":        report.valid,
                "invalid":      report.invalid,
                "errors":       report.error_count,
                "warnings":     report.warning_count,
                "elapsed_ms":   round(report.elapsed_ms, 2),
            },
        )
        return report
