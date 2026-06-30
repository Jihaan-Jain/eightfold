"""
src/extractors/ats_json_extractor.py
=====================================

Extractor for ATS (Applicant Tracking System) JSON exports.

Handles
-------
- Single JSON object ``{…}`` → one :class:`~src.models.RawRecord`
- JSON array ``[{…}, {…}]`` → one record per array element
- Nested objects — stored verbatim in ``raw_fields``; no flattening
- Missing / null fields — kept as-is
- Extra / unknown fields — kept as-is
- Invalid JSON — raises :class:`~src.exceptions.ExtractionError`
- JSON Lines (``.jsonl``) — one record per newline-delimited object

RawRecord layout
----------------
``raw_fields``
    The parsed JSON object as a Python dict.  Nested dicts and lists
    are stored as native Python types (not re-serialised to strings).

``metadata`` — standard block
    +----------------------------+------------------------------------------+
    | Key                        | Value                                    |
    +============================+==========================================+
    | ``checksum``               | ``"sha256:<hex>"`` digest of the file    |
    | ``file_size``              | File size in bytes (int)                 |
    | ``mime``                   | Detected MIME type string                |
    | ``encoding``               | Detected / used encoding string          |
    | ``pages``                  | ``None`` (N/A for JSON)                  |
    | ``language``               | ``None`` (N/A for JSON)                  |
    +----------------------------+------------------------------------------+

``metadata`` — ATS-specific keys
    +--------------------------+------------------------------------------+
    | Key                      | Value                                    |
    +==========================+==========================================+
    | ``json_structure``       | ``"object"``, ``"array"``, ``"jsonl"``   |
    | ``total_records_in_file``| Total objects parsed from the file       |
    | ``record_index``         | 0-based index of this object in the file |
    +--------------------------+------------------------------------------+
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.exceptions import ExtractionError
from src.extractors.base import BaseExtractor
from src.extractors.utils import (
    build_standard_metadata,
    detect_encoding,
    detect_mime_type,
    hash_file,
    normalise_source_label,
    safe_read_bytes,
)
from src.models import RawRecord, SourceType


class ATSJsonExtractor(BaseExtractor):
    """
    Extractor for ATS candidate data in JSON or JSON Lines format.

    Config Keys
    -----------
    ``encoding`` (str | None)
        Force a specific encoding.  Auto-detected when ``None``.
    ``records_key`` (str | None)
        When the top-level JSON object has a wrapper key that holds
        the candidate array (e.g. ``"candidates"``), set this to
        that key.  When ``None`` (default), the top-level value is
        used directly.

    Examples
    --------
    ::

        extractor = ATSJsonExtractor()
        records = extractor.extract(Path("data/ats_export.json"))
        # 1 record per candidate object in the JSON

        # With a records_key wrapper:
        extractor = ATSJsonExtractor(config={"records_key": "candidates"})
        records = extractor.extract(Path("data/ats_with_wrapper.json"))
    """

    @property
    def source_type(self) -> SourceType:
        """Returns :attr:`~src.models.SourceType.ATS`."""
        return SourceType.ATS

    def supports(self, source: str | Path) -> bool:
        """Return ``True`` for ``.json`` and ``.jsonl`` extensions."""
        return Path(str(source)).suffix.lower() in {".json", ".jsonl"}

    def validate_source(self, source: str | Path) -> None:
        """
        Check that ``source`` is a readable file with a JSON extension
        or compatible MIME type.

        Raises
        ------
        src.exceptions.ExtractionError
            If the file is absent, unreadable, or is a binary format.
        """
        p = Path(str(source))
        if not p.exists():
            raise ExtractionError(
                f"ATS JSON source file not found: {p}",
                source_type=self.source_type.value,
                source_path=str(p),
            )
        if not p.is_file():
            raise ExtractionError(
                f"ATS JSON source is not a regular file: {p}",
                source_type=self.source_type.value,
                source_path=str(p),
            )
        mime = detect_mime_type(p)
        blocked_mimes = {"application/pdf", "image/png", "image/jpeg"}
        if mime in blocked_mimes:
            raise ExtractionError(
                f"ATS source has incompatible MIME type '{mime}': {p}",
                source_type=self.source_type.value,
                source_path=str(p),
            )

    def extract(self, source: str | Path) -> list[RawRecord]:
        """
        Parse a JSON / JSONL file and return one
        :class:`~src.models.RawRecord` per candidate object.

        Parameters
        ----------
        source:
            Path to the ``.json`` or ``.jsonl`` file.

        Returns
        -------
        list[RawRecord]
            One record per candidate object.

        Raises
        ------
        src.exceptions.ExtractionError
            On file-not-found, invalid JSON, or unexpected file structure.
        """
        self.validate_source(source)
        return self._timed_extract(source, self._do_extract)

    def metadata(self) -> dict[str, Any]:
        """Return static metadata about this extractor."""
        return {
            "extractor":             self.__class__.__name__,
            "source_type":           self.source_type.value,
            "version":               "1.0.0",
            "supported_extensions":  [".json", ".jsonl"],
            "supported_structures":  ["object", "array", "jsonl"],
        }

    # ── Internal implementation ───────────────────────────────

    def _do_extract(self, source: str | Path) -> list[RawRecord]:
        """
        Core extraction: decode → detect structure → parse → build records.
        """
        p = Path(str(source))
        source_label = normalise_source_label(p)

        raw_bytes = safe_read_bytes(p)
        file_hash = hash_file(p)
        file_size = p.stat().st_size
        mime_type = detect_mime_type(p)

        # ── Decode ────────────────────────────────────────────
        forced_enc = self._config.get("encoding")
        encoding = forced_enc if forced_enc else detect_encoding(raw_bytes)
        try:
            text = raw_bytes.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            encoding = "utf-8"
            text = raw_bytes.decode("utf-8", errors="replace")

        # ── Choose parse strategy ─────────────────────────────
        is_jsonl = p.suffix.lower() == ".jsonl"

        if is_jsonl:
            objects, structure = self._parse_jsonl(text, source_label)
        else:
            objects, structure = self._parse_json(text, source_label)

        # ── Apply records_key unwrap ──────────────────────────
        records_key = self._config.get("records_key")
        if records_key and len(objects) == 1 and isinstance(objects[0], dict):
            inner = objects[0].get(records_key)
            if isinstance(inner, list):
                objects = inner
                structure = "array"
            elif isinstance(inner, dict):
                objects = [inner]

        total = len(objects)
        base_metadata = {
            # ── Standard block ─────────────────────────────────────────
            **build_standard_metadata(
                checksum=f"sha256:{file_hash}",
                file_size=file_size,
                mime=mime_type,
                encoding=encoding,
                pages=None,
                language=None,
            ),
            # ── ATS-specific ────────────────────────────────────────
            "json_structure":         structure,
            "total_records_in_file":  total,
        }

        records: list[RawRecord] = []
        for idx, obj in enumerate(objects):
            if not isinstance(obj, dict):
                # Non-dict element (e.g. plain string or number in an
                # array) — wrap it so we still have a RawRecord.
                obj = {"_value": obj}

            records.append(
                RawRecord(
                    source=source_label,
                    source_type=self.source_type,
                    raw_fields=obj,
                    metadata={**base_metadata, "record_index": idx},
                )
            )

        self._log.debug(
            "ATS JSON parsed",
            extra={
                "source":    source_label,
                "structure": structure,
                "total":     total,
                "encoding":  encoding,
            },
        )
        return records

    # ── Parsers ───────────────────────────────────────────────

    def _parse_json(
        self,
        text: str,
        source_label: str,
    ) -> tuple[list[Any], str]:
        """
        Parse a standard JSON string (single object or array).

        Returns
        -------
        tuple[list[Any], str]
            (list of parsed objects, structure label)
        """
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExtractionError(
                f"Invalid JSON in {source_label}: {exc}",
                source_type=self.source_type.value,
                source_path=source_label,
            ) from exc

        if isinstance(parsed, list):
            return parsed, "array"
        elif isinstance(parsed, dict):
            return [parsed], "object"
        else:
            # JSON primitive at root level — rare but valid.
            return [{"_value": parsed}], "primitive"

    def _parse_jsonl(
        self,
        text: str,
        source_label: str,
    ) -> tuple[list[Any], str]:
        """
        Parse a JSON Lines document (one JSON object per line).

        Non-empty lines that are not valid JSON raise
        :class:`~src.exceptions.ExtractionError`.

        Returns
        -------
        tuple[list[Any], str]
            (list of parsed objects, ``"jsonl"``)
        """
        objects: list[Any] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                objects.append(obj)
            except json.JSONDecodeError as exc:
                raise ExtractionError(
                    f"Invalid JSON on line {line_no} of {source_label}: {exc}",
                    source_type=self.source_type.value,
                    source_path=source_label,
                    record_id=f"line-{line_no}",
                ) from exc
        return objects, "jsonl"
