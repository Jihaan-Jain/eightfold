"""
tests/test_projector.py
========================

Unit tests for the projection layer.
"""
from __future__ import annotations

import pytest
from src.models import CandidateProfile, SourceType
from src.projection.config_resolver import ConfigResolver, ProjectionConfig
from src.projection.factory import ProjectorFactory
from src.projection.field_selector import FieldSelector
from src.projection.projector import Projector
from src.projection.utils import (
    apply_transform,
    evaluate_condition,
    extract_array_path,
    get_nested,
    set_nested,
)


# ── Helpers ──────────────────────────────────────────────────────


def _profile(**kwargs) -> CandidateProfile:
    defaults = dict(
        full_name="Alice Smith",
        emails=["alice@example.com"],
        phones=["+14155552671"],
        headline="Senior ML Engineer",
        years_experience=8.0,
        overall_confidence=0.91,
    )
    defaults.update(kwargs)
    return CandidateProfile(**defaults)


# ================================================================
# Utilities
# ================================================================


class TestGetNested:
    def test_simple_key(self):
        assert get_nested({"a": 1}, "a") == 1

    def test_nested_key(self):
        assert get_nested({"a": {"b": 2}}, "a.b") == 2

    def test_missing_returns_default(self):
        assert get_nested({}, "x", default="N/A") == "N/A"

    def test_none_intermediate(self):
        assert get_nested({"a": None}, "a.b", default=0) == 0

    def test_three_levels(self):
        assert get_nested({"a": {"b": {"c": 42}}}, "a.b.c") == 42


class TestSetNested:
    def test_simple_set(self):
        d: dict = {}
        set_nested(d, "x", 1)
        assert d["x"] == 1

    def test_nested_set_creates_intermediates(self):
        d: dict = {}
        set_nested(d, "a.b.c", 99)
        assert d["a"]["b"]["c"] == 99


class TestExtractArrayPath:
    def test_simple_field(self):
        items = [{"name": "Python"}, {"name": "SQL"}]
        assert extract_array_path(items, "name") == ["Python", "SQL"]

    def test_non_list_returns_empty(self):
        assert extract_array_path("not a list", "name") == []

    def test_missing_field_excluded(self):
        items = [{"name": "Python"}, {"other": "x"}]
        result = extract_array_path(items, "name")
        assert result == ["Python"]

    def test_empty_list(self):
        assert extract_array_path([], "name") == []


class TestApplyTransform:
    def test_uppercase(self):
        assert apply_transform("hello", "uppercase") == "HELLO"

    def test_lowercase(self):
        assert apply_transform("HELLO", "lowercase") == "hello"

    def test_title(self):
        assert apply_transform("hello world", "title") == "Hello World"

    def test_strip(self):
        assert apply_transform("  hi  ", "strip") == "hi"

    def test_truncate(self):
        assert apply_transform("hello world", "truncate:5") == "hello"

    def test_join(self):
        assert apply_transform(["a", "b", "c"], "join:,") == "a,b,c"

    def test_first(self):
        assert apply_transform([10, 20, 30], "first") == 10

    def test_last(self):
        assert apply_transform([10, 20, 30], "last") == 30

    def test_count(self):
        assert apply_transform([1, 2, 3], "count") == 3

    def test_str(self):
        assert apply_transform(42, "str") == "42"

    def test_int(self):
        assert apply_transform("5", "int") == 5

    def test_float(self):
        assert apply_transform("3.14", "float") == pytest.approx(3.14)

    def test_bool(self):
        assert apply_transform(1, "bool") is True

    def test_none_passthrough(self):
        assert apply_transform(None, "uppercase") is None

    def test_unknown_transform_passthrough(self):
        assert apply_transform("hello", "nonexistent") == "hello"


class TestEvaluateCondition:
    def test_truthy_field(self):
        assert evaluate_condition("name", {"name": "Alice"}) is True

    def test_falsy_field(self):
        assert evaluate_condition("name", {"name": ""}) is False

    def test_not_condition(self):
        assert evaluate_condition("not name", {"name": ""}) is True

    def test_equals(self):
        assert evaluate_condition('status == active', {"status": "active"}) is True

    def test_not_equals(self):
        assert evaluate_condition('status != draft', {"status": "active"}) is True

    def test_greater_than(self):
        assert evaluate_condition("score > 5", {"score": 10}) is True

    def test_less_than(self):
        assert evaluate_condition("score < 5", {"score": 3}) is True

    def test_missing_field_is_falsy(self):
        assert evaluate_condition("missing_field", {}) is False


