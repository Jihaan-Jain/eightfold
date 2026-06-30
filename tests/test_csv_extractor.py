"""
tests/test_csv_extractor.py
============================

Unit tests for CsvExtractor.

Uses only in-memory tempfiles — no network calls.
"""

from __future__ import annotations

import csv
import io
import os
import stat
import tempfile
from pathlib import Path

import pytest

from src.extractors.csv_extractor import CsvExtractor
from src.exceptions import ExtractionError
from src.models import SourceType


# ── Fixtures ──────────────────────────────────────────────────


def _write_csv(content: str, suffix: str = ".csv") -> Path:
    """Write content to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return Path(path)


def _write_bytes(content: bytes, suffix: str = ".csv") -> Path:
    """Write raw bytes to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return Path(path)


@pytest.fixture(autouse=True)
def extractor() -> CsvExtractor:
    return CsvExtractor()


# ── supports() ────────────────────────────────────────────────


class TestSupports:
    def test_csv_extension(self, extractor) -> None:
        assert extractor.supports(Path("file.csv")) is True

    def test_tsv_extension(self, extractor) -> None:
        assert extractor.supports(Path("file.tsv")) is True

    def test_uppercase_extension(self, extractor) -> None:
        assert extractor.supports(Path("file.CSV")) is True

    def test_json_extension_not_supported(self, extractor) -> None:
        assert extractor.supports(Path("file.json")) is False

    def test_pdf_not_supported(self, extractor) -> None:
        assert extractor.supports(Path("file.pdf")) is False

    def test_github_url_not_supported(self, extractor) -> None:
        assert extractor.supports("https://github.com/user") is False


# ── validate_source() ─────────────────────────────────────────


class TestValidateSource:
    def test_missing_file_raises(self, extractor) -> None:
        with pytest.raises(ExtractionError, match="not found"):
            extractor.validate_source(Path("nonexistent_file.csv"))

    def test_directory_raises(self, extractor, tmp_path) -> None:
        with pytest.raises(ExtractionError):
            extractor.validate_source(tmp_path)

    def test_valid_file_passes(self, extractor) -> None:
        path = _write_csv("name,email\nAlice,alice@x.com\n")
        try:
            extractor.validate_source(path)
        finally:
            path.unlink()


# ── extract() — Happy Path ────────────────────────────────────


class TestExtractHappyPath:
    def test_basic_two_row_csv(self, extractor) -> None:
        path = _write_csv("name,email\nAlice,alice@x.com\nBob,bob@x.com\n")
        try:
            records = extractor.extract(path)
            assert len(records) == 2
            assert records[0].raw_fields["name"] == "Alice"
            assert records[1].raw_fields["email"] == "bob@x.com"
        finally:
            path.unlink()

    def test_source_type_is_csv(self, extractor) -> None:
        path = _write_csv("name\nAlice\n")
        try:
            records = extractor.extract(path)
            assert records[0].source_type == SourceType.CSV
        finally:
            path.unlink()

    def test_record_id_auto_generated(self, extractor) -> None:
        path = _write_csv("name\nAlice\n")
        try:
            records = extractor.extract(path)
            assert records[0].record_id is not None
            assert len(records[0].record_id) > 0
        finally:
            path.unlink()

    def test_metadata_contains_expected_keys(self, extractor) -> None:
        path = _write_csv("name,email\nAlice,a@x.com\n")
        try:
            records = extractor.extract(path)
            meta = records[0].metadata
            # Standard block
            for key in ("checksum", "file_size", "mime", "encoding", "pages", "language"):
                assert key in meta, f"Missing standard metadata key: {key}"
            # CSV-specific
            for key in ("delimiter", "headers", "row_number", "duplicate_row",
                        "total_rows", "empty_rows_skipped"):
                assert key in meta, f"Missing CSV metadata key: {key}"
        finally:
            path.unlink()

    def test_row_number_is_one_indexed(self, extractor) -> None:
        path = _write_csv("name\nAlice\nBob\n")
        try:
            records = extractor.extract(path)
            assert records[0].metadata["row_number"] == 1
            assert records[1].metadata["row_number"] == 2
        finally:
            path.unlink()

    def test_tsv_file(self, extractor) -> None:
        path = _write_csv("name\temail\nAlice\talice@x.com\n", suffix=".tsv")
        try:
            records = extractor.extract(path)
            assert len(records) == 1
            assert records[0].raw_fields["name"] == "Alice"
        finally:
            path.unlink()

    def test_semicolon_delimiter(self, extractor) -> None:
        path = _write_csv("name;email\nAlice;alice@x.com\n")
        try:
            records = extractor.extract(path)
            assert len(records) == 1
            assert records[0].raw_fields["name"] == "Alice"
        finally:
            path.unlink()

    def test_pipe_delimiter(self, extractor) -> None:
        path = _write_csv("name|email\nAlice|alice@x.com\n")
        try:
            records = extractor.extract(path)
            assert len(records) == 1
        finally:
            path.unlink()


