"""
src/validation/business_validator.py
=======================================

Business-rule validation of projected output dicts and
:class:`~src.models.CandidateProfile` objects.

Rules Implemented
-----------------
Profile-level (CandidateProfile)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- ``experience_dates_ordered``  : start_date < end_date for each experience entry
- ``education_dates_ordered``   : start_date < end_date for each education entry
- ``no_future_graduation``      : education end_date not in the future
- ``experience_not_before_1900``: experience start_date year >= 1900
- ``no_duplicate_emails``       : no repeated email addresses (case-insensitive)
- ``no_duplicate_phones``       : no repeated phone numbers
- ``no_duplicate_skills``       : no repeated skill normalized_names (case-insensitive)
- ``github_username_format``    : GitHub username must match valid pattern
- ``years_experience_range``    : 0 ≤ years_experience ≤ 60
- ``min_confidence``            : overall_confidence ≥ MIN_PROFILE_CONFIDENCE

Output-dict level
~~~~~~~~~~~~~~~~~
- ``no_empty_name``             : full_name / name must be non-empty string
- ``primary_email_present``     : at least one email present
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from src.constants import MIN_PROFILE_CONFIDENCE, MIN_EMPLOYMENT_YEAR
from src.logging_config import get_logger
from src.models import CandidateProfile
from src.validation.report import ValidationIssueDetail

_log = get_logger(__name__)

_GITHUB_USER_RE = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,37}[a-zA-Z0-9])?$"
)
_CURRENT_YEAR = datetime.now(timezone.utc).year


def _parse_year(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, TypeError):
        return None


def _parse_year_month(date_str: str | None) -> tuple[int, int] | None:
    if not date_str:
        return None
    parts = date_str.split("-")
    try:
        year  = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 0
        return (year, month)
    except (ValueError, IndexError):
        return None


class BusinessValidator:
    """
    Validates business rules on a :class:`~src.models.CandidateProfile`
    and its projected output dict.

    Parameters
    ----------
    config:
        Optional config dict.  Supported keys:

        - ``min_confidence`` (float, default MIN_PROFILE_CONFIDENCE)
        - ``require_email`` (bool, default True)
        - ``check_github_username`` (bool, default True)
        - ``check_future_dates`` (bool, default True)
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._min_confidence:      float = cfg.get("min_confidence", MIN_PROFILE_CONFIDENCE)
        self._require_email:       bool  = cfg.get("require_email", True)
        self._check_github:        bool  = cfg.get("check_github_username", True)
        self._check_future_dates:  bool  = cfg.get("check_future_dates", True)

    def validate(
        self,
        profile: CandidateProfile,
        output: dict[str, Any],
    ) -> list[ValidationIssueDetail]:
        """
        Run all business rules.

        Parameters
        ----------
        profile:
            The merged :class:`~src.models.CandidateProfile`.
        output:
            The projected output dict.

        Returns
        -------
        list[ValidationIssueDetail]
        """
        issues: list[ValidationIssueDetail] = []

        issues.extend(self._check_experience_dates(profile))
        issues.extend(self._check_education_dates(profile))
        issues.extend(self._check_duplicate_emails(profile))
        issues.extend(self._check_duplicate_phones(profile))
        issues.extend(self._check_duplicate_skills(profile))
        issues.extend(self._check_years_experience(profile))
        issues.extend(self._check_confidence(profile))
        issues.extend(self._check_output_name(output))

        if self._require_email:
            issues.extend(self._check_email_present(profile))

        if self._check_github:
            issues.extend(self._check_github_username(profile, output))

        return issues

    # ── Experience ────────────────────────────────────────────

    def _check_experience_dates(
        self, profile: CandidateProfile
    ) -> list[ValidationIssueDetail]:
        issues = []
        for exp in profile.experience:
            sd = _parse_year_month(exp.start_date)
            ed = _parse_year_month(exp.end_date)
            if sd and ed and sd > ed:
                issues.append(ValidationIssueDetail(
                    field="experience",
                    rule="experience_dates_ordered",
                    message=(
                        f"Experience at '{exp.company}': "
                        f"start_date ({exp.start_date}) is after end_date ({exp.end_date})."
                    ),
                    severity="error",
                    actual_value=f"{exp.start_date} → {exp.end_date}",
                ))
            sy = _parse_year(exp.start_date)
            if sy and sy < MIN_EMPLOYMENT_YEAR:
                issues.append(ValidationIssueDetail(
                    field="experience",
                    rule="experience_not_before_1900",
                    message=(
                        f"Experience at '{exp.company}': "
                        f"start_date year {sy} is unrealistically old."
                    ),
                    severity="warning",
                    actual_value=exp.start_date,
                ))
        return issues

    # ── Education ─────────────────────────────────────────────

    def _check_education_dates(
        self, profile: CandidateProfile
    ) -> list[ValidationIssueDetail]:
        issues = []
        for edu in profile.education:
            sd = _parse_year_month(edu.start_date)
            ed = _parse_year_month(edu.end_date)
            if sd and ed and sd > ed:
                issues.append(ValidationIssueDetail(
                    field="education",
                    rule="education_dates_ordered",
                    message=(
                        f"Education at '{edu.institution}': "
                        f"start_date ({edu.start_date}) is after end_date ({edu.end_date})."
                    ),
                    severity="error",
                    actual_value=f"{edu.start_date} → {edu.end_date}",
                ))
            if self._check_future_dates:
                ey = _parse_year(edu.end_date)
                if ey and ey > _CURRENT_YEAR + 10:
                    issues.append(ValidationIssueDetail(
                        field="education",
                        rule="no_future_graduation",
                        message=(
                            f"Education at '{edu.institution}': "
                            f"graduation year {ey} is unrealistically far in the future."
                        ),
                        severity="warning",
                        actual_value=edu.end_date,
                    ))
        return issues

    # ── Duplicates ────────────────────────────────────────────

    def _check_duplicate_emails(
        self, profile: CandidateProfile
    ) -> list[ValidationIssueDetail]:
        seen: set[str] = set()
        dupes: list[str] = []
        for email in profile.emails:
            key = email.strip().lower()
            if key in seen:
                dupes.append(email)
            seen.add(key)
        if dupes:
            return [ValidationIssueDetail(
                field="emails",
                rule="no_duplicate_emails",
                message=f"Duplicate email addresses found: {dupes}.",
                severity="warning",
                actual_value=dupes,
            )]
        return []

    def _check_duplicate_phones(
        self, profile: CandidateProfile
    ) -> list[ValidationIssueDetail]:
        seen: set[str] = set()
        dupes: list[str] = []
        for phone in profile.phones:
            key = re.sub(r"[^\d+]", "", phone)
            if key in seen:
                dupes.append(phone)
            seen.add(key)
        if dupes:
            return [ValidationIssueDetail(
                field="phones",
                rule="no_duplicate_phones",
                message=f"Duplicate phone numbers found: {dupes}.",
                severity="warning",
                actual_value=dupes,
            )]
        return []

    def _check_duplicate_skills(
        self, profile: CandidateProfile
    ) -> list[ValidationIssueDetail]:
        seen: set[str] = set()
        dupes: list[str] = []
        for skill in profile.skills:
            key = skill.normalized_name.lower().strip()
            if key in seen:
                dupes.append(skill.normalized_name)
            seen.add(key)
        if dupes:
            return [ValidationIssueDetail(
                field="skills",
                rule="no_duplicate_skills",
                message=f"Duplicate skills found: {dupes}.",
                severity="warning",
                actual_value=dupes,
            )]
        return []

    # ── Scalars ───────────────────────────────────────────────

    def _check_years_experience(
        self, profile: CandidateProfile
    ) -> list[ValidationIssueDetail]:
        yoe = profile.years_experience
        if yoe is None:
            return []
        if yoe < 0:
            return [ValidationIssueDetail(
                field="years_experience",
                rule="years_experience_range",
                message=f"years_experience is negative: {yoe}.",
                severity="error",
                actual_value=yoe,
            )]
        if yoe > 60:
            return [ValidationIssueDetail(
                field="years_experience",
                rule="years_experience_range",
                message=f"years_experience {yoe} exceeds maximum of 60.",
                severity="warning",
                actual_value=yoe,
            )]
        return []

    def _check_confidence(
        self, profile: CandidateProfile
    ) -> list[ValidationIssueDetail]:
        conf = profile.overall_confidence
        if conf is not None and conf < self._min_confidence:
            return [ValidationIssueDetail(
                field="overall_confidence",
                rule="min_confidence",
                message=(
                    f"overall_confidence {conf:.3f} is below minimum "
                    f"{self._min_confidence:.3f}."
                ),
                severity="warning",
                actual_value=conf,
            )]
        return []

    def _check_email_present(
        self, profile: CandidateProfile
    ) -> list[ValidationIssueDetail]:
        if not profile.emails:
            return [ValidationIssueDetail(
                field="emails",
                rule="primary_email_present",
                message="No email address found for this candidate.",
                severity="warning",
                actual_value=None,
            )]
        return []

    # ── GitHub ────────────────────────────────────────────────

    def _check_github_username(
        self, profile: CandidateProfile, output: dict[str, Any]
    ) -> list[ValidationIssueDetail]:
        username = profile.links.__class__  # placeholder
        for link in profile.links:
            if link.platform == "github":
                # Extract username from URL
                m = re.search(r"github\.com/([^/\s]+)", link.url)
                if m:
                    uname = m.group(1)
                    if not _GITHUB_USER_RE.match(uname):
                        return [ValidationIssueDetail(
                            field="links",
                            rule="github_username_format",
                            message=f"GitHub username '{uname}' contains invalid characters.",
                            severity="warning",
                            actual_value=uname,
                        )]
        return []

    # ── Output dict ───────────────────────────────────────────

    def _check_output_name(
        self, output: dict[str, Any]
    ) -> list[ValidationIssueDetail]:
        # Explicitly look up each key so empty-string doesn't fall through `or`
        if "full_name" in output:
            name = output["full_name"]
        elif "name" in output:
            name = output["name"]
        else:
            return []
        if not isinstance(name, str) or not name.strip():
            return [ValidationIssueDetail(
                field="full_name",
                rule="no_empty_name",
                message="Candidate name is an empty string.",
                severity="warning",
                actual_value=repr(name),
            )]
        return []
