"""
src/mapping/ats_mapper.py
==========================

Mapper for ATS (Applicant Tracking System) JSON exports.

Supports
--------
- **Greenhouse** — ``{"candidate": {"first_name": …, "email_addresses": […]}}``
- **Lever**      — ``{"name": …, "emails": […], "stage": {…}}``
- **Workday**    — ``{"Worker": {"Personal_Data": {"Contact_Data": {…}}}}``
- **Generic**    — any flat or nested JSON object

Schema Detection
----------------
The mapper inspects the top-level keys of the JSON object and selects
a schema-specific extraction strategy.  It falls back to generic
flat-dict mapping (using the field registry) when no known schema
matches.

Nested Field Access
-------------------
All nested access goes through :func:`~src.mapping.utils.safe_get`.
No raw nested traversal is done without a ``default`` fallback.
"""

from __future__ import annotations

from typing import Any

from src.mapping.base import BaseMapper
from src.mapping.utils import (
    classify_url,
    clean_str,
    make_provenance,
    parse_skill_list,
    safe_get,
    set_field,
    split_name,
)
from src.models import (
    CanonicalRecord,
    MappingMethod,
    RawRecord,
    SourceType,
)


# ── Schema Detection ──────────────────────────────────────────────


def _detect_schema(raw_fields: dict[str, Any]) -> str:
    """
    Detect the ATS schema variant from the top-level keys.

    Returns one of ``"greenhouse"``, ``"lever"``, ``"workday"``,
    or ``"generic"``.
    """
    keys = {k.lower() for k in raw_fields}
    if "candidate" in keys and any(
        k in keys for k in ("applications", "attachments")
    ):
        return "greenhouse"
    if "applications" in keys and "stage" in keys:
        return "lever"
    if "worker" in keys or "workdayid" in keys:
        return "workday"
    return "generic"


# ── ATS Mapper ────────────────────────────────────────────────────


