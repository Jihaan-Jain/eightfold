"""
src/projection/field_selector.py
==================================

Applies a single field projection spec to a profile dict.

Each spec in ``ProjectionConfig.fields`` is a dict with these keys:

=============  ================================================================
Key            Description
=============  ================================================================
source         Source path in the profile dict (dot-notation supported).
output         Output key name in the projected dict.
transform      Optional named transform (see :func:`~src.projection.utils.apply_transform`).
array_path     If set, treats source value as a list and extracts this sub-field
               from each element.
flatten        If True and source is a list of dicts, flatten each item.
default        Default value when the source field is null/missing.
condition      Condition expression evaluated against the *profile* dict.
               Field is skipped when condition evaluates to False.
=============  ================================================================
"""

from __future__ import annotations

from typing import Any

from src.logging_config import get_logger
from src.projection.utils import (
    apply_transform,
    evaluate_condition,
    extract_array_path,
    get_nested,
    model_to_dict,
)

_log = get_logger(__name__)


class FieldSelector:
    """
    Applies field projection specs to a flat profile dict.

    Parameters
    ----------
    spec:
        One field projection specification dict.
    """

    def __init__(self, spec: dict[str, Any]) -> None:
        self._source:     str        = spec["source"]
        self._output:     str        = spec.get("output", spec["source"])
        self._transform:  str | None = spec.get("transform")
        self._array_path: str | None = spec.get("array_path")
        self._flatten:    bool       = bool(spec.get("flatten", False))
        self._default:    Any        = spec.get("default")
        self._condition:  str | None = spec.get("condition")

    # ── Public API ────────────────────────────────────────────

    def apply(
        self,
        profile_dict: dict[str, Any],
        missing_strategy: str = "omit",
    ) -> tuple[str, Any, bool]:
        """
        Extract and transform one field from the profile dict.

        Parameters
        ----------
        profile_dict:
            The fully-serialised ``CandidateProfile`` dict.
        missing_strategy:
            What to do when field is absent: ``"omit"``, ``"null"``,
            ``"error"``, ``"default"``.

        Returns
        -------
        tuple[str, Any, bool]
            ``(output_key, value, should_include)``

            ``should_include`` is ``False`` when the field should be
            skipped entirely (condition false or omit-on-missing).
        """
        # ── Condition guard ───────────────────────────────────
        if self._condition:
            try:
                include = evaluate_condition(self._condition, profile_dict)
            except Exception as exc:
                _log.warning(
                    "Condition evaluation error",
                    extra={
                        "field":     self._source,
                        "condition": self._condition,
                        "error":     str(exc),
                    },
                )
                include = False
            if not include:
                return self._output, None, False

        # ── Extract value ─────────────────────────────────────
        value = get_nested(profile_dict, self._source)

        # Pydantic model fallback (top-level attribute)
        if value is None and "." not in self._source:
            value = profile_dict.get(self._source)

        # Convert Pydantic models to plain dicts
        value = model_to_dict(value)

        # ── Array path extraction ─────────────────────────────
        if self._array_path and value is not None:
            value = extract_array_path(value, self._array_path)

        # ── Flatten ───────────────────────────────────────────
        if self._flatten and isinstance(value, list):
            value = [item if isinstance(item, dict) else model_to_dict(item)
                     for item in value]

        # ── Missing field handling ────────────────────────────
        if value is None or value == [] or value == {}:
            if self._default is not None:
                value = self._default
            elif missing_strategy == "omit":
                return self._output, None, False
            elif missing_strategy == "null":
                value = None
            elif missing_strategy == "error":
                _log.warning(
                    "Required field missing",
                    extra={"field": self._source},
                )
                return self._output, None, False
            else:
                value = self._default

        # ── Transform ─────────────────────────────────────────
        if self._transform and value is not None:
            try:
                value = apply_transform(value, self._transform)
            except Exception as exc:
                _log.warning(
                    "Transform error",
                    extra={
                        "field":     self._source,
                        "transform": self._transform,
                        "error":     str(exc),
                    },
                )

        return self._output, value, True

    @property
    def output_key(self) -> str:
        return self._output

    @property
    def source_key(self) -> str:
        return self._source