# ================================================================
# FieldSelector
# ================================================================


class TestFieldSelector:
    def test_simple_source_output(self):
        spec = {"source": "full_name", "output": "name"}
        sel = FieldSelector(spec)
        d = {"full_name": "Alice Smith"}
        key, val, include = sel.apply(d)
        assert key == "name"
        assert val == "Alice Smith"
        assert include is True

    def test_missing_omit_strategy(self):
        spec = {"source": "missing_field", "output": "x"}
        sel = FieldSelector(spec)
        _, _, include = sel.apply({}, missing_strategy="omit")
        assert include is False

    def test_missing_null_strategy(self):
        spec = {"source": "missing_field", "output": "x"}
        sel = FieldSelector(spec)
        key, val, include = sel.apply({}, missing_strategy="null")
        assert include is True
        assert val is None

    def test_default_value(self):
        spec = {"source": "missing_field", "output": "x", "default": "N/A"}
        sel = FieldSelector(spec)
        _, val, include = sel.apply({})
        assert include is True
        assert val == "N/A"

    def test_transform_applied(self):
        spec = {"source": "name", "output": "name_upper", "transform": "uppercase"}
        sel = FieldSelector(spec)
        _, val, _ = sel.apply({"name": "alice"})
        assert val == "ALICE"

    def test_array_path(self):
        spec = {"source": "skills", "output": "skill_names", "array_path": "name"}
        sel = FieldSelector(spec)
        d = {"skills": [{"name": "Python"}, {"name": "SQL"}]}
        _, val, _ = sel.apply(d)
        assert val == ["Python", "SQL"]

    def test_condition_false_skips_field(self):
        # condition='include_score' → falsy when include_score is False → field skipped
        spec = {"source": "score", "output": "score",
                "condition": "include_score"}
        sel = FieldSelector(spec)
        _, _, include = sel.apply({"score": 10, "include_score": False})
        assert include is False

    def test_condition_true_includes_field(self):
        spec = {"source": "score", "output": "score",
                "condition": "include_score"}
        sel = FieldSelector(spec)
        _, val, include = sel.apply({"score": 10, "include_score": True})
        assert include is True
        assert val == 10

    def test_dot_path_source(self):
        spec = {"source": "location.city", "output": "city"}
        sel = FieldSelector(spec)
        _, val, include = sel.apply({"location": {"city": "San Francisco"}})
        assert include is True
        assert val == "San Francisco"

    def test_output_key_property(self):
        spec = {"source": "emails", "output": "email_list"}
        assert FieldSelector(spec).output_key == "email_list"

    def test_source_key_property(self):
        spec = {"source": "emails", "output": "email_list"}
        assert FieldSelector(spec).source_key == "emails"


# ================================================================
# ProjectionConfig
# ================================================================


class TestProjectionConfig:
    def test_default_is_pass_through(self):
        cfg = ProjectionConfig.default()
        assert cfg.pass_through is True

    def test_with_fields_not_pass_through(self):
        cfg = ProjectionConfig({"fields": [{"source": "a", "output": "b"}]})
        assert cfg.pass_through is False

    def test_include_flags(self):
        cfg = ProjectionConfig({
            "include_confidence": False,
            "include_provenance": True,
            "include_quality_metrics": False,
        })
        assert cfg.include_confidence is False
        assert cfg.include_provenance is True
        assert cfg.include_quality_metrics is False

    def test_missing_field_strategy_default(self):
        cfg = ProjectionConfig.default()
        assert cfg.missing_field_strategy == "omit"

    def test_drop_list(self):
        cfg = ProjectionConfig({"drop": ["candidate_id", "provenance"]})
        assert "candidate_id" in cfg.drop


# ================================================================
# ConfigResolver
# ================================================================


class TestConfigResolver:
    def test_none_path_returns_default(self):
        cfg = ConfigResolver(None).resolve()
        assert cfg.pass_through is True

    def test_missing_file_returns_default(self):
        cfg = ConfigResolver("/nonexistent/path/config.yaml").resolve()
        assert cfg.pass_through is True

    def test_from_dict(self):
        cfg = ConfigResolver.from_dict({
            "include_confidence": False,
            "fields": [{"source": "full_name", "output": "name"}],
        })
        assert cfg.include_confidence is False
        assert len(cfg.fields) == 1