# ── extract() — Edge Cases ────────────────────────────────────


class TestExtractEdgeCases:
    def test_utf8_bom_encoding(self, extractor) -> None:
        bom_content = b"\xef\xbb\xbfname,email\nAlice,alice@x.com\n"
        path = _write_bytes(bom_content)
        try:
            records = extractor.extract(path)
            assert len(records) == 1
            # BOM should not appear in the field name.
            assert "name" in records[0].raw_fields
        finally:
            path.unlink()

    def test_empty_rows_skipped(self, extractor) -> None:
        path = _write_csv("name,email\nAlice,alice@x.com\n\n\nBob,bob@x.com\n")
        try:
            records = extractor.extract(path)
            # 2 data rows, 2 empty rows skipped.
            assert len(records) == 2
            assert records[0].metadata["empty_rows_skipped"] == 2
        finally:
            path.unlink()

    def test_duplicate_rows_flagged(self, extractor) -> None:
        path = _write_csv("name,email\nAlice,alice@x.com\nAlice,alice@x.com\n")
        try:
            records = extractor.extract(path)
            assert len(records) == 2
            assert records[0].metadata["duplicate_row"] is False
            assert records[1].metadata["duplicate_row"] is True
        finally:
            path.unlink()

    def test_quoted_commas_in_values(self, extractor) -> None:
        path = _write_csv('name,title\n"Alice, Jr.","Engineer, Lead"\n')
        try:
            records = extractor.extract(path)
            assert len(records) == 1
            assert records[0].raw_fields["name"] == "Alice, Jr."
            assert records[0].raw_fields["title"] == "Engineer, Lead"
        finally:
            path.unlink()

    def test_missing_header_uses_generated_names(self) -> None:
        extractor = CsvExtractor(config={"has_header": False})
        path = _write_csv("Alice,alice@x.com\nBob,bob@x.com\n")
        try:
            records = extractor.extract(path)
            assert len(records) == 2
            assert "col_0" in records[0].raw_fields
            assert "col_1" in records[0].raw_fields
        finally:
            path.unlink()

    def test_header_only_csv_returns_empty_list(self, extractor) -> None:
        path = _write_csv("name,email\n")
        try:
            records = extractor.extract(path)
            assert records == []
        finally:
            path.unlink()

    def test_forced_delimiter_config(self) -> None:
        extractor = CsvExtractor(config={"delimiter": ";"})
        path = _write_csv("name;email\nAlice;alice@x.com\n")
        try:
            records = extractor.extract(path)
            assert records[0].raw_fields["name"] == "Alice"
        finally:
            path.unlink()

    def test_total_rows_includes_empty_rows(self, extractor) -> None:
        path = _write_csv("name\nAlice\n\nBob\n")
        try:
            records = extractor.extract(path)
            # total_rows = 3 (Alice + empty + Bob), empty_skipped = 1
            assert records[0].metadata["total_rows"] == 3
        finally:
            path.unlink()

    def test_file_hash_in_metadata(self, extractor) -> None:
        path = _write_csv("name\nAlice\n")
        try:
            records = extractor.extract(path)
            checksum = records[0].metadata["checksum"]
            assert isinstance(checksum, str)
            assert checksum.startswith("sha256:")
            # sha256: prefix (7) + 64 hex chars = 71
            assert len(checksum) == 71
        finally:
            path.unlink()


# ── extract() — Error Cases ───────────────────────────────────


class TestExtractErrors:
    def test_standard_metadata_values(self, extractor) -> None:
        """Standard block values are correct for CSV records."""
        path = _write_csv("name\nAlice\n")
        try:
            records = extractor.extract(path)
            meta = records[0].metadata
            assert meta["pages"] is None
            assert meta["language"] is None
            assert meta["encoding"] in ("utf-8", "utf-8-sig", "ascii")
            assert isinstance(meta["file_size"], int)
            assert meta["file_size"] > 0
        finally:
            path.unlink()

    def test_nonexistent_file_raises(self, extractor) -> None:
        with pytest.raises(ExtractionError):
            extractor.extract(Path("does_not_exist.csv"))

    def test_metadata_method_returns_dict(self, extractor) -> None:
        m = extractor.metadata()
        assert isinstance(m, dict)
        assert m["source_type"] == "csv"
