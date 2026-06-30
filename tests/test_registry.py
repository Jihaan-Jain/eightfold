"""
tests/test_registry.py
=======================

Unit tests for src/mapping/field_registry.py.

Covers
------
- FieldDefinition construction
- FieldRegistry.register / duplicate detection
- FieldRegistry.resolve (exact, alias, case-insensitive, unknown)
- FieldRegistry.get
- FieldRegistry.all_fields / required_fields / aliases_for
- FieldRegistry.all_aliases
- REGISTRY singleton: field count, known fields, known aliases
"""

from __future__ import annotations

import pytest

from src.mapping.field_registry import (
    REGISTRY,
    FieldDefinition,
    FieldRegistry,
)


# ================================================================
# FieldDefinition
# ================================================================


class TestFieldDefinition:
    def test_frozen(self) -> None:
        fd = FieldDefinition(
            canonical="test_field",
            aliases=("alias_a", "alias_b"),
            field_type="str",
            required=False,
            description="A test field.",
            priority=2,
            example="example value",
        )
        with pytest.raises(Exception):
            fd.canonical = "mutated"  # type: ignore[misc]

    def test_aliases_is_tuple(self) -> None:
        fd = FieldDefinition(
            canonical="f",
            aliases=("a", "b"),
            field_type="str",
            required=True,
            description="desc",
            priority=1,
            example="ex",
        )
        assert isinstance(fd.aliases, tuple)


# ================================================================
# FieldRegistry
# ================================================================


class TestFieldRegistry:
    @pytest.fixture()
    def empty_reg(self) -> FieldRegistry:
        return FieldRegistry()

    @pytest.fixture()
    def reg(self) -> FieldRegistry:
        r = FieldRegistry()
        r.register(FieldDefinition(
            canonical="email",
            aliases=("email address", "e-mail", "mail"),
            field_type="str",
            required=False,
            description="Email address.",
            priority=1,
            example="alice@example.com",
        ))
        r.register(FieldDefinition(
            canonical="full_name",
            aliases=("name", "full name", "candidate name"),
            field_type="str",
            required=False,
            description="Full name.",
            priority=1,
            example="Alice Smith",
        ))
        return r

    # ── register ──────────────────────────────────────────────

    def test_register_adds_field(self, empty_reg) -> None:
        fd = FieldDefinition(
            canonical="skills",
            aliases=("skill set",),
            field_type="list",
            required=False,
            description="Skills.",
            priority=2,
            example="Python",
        )
        empty_reg.register(fd)
        assert len(empty_reg) == 1

    def test_register_duplicate_raises(self, reg) -> None:
        fd = FieldDefinition(
            canonical="email",
            aliases=(),
            field_type="str",
            required=False,
            description="dup",
            priority=1,
            example="",
        )
        with pytest.raises(ValueError, match="Duplicate"):
            reg.register(fd)

    def test_replace_overwrites(self, reg) -> None:
        fd = FieldDefinition(
            canonical="email",
            aliases=("electronic mail",),
            field_type="str",
            required=True,
            description="Updated email.",
            priority=1,
            example="alice@example.com",
        )
        reg.replace(fd)
        assert reg.get("email").required is True
        assert reg.resolve("electronic mail") == "email"
        # Old alias gone
        assert reg.resolve("e-mail") is None

    # ── resolve ───────────────────────────────────────────────

    def test_resolve_canonical_name_itself(self, reg) -> None:
        assert reg.resolve("email") == "email"

    def test_resolve_exact_alias(self, reg) -> None:
        assert reg.resolve("e-mail") == "email"

    def test_resolve_case_insensitive(self, reg) -> None:
        assert reg.resolve("EMAIL ADDRESS") == "email"
        assert reg.resolve("Full Name") == "full_name"
        assert reg.resolve("CANDIDATE NAME") == "full_name"

    def test_resolve_with_whitespace(self, reg) -> None:
        assert reg.resolve("  email address  ") == "email"

    def test_resolve_unknown_returns_none(self, reg) -> None:
        assert reg.resolve("completely_unknown_field") is None

    def test_resolve_empty_string(self, reg) -> None:
        assert reg.resolve("") is None

    # ── get ───────────────────────────────────────────────────

    def test_get_known_field(self, reg) -> None:
        fd = reg.get("email")
        assert fd is not None
        assert fd.canonical == "email"
        assert fd.priority == 1

    def test_get_unknown_field_returns_none(self, reg) -> None:
        assert reg.get("nonexistent") is None

    # ── all_fields ────────────────────────────────────────────

    def test_all_fields_returns_list(self, reg) -> None:
        fields = reg.all_fields()
        assert isinstance(fields, list)
        assert len(fields) == 2

    def test_all_fields_contains_all_canonicals(self, reg) -> None:
        canonicals = {fd.canonical for fd in reg.all_fields()}
        assert "email" in canonicals
        assert "full_name" in canonicals

    # ── required_fields ───────────────────────────────────────

    def test_required_fields_empty_when_none(self, reg) -> None:
        assert reg.required_fields() == []

    def test_required_fields_returns_only_required(self) -> None:
        r = FieldRegistry()
        r.register(FieldDefinition(
            canonical="req_field",
            aliases=(),
            field_type="str",
            required=True,
            description="Required.",
            priority=1,
            example="",
        ))
        r.register(FieldDefinition(
            canonical="opt_field",
            aliases=(),
            field_type="str",
            required=False,
            description="Optional.",
            priority=2,
            example="",
        ))
        assert r.required_fields() == ["req_field"]

    # ── aliases_for ───────────────────────────────────────────

    def test_aliases_for_known_field(self, reg) -> None:
        aliases = reg.aliases_for("email")
        assert "email address" in aliases
        assert "e-mail" in aliases

    def test_aliases_for_unknown_field(self, reg) -> None:
        assert reg.aliases_for("ghost") == ()

    # ── all_aliases ───────────────────────────────────────────

    def test_all_aliases_is_dict(self, reg) -> None:
        alias_map = reg.all_aliases()
        assert isinstance(alias_map, dict)
        assert "email" in alias_map        # canonical itself
        assert "e-mail" in alias_map       # declared alias
        assert alias_map["e-mail"] == "email"

    # ── __contains__ / __len__ ────────────────────────────────

    def test_contains_canonical(self, reg) -> None:
        assert "email" in reg

    def test_contains_alias(self, reg) -> None:
        assert "e-mail" in reg

    def test_not_contains_unknown(self, reg) -> None:
        assert "ghost_field" not in reg

    def test_len(self, reg) -> None:
        assert len(reg) == 2


