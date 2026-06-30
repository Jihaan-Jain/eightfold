"""
src/mapping/field_registry.py
==============================

The canonical field registry for the mapping layer.

Every canonical field is defined **once** here with:

- A list of source-side aliases (case-insensitive)
- The field's Python type name
- Whether it is required in a valid :class:`~src.models.CanonicalRecord`
- A human-readable description
- A priority tier (1 = most important)
- An example value

Every mapper queries this registry to resolve raw field names —
**no hardcoded field names live inside mapper classes**.

Usage
-----
::

    from src.mapping.field_registry import REGISTRY

    # resolve a raw field name
    canonical = REGISTRY.resolve("First Name")   # "first_name"
    defn      = REGISTRY.get("email")

    # iterate all fields
    for fd in REGISTRY.all_fields():
        print(fd.canonical, fd.required)
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ================================================================
# FieldDefinition
# ================================================================


@dataclass(frozen=True)
class FieldDefinition:
    """
    Complete definition of one canonical field.

    Attributes
    ----------
    canonical:
        The canonical field name — exactly the attribute name on
        :class:`~src.models.CanonicalRecord`
        (e.g. ``"email"``, ``"full_name"``).
    aliases:
        Source-side aliases that should resolve to this field.
        All stored lowercase for case-insensitive matching.
    field_type:
        Python type hint string (informational).
    required:
        ``True`` if a valid :class:`~src.models.CanonicalRecord` must
        have this field populated.
    description:
        Human-readable description of the field's semantics.
    priority:
        Importance tier: ``1`` = critical, ``2`` = important,
        ``3`` = supplementary.
    example:
        Representative example value (as a string).
    """

    canonical:   str
    aliases:     tuple[str, ...]
    field_type:  str
    required:    bool
    description: str
    priority:    int
    example:     str


# ================================================================
# FieldRegistry
# ================================================================


class FieldRegistry:
    """
    Registry of all canonical fields and their source-side aliases.

    The registry maintains two internal indices:

    1. ``_fields``     — ``{canonical_name: FieldDefinition}``
    2. ``_alias_map``  — ``{lowercase_alias: canonical_name}``

    Resolution is always case-insensitive.  Aliases take precedence;
    if a raw key exactly equals a canonical name it also resolves
    correctly because each field registers its own name as an alias.
    """

    def __init__(self) -> None:
        self._fields:    dict[str, FieldDefinition] = {}
        self._alias_map: dict[str, str] = {}

    # ── Registration ─────────────────────────────────────────

    def register(self, fd: FieldDefinition) -> None:
        """
        Add a :class:`FieldDefinition` to the registry.

        Registers all aliases (including the canonical name itself).
        Raises :class:`ValueError` on duplicate canonical name.
        """
        if fd.canonical in self._fields:
            raise ValueError(
                f"Duplicate canonical field: {fd.canonical!r}. "
                "Call replace() to overwrite."
            )
        self._fields[fd.canonical] = fd
        # Register canonical name as an alias
        self._alias_map[fd.canonical.lower()] = fd.canonical
        # Register all declared aliases
        for alias in fd.aliases:
            low = alias.lower()
            if low not in self._alias_map:
                self._alias_map[low] = fd.canonical

    def replace(self, fd: FieldDefinition) -> None:
        """Overwrite an existing field definition."""
        if fd.canonical in self._fields:
            old = self._fields[fd.canonical]
            for alias in old.aliases:
                self._alias_map.pop(alias.lower(), None)
            self._alias_map.pop(old.canonical.lower(), None)
            del self._fields[fd.canonical]
        self.register(fd)

    # ── Resolution ────────────────────────────────────────────

    def resolve(self, raw_name: str) -> str | None:
        """
        Return the canonical field name for a raw source-side key.

        Parameters
        ----------
        raw_name:
            Raw field name as it appears in the source (any case).

        Returns
        -------
        str | None
            The canonical field name, or ``None`` when the raw name is
            not registered as an alias of any canonical field.

        Examples
        --------
        ::

            REGISTRY.resolve("First Name")          # "first_name"
            REGISTRY.resolve("EMAIL ADDRESS")       # "email"
            REGISTRY.resolve("completely_unknown")  # None
        """
        return self._alias_map.get(raw_name.strip().lower())

    def get(self, canonical: str) -> FieldDefinition | None:
        """
        Return the :class:`FieldDefinition` for a canonical field name.

        Returns ``None`` when the canonical name is not registered.
        """
        return self._fields.get(canonical)

    def all_fields(self) -> list[FieldDefinition]:
        """Return all registered :class:`FieldDefinition` objects."""
        return list(self._fields.values())

    def required_fields(self) -> list[str]:
        """Return canonical names of all required fields."""
        return [fd.canonical for fd in self._fields.values() if fd.required]

    def aliases_for(self, canonical: str) -> tuple[str, ...]:
        """
        Return the registered aliases for a canonical field.

        Returns an empty tuple when the canonical name is not found.
        """
        fd = self._fields.get(canonical)
        return fd.aliases if fd else ()

    def all_aliases(self) -> dict[str, str]:
        """Return the full ``{lowercase_alias: canonical}`` alias map."""
        return dict(self._alias_map)

    def __contains__(self, item: str) -> bool:
        return item in self._fields or item.lower() in self._alias_map

    def __len__(self) -> int:
        return len(self._fields)


# ================================================================
# Default Registry — singleton instance
# ================================================================


def _build_default_registry() -> FieldRegistry:
    """Construct and return the pre-populated default registry."""
    reg = FieldRegistry()

    # ── Identity / Name ───────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="full_name",
        aliases=(
            "name", "full name", "candidate name", "candidate_name",
            "applicant name", "applicant_name", "fullname",
            "contact name", "contact_name", "person name",
        ),
        field_type="str",
        required=False,
        description="Candidate's full name.",
        priority=1,
        example="Alice Smith",
    ))
    reg.register(FieldDefinition(
        canonical="first_name",
        aliases=(
            "first name", "firstname", "given name", "given_name",
            "fname", "forename",
        ),
        field_type="str",
        required=False,
        description="Candidate's first / given name.",
        priority=1,
        example="Alice",
    ))
    reg.register(FieldDefinition(
        canonical="last_name",
        aliases=(
            "last name", "lastname", "surname", "family name",
            "family_name", "lname",
        ),
        field_type="str",
        required=False,
        description="Candidate's last / family name.",
        priority=1,
        example="Smith",
    ))

    # ── Contact ───────────────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="emails",
        aliases=(
            "email", "email address", "email_address", "e-mail",
            "e_mail", "mail", "electronic mail",
        ),
        field_type="list[str]",
        required=False,
        description="Email address(es).",
        priority=1,
        example="alice@example.com",
    ))
    reg.register(FieldDefinition(
        canonical="phones",
        aliases=(
            "phone", "phone number", "phone_number", "mobile",
            "mobile number", "mobile_number", "cell", "cell phone",
            "telephone", "tel", "contact number", "contact_number",
        ),
        field_type="list[str]",
        required=False,
        description="Phone number(s).",
        priority=1,
        example="+1-555-123-4567",
    ))

    # ── Location ──────────────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="location",
        aliases=(
            "location", "city", "city state", "city_state",
            "address", "current location", "current_location",
            "residence", "region", "area",
        ),
        field_type="str",
        required=False,
        description="Location string (city, country, etc.).",
        priority=2,
        example="Bangalore, India",
    ))

    # ── Professional Headline / Summary ───────────────────────
    reg.register(FieldDefinition(
        canonical="headline",
        aliases=(
            "headline", "title", "job title", "job_title",
            "current title", "current_title", "position",
            "professional title", "professional_title",
            "role", "designation",
        ),
        field_type="str",
        required=False,
        description="Professional headline or current job title.",
        priority=2,
        example="Senior ML Engineer",
    ))
    reg.register(FieldDefinition(
        canonical="summary",
        aliases=(
            "summary", "bio", "about", "about me", "profile",
            "professional summary", "professional_summary",
            "objective", "career objective", "introduction",
            "overview", "description",
        ),
        field_type="str",
        required=False,
        description="Free-text professional summary or bio.",
        priority=2,
        example="10+ years of ML engineering experience…",
    ))

    # ── Current Company ───────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="current_company",
        aliases=(
            "company", "current company", "current_company",
            "employer", "current employer", "current_employer",
            "organization", "organisation", "org",
            "company name", "company_name",
        ),
        field_type="str",
        required=False,
        description="Current or most recent employer.",
        priority=2,
        example="Eightfold AI",
    ))
    reg.register(FieldDefinition(
        canonical="current_title",
        aliases=(
            "current title", "current_title",
            "current position", "current_position",
            "latest title", "recent title",
        ),
        field_type="str",
        required=False,
        description="Most recent job title (distinct from headline when provided).",
        priority=2,
        example="Lead Software Engineer",
    ))

    # ── Experience ────────────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="experience",
        aliases=(
            "experience", "work experience", "work_experience",
            "employment", "employment history", "employment_history",
            "work history", "work_history", "jobs",
            "positions", "career", "professional experience",
        ),
        field_type="list[dict]",
        required=False,
        description="Work history entries.",
        priority=2,
        example='[{"company": "Acme", "title": "Engineer"}]',
    ))
    reg.register(FieldDefinition(
        canonical="years_of_experience",
        aliases=(
            "years of experience", "years_of_experience", "yoe",
            "total experience", "total_experience",
            "experience years", "experience_years",
        ),
        field_type="float",
        required=False,
        description="Estimated total years of professional experience.",
        priority=2,
        example="5.5",
    ))

    # ── Education ─────────────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="education",
        aliases=(
            "education", "educational background", "educational_background",
            "academics", "academic background", "qualifications",
            "degrees", "schooling",
        ),
        field_type="list[dict]",
        required=False,
        description="Educational history entries.",
        priority=2,
        example='[{"institution": "MIT", "degree": "B.Sc. CS"}]',
    ))

    # ── Skills ────────────────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="skills",
        aliases=(
            "skills", "skill set", "skill_set", "skillset",
            "technical skills", "technical_skills",
            "technologies", "tech stack", "tech_stack",
            "competencies", "expertise", "tools", "languages",
            "programming languages", "programming_languages",
        ),
        field_type="list[str]",
        required=False,
        description="Raw skill strings (not normalised).",
        priority=1,
        example="Python, TensorFlow, Docker",
    ))

    # ── Certifications ────────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="certifications",
        aliases=(
            "certifications", "certificates", "certification",
            "professional certifications", "awards", "licences",
        ),
        field_type="list[str]",
        required=False,
        description="Certification and award strings.",
        priority=3,
        example="AWS Solutions Architect",
    ))

    # ── Projects ──────────────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="projects",
        aliases=(
            "projects", "project", "side projects", "personal projects",
            "open source", "open_source", "portfolio",
        ),
        field_type="list[dict]",
        required=False,
        description="Project entries.",
        priority=3,
        example='[{"name": "ml-pipeline", "url": "github.com/…"}]',
    ))

    # ── GitHub ────────────────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="github_url",
        aliases=(
            "github", "github url", "github_url", "github profile",
            "github_profile", "github link", "gh",
        ),
        field_type="str",
        required=False,
        description="Full GitHub profile URL.",
        priority=2,
        example="https://github.com/alice",
    ))
    reg.register(FieldDefinition(
        canonical="github_username",
        aliases=(
            "github username", "github_username",
            "github handle", "github login",
        ),
        field_type="str",
        required=False,
        description="GitHub username / login.",
        priority=2,
        example="alice",
    ))

    # ── LinkedIn ──────────────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="linkedin_url",
        aliases=(
            "linkedin", "linkedin url", "linkedin_url",
            "linkedin profile", "linkedin_profile",
            "linkedin link", "li",
        ),
        field_type="str",
        required=False,
        description="Full LinkedIn profile URL.",
        priority=2,
        example="https://linkedin.com/in/alice",
    ))

    # ── Website ───────────────────────────────────────────────
    reg.register(FieldDefinition(
        canonical="website",
        aliases=(
            "website", "website url", "website_url",
            "portfolio", "personal website", "personal_website",
            "blog", "homepage", "url", "web",
        ),
        field_type="str",
        required=False,
        description="Personal or portfolio website URL.",
        priority=3,
        example="https://alice.dev",
    ))

    # ── GitHub stats (populated by GitHubMapper) ──────────────
    reg.register(FieldDefinition(
        canonical="github_stars",
        aliases=(
            "github stars", "github_stars", "total stars",
            "total_stars", "stars",
        ),
        field_type="int",
        required=False,
        description="Total GitHub stars across public repositories.",
        priority=3,
        example="342",
    ))
    reg.register(FieldDefinition(
        canonical="github_repos",
        aliases=(
            "github repos", "github_repos", "public repos",
            "public_repos", "repositories",
        ),
        field_type="int",
        required=False,
        description="Public repository count.",
        priority=3,
        example="18",
    ))
    reg.register(FieldDefinition(
        canonical="primary_language",
        aliases=(
            "primary language", "primary_language",
            "top language", "main language",
        ),
        field_type="str",
        required=False,
        description="Most-used programming language (GitHub only).",
        priority=3,
        example="Python",
    ))

    return reg


#: Module-level singleton.  Import this instance in all mappers.
REGISTRY: FieldRegistry = _build_default_registry()
