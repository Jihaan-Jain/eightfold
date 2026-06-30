"""
src/validation/schema_validator.py
=====================================

Schema-level validation of projected output dicts.

Rules
-----
- ``required_fields``     : listed fields must be present and non-null
- ``string_max_length``   : string fields must not exceed configured max
- ``list_min_length``     : list fields must have at least N items
- ``email_format``        : email fields must match RFC-compliant regex
- ``phone_format``        : phone fields must match E.164 pattern
- ``url_format``          : URL fields must have valid scheme + host
"""

from __future__ import annotations

import re
from typing import Any

from src.constants import EMAIL_REGEX, URL_REGEX
from src.logging_config import get_logger
from src.validation.report import ValidationIssueDetail

_log = get_logger(__name__)

_PHONE_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
_GITHUB_USER_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$")


class SchemaValidator:
    """
    Validates the *structure* of projected output dicts.

    Parameters
    ----------
    config:
        Optional schema config dict.  Supported keys:

        - ``required_fields`` (list[str])
        - ``string_max_length`` (dict[str, int])
        - ``list_min_length`` (dict[str, int])
        - ``validate_email_format`` (bool, default True)
        - ``validate_phone_format`` (bool, default True)
        - ``validate_url_format`` (bool, default True)
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._required:       list[str]       = cfg.get("required_fields", [])
        self._str_max:        dict[str, int]  = cfg.get("string_max_length", {})
        self._list_min:       dict[str, int]  = cfg.get("list_min_length", {})
        self._check_email:    bool            = cfg.get("validate_email_format", True)
        self._check_phone:    bool            = cfg.get("validate_phone_format", True)
        self._check_url:      bool            = cfg.get("validate_url_format", True)

    def validate(self, output: dict[str, Any]) -> list[ValidationIssueDetail]:
        """
        Validate one projected output dict.

        Returns
        -------
        list[ValidationIssueDetail]
            All schema violations found.
        """
        issues: list[ValidationIssueDetail] = []

        # ── Required fields ───────────────────────────────────
        for field_name in self._required:
            value = output.get(field_name)
            if value is None or value == "" or value == []:
                issues.append(ValidationIssueDetail(
                    field=field_name,
                    rule="required_field",
                    message=f"Required field '{field_name}' is missing or empty.",
                    severity="error",
                    actual_value=value,
                ))

        # ── String max length ─────────────────────────────────
        for field_name, max_len in self._str_max.items():
            value = output.get(field_name)
            if isinstance(value, str) and len(value) > max_len:
                issues.append(ValidationIssueDetail(
                    field=field_name,
                    rule="string_max_length",
                    message=f"'{field_name}' exceeds max length {max_len} (actual: {len(value)}).",
                    severity="warning",
                    actual_value=value[:80] + "...",
                ))

        # ── List min length ───────────────────────────────────
        for field_name, min_len in self._list_min.items():
            value = output.get(field_name)
            if isinstance(value, list) and len(value) < min_len:
                issues.append(ValidationIssueDetail(
                    field=field_name,
                    rule="list_min_length",
                    message=f"'{field_name}' has {len(value)} items (minimum: {min_len}).",
                    severity="warning",
                    actual_value=len(value),
                ))

        # ── Email format ──────────────────────────────────────
        if self._check_email:
            for field_name in ("emails", "email", "primary_email"):
                values = output.get(field_name)
                if values is None:
                    continue
                if isinstance(values, str):
                    values = [values]
                if isinstance(values, list):
                    for email in values:
                        if not isinstance(email, str):
                            continue
                        if not EMAIL_REGEX.match(email):
                            issues.append(ValidationIssueDetail(
                                field=field_name,
                                rule="email_format",
                                message=f"Invalid email format: '{email}'.",
                                severity="warning",
                                actual_value=email,
                            ))

        # ── Phone format (E.164) ──────────────────────────────
        if self._check_phone:
            for field_name in ("phones", "phone", "primary_phone"):
                values = output.get(field_name)
                if values is None:
                    continue
                if isinstance(values, str):
                    values = [values]
                if isinstance(values, list):
                    for phone in values:
                        if not isinstance(phone, str):
                            continue
                        if not _PHONE_E164_RE.match(phone):
                            issues.append(ValidationIssueDetail(
                                field=field_name,
                                rule="phone_e164_format",
                                message=f"Phone '{phone}' is not in E.164 format.",
                                severity="warning",
                                actual_value=phone,
                            ))

        # ── URL format ────────────────────────────────────────
        if self._check_url:
            for field_name in ("github_url", "linkedin_url", "website"):
                value = output.get(field_name)
                if isinstance(value, str) and value:
                    if not re.match(r"^https?://", value):
                        issues.append(ValidationIssueDetail(
                            field=field_name,
                            rule="url_format",
                            message=f"'{field_name}' does not have a valid http(s) scheme.",
                            severity="warning",
                            actual_value=value,
                        ))

        return issues
