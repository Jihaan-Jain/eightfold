"""
src/projection/utils.py
========================

Shared utilities for the projection layer.
"""

from __future__ import annotations

import re
from typing import Any


def get_nested(obj: dict[str, Any], path: str, default: Any = None) -> Any:
    """
    Traverse a nested dict using a dot-separated path.

    Examples
    --------
    >>> get_nested({"a": {"b": 1}}, "a.b")
    1
    >>> get_nested({"a": {}}, "a.c", default="N/A")
    'N/A'
    """
    parts = path.split(".")
    current = obj
    for part in parts:
        if not isinstance(current, dict):
            return default
        current = current.get(part, default)
        if current is None:
            return default
    return current


def set_nested(obj: dict[str, Any], path: str, value: Any) -> None:
    """Set a value at a dot-separated path, creating intermediate dicts."""
    parts = path.split(".")
    current = obj
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def extract_array_path(value: Any, field_path: str) -> list[Any]:
    """
    Extract a sub-field from each element of a list.

    Examples
    --------
    >>> extract_array_path([{"name": "Python"}], "name")
    ['Python']
    """
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, dict):
            v = get_nested(item, field_path)
        elif hasattr(item, field_path):
            v = getattr(item, field_path, None)
        else:
            try:
                v = item.model_dump().get(field_path)
            except Exception:
                v = None
        if v is not None:
            result.append(v)
    return result


def apply_transform(value: Any, transform: str) -> Any:
    """
    Apply a named transform to a value.

    Supported transforms
    --------------------
    uppercase, lowercase, title, strip, truncate:<n>,
    join:<sep>, first, last, count, bool, str, int, float
    """
    if value is None:
        return value

    if transform == "uppercase":
        return str(value).upper()
    if transform == "lowercase":
        return str(value).lower()
    if transform == "title":
        return str(value).title()
    if transform == "strip":
        return str(value).strip()
    if transform.startswith("truncate:"):
        n = int(transform.split(":")[1])
        return str(value)[:n]
    if transform.startswith("join:"):
        sep = transform.split(":", 1)[1]
        return sep.join(str(v) for v in value) if isinstance(value, list) else str(value)
    if transform == "first":
        return value[0] if isinstance(value, list) and value else value
    if transform == "last":
        return value[-1] if isinstance(value, list) and value else value
    if transform == "count":
        return len(value) if isinstance(value, list) else (1 if value else 0)
    if transform == "bool":
        return bool(value)
    if transform == "str":
        return str(value)
    if transform == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if transform == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return value


def model_to_dict(obj: Any) -> Any:
    """Recursively convert Pydantic models, lists, and primitives to plain dicts."""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [model_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: model_to_dict(v) for k, v in obj.items()}
    if hasattr(obj, "model_dump"):
        return model_to_dict(obj.model_dump())
    return obj


def evaluate_condition(condition: str, profile_dict: dict[str, Any]) -> bool:
    """
    Evaluate a simple condition string against the profile dict.

    Supported syntax
    ----------------
    ``"field_name"``               — field is truthy
    ``"not field_name"``           — field is falsy
    ``"field_name == value"``      — field equals value
    ``"field_name != value"``      — field does not equal value
    ``"field_name > N"``           — field (numeric) > N
    ``"field_name < N"``           — field (numeric) < N
    """
    condition = condition.strip()

    # not <field>
    if condition.startswith("not "):
        field = condition[4:].strip()
        return not bool(get_nested(profile_dict, field))

    # <field> == <value>
    m = re.match(r"^(.+?)\s*==\s*(.+)$", condition)
    if m:
        field, expected = m.group(1).strip(), m.group(2).strip().strip("\"'")
        return str(get_nested(profile_dict, field, "")) == expected

    # <field> != <value>
    m = re.match(r"^(.+?)\s*!=\s*(.+)$", condition)
    if m:
        field, expected = m.group(1).strip(), m.group(2).strip().strip("\"'")
        return str(get_nested(profile_dict, field, "")) != expected

    # <field> > N
    m = re.match(r"^(.+?)\s*>\s*(\d+\.?\d*)$", condition)
    if m:
        field, n = m.group(1).strip(), float(m.group(2))
        v = get_nested(profile_dict, field, 0)
        try:
            return float(v) > n
        except (TypeError, ValueError):
            return False

    # <field> < N
    m = re.match(r"^(.+?)\s*<\s*(\d+\.?\d*)$", condition)
    if m:
        field, n = m.group(1).strip(), float(m.group(2))
        v = get_nested(profile_dict, field, 0)
        try:
            return float(v) < n
        except (TypeError, ValueError):
            return False

    # bare field name → truthy check
    return bool(get_nested(profile_dict, condition))
