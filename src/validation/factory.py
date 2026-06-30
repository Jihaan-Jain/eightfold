"""
src/validation/factory.py
==========================

Factory for building configured :class:`~src.validation.validator.Validator`
instances.
"""

from __future__ import annotations

from typing import Any

from src.validation.business_validator import BusinessValidator
from src.validation.schema_validator import SchemaValidator
from src.validation.validator import Validator


class ValidatorFactory:
    """Factory for :class:`~src.validation.validator.Validator` instances."""

    @classmethod
    def build(cls, config: dict[str, Any] | None = None) -> Validator:
        """
        Build a :class:`~src.validation.validator.Validator`.

        Parameters
        ----------
        config:
            Optional config dict.  Supported keys:

            ``schema`` (dict):
                Passed to :class:`~src.validation.schema_validator.SchemaValidator`.
            ``business`` (dict):
                Passed to :class:`~src.validation.business_validator.BusinessValidator`.
            ``fail_on_error`` (bool, default ``True``):
                Whether errors mark a candidate as invalid.

        Returns
        -------
        Validator
        """
        cfg = config or {}
        return Validator(
            schema_validator=SchemaValidator(cfg.get("schema")),
            business_validator=BusinessValidator(cfg.get("business")),
            fail_on_error=cfg.get("fail_on_error", True),
        )

    @classmethod
    def build_strict(cls) -> Validator:
        """
        Strict validator: requires full_name + at least one email,
        and flags any confidence below 0.5.
        """
        return cls.build(config={
            "schema": {
                "required_fields":       ["full_name", "emails"],
                "validate_email_format": True,
                "validate_phone_format": True,
            },
            "business": {
                "min_confidence":     0.50,
                "require_email":      True,
                "check_future_dates": True,
            },
            "fail_on_error": True,
        })

    @classmethod
    def build_lenient(cls) -> Validator:
        """
        Lenient validator: no required fields, warnings only.
        """
        return cls.build(config={
            "schema": {
                "required_fields":       [],
                "validate_email_format": True,
                "validate_phone_format": False,
            },
            "business": {
                "min_confidence":     0.0,
                "require_email":      False,
                "check_future_dates": True,
            },
            "fail_on_error": False,
        })
