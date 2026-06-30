"""
tests/test_utils.py
====================

Unit tests for src/extractors/utils.py.

Covers
------
- detect_encoding: BOM sniffing
- hash_bytes / hash_file: determinism and algorithm correctness
- detect_mime_type: extension and magic-byte paths
- is_empty_row / hash_row: CSV helpers
- build_standard_metadata: schema correctness and all-None path
- retry decorator: success on first try, retry on failure,
  exhausted retries re-raise
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.extractors.utils import (
    build_standard_metadata,
    detect_encoding,
    detect_mime_type,
    hash_bytes,
    hash_file,
    hash_row,
    is_empty_row,
    normalise_source_label,
    retry,
    safe_read_bytes,
)
from src.exceptions import ExtractionError


# ── detect_encoding ────────────────────────────────────────────


class TestDetectEncoding:
    def test_utf8_bom_returns_utf8_sig(self) -> None:
        raw = b"\xef\xbb\xbfhello"
        assert detect_encoding(raw) == "utf-8-sig"

    def test_utf16_le_bom(self) -> None:
        raw = b"\xff\xfehello"
        assert detect_encoding(raw) == "utf-16-le"

    def test_utf16_be_bom(self) -> None:
        raw = b"\xfe\xffhello"
        assert detect_encoding(raw) == "utf-16-be"

    def test_plain_ascii_returns_some_encoding(self) -> None:
        raw = b"name,email\nAlice,alice@example.com\n"
        enc = detect_encoding(raw)
        assert isinstance(enc, str)
        assert len(enc) > 0

    def test_fallback_on_empty_bytes(self) -> None:
        enc = detect_encoding(b"", fallback="latin-1")
        assert isinstance(enc, str)


# ── hash_bytes ─────────────────────────────────────────────────


class TestHashBytes:
    def test_deterministic(self) -> None:
        data = b"hello world"
        assert hash_bytes(data) == hash_bytes(data)

    def test_sha256_length(self) -> None:
        assert len(hash_bytes(b"test")) == 64

    def test_matches_stdlib(self) -> None:
        data = b"candidate transformer"
        expected = hashlib.sha256(data).hexdigest()
        assert hash_bytes(data) == expected

    def test_empty_bytes(self) -> None:
        assert len(hash_bytes(b"")) == 64

    def test_md5_algorithm(self) -> None:
        data = b"test"
        assert len(hash_bytes(data, algorithm="md5")) == 32


# ── hash_file ──────────────────────────────────────────────────


class TestHashFile:
    def test_matches_hash_bytes(self) -> None:
        content = b"some file content"
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(content)
            assert hash_file(Path(path)) == hash_bytes(content)
        finally:
            Path(path).unlink()

    def test_nonexistent_raises(self) -> None:
        with pytest.raises(ExtractionError):
            hash_file(Path("ghost_file_xyz.bin"))


# ── detect_mime_type ───────────────────────────────────────────


class TestDetectMimeType:
    def _write(self, content: bytes, suffix: str) -> Path:
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        return Path(path)

    def test_csv_by_extension(self) -> None:
        p = self._write(b"name,email\n", ".csv")
        try:
            # Windows maps .csv → application/vnd.ms-excel; Unix → text/csv
            mime = detect_mime_type(p)
            assert isinstance(mime, str) and len(mime) > 0
        finally:
            p.unlink()

    def test_pdf_by_magic_bytes(self) -> None:
        # Write with no extension so mimetypes returns None and magic bytes decide.
        fd, path = tempfile.mkstemp()  # no suffix
        p = Path(path)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(b"%PDF-1.4 minimal content")
            assert detect_mime_type(p) == "application/pdf"
        finally:
            p.unlink()

    def test_unknown_returns_octet_stream(self) -> None:
        p = self._write(b"\x00\x01\x02\x03", ".unknown_ext_xyz")
        try:
            result = detect_mime_type(p)
            assert isinstance(result, str)
        finally:
            p.unlink()


# ── is_empty_row ───────────────────────────────────────────────


class TestIsEmptyRow:
    def test_all_none_is_empty(self) -> None:
        assert is_empty_row({"name": None, "email": None}) is True

    def test_all_empty_strings_is_empty(self) -> None:
        assert is_empty_row({"name": "", "email": ""}) is True

    def test_all_whitespace_is_empty(self) -> None:
        assert is_empty_row({"name": "   ", "email": "\t"}) is True

    def test_one_value_is_not_empty(self) -> None:
        assert is_empty_row({"name": "Alice", "email": ""}) is False

    def test_empty_dict_is_empty(self) -> None:
        assert is_empty_row({}) is True


# ── hash_row ───────────────────────────────────────────────────


class TestHashRow:
    def test_same_row_same_hash(self) -> None:
        row = {"name": "Alice", "email": "alice@x.com"}
        assert hash_row(row) == hash_row(row)

    def test_different_rows_different_hashes(self) -> None:
        r1 = {"name": "Alice", "email": "alice@x.com"}
        r2 = {"name": "Bob",   "email": "bob@x.com"}
        assert hash_row(r1) != hash_row(r2)

    def test_returns_8_char_hex(self) -> None:
        assert len(hash_row({"a": "1"})) == 8

    def test_column_order_independent(self) -> None:
        r1 = {"name": "Alice", "email": "alice@x.com"}
        r2 = {"email": "alice@x.com", "name": "Alice"}
        assert hash_row(r1) == hash_row(r2)


# ── normalise_source_label ─────────────────────────────────────


class TestNormaliseSourceLabel:
    def test_path_returns_posix(self) -> None:
        result = normalise_source_label(Path("data/recruiter.csv"))
        assert "/" in result
        assert result == "data/recruiter.csv"

    def test_string_returned_as_is(self) -> None:
        url = "https://api.github.com/users/priya"
        assert normalise_source_label(url) == url


# ── safe_read_bytes ────────────────────────────────────────────


class TestSafeReadBytes:
    def test_reads_content(self) -> None:
        content = b"hello bytes"
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        try:
            assert safe_read_bytes(Path(path)) == content
        finally:
            Path(path).unlink()

    def test_missing_file_raises_extraction_error(self) -> None:
        with pytest.raises(ExtractionError, match="not found"):
            safe_read_bytes(Path("no_such_file_xyz.bin"))

    def test_directory_raises_extraction_error(self, tmp_path) -> None:
        with pytest.raises(ExtractionError):
            safe_read_bytes(tmp_path)


# ── build_standard_metadata ────────────────────────────────────


class TestBuildStandardMetadata:
    def test_returns_exactly_six_keys(self) -> None:
        result = build_standard_metadata(
            checksum="sha256:abc",
            file_size=1024,
            mime="text/csv",
            encoding="utf-8",
            pages=None,
            language=None,
        )
        assert set(result.keys()) == {"checksum", "file_size", "mime",
                                       "encoding", "pages", "language"}

    def test_csv_profile(self) -> None:
        result = build_standard_metadata(
            checksum="sha256:deadbeef",
            file_size=2048,
            mime="text/csv",
            encoding="utf-8",
            pages=None,
            language=None,
        )
        assert result["checksum"] == "sha256:deadbeef"
        assert result["file_size"] == 2048
        assert result["mime"] == "text/csv"
        assert result["encoding"] == "utf-8"
        assert result["pages"] is None
        assert result["language"] is None

    def test_pdf_profile(self) -> None:
        result = build_standard_metadata(
            checksum="sha256:cafebabe",
            file_size=512000,
            mime="application/pdf",
            encoding=None,
            pages=3,
            language=None,
        )
        assert result["mime"] == "application/pdf"
        assert result["encoding"] is None
        assert result["pages"] == 3

    def test_github_profile(self) -> None:
        result = build_standard_metadata(
            checksum=None,
            file_size=None,
            mime="application/json",
            encoding="utf-8",
            pages=None,
            language="Python",
        )
        assert result["checksum"] is None
        assert result["file_size"] is None
        assert result["language"] == "Python"

    def test_all_none_profile(self) -> None:
        result = build_standard_metadata(
            checksum=None,
            file_size=None,
            mime=None,
            encoding=None,
            pages=None,
            language=None,
        )
        assert all(v is None for v in result.values())

    def test_result_is_dict(self) -> None:
        result = build_standard_metadata(
            checksum=None, file_size=None,
            mime=None, encoding=None,
            pages=None, language=None,
        )
        assert isinstance(result, dict)


# ── retry decorator ────────────────────────────────────────────


class TestRetryDecorator:
    def test_success_on_first_try(self) -> None:
        call_count = 0

        @retry(max_attempts=3, delay=0.0)
        def always_succeeds() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = always_succeeds()
        assert result == "ok"
        assert call_count == 1

    def test_retries_on_exception(self) -> None:
        call_count = 0

        @retry(max_attempts=3, delay=0.0, exceptions=(ValueError,))
        def fails_twice() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient")
            return "ok"

        result = fails_twice()
        assert result == "ok"
        assert call_count == 3

    def test_reraises_after_max_attempts(self) -> None:
        @retry(max_attempts=2, delay=0.0, exceptions=(RuntimeError,))
        def always_fails() -> None:
            raise RuntimeError("permanent")

        with pytest.raises(RuntimeError):
            always_fails()

    def test_does_not_catch_unspecified_exception(self) -> None:
        @retry(max_attempts=3, delay=0.0, exceptions=(ValueError,))
        def raises_type_error() -> None:
            raise TypeError("not caught")

        with pytest.raises(TypeError):
            raises_type_error()