class ATSMapper(BaseMapper):
    """
    Maps an ATS-sourced :class:`~src.models.RawRecord` to a
    :class:`~src.models.CanonicalRecord`.

    The mapper auto-detects the ATS schema and dispatches to the
    appropriate private extraction method.  All unknown top-level keys
    are logged as warnings.

    Config Keys
    -----------
    ``schema`` (str)
        Force a specific schema: ``"greenhouse"``, ``"lever"``,
        ``"workday"``, or ``"generic"``.  Auto-detected when ``None``.
    ``ignored_keys`` (list[str])
        Additional top-level keys to ignore.
    """

    @property
    def source_type(self) -> SourceType:
        return SourceType.ATS

    def supports(self, record: RawRecord) -> bool:
        return record.source_type == SourceType.ATS

    def metadata(self) -> dict[str, Any]:
        return {
            "mapper":      self.__class__.__name__,
            "source_type": self.source_type.value,
            "version":     "1.0.0",
            "schemas":     ["greenhouse", "lever", "workday", "generic"],
        }

    def map(self, record: RawRecord) -> CanonicalRecord:
        """Map an ATS RawRecord to a CanonicalRecord."""
        return self._timed_map(record, self._do_map)

    # ── Dispatch ─────────────────────────────────────────────

    def _do_map(self, record: RawRecord) -> CanonicalRecord:
        canonical = self._make_canonical(record)
        rf = record.raw_fields

        forced = self._config.get("schema")
        schema = forced if forced else _detect_schema(rf)
        canonical.mapping_metadata["ats_schema"] = schema

        if schema == "greenhouse":
            self._map_greenhouse(canonical, rf, record)
        elif schema == "lever":
            self._map_lever(canonical, rf, record)
        elif schema == "workday":
            self._map_workday(canonical, rf, record)
        else:
            self._map_generic(canonical, rf, record)

        self._infer_names(canonical, record)
        return canonical

    # ── Greenhouse ────────────────────────────────────────────

    def _map_greenhouse(
        self,
        canonical: CanonicalRecord,
        rf: dict[str, Any],
        record: RawRecord,
    ) -> None:
        cand = safe_get(rf, "candidate") or {}

        def _prov(field: str, orig: Any, mapped: Any,
                  raw_path: str, method: MappingMethod = MappingMethod.NESTED
                  ) -> None:
            prov = make_provenance(
                field=field, source=record.source_type,
                method=method, original_value=orig,
                mapped_value=mapped, raw_field_name=raw_path,
            )
            set_field(canonical, field, mapped, prov)

        # Name
        first = clean_str(safe_get(cand, "first_name"))
        last  = clean_str(safe_get(cand, "last_name"))
        if first:
            _prov("first_name", safe_get(cand, "first_name"), first, "candidate.first_name")
        if last:
            _prov("last_name", safe_get(cand, "last_name"), last, "candidate.last_name")

        # Emails
        for addr_obj in safe_get(cand, "email_addresses") or []:
            email = clean_str(safe_get(addr_obj, "value"))
            if email:
                _prov("emails", addr_obj, email, "candidate.email_addresses[].value")

        # Phones
        for phone_obj in safe_get(cand, "phone_numbers") or []:
            phone = clean_str(safe_get(phone_obj, "value"))
            if phone:
                _prov("phones", phone_obj, phone, "candidate.phone_numbers[].value")

        # Location
        loc = clean_str(safe_get(cand, "addresses", 0, "value")) or \
              clean_str(safe_get(cand, "location", "name"))
        if loc:
            _prov("location", loc, loc, "candidate.addresses[0].value")

        # Title / headline
        title = clean_str(safe_get(cand, "title"))
        if title:
            _prov("headline", title, title, "candidate.title")

        # Company
        company = clean_str(safe_get(cand, "company"))
        if company:
            _prov("current_company", company, company, "candidate.company")

        # Social links
        for url_obj in safe_get(cand, "website_addresses") or []:
            url = clean_str(safe_get(url_obj, "value"))
            if url:
                platform, cleaned = classify_url(url)
                target = {"github": "github_url", "linkedin": "linkedin_url",
                          "website": "website"}.get(platform, "website")
                _prov(target, url, cleaned, "candidate.website_addresses[].value")

        # Tags as skills
        tags = safe_get(rf, "tags") or []
        if tags:
            skills = [clean_str(t) for t in tags if clean_str(t)]
            if skills:
                _prov("skills", tags, skills, "tags")

        # Unhandled top-level keys
        for key in rf:
            if key not in {"candidate", "applications", "attachments",
                           "tags", "custom_fields"}:
                self._record_ignored(canonical, key)

    # ── Lever ─────────────────────────────────────────────────

    def _map_lever(
        self,
        canonical: CanonicalRecord,
        rf: dict[str, Any],
        record: RawRecord,
    ) -> None:
        def _prov(field: str, orig: Any, mapped: Any,
                  raw_path: str, method: MappingMethod = MappingMethod.NESTED) -> None:
            prov = make_provenance(
                field=field, source=record.source_type,
                method=method, original_value=orig,
                mapped_value=mapped, raw_field_name=raw_path,
            )
            set_field(canonical, field, mapped, prov)

        # Name
        name = clean_str(safe_get(rf, "name"))
        if name:
            _prov("full_name", name, name, "name")

        # Emails
        for email in safe_get(rf, "emails") or []:
            e = clean_str(email)
            if e:
                _prov("emails", email, e, "emails[]")

        # Phones
        for phone_obj in safe_get(rf, "phones") or []:
            phone = clean_str(
                safe_get(phone_obj, "value") if isinstance(phone_obj, dict) else phone_obj
            )
            if phone:
                _prov("phones", phone_obj, phone, "phones[]")

        # Headline / title
        headline = clean_str(safe_get(rf, "headline"))
        if headline:
            _prov("headline", headline, headline, "headline")

        # Location
        loc = clean_str(safe_get(rf, "location", "name")) or \
              clean_str(safe_get(rf, "location"))
        if loc:
            _prov("location", loc, loc, "location.name")

        # Summary
        summary = clean_str(safe_get(rf, "summary"))
        if summary:
            _prov("summary", summary, summary, "summary")

        # Social links
        for link_obj in safe_get(rf, "links") or []:
            url = clean_str(
                safe_get(link_obj, "url") if isinstance(link_obj, dict) else link_obj
            )
            if url:
                platform, cleaned = classify_url(url)
                target = {"github": "github_url", "linkedin": "linkedin_url",
                          "website": "website"}.get(platform, "website")
                _prov(target, url, cleaned, "links[]")

        # Tags as skills
        tags = safe_get(rf, "tags") or []
        if tags:
            skills = [clean_str(t) for t in tags if clean_str(t)]
            if skills:
                _prov("skills", tags, skills, "tags")

        for key in rf:
            if key not in {"name", "emails", "phones", "headline", "location",
                           "summary", "links", "tags", "stage", "applications",
                           "sources", "owner", "createdAt", "updatedAt"}:
                self._record_ignored(canonical, key)

    # ── Workday ───────────────────────────────────────────────

    def _map_workday(
        self,
        canonical: CanonicalRecord,
        rf: dict[str, Any],
        record: RawRecord,
    ) -> None:
        def _prov(field: str, orig: Any, mapped: Any,
                  raw_path: str, method: MappingMethod = MappingMethod.NESTED) -> None:
            prov = make_provenance(
                field=field, source=record.source_type,
                method=method, original_value=orig,
                mapped_value=mapped, raw_field_name=raw_path,
            )
            set_field(canonical, field, mapped, prov)

        worker = safe_get(rf, "Worker") or rf
        personal = safe_get(worker, "Personal_Data") or {}
        name_data = safe_get(personal, "Name_Data") or {}
        contact   = safe_get(personal, "Contact_Data") or {}

        # Name
        first = clean_str(safe_get(name_data, "First_Name"))
        last  = clean_str(safe_get(name_data, "Last_Name"))
        if first:
            _prov("first_name", first, first, "Worker.Personal_Data.Name_Data.First_Name")
        if last:
            _prov("last_name", last, last, "Worker.Personal_Data.Name_Data.Last_Name")

        # Email
        email = clean_str(
            safe_get(contact, "Email_Address") or
            safe_get(contact, "Primary_Email")
        )
        if email:
            _prov("emails", email, email, "Worker.Personal_Data.Contact_Data.Email_Address")

        # Phone
        phone = clean_str(
            safe_get(contact, "Phone_Number") or
            safe_get(contact, "Primary_Phone")
        )
        if phone:
            _prov("phones", phone, phone, "Worker.Personal_Data.Contact_Data.Phone_Number")

        # Location
        addr = safe_get(contact, "Address_Data") or {}
        city    = clean_str(safe_get(addr, "City"))
        country = clean_str(safe_get(addr, "Country"))
        if city or country:
            loc = ", ".join(filter(None, [city, country]))
            _prov("location", addr, loc, "Worker.Personal_Data.Contact_Data.Address_Data")

    # ── Generic ───────────────────────────────────────────────

    def _map_generic(
        self,
        canonical: CanonicalRecord,
        rf: dict[str, Any],
        record: RawRecord,
    ) -> None:
        """
        Fall-back: treat the JSON object as a flat dict and resolve
        every key against the field registry.
        """
        _IGNORED = {
            "id", "candidate_id", "ats_id", "created_at", "updated_at",
            "stage", "pipeline", "owner", "source", "status",
        }
        for raw_key, raw_value in rf.items():
            low = raw_key.lower()
            if low in _IGNORED:
                self._record_ignored(canonical, raw_key)
                continue

            canon_name = self._registry.resolve(raw_key)
            if canon_name is None:
                # For compound keys like "contact.email", also try the leaf
                leaf = raw_key.split(".")[-1]
                if leaf != raw_key:
                    canon_name = self._registry.resolve(leaf)

            if canon_name is None:
                # Try nested expansion for dict values
                if isinstance(raw_value, dict):
                    self._map_generic(
                        canonical,
                        {f"{raw_key}.{k}": v for k, v in raw_value.items()},
                        record,
                    )
                else:
                    self._record_unknown(canonical, raw_key)
                continue


            method = (
                MappingMethod.DIRECT
                if low == canon_name
                else MappingMethod.ALIAS
            )

            if canon_name == "skills":
                skill_list = parse_skill_list(raw_value)
                if skill_list:
                    prov = make_provenance(
                        field="skills", source=record.source_type,
                        method=method, original_value=raw_value,
                        mapped_value=skill_list, raw_field_name=raw_key,
                    )
                    set_field(canonical, "skills", skill_list, prov)
            elif canon_name in ("github_url", "linkedin_url", "website"):
                if url := clean_str(raw_value):
                    platform, cleaned = classify_url(url)
                    target = {"github": "github_url", "linkedin": "linkedin_url",
                              "website": "website"}.get(platform, "website")
                    prov = make_provenance(
                        field=target, source=record.source_type,
                        method=method, original_value=url,
                        mapped_value=cleaned, raw_field_name=raw_key,
                    )
                    set_field(canonical, target, cleaned, prov)
            else:
                value = clean_str(raw_value) if isinstance(raw_value, str) else raw_value
                if value is not None:
                    prov = make_provenance(
                        field=canon_name, source=record.source_type,
                        method=method, original_value=raw_value,
                        mapped_value=value, raw_field_name=raw_key,
                    )
                    set_field(canonical, canon_name, value, prov)

    def _infer_names(
        self,
        canonical: CanonicalRecord,
        record: RawRecord,
    ) -> None:
        has_full  = canonical.full_name is not None
        has_first = canonical.first_name is not None
        has_last  = canonical.last_name is not None

        if has_first and has_last and not has_full:
            inferred = f"{canonical.first_name} {canonical.last_name}"
            prov = make_provenance(
                field="full_name", source=record.source_type,
                method=MappingMethod.INFERRED,
                original_value=f"{canonical.first_name} + {canonical.last_name}",
                mapped_value=inferred, confidence=0.9,
            )
            set_field(canonical, "full_name", inferred, prov)
        elif has_full and not has_first and not has_last:
            first, last = split_name(canonical.full_name)
            if first:
                prov = make_provenance(
                    field="first_name", source=record.source_type,
                    method=MappingMethod.INFERRED,
                    original_value=canonical.full_name,
                    mapped_value=first, confidence=0.9,
                )
                set_field(canonical, "first_name", first, prov)
            if last:
                prov = make_provenance(
                    field="last_name", source=record.source_type,
                    method=MappingMethod.INFERRED,
                    original_value=canonical.full_name,
                    mapped_value=last, confidence=0.9,
                )
                set_field(canonical, "last_name", last, prov)
