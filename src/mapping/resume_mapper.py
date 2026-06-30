"""
src/mapping/resume_mapper.py
=============================

Mapper for PDF résumé text extracted by :class:`~src.extractors.ResumePdfExtractor`.

**No NLP is used.**  All extraction is based on:

- Regex-based section header detection
- Regex-based contact field extraction (email, phone, URL)
- Bullet / line splitting for skills and list-type sections
- First-line heuristic for candidate name

Section Detection
-----------------
The mapper scans ``raw_fields["full_text"]`` line-by-line for headers
that match a set of known section patterns:

+-------------------+-----------------------------------------------+
| Section           | Header Patterns                               |
+===================+===============================================+
| CONTACT           | top-of-document (first 10 lines)              |
| SUMMARY           | Summary, Objective, Profile, About            |
| SKILLS            | Skills, Technical Skills, Technologies        |
| EXPERIENCE        | Experience, Work History, Employment          |
| EDUCATION         | Education, Academic, Qualifications           |
| PROJECTS          | Projects, Portfolio, Open Source              |
| CERTIFICATIONS    | Certifications, Licences, Awards              |
+-------------------+-----------------------------------------------+

When a section header is found, all lines until the next header
(or end of document) are grouped into that section.

Contact Extraction
------------------
Email, phone, and URLs are extracted from the contact section (top
lines) using regex patterns.  The name is inferred from the first
non-empty, non-email line of the document.
"""

from __future__ import annotations

import re
from typing import Any

from src.mapping.base import BaseMapper
from src.mapping.utils import (
    classify_url,
    clean_str,
    make_provenance,
    parse_skill_list,
    set_field,
    split_name,
)
from src.models import (
    CanonicalRecord,
    MappingMethod,
    RawRecord,
    SourceType,
)


# ================================================================
# Section Detection
# ================================================================

# Regex patterns for known section headers (case-insensitive).
_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SUMMARY",       re.compile(
        r"^\s*(summary|professional\s+summary|objective|career\s+objective"
        r"|profile|about\s+me|overview|introduction)\s*:?\s*$",
        re.IGNORECASE,
    )),
    ("SKILLS",        re.compile(
        r"^\s*(skills|technical\s+skills|core\s+skills|competencies"
        r"|technologies|tech\s+stack|expertise|tools|programming\s+languages"
        r"|languages\s+&\s+tools)\s*:?\s*$",
        re.IGNORECASE,
    )),
    ("EXPERIENCE",    re.compile(
        r"^\s*(experience|work\s+experience|professional\s+experience"
        r"|employment|employment\s+history|work\s+history|career\s+history"
        r"|positions?)\s*:?\s*$",
        re.IGNORECASE,
    )),
    ("EDUCATION",     re.compile(
        r"^\s*(education|academic|academics|qualifications"
        r"|educational\s+background|degrees?|schooling)\s*:?\s*$",
        re.IGNORECASE,
    )),
    ("PROJECTS",      re.compile(
        r"^\s*(projects?|personal\s+projects?|side\s+projects?"
        r"|open\s+source|portfolio)\s*:?\s*$",
        re.IGNORECASE,
    )),
    ("CERTIFICATIONS", re.compile(
        r"^\s*(certifications?|certificates?|licen[sc]es?"
        r"|professional\s+certifications?|awards?)\s*:?\s*$",
        re.IGNORECASE,
    )),
]

# ── Contact regexes ───────────────────────────────────────────────

_EMAIL_RE  = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE  = re.compile(
    r"(?:\+?\d[\d\s\-().]{7,14}\d)"
)
_URL_RE    = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

# Bullet point characters to strip from line beginnings.
_BULLET_RE = re.compile(r"^[\•\-\*\·\u2022\u00b7\u2013\u2014]\s*")

# Experience entry date range pattern.
_DATE_RANGE_RE = re.compile(
    r"(\d{4})\s*[-–—]\s*(\d{4}|present|current|now)",
    re.IGNORECASE,
)

# ================================================================
# ResumePdfMapper
# ================================================================


