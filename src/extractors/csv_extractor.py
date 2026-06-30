"""
src/extractors/csv_extractor.py
================================

Extractor for recruiter-managed CSV / TSV source files.

Features
--------
- Auto-detects character encoding (UTF-8, UTF-8 BOM, Latin-1, etc.)
- Auto-detects delimiter from a candidate set (',' '\\t' ';' '|')
- Handles missing / malformed headers (generates ``col_0 … col_N``)
- Skips completely empty rows silently
- Detects and flags duplicate rows in metadata
- Stores every column value as a raw string — no type coercion

RawRecord layout
----------------
``raw_fields``
    Dict of ``{header: value}`` for every column in the row.
    Values are always ``str | None``.

``metadata`` — standard block (all extractors)
    +-------------------+----------------------------------------------+
    | Key               | Value                                        |
    +===================+==============================================+
    | ``checksum``      | ``"sha256:<hex>"`` digest of the file        |
    | ``file_size``     | File size in bytes (int)                     |
    | ``mime``          | Detected MIME type string                    |
    | ``encoding``      | Detected / used encoding string              |
    | ``pages``         | ``None`` (N/A for CSV)                       |
    | ``language``      | ``None`` (N/A for CSV)                       |
    +-------------------+----------------------------------------------+

``metadata`` — CSV-specific keys
    +-----------------------+------------------------------------------+
    | Key                   | Value                                    |
    +=======================+==========================================+
    | ``delimiter``         | Detected delimiter character (repr)      |
    | ``headers``           | List of column header strings            |
    | ``total_rows``        | Total data lines (incl. blank)           |
    | ``empty_rows_skipped``| Count of blank rows skipped              |
    | ``duplicate_row``     | ``True`` when this record is a duplicate |
    | ``row_number``        | 1-based row number in the source file    |
    +-----------------------+------------------------------------------+
"""

from __future__ import annotations

import csv
import io
import itertools
from pathlib import Path
from typing import Any

from src.exceptions import ExtractionError
from src.extractors.base import BaseExtractor
from src.extractors.utils import (
    build_standard_metadata,
    detect_encoding,
    detect_mime_type,
    hash_file,
    is_empty_row,
    hash_row,
    normalise_source_label,
    safe_read_bytes,
)
from src.models import RawRecord, SourceType

# Candidate delimiters tried in preference order.
_CANDIDATE_DELIMITERS: list[str] = [",", "\t", ";", "|"]

# How many bytes to feed to csv.Sniffer for delimiter detection.
_SNIFFER_SAMPLE_BYTES: int = 8192

# Fallback delimiter when Sniffer fails.
_DEFAULT_DELIMITER: str = ","

# Maximum bytes read for encoding detection.
_ENCODING_SAMPLE: int = 32768


