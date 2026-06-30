"""
src/mapping/utils.py
=====================

Shared utility functions for all mapper modules.

Provides
--------
- :func:`safe_get`          — safely traverse nested dicts / lists
- :func:`flatten_dict`      — flatten a nested dict to dot-separated keys
- :func:`find_alias`        — look up a raw field name against the registry
- :func:`split_name`        — heuristic first/last name splitter
- :func:`parse_skill_list`  — parse a raw skill string into a list
- :func:`clean_str`         — strip / normalise a raw string value
- :func:`make_provenance`   — construct a :class:`~src.models.Provenance` entry
"""

from __future__ import annotations

import re
from datetime import timezone, datetime
from typing import Any

from src.models import (
    CanonicalRecord,
    MappingMethod,
    NormalizationMethod,
    ProcessingStage,
    Provenance,
    SourceType,
)


# ================================================================
# Safe Access
# ================================================================


def safe_get(obj: Any, *keys: str | int, default: Any = None) -> Any:
    """
    Safely traverse a nested dict / list structure.

    Parameters
    ----------
    obj:
        Root object (dict, list, or scalar).
    *keys:
        Sequence of keys or integer indices to follow.
    default:
        Value to return when any step fails.

    Returns
    -------
    Any
        The value at the resolved path, or ``default`` on any error.

    Examples
    --------
    ::

        safe_get({"a": {"b": 1}}, "a", "b")       # 1
        safe_get({"a": [10, 20]}, "a", 1)          # 20
        safe_get({"a": None}, "a", "b")            # None
        safe_get({}, "missing", default="N/A")     # "N/A"
    """
    current = obj
    for key in keys:
        if current is None:
            return default
        try:
            if isinstance(key, int):
                current = current[key]
            elif isinstance(current, dict):
                current = current.get(key)
            else:
                return default
        except (KeyError, IndexError, TypeError):
            return default
    return current if current is not None else default


# ================================================================
# Dict Flattening
# ================================================================


def flatten_dict(
    obj: dict[str, Any],
    prefix: str = "",
    separator: str = ".",
    max_depth: int = 5,
    _depth: int = 0,
) -> dict[str, Any]:
    """
    Recursively flatten a nested dict to a single-level dict with
    dot-separated keys.

    Parameters
    ----------
    obj:
        The nested dict to flatten.
    prefix:
        Key prefix to prepend to every key in the result.
    separator:
        Character(s) used to join parent and child keys.
    max_depth:
        Maximum recursion depth.  Deeper objects are stored verbatim.
    _depth:
        Internal recursion counter — do not set manually.

    Returns
    -------
    dict[str, Any]
        Flattened key-value pairs.

    Examples
    --------
    ::

        flatten_dict({"a": {"b": 1, "c": 2}})
        # {"a.b": 1, "a.c": 2}

        flatten_dict({"x": [1, 2]})
        # {"x": [1, 2]}   (lists are left as-is)
    """
    result: dict[str, Any] = {}
    for key, value in obj.items():
        full_key = f"{prefix}{separator}{key}" if prefix else key
        if (
            isinstance(value, dict)
            and value
            and _depth < max_depth
        ):
            result.update(
                flatten_dict(value, full_key, separator, max_depth, _depth + 1)
            )
        else:
            result[full_key] = value
    return result


# ================================================================
# String Cleaning
# ================================================================


def clean_str(value: Any) -> str | None:
    """
    Convert a raw field value to a stripped string, or ``None`` when
    the value is empty, ``None``, or only whitespace.

    Parameters
    ----------
    value:
        Any raw value from a source field.

    Returns
    -------
    str | None
        Stripped string, or ``None`` for empty / null values.
    """
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


# ================================================================
# Name Splitting
# ================================================================


def split_name(full_name: str) -> tuple[str | None, str | None]:
    """
    Heuristic split of a full-name string into first and last name.

    Does **not** use any NLP.  Handles common formats:

    - ``"Alice Smith"``               → ``("Alice", "Smith")``
    - ``"Alice Marie Smith"``         → ``("Alice", "Smith")``
    - ``"Smith, Alice"``              → ``("Alice", "Smith")``
    - ``"Alice"``                     → ``("Alice", None)``

    Parameters
    ----------
    full_name:
        Full name string to split.

    Returns
    -------
    tuple[str | None, str | None]
        ``(first_name, last_name)`` pair.  Either component may be
        ``None`` when the name is too short to split.
    """
    name = full_name.strip()
    if not name:
        return None, None

    # "Last, First" format
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[1], parts[0]

    parts = name.split()
    if len(parts) == 1:
        return parts[0], None
    # First word = first name; last word = last name
    return parts[0], parts[-1]