# ================================================================
# Projector
# ================================================================


class TestProjectorPassThrough:
    def test_includes_full_name(self):
        p = ProjectorFactory.build_pass_through()
        profile = _profile()
        output = p.project(profile)
        assert output.get("full_name") == "Alice Smith"

    def test_includes_emails(self):
        p = ProjectorFactory.build_pass_through()
        output = p.project(_profile())
        assert "alice@example.com" in output.get("emails", [])

    def test_confidence_included_by_default(self):
        p = ProjectorFactory.build_pass_through()
        output = p.project(_profile())
        assert "overall_confidence" in output

    def test_provenance_omitted_by_default(self):
        p = ProjectorFactory.build_pass_through()
        output = p.project(_profile())
        # default config has include_provenance=False
        assert "provenance" not in output

    def test_quality_metrics_included(self):
        # quality_metrics is None on a bare CandidateProfile.
        # After merging it gets populated. Test that the key is present
        # (even if None) in pass-through mode with null strategy.
        p = ProjectorFactory.build(config_dict={"missing_field_strategy": "null"})
        output = p.project(_profile())
        # In null strategy, quality_metrics key must be present (as None)
        assert "quality_metrics" in output

    def test_project_many_returns_list(self):
        p = ProjectorFactory.build_pass_through()
        profiles = [_profile(), _profile()]
        outputs = p.project_many(profiles)
        assert len(outputs) == 2

    def test_drop_field(self):
        p = ProjectorFactory.build(config_dict={
            "drop": ["overall_confidence"]
        })
        output = p.project(_profile())
        assert "overall_confidence" not in output


class TestProjectorWithSpecs:
    def test_rename_field(self):
        p = ProjectorFactory.build(config_dict={
            "fields": [{"source": "full_name", "output": "name"}]
        })
        output = p.project(_profile())
        assert "name" in output
        assert output["name"] == "Alice Smith"
        assert "full_name" not in output

    def test_transform_uppercase(self):
        p = ProjectorFactory.build(config_dict={
            "fields": [{"source": "full_name", "output": "name", "transform": "uppercase"}]
        })
        output = p.project(_profile())
        assert output["name"] == "ALICE SMITH"

    def test_first_email_extracted(self):
        p = ProjectorFactory.build(config_dict={
            "fields": [{"source": "emails", "output": "primary_email", "transform": "first"}]
        })
        output = p.project(_profile())
        assert output["primary_email"] == "alice@example.com"

    def test_missing_omitted(self):
        p = ProjectorFactory.build(config_dict={
            "missing_field_strategy": "omit",
            "fields": [{"source": "no_such_field", "output": "x"}]
        })
        output = p.project(_profile())
        assert "x" not in output

    def test_default_value_used(self):
        p = ProjectorFactory.build(config_dict={
            "fields": [{"source": "no_such_field", "output": "x", "default": 0}]
        })
        output = p.project(_profile())
        assert output.get("x") == 0

    def test_suppress_confidence(self):
        p = ProjectorFactory.build(config_dict={
            "include_confidence": False,
            "fields": [
                {"source": "full_name", "output": "name"},
                {"source": "overall_confidence", "output": "overall_confidence"},
            ]
        })
        output = p.project(_profile())
        assert "overall_confidence" not in output

    def test_conditional_field_included(self):
        p = ProjectorFactory.build(config_dict={
            "fields": [
                {"source": "overall_confidence", "output": "score",
                 "condition": "full_name"}
            ]
        })
        output = p.project(_profile())
        assert "score" in output

    def test_conditional_field_excluded(self):
        p = ProjectorFactory.build(config_dict={
            "fields": [
                {"source": "overall_confidence", "output": "score",
                 "condition": "not full_name"}
            ]
        })
        output = p.project(_profile())
        assert "score" not in output


class TestProjectorFactory:
    def test_build_minimal(self):
        p = ProjectorFactory.build_minimal()
        output = p.project(_profile())
        assert "name" in output
        assert "id" in output

    def test_minimal_skills_as_names(self):
        from src.models import Skill
        profile = _profile(
            skills=[Skill(name="Python", normalized_name="Python", confidence=0.9)]
        )
        p = ProjectorFactory.build_minimal()
        output = p.project(profile)
        assert isinstance(output.get("skills"), list)