# ================================================================
# REGISTRY Singleton
# ================================================================


class TestDefaultRegistry:
    def test_has_minimum_fields(self) -> None:
        assert len(REGISTRY) >= 20

    def test_full_name_resolves(self) -> None:
        assert REGISTRY.resolve("full name") == "full_name"
        assert REGISTRY.resolve("Candidate Name") == "full_name"

    def test_first_name_resolves(self) -> None:
        assert REGISTRY.resolve("First Name") == "first_name"
        assert REGISTRY.resolve("given name") == "first_name"

    def test_email_resolves(self) -> None:
        assert REGISTRY.resolve("Email") == "emails"
        assert REGISTRY.resolve("email address") == "emails"

    def test_phone_resolves(self) -> None:
        assert REGISTRY.resolve("Mobile") == "phones"
        assert REGISTRY.resolve("Cell Phone") == "phones"

    def test_location_resolves(self) -> None:
        assert REGISTRY.resolve("city") == "location"

    def test_skills_resolves(self) -> None:
        assert REGISTRY.resolve("Technologies") == "skills"
        assert REGISTRY.resolve("Tech Stack") == "skills"

    def test_github_resolves(self) -> None:
        assert REGISTRY.resolve("github") == "github_url"
        assert REGISTRY.resolve("Github Profile") == "github_url"

    def test_linkedin_resolves(self) -> None:
        assert REGISTRY.resolve("LinkedIn") == "linkedin_url"

    def test_website_resolves(self) -> None:
        assert REGISTRY.resolve("blog") == "website"
        assert REGISTRY.resolve("personal website") == "website"
        assert REGISTRY.resolve("homepage") == "website"

    def test_company_resolves(self) -> None:
        assert REGISTRY.resolve("employer") == "current_company"

    def test_summary_resolves(self) -> None:
        assert REGISTRY.resolve("bio") == "summary"
        assert REGISTRY.resolve("About Me") == "summary"

    def test_no_required_fields_by_default(self) -> None:
        # All fields are optional — the mapping layer never enforces presence
        assert REGISTRY.required_fields() == []