class ResumePdfMapper(BaseMapper):
    """
    Maps a résumé PDF :class:`~src.models.RawRecord` to a
    :class:`~src.models.CanonicalRecord`.

    The mapper reads ``raw_fields["full_text"]`` and:

    1. Splits the text into labelled sections.
    2. Extracts contact fields (email, phone, URL, name) from the
       top section.
    3. Extracts skills, experience, education, projects, and
       certifications from their respective sections.

    No NLP is used — all extraction is regex and heuristic.

    Config Keys
    -----------
    ``contact_lines`` (int)
        How many top-of-document lines to treat as the contact block.
        Default: ``12``.
    ``min_section_lines`` (int)
        Minimum number of non-empty lines a section must contain to
        be parsed.  Default: ``1``.
    """

    @property
    def source_type(self) -> SourceType:
        return SourceType.RESUME

    def supports(self, record: RawRecord) -> bool:
        return record.source_type == SourceType.RESUME

    def metadata(self) -> dict[str, Any]:
        return {
            "mapper":       self.__class__.__name__,
            "source_type":  self.source_type.value,
            "version":      "1.0.0",
            "method":       "regex_section_detection",
            "nlp":          False,
        }

    def map(self, record: RawRecord) -> CanonicalRecord:
        """Map a résumé PDF RawRecord to a CanonicalRecord."""
        return self._timed_map(record, self._do_map)

    # ── Internal implementation ───────────────────────────────

    def _do_map(self, record: RawRecord) -> CanonicalRecord:
        canonical = self._make_canonical(record)
        full_text: str = record.raw_fields.get("full_text", "") or ""
        pages: list[str] = record.raw_fields.get("pages", []) or []

        canonical.mapping_metadata["mapper"] = "ResumePdfMapper"
        canonical.mapping_metadata["char_count"] = len(full_text)
        canonical.mapping_metadata["page_count"] = len(pages)

        if not full_text.strip():
            canonical.mapping_metadata["empty_text"] = True
            return canonical

        lines = [ln for ln in full_text.splitlines()]
        sections = self._split_sections(lines)
        canonical.mapping_metadata["sections_detected"] = list(sections.keys())

        # Contact block: top N lines + any CONTACT section
        contact_limit = self._config.get("contact_lines", 12)
        contact_lines = lines[:contact_limit]
        if "CONTACT" in sections:
            contact_lines = sections["CONTACT"]

        self._extract_contact(canonical, contact_lines, record)
        self._extract_summary(canonical, sections, record)
        self._extract_skills(canonical, sections, record)
        self._extract_experience(canonical, sections, lines, record)
        self._extract_education(canonical, sections, record)
        self._extract_projects(canonical, sections, record)
        self._extract_certifications(canonical, sections, record)

        return canonical

    # ── Section Splitter ──────────────────────────────────────

    def _split_sections(self, lines: list[str]) -> dict[str, list[str]]:
        """
        Split document lines into named sections.

        Returns a dict mapping section name → list of content lines
        (the header line itself is excluded).
        """
        sections: dict[str, list[str]] = {}
        current_section: str | None = None
        current_lines: list[str] = []

        for line in lines:
            matched_section = None
            for section_name, pattern in _SECTION_PATTERNS:
                if pattern.match(line.strip()):
                    matched_section = section_name
                    break

            if matched_section:
                if current_section:
                    sections[current_section] = current_lines
                current_section = matched_section
                current_lines = []
            else:
                if current_section:
                    current_lines.append(line)

        if current_section and current_lines:
            sections[current_section] = current_lines

        return sections

    # ── Contact Extraction ────────────────────────────────────

    def _extract_contact(
        self,
        canonical: CanonicalRecord,
        contact_lines: list[str],
        record: RawRecord,
    ) -> None:
        """
        Extract email, phone, URLs, and name from the contact block.

        Name heuristic: first non-empty line that contains no
        ``@`` (not an email) and no ``http`` (not a URL), and is
        shorter than 60 characters.
        """
        emails_found: list[str] = []
        phones_found: list[str] = []
        urls_found:   list[str] = []
        name_candidate: str | None = None

        for line in contact_lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Emails
            for email in _EMAIL_RE.findall(stripped):
                if email not in emails_found:
                    emails_found.append(email)

            # Phones
            for phone in _PHONE_RE.findall(stripped):
                phone = phone.strip()
                if phone and len(phone) >= 7 and phone not in phones_found:
                    phones_found.append(phone)

            # URLs
            for url in _URL_RE.findall(stripped):
                if url not in urls_found:
                    urls_found.append(url)

            # Name candidate
            if name_candidate is None:
                no_email = _EMAIL_RE.sub("", stripped)
                no_url   = _URL_RE.sub("", no_email).strip()
                no_phone = _PHONE_RE.sub("", no_url).strip()
                if no_phone and len(no_phone) < 60 and "@" not in no_phone:
                    name_candidate = no_phone

        # Store email
        for email in emails_found:
            prov = make_provenance(
                field="emails", source=record.source_type,
                method=MappingMethod.SECTION,
                original_value=email, mapped_value=email,
                raw_field_name="contact_block",
                confidence=0.9,
            )
            set_field(canonical, "emails", email, prov)

        # Store phone
        for phone in phones_found:
            prov = make_provenance(
                field="phones", source=record.source_type,
                method=MappingMethod.SECTION,
                original_value=phone, mapped_value=phone,
                raw_field_name="contact_block",
                confidence=0.8,
            )
            set_field(canonical, "phones", phone, prov)

        # Classify URLs
        for url in urls_found:
            platform, cleaned = classify_url(url)
            target = {
                "github":   "github_url",
                "linkedin": "linkedin_url",
                "website":  "website",
            }.get(platform, "website")
            prov = make_provenance(
                field=target, source=record.source_type,
                method=MappingMethod.SECTION,
                original_value=url, mapped_value=cleaned,
                raw_field_name="contact_block", confidence=0.9,
            )
            set_field(canonical, target, cleaned, prov)

        # Name
        if name_candidate and not canonical.full_name:
            name = clean_str(name_candidate)
            if name:
                prov = make_provenance(
                    field="full_name", source=record.source_type,
                    method=MappingMethod.SECTION,
                    original_value=name_candidate, mapped_value=name,
                    raw_field_name="first_line", confidence=0.75,
                )
                set_field(canonical, "full_name", name, prov)
                first, last = split_name(name)
                if first:
                    prov2 = make_provenance(
                        field="first_name", source=record.source_type,
                        method=MappingMethod.INFERRED,
                        original_value=name, mapped_value=first,
                        confidence=0.75,
                    )
                    set_field(canonical, "first_name", first, prov2)
                if last:
                    prov3 = make_provenance(
                        field="last_name", source=record.source_type,
                        method=MappingMethod.INFERRED,
                        original_value=name, mapped_value=last,
                        confidence=0.75,
                    )
                    set_field(canonical, "last_name", last, prov3)

        # GitHub username inference
        if canonical.github_url and not canonical.github_username:
            from src.mapping.utils import _GITHUB_URL_RE
            m = _GITHUB_URL_RE.search(canonical.github_url)
            if m:
                username = m.group(1)
                prov = make_provenance(
                    field="github_username", source=record.source_type,
                    method=MappingMethod.INFERRED,
                    original_value=canonical.github_url, mapped_value=username,
                    confidence=0.95,
                )
                set_field(canonical, "github_username", username, prov)

    # ── Summary Extraction ────────────────────────────────────

    def _extract_summary(
        self,
        canonical: CanonicalRecord,
        sections: dict[str, list[str]],
        record: RawRecord,
    ) -> None:
        lines = sections.get("SUMMARY", [])
        text = " ".join(ln.strip() for ln in lines if ln.strip())
        text = clean_str(text)
        if text and not canonical.summary:
            prov = make_provenance(
                field="summary", source=record.source_type,
                method=MappingMethod.SECTION,
                original_value=text, mapped_value=text,
                raw_field_name="SUMMARY section", confidence=0.85,
            )
            set_field(canonical, "summary", text, prov)

    # ── Skills Extraction ─────────────────────────────────────

    def _extract_skills(
        self,
        canonical: CanonicalRecord,
        sections: dict[str, list[str]],
        record: RawRecord,
    ) -> None:
        lines = sections.get("SKILLS", [])
        raw_text = "\n".join(lines)
        skills = parse_skill_list(raw_text)
        # Also handle bullet-list format
        if not skills:
            for ln in lines:
                ln = _BULLET_RE.sub("", ln.strip())
                if ln:
                    skills.extend(parse_skill_list(ln))
        # Deduplicate
        seen: set[str] = set()
        unique: list[str] = []
        for s in skills:
            if s.lower() not in seen:
                seen.add(s.lower())
                unique.append(s)

        if unique:
            prov = make_provenance(
                field="skills", source=record.source_type,
                method=MappingMethod.SECTION,
                original_value=raw_text, mapped_value=unique,
                raw_field_name="SKILLS section", confidence=0.85,
            )
            set_field(canonical, "skills", unique, prov)

    # ── Experience Extraction ─────────────────────────────────

    def _extract_experience(
        self,
        canonical: CanonicalRecord,
        sections: dict[str, list[str]],
        all_lines: list[str],
        record: RawRecord,
    ) -> None:
        lines = sections.get("EXPERIENCE", [])
        if not lines:
            return

        entries = self._parse_experience_lines(lines)
        for entry in entries:
            prov = make_provenance(
                field="experience", source=record.source_type,
                method=MappingMethod.SECTION,
                original_value=entry, mapped_value=entry,
                raw_field_name="EXPERIENCE section", confidence=0.7,
            )
            set_field(canonical, "experience", entry, prov)

    def _parse_experience_lines(
        self,
        lines: list[str],
    ) -> list[dict[str, Any]]:
        """
        Heuristic parser for experience section lines.

        Groups lines into entries.  A new entry starts when:
        - A line contains a date range (YYYY–YYYY or YYYY–Present)
        - The next company/title line is inferred from position

        Returns a list of raw experience dicts.
        """
        entries: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        desc_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            date_match = _DATE_RANGE_RE.search(stripped)
            if date_match:
                # Save previous entry
                if current:
                    current["description"] = " ".join(desc_lines).strip()
                    entries.append(current)
                    current = {}
                    desc_lines = []

                start_year = date_match.group(1)
                end_raw = date_match.group(2)
                is_current = end_raw.lower() in ("present", "current", "now")
                end_year = None if is_current else end_raw

                # Title / company often on the same line as dates
                title_part = _DATE_RANGE_RE.sub("", stripped).strip(" |-–—")
                if title_part:
                    parts = [p.strip() for p in re.split(r"\s+at\s+|\s*[|,\u2013\u2014]\s*", title_part)]
                    current["title"]      = parts[0] if parts else None
                    current["company"]    = parts[1] if len(parts) > 1 else None
                else:
                    current["title"]   = None
                    current["company"] = None

                current["start_date"] = start_year
                current["end_date"]   = end_year
                current["is_current"] = is_current
                current["location"]   = None
            else:
                # Bullet lines → description
                clean = _BULLET_RE.sub("", stripped)
                if clean:
                    if not current:
                        # Title/company line before a date range
                        parts = [p.strip() for p in re.split(r"\s+at\s+|\s*[|,\u2013\u2014]\s*", clean)]
                        current["title"]      = parts[0] if parts else clean
                        current["company"]    = parts[1] if len(parts) > 1 else None
                        current["start_date"] = None
                        current["end_date"]   = None
                        current["is_current"] = False
                        current["location"]   = None
                    else:
                        desc_lines.append(clean)

        if current:
            current["description"] = " ".join(desc_lines).strip()
            entries.append(current)

        return entries

    # ── Education Extraction ──────────────────────────────────

    def _extract_education(
        self,
        canonical: CanonicalRecord,
        sections: dict[str, list[str]],
        record: RawRecord,
    ) -> None:
        lines = sections.get("EDUCATION", [])
        if not lines:
            return

        entries = self._parse_education_lines(lines)
        for entry in entries:
            prov = make_provenance(
                field="education", source=record.source_type,
                method=MappingMethod.SECTION,
                original_value=entry, mapped_value=entry,
                raw_field_name="EDUCATION section", confidence=0.75,
            )
            set_field(canonical, "education", entry, prov)

    def _parse_education_lines(
        self, lines: list[str]
    ) -> list[dict[str, Any]]:
        """Heuristic parser for education lines."""
        _DEGREE_RE = re.compile(
            r"\b(B\.?S\.?|B\.?E\.?|B\.?Tech|B\.?Sc\.?|M\.?S\.?|M\.?E\.?"
            r"|M\.?Tech|M\.?Sc\.?|MBA|Ph\.?D\.?|Bachelor|Master|Doctor)\b",
            re.IGNORECASE,
        )
        entries: list[dict[str, Any]] = []
        current: dict[str, Any] = {}

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            date_match = _DATE_RANGE_RE.search(stripped)
            degree_match = _DEGREE_RE.search(stripped)

            if date_match or degree_match:
                if current:
                    entries.append(current)
                current = {
                    "institution": None,
                    "degree":      None,
                    "field":       None,
                    "start_date":  None,
                    "end_date":    None,
                    "gpa":         None,
                }
                if date_match:
                    current["start_date"] = date_match.group(1)
                    end_raw = date_match.group(2)
                    current["end_date"] = (
                        None if end_raw.lower() in ("present", "current", "now")
                        else end_raw
                    )
                # Remainder of line is institution / degree
                remainder = stripped
                if date_match:
                    remainder = _DATE_RANGE_RE.sub("", remainder).strip(" |-–—")
                if remainder:
                    parts = [p.strip() for p in re.split(r"\s*[|,\u2013\u2014]\s*|,\s*", remainder)]
                    current["institution"] = parts[0] if parts else remainder
                    if len(parts) > 1:
                        current["degree"] = parts[1]
            else:
                if not current:
                    current = {
                        "institution": stripped,
                        "degree": None, "field": None,
                        "start_date": None, "end_date": None, "gpa": None,
                    }
                elif current.get("degree") is None:
                    current["degree"] = _BULLET_RE.sub("", stripped)

        if current:
            entries.append(current)

        return entries

    # ── Projects Extraction ───────────────────────────────────

    def _extract_projects(
        self,
        canonical: CanonicalRecord,
        sections: dict[str, list[str]],
        record: RawRecord,
    ) -> None:
        lines = sections.get("PROJECTS", [])
        if not lines:
            return

        projects: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        desc_lines: list[str] = []

        for line in lines:
            stripped = _BULLET_RE.sub("", line.strip())
            if not stripped:
                continue

            urls = _URL_RE.findall(stripped)
            if urls and not current.get("name"):
                # First line with a URL is the project header
                name = _URL_RE.sub("", stripped).strip(" :-")
                current = {"name": name or stripped, "url": urls[0],
                           "description": None, "technologies": []}
            elif current:
                desc_lines.append(stripped)
            else:
                current = {"name": stripped, "url": None,
                           "description": None, "technologies": []}

            if current and (not current.get("name") or desc_lines):
                pass  # accumulating

        if current:
            current["description"] = " ".join(desc_lines).strip() or None
            projects.append(current)

        for proj in projects:
            prov = make_provenance(
                field="projects", source=record.source_type,
                method=MappingMethod.SECTION,
                original_value=proj, mapped_value=proj,
                raw_field_name="PROJECTS section", confidence=0.7,
            )
            set_field(canonical, "projects", proj, prov)

    # ── Certifications Extraction ─────────────────────────────

    def _extract_certifications(
        self,
        canonical: CanonicalRecord,
        sections: dict[str, list[str]],
        record: RawRecord,
    ) -> None:
        lines = sections.get("CERTIFICATIONS", [])
        certs: list[str] = []
        for line in lines:
            cert = clean_str(_BULLET_RE.sub("", line.strip()))
            if cert:
                certs.append(cert)

        for cert in certs:
            prov = make_provenance(
                field="certifications", source=record.source_type,
                method=MappingMethod.SECTION,
                original_value=cert, mapped_value=cert,
                raw_field_name="CERTIFICATIONS section", confidence=0.8,
            )
            set_field(canonical, "certifications", cert, prov)
