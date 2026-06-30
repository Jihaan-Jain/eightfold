"""
tests/test_pdf_extractor.py
============================

Unit tests for ResumePdfExtractor.

Strategy
--------
- Happy-path tests use a real minimal PDF created with pdfplumber's
  dependency (pdfminer / reportlab is not available, so we create
  the smallest valid PDF inline as bytes).
- Failure-path tests mock pdfplumber and pypdf to control exact
  error conditions without needing actual corrupt files.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.extractors.resume_pdf_extractor import ResumePdfExtractor
from src.exceptions import ExtractionError
from src.models import SourceType


# ── Minimal valid PDF bytes (real %PDF header, no text) ───────

# A syntactically minimal PDF that any library will open without error.
# It has 1 page with no content stream, but is structurally valid.
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer\n<< /Size 4 /Root 1 0 R >>\n"
    b"startxref\n210\n%%EOF\n"
)


def _write_bytes(content: bytes, suffix: str = ".pdf") -> Path:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return Path(path)


@pytest.fixture
def extractor() -> ResumePdfExtractor:
    return ResumePdfExtractor()


# ── supports() ────────────────────────────────────────────────


class TestSupports:
    def test_pdf_extension(self, extractor) -> None:
        assert extractor.supports(Path("file.pdf")) is True

    def test_uppercase_pdf(self, extractor) -> None:
        assert extractor.supports(Path("RESUME.PDF")) is True

    def test_csv_not_supported(self, extractor) -> None:
        assert extractor.supports(Path("file.csv")) is False

    def test_json_not_supported(self, extractor) -> None:
        assert extractor.supports(Path("file.json")) is False

    def test_github_url_not_supported(self, extractor) -> None:
        assert extractor.supports("https://github.com/user") is False


# ── validate_source() ─────────────────────────────────────────


class TestValidateSource:
    def test_missing_file_raises(self, extractor) -> None:
        with pytest.raises(ExtractionError, match="not found"):
            extractor.validate_source(Path("ghost.pdf"))

    def test_non_pdf_magic_bytes_raises(self, extractor) -> None:
        path = _write_bytes(b"NOT A PDF HEADER")
        try:
            with pytest.raises(ExtractionError, match="missing %PDF"):
                extractor.validate_source(path)
        finally:
            path.unlink()

    def test_valid_pdf_magic_bytes_passes(self, extractor) -> None:
        path = _write_bytes(_MINIMAL_PDF)
        try:
            extractor.validate_source(path)  # Must not raise
        finally:
            path.unlink()

    def test_directory_raises(self, extractor, tmp_path) -> None:
        with pytest.raises(ExtractionError):
            extractor.validate_source(tmp_path)


# ── extract() — mocked pdfplumber ────────────────────────────


class TestExtractWithMockedPdfplumber:
    def test_returns_single_record(self, extractor) -> None:
        path = _write_bytes(_MINIMAL_PDF)
        try:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "Alice Smith\nSoftware Engineer"

            mock_pdf = MagicMock()
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)
            mock_pdf.pages = [mock_page]
            mock_pdf.metadata = {"Author": "Alice Smith", "Title": "Resume"}

            with patch("pdfplumber.open", return_value=mock_pdf):
                records = extractor.extract(path)

            assert len(records) == 1
        finally:
            path.unlink()

    def test_source_type_is_resume(self, extractor) -> None:
        path = _write_bytes(_MINIMAL_PDF)
        try:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "Some text"
            mock_pdf = MagicMock()
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)
            mock_pdf.pages = [mock_page]
            mock_pdf.metadata = {}

            with patch("pdfplumber.open", return_value=mock_pdf):
                records = extractor.extract(path)

            assert records[0].source_type == SourceType.RESUME
        finally:
            path.unlink()

    def test_full_text_concatenates_pages(self, extractor) -> None:
        path = _write_bytes(_MINIMAL_PDF)
        try:
            pages = [MagicMock(), MagicMock()]
            pages[0].extract_text.return_value = "Page one content"
            pages[1].extract_text.return_value = "Page two content"

            mock_pdf = MagicMock()
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)
            mock_pdf.pages = pages
            mock_pdf.metadata = {}

            with patch("pdfplumber.open", return_value=mock_pdf):
                records = extractor.extract(path)

            full_text = records[0].raw_fields["full_text"]
            assert "Page one content" in full_text
            assert "Page two content" in full_text
        finally:
            path.unlink()

    def test_raw_fields_keys(self, extractor) -> None:
        path = _write_bytes(_MINIMAL_PDF)
        try:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "hello world"
            mock_pdf = MagicMock()
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)
            mock_pdf.pages = [mock_page]
            mock_pdf.metadata = {}

            with patch("pdfplumber.open", return_value=mock_pdf):
                records = extractor.extract(path)

            rf = records[0].raw_fields
            assert "full_text" in rf
            assert "pages" in rf
            assert "char_count" in rf
            assert "word_count" in rf
        finally:
            path.unlink()

    def test_metadata_keys(self, extractor) -> None:
        path = _write_bytes(_MINIMAL_PDF)
        try:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "text"
            mock_pdf = MagicMock()
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)
            mock_pdf.pages = [mock_page]
            mock_pdf.metadata = {"Author": "Test"}

            with patch("pdfplumber.open", return_value=mock_pdf):
                records = extractor.extract(path)

            meta = records[0].metadata
            # Standard block
            for key in ("checksum", "file_size", "mime", "encoding", "pages", "language"):
                assert key in meta, f"Missing standard key: {key}"
            # PDF-specific
            for key in ("extraction_method", "pdf_metadata", "encrypted"):
                assert key in meta, f"Missing PDF key: {key}"
            # PDF-specific standard values
            assert meta["mime"] == "application/pdf"
            assert meta["encoding"] is None   # binary; no text decode
            assert meta["pages"] == 1         # one mock page
            assert meta["language"] is None
        finally:
            path.unlink()

    def test_extraction_method_is_pdfplumber(self, extractor) -> None:
        path = _write_bytes(_MINIMAL_PDF)
        try:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "text"
            mock_pdf = MagicMock()
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)
            mock_pdf.pages = [mock_page]
            mock_pdf.metadata = {}

            with patch("pdfplumber.open", return_value=mock_pdf):
                records = extractor.extract(path)

            assert records[0].metadata["extraction_method"] == "pdfplumber"
        finally:
            path.unlink()

    def test_page_with_no_text_stores_empty_string(self, extractor) -> None:
        path = _write_bytes(_MINIMAL_PDF)
        try:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = None  # pdfplumber returns None for image pages

            mock_pdf = MagicMock()
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)
            mock_pdf.pages = [mock_page]
            mock_pdf.metadata = {}

            with patch("pdfplumber.open", return_value=mock_pdf):
                records = extractor.extract(path)

            pages = records[0].raw_fields["pages"]
            assert pages == [""]
        finally:
            path.unlink()


# ── extract() — fallback to pypdf ─────────────────────────────


class TestFallbackToPypdf:
    def test_pdfplumber_failure_falls_back_to_pypdf(self, extractor) -> None:
        path = _write_bytes(_MINIMAL_PDF)
        try:
            mock_pypdf_page = MagicMock()
            mock_pypdf_page.extract_text.return_value = "Fallback text"
            mock_reader = MagicMock()
            mock_reader.is_encrypted = False
            mock_reader.pages = [mock_pypdf_page]
            mock_reader.metadata = None

            mock_reader_ctx = MagicMock()
            mock_reader_ctx.__enter__ = MagicMock(return_value=mock_reader)
            mock_reader_ctx.__exit__ = MagicMock(return_value=False)

            with patch("pdfplumber.open", side_effect=Exception("pdfplumber broke")):
                with patch("pypdf.PdfReader", return_value=mock_reader):
                    records = extractor.extract(path)

            assert records[0].metadata["extraction_method"] == "pypdf"
            assert "Fallback text" in records[0].raw_fields["full_text"]
        finally:
            path.unlink()


# ── extract() — graceful failure ──────────────────────────────


class TestGracefulFailure:
    def test_both_libraries_fail_returns_empty_text_record(self, extractor) -> None:
        path = _write_bytes(_MINIMAL_PDF)
        try:
            with patch("pdfplumber.open", side_effect=Exception("pdfplumber broke")):
                with patch("pypdf.PdfReader", side_effect=Exception("pypdf broke")):
                    records = extractor.extract(path)

            assert len(records) == 1
            assert records[0].raw_fields["full_text"] == ""
            assert records[0].metadata["extraction_method"] == "failed"
        finally:
            path.unlink()


# ── Error cases ────────────────────────────────────────────────


class TestErrors:
    def test_nonexistent_file_raises(self, extractor) -> None:
        with pytest.raises(ExtractionError):
            extractor.extract(Path("ghost.pdf"))

    def test_metadata_method(self, extractor) -> None:
        m = extractor.metadata()
        assert m["source_type"] == "resume"
        assert m["primary_library"] == "pdfplumber"
        assert m["fallback_library"] == "pypdf"