# ================================================================
# Skill Parsing
# ================================================================

# Delimiters used to split raw skill strings in CSV/ATS sources.
_SKILL_SPLIT_RE = re.compile(r"[,;|/•\u2022\u00b7\n\r]+")


def parse_skill_list(raw: Any) -> list[str]:
    """
    Parse a raw skills field into a list of individual skill strings.

    Handles:

    - Already a list → elements cleaned and returned
    - Comma / semicolon / pipe / bullet separated string
    - Single skill string
    - ``None`` / empty → ``[]``

    Parameters
    ----------
    raw:
        Raw field value from a source record.

    Returns
    -------
    list[str]
        De-duplicated, non-empty skill strings in original order.
    """
    if not raw:
        return []

    if isinstance(raw, list):
        items = [clean_str(item) for item in raw]
        return [s for s in items if s]

    text = clean_str(raw)
    if not text:
        return []

    parts = _SKILL_SPLIT_RE.split(text)
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        skill = part.strip()
        if skill and skill.lower() not in seen:
            seen.add(skill.lower())
            result.append(skill)
    return result


# ================================================================
# URL Detection
# ================================================================

_GITHUB_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9\-]+)/?",
    re.IGNORECASE,
)
_LINKEDIN_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9\-_%]+)/?",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def classify_url(url: str) -> tuple[str, str]:
    """
    Classify a URL as ``"github"``, ``"linkedin"``, or ``"website"``.

    Parameters
    ----------
    url:
        URL string to classify.

    Returns
    -------
    tuple[str, str]
        ``(platform, url)`` pair.
    """
    url = url.strip()
    if _GITHUB_URL_RE.search(url):
        return "github", url
    if _LINKEDIN_URL_RE.search(url):
        return "linkedin", url
    return "website", url


# ================================================================
# Provenance Builder
# ================================================================


def make_provenance(
    *,
    field: str,
    source: SourceType,
    method: MappingMethod,
    original_value: Any,
    mapped_value: Any,
    confidence: float = 1.0,
    raw_field_name: str | None = None,
) -> Provenance:
    """
    Construct a :class:`~src.models.Provenance` entry for the mapping
    stage.

    Parameters
    ----------
    field:
        Canonical field name being mapped.
    source:
        Source type of the originating :class:`~src.models.RawRecord`.
    method:
        :class:`~src.models.MappingMethod` that resolved this field.
    original_value:
        Raw value before mapping.
    mapped_value:
        Value after mapping (same type as stored in
        :class:`~src.models.CanonicalRecord`).
    confidence:
        Mapping confidence.  ``1.0`` for direct / alias maps;
        ``0.9`` for inferred; ``0.8`` for section-detected.
    raw_field_name:
        The source-side field name.  Included in ``reason`` for
        alias and nested maps.

    Returns
    -------
    Provenance
        Frozen provenance entry ready to append to
        :attr:`CanonicalRecord.provenance`.
    """
    if raw_field_name:
        reason = f"[{method.value}] {raw_field_name!r} → {field!r}"
    else:
        reason = f"[{method.value}] → {field!r}"

    return Provenance(
        field=field,
        source=source,
        method=NormalizationMethod.NONE,   # mapping does not normalise
        original_value=original_value,
        normalized_value=mapped_value,
        processing_stage=ProcessingStage.MAPPING,
        confidence=confidence,
        reason=reason,
        timestamp=datetime.now(tz=timezone.utc),
    )


# ================================================================
# CanonicalRecord Field Setter
# ================================================================


def set_field(
    record: CanonicalRecord,
    field: str,
    value: Any,
    provenance: Provenance,
) -> None:
    """
    Set a scalar field on a :class:`~src.models.CanonicalRecord` and
    register its provenance and mapped-field tracking in a single call.

    For list fields (``emails``, ``phones``, ``skills``, …) the value
    is **appended** rather than assigned.

    Parameters
    ----------
    record:
        The mutable :class:`~src.models.CanonicalRecord` being built.
    field:
        Canonical field name (must be a real attribute on the record).
    value:
        The mapped value to store.
    provenance:
        Pre-built :class:`~src.models.Provenance` entry for this field.
    """
    _LIST_FIELDS = {
        "emails", "phones", "skills", "experience",
        "education", "certifications", "projects",
    }
    if field in _LIST_FIELDS:
        existing: list = getattr(record, field)
        if isinstance(value, list):
            existing.extend(value)
        else:
            existing.append(value)
    else:
        setattr(record, field, value)

    if field not in record.mapped_fields:
        record.mapped_fields.append(field)
    record.provenance.append(provenance)