class CsvExtractor(BaseExtractor):
    """
    Extractor for candidate data stored in CSV or TSV files.

    Config Keys
    -----------
    ``delimiter`` (str | None)
        Force a specific delimiter.  When ``None`` (default), the
        extractor auto-detects from ``,``, ``\\t``, ``;``, ``|``.
    ``has_header`` (bool)
        ``True`` (default) — first row is a header.
        ``False`` — generate synthetic headers ``col_0 … col_N``.
    ``skip_duplicates`` (bool)
        When ``True`` (default), duplicate rows are still returned but
        their ``metadata["duplicate_row"]`` flag is set to ``True``.
    ``encoding`` (str | None)
        Force a specific encoding.  When ``None`` (default),
        auto-detected via :func:`~src.extractors.utils.detect_encoding`.

    Examples
    --------
    ::

        extractor = CsvExtractor()
        records = extractor.extract(Path("data/recruiter_q3.csv"))
        print(len(records))  # → 1 per data row
    """

    # ── BaseExtractor interface ───────────────────────────────

    @property
    def source_type(self) -> SourceType:
        """Returns :attr:`~src.models.SourceType.CSV`."""
        return SourceType.CSV

    def supports(self, source: str | Path) -> bool:
        """
        Return ``True`` for ``.csv`` and ``.tsv`` file extensions.

        Parameters
        ----------
        source:
            File path (extension is inspected) or URL string.
        """
        return Path(str(source)).suffix.lower() in {".csv", ".tsv"}

    def validate_source(self, source: str | Path) -> None:
        """
        Check that ``source`` is a readable file with a CSV-compatible
        MIME type or extension.

        Raises
        ------
        src.exceptions.ExtractionError
            If the file is absent, unreadable, or is a binary format
            (e.g. PDF, ZIP) that cannot be a CSV.
        """
        p = Path(str(source))
        if not p.exists():
            raise ExtractionError(
                f"CSV source file not found: {p}",
                source_type=self.source_type.value,
                source_path=str(p),
            )
        if not p.is_file():
            raise ExtractionError(
                f"CSV source is not a regular file: {p}",
                source_type=self.source_type.value,
                source_path=str(p),
            )
        mime = detect_mime_type(p)
        blocked_mimes = {"application/pdf", "application/zip",
                         "image/png", "image/jpeg"}
        if mime in blocked_mimes:
            raise ExtractionError(
                f"CSV source has incompatible MIME type '{mime}': {p}",
                source_type=self.source_type.value,
                source_path=str(p),
            )

    def extract(self, source: str | Path) -> list[RawRecord]:
        """
        Parse a CSV / TSV file and return one :class:`~src.models.RawRecord`
        per non-empty data row.

        Parameters
        ----------
        source:
            Path to the CSV / TSV file.

        Returns
        -------
        list[RawRecord]
            One record per data row.  Empty list if the file has no
            data rows.

        Raises
        ------
        src.exceptions.ExtractionError
            On file-not-found, permission error, or unrecoverable parse
            failure.
        """
        self.validate_source(source)
        return self._timed_extract(source, self._do_extract)

    def metadata(self) -> dict[str, Any]:
        """Return static metadata about this extractor."""
        return {
            "extractor":   self.__class__.__name__,
            "source_type": self.source_type.value,
            "version":     "1.0.0",
            "supported_extensions": [".csv", ".tsv"],
            "supported_delimiters": _CANDIDATE_DELIMITERS,
        }

    # ── Internal implementation ───────────────────────────────

    def _do_extract(self, source: str | Path) -> list[RawRecord]:
        """
        Core extraction logic — reads, decodes, sniffs, and parses
        the CSV file row by row.

        Parameters
        ----------
        source:
            Validated file path.

        Returns
        -------
        list[RawRecord]
            One record per data row (empty / duplicate rows flagged).
        """
        p = Path(str(source))
        source_label = normalise_source_label(p)

        # ── Read bytes ────────────────────────────────────────
        raw_bytes = safe_read_bytes(p)
        file_hash  = hash_file(p)
        file_size  = p.stat().st_size
        mime_type  = detect_mime_type(p)

        # ── Detect encoding ───────────────────────────────────
        forced_enc = self._config.get("encoding")
        encoding = forced_enc if forced_enc else detect_encoding(raw_bytes)
        try:
            text = raw_bytes.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            # Unknown encoding name — fall back gracefully.
            encoding = "utf-8"
            text = raw_bytes.decode("utf-8", errors="replace")

        # ── Detect delimiter ──────────────────────────────────
        forced_delim = self._config.get("delimiter")
        delimiter = forced_delim if forced_delim else self._detect_delimiter(text)

        # ── Determine header mode ─────────────────────────────
        has_header: bool = bool(self._config.get("has_header", True))

        # ── Count raw data lines (for accurate empty-row accounting) ─────
        # csv.DictReader silently skips blank lines, so we count them
        # from the raw text before parsing.
        all_lines = text.splitlines()
        # Skip the header line (if present) for counting.
        data_lines = all_lines[1:] if has_header else all_lines
        # A line is "empty" if it strips to nothing.
        raw_empty_count: int = sum(1 for line in data_lines if not line.strip())
        raw_total_count: int = len(data_lines)

        # ── Parse rows ────────────────────────────────────────
        records: list[RawRecord] = []
        seen_hashes: set[str] = set()
        total_rows: int = 0
        empty_skipped: int = 0

        try:
            reader = self._make_reader(text, delimiter, has_header)
            headers: list[str] = []

            for line_idx, row in enumerate(reader, start=1):
                total_rows += 1

                if isinstance(row, dict):
                    # DictReader path
                    if not headers:
                        headers = list(row.keys())
                    row_dict: dict[str, Any] = dict(row)
                else:
                    # Plain reader path (no header row)
                    if not headers:
                        headers = [f"col_{i}" for i in range(len(row))]
                    row_dict = dict(zip(headers, row))

                # Skip blank rows
                if is_empty_row(row_dict):
                    empty_skipped += 1
                    continue

                # Detect duplicate
                row_hash = hash_row(row_dict)
                is_duplicate = row_hash in seen_hashes
                seen_hashes.add(row_hash)

                record = RawRecord(
                    source=source_label,
                    source_type=self.source_type,
                    raw_fields=row_dict,
                    metadata={
                        # ── Standard block (same keys in every extractor) ──
                        **build_standard_metadata(
                            checksum=f"sha256:{file_hash}",
                            file_size=file_size,
                            mime=mime_type,
                            encoding=encoding,
                            pages=None,
                            language=None,
                        ),
                        # ── CSV-specific ───────────────────────────────────
                        "delimiter":          repr(delimiter),
                        "headers":            headers,
                        "total_rows":         None,  # back-filled after loop
                        "empty_rows_skipped": None,  # back-filled after loop
                        "duplicate_row":      is_duplicate,
                        "row_number":         line_idx,
                    },
                )
                records.append(record)

        except csv.Error as exc:
            raise ExtractionError(
                f"CSV parse error in {source_label}: {exc}",
                source_type=self.source_type.value,
                source_path=source_label,
            ) from exc

        # ── Back-fill aggregate metadata ──────────────────────
        # Use the raw line counts (which include blank lines DictReader
        # skipped) so consumers see accurate total_rows / empty_rows_skipped.
        final_records: list[RawRecord] = []
        for rec in records:
            updated_meta = {
                **rec.metadata,
                "total_rows":         raw_total_count,
                "empty_rows_skipped": raw_empty_count,
            }
            final_records.append(
                rec.model_copy(update={"metadata": updated_meta})
            )

        self._log.debug(
            "CSV parsed",
            extra={
                "source": source_label,
                "total_rows": total_rows,
                "empty_skipped": empty_skipped,
                "records": len(final_records),
                "encoding": encoding,
                "delimiter": repr(delimiter),
            },
        )
        return final_records

    # ── Private helpers ───────────────────────────────────────

    def _detect_delimiter(self, text: str) -> str:
        """
        Auto-detect the field delimiter in a CSV text string.

        First tries :class:`csv.Sniffer`; if that fails or the detected
        delimiter is not in the candidate set, counts occurrences of
        each candidate per header line and picks the most frequent.

        Parameters
        ----------
        text:
            Full decoded CSV text.

        Returns
        -------
        str
            The detected delimiter character.
        """
        sample = text[:_SNIFFER_SAMPLE_BYTES]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters="".join(_CANDIDATE_DELIMITERS))
            if dialect.delimiter in _CANDIDATE_DELIMITERS:
                return dialect.delimiter
        except csv.Error:
            pass

        # Fallback: count occurrences in first non-empty line.
        first_line = next(
            (line for line in text.splitlines() if line.strip()), ""
        )
        counts = {d: first_line.count(d) for d in _CANDIDATE_DELIMITERS}
        best = max(counts, key=lambda d: counts[d])
        return best if counts[best] > 0 else _DEFAULT_DELIMITER

    def _make_reader(
        self,
        text: str,
        delimiter: str,
        has_header: bool,
    ) -> Any:
        """
        Construct a csv.DictReader or csv.reader from decoded text.

        Parameters
        ----------
        text:
            Full decoded CSV content.
        delimiter:
            Detected or forced delimiter character.
        has_header:
            Whether to treat the first row as column headers.

        Returns
        -------
        csv.DictReader | csv.reader
            Iterator over rows.
        """
        stream = io.StringIO(text)
        if has_header:
            reader = csv.DictReader(
                stream,
                delimiter=delimiter,
                skipinitialspace=True,
            )
            # Replace blank / None header names with generated names.
            if reader.fieldnames:
                reader.fieldnames = [
                    h.strip() if h and h.strip() else f"col_{i}"
                    for i, h in enumerate(reader.fieldnames)
                ]
            return reader
        else:
            return csv.reader(
                stream,
                delimiter=delimiter,
                skipinitialspace=True,
            )
