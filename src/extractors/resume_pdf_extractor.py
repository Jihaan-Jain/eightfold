"""
src/extractors/resume_pdf_extractor.py
=======================================

Extractor for candidate résumé documents in PDF format.

**Extraction scope only** — this module reads text and metadata from a
PDF file and stores them verbatim in a :class:`~src.models.RawRecord`.
It does NOT parse names, emails, skills, or any other field from the
text.  Field parsing is the responsibility of downstream pipeline stages.

PDF Library Strategy
--------------------
1. **pdfplumber** (preferred) — provides per-page text with layout
   awareness (preserves column structure better than raw PDF parsers).
2. **pypdf** (fallback) — used when ``pdfplumber`` is not installed or
   raises an exception on a specific file.

If both libraries fail, the extractor stores an empty text string,
sets ``metadata["extraction_method"]`` to ``"failed"``, and returns
the record so the pipeline knows extraction was attempted.

RawRecord layout
----------------
``raw_fields``
    +--------------------+----------------------------------------------+
    | Key                | Value                                        |
    +====================+==============================================+
    | ``full_text``      | Concatenated text from all pages             |
    | ``pages``          | List of per-page text strings                |
    | ``char_count``     | Total character count                        |
    | ``word_count``     | Approximate word count (whitespace split)    |
    +--------------------+----------------------------------------------+

``metadata`` — standard block
    +----------------------+------------------------------------------+
    | Key                  | Value                                    |
    +======================+==========================================+
    | ``checksum``         | ``"sha256:<hex>"`` digest of the file    |
    | ``file_size``        | File size in bytes (int)                 |
    | ``mime``             | ``"application/pdf"``                    |
    | ``encoding``         | ``None`` (PDF is binary; no text decode) |
    | ``pages``            | Total page count (int)                   |
    | ``language``         | ``None`` (N/A for PDF)                   |
    +----------------------+------------------------------------------+

``metadata`` — PDF-specific keys
    +------------------------+------------------------------------------+
    | Key                    | Value                                    |
    +========================+==========================================+
    | ``extraction_method``  | ``"pdfplumber"`` / ``"pypdf"`` / ``"failed"`` |
    | ``pdf_metadata``       | Raw PDF info dict (author, title …)     |
    | ``encrypted``          | ``True`` when the PDF is password-locked |
    +------------------------+------------------------------------------+
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.exceptions import ExtractionError
from src.extractors.base import BaseExtractor
from src.extractors.utils import (
    build_standard_metadata,
    detect_mime_type,
    hash_file,
    normalise_source_label,
)
from src.models import RawRecord, SourceType


class ResumePdfExtractor(BaseExtractor):
    """
    Extractor for candidate résumé PDF files.

    Returns **one** :class:`~src.models.RawRecord` per PDF file
    containing the full page text and PDF metadata.

    Config Keys
    -----------
    ``prefer_pypdf`` (bool)
        When ``True``, attempt ``pypdf`` first instead of ``pdfplumber``.
        Default: ``False``.
    ``page_separator`` (str)
        String inserted between pages when building ``full_text``.
        Default: ``"\\n\\n"`` (blank line).

    Examples
    --------
    ::

        extractor = ResumePdfExtractor()
        records = extractor.extract(Path("data/priya_sharma_cv.pdf"))
        assert len(records) == 1
        print(records[0].raw_fields["char_count"])
    """

    @property
    def source_type(self) -> SourceType:
        """Returns :attr:`~src.models.SourceType.RESUME`."""
        return SourceType.RESUME

    def supports(self, source: str | Path) -> bool:
        """Return ``True`` for ``.pdf`` file extension."""
        return Path(str(source)).suffix.lower() == ".pdf"

    def validate_source(self, source: str | Path) -> None:
        """
        Verify the file exists, is readable, and is a PDF.

        Raises
        ------
        src.exceptions.ExtractionError
            If the file is missing, not a regular file, or the first
            four bytes do not contain the PDF magic ``%PDF``.
        """
        p = Path(str(source))
        if not p.exists():
            raise ExtractionError(
                f"PDF resume not found: {p}",
                source_type=self.source_type.value,
                source_path=str(p),
            )
        if not p.is_file():
            raise ExtractionError(
                f"PDF source is not a regular file: {p}",
                source_type=self.source_type.value,
                source_path=str(p),
            )
        # Magic-byte check: PDF files must start with %PDF.
        try:
            header = p.read_bytes()[:4]
        except OSError as exc:
            raise ExtractionError(
                f"Cannot read PDF file {p}: {exc}",
                source_type=self.source_type.value,
                source_path=str(p),
            ) from exc

        if header != b"%PDF":
            raise ExtractionError(
                f"File does not appear to be a PDF (missing %PDF header): {p}",
                source_type=self.source_type.value,
                source_path=str(p),
            )

    def extract(self, source: str | Path) -> list[RawRecord]:
        """
        Extract text and metadata from a PDF résumé file.

        Returns a **single-element list** containing one
        :class:`~src.models.RawRecord` with the full page text,
        per-page text list, and PDF metadata.

        Parameters
        ----------
        source:
            Path to the PDF file.

        Returns
        -------
        list[RawRecord]
            Always a list with exactly one element.

        Raises
        ------
        src.exceptions.ExtractionError
            If the file is absent, not a PDF, or unreadable.
        """
        self.validate_source(source)
        return self._timed_extract(source, self._do_extract)

    def metadata(self) -> dict[str, Any]:
        """Return static metadata about this extractor."""
        return {
            "extractor":            self.__class__.__name__,
            "source_type":          self.source_type.value,
            "version":              "1.0.0",
            "supported_extensions": [".pdf"],
            "primary_library":      "pdfplumber",
            "fallback_library":     "pypdf",
        }

    # ── Internal implementation ───────────────────────────────

    def _do_extract(self, source: str | Path) -> list[RawRecord]:
        """Core extraction: try pdfplumber → pypdf → graceful failure."""
        p = Path(str(source))
        source_label = normalise_source_label(p)
        file_hash = hash_file(p)
        file_size = p.stat().st_size
        page_sep: str = self._config.get("page_separator", "\n\n")
        prefer_pypdf: bool = bool(self._config.get("prefer_pypdf", False))

        page_texts: list[str] = []
        page_count: int = 0
        pdf_meta: dict[str, Any] = {}
        extraction_method: str = "failed"
        encrypted: bool = False

        if prefer_pypdf:
            result = self._extract_pypdf(p, page_sep)
            if result is None:
                result = self._extract_pdfplumber(p, page_sep)
        else:
            result = self._extract_pdfplumber(p, page_sep)
            if result is None:
                result = self._extract_pypdf(p, page_sep)

        if result is not None:
            page_texts, page_count, pdf_meta, extraction_method, encrypted = result
        else:
            self._log.warning(
                "All PDF extraction methods failed — storing empty text",
                extra={"source": source_label},
            )

        full_text = page_sep.join(page_texts)
        char_count = len(full_text)
        word_count = len(full_text.split())

        record = RawRecord(
            source=source_label,
            source_type=self.source_type,
            raw_fields={
                "full_text":  full_text,
                "pages":      page_texts,
                "char_count": char_count,
                "word_count": word_count,
            },
            metadata={
                # ── Standard block ──────────────────────────────────
                **build_standard_metadata(
                    checksum=f"sha256:{file_hash}",
                    file_size=file_size,
                    mime="application/pdf",
                    encoding=None,        # PDF is binary; no text decode step
                    pages=page_count,     # <─ non-None only for PDF records
                    language=None,
                ),
                # ── PDF-specific ─────────────────────────────────
                "extraction_method":  extraction_method,
                "pdf_metadata":       pdf_meta,
                "encrypted":          encrypted,
            },
        )
        return [record]

    # ── Library-specific helpers ──────────────────────────────

    def _extract_pdfplumber(
        self,
        path: Path,
        page_sep: str,
    ) -> tuple[list[str], int, dict[str, Any], str, bool] | None:
        """
        Attempt text extraction via ``pdfplumber``.

        Returns
        -------
        tuple | None
            ``(page_texts, page_count, pdf_meta, method, encrypted)``
            or ``None`` if pdfplumber is unavailable or fails.
        """
        try:
            import pdfplumber  # type: ignore[import]
        except ImportError:
            self._log.debug("pdfplumber not installed; skipping")
            return None

        try:
            with pdfplumber.open(str(path)) as pdf:
                page_count = len(pdf.pages)
                page_texts: list[str] = []
                for page in pdf.pages:
                    text = page.extract_text()
                    page_texts.append(text or "")

                # pdfplumber exposes PDF metadata via pdf.metadata
                raw_meta: dict[str, Any] = {}
                try:
                    raw_meta = dict(pdf.metadata or {})
                except Exception:
                    pass

                return page_texts, page_count, raw_meta, "pdfplumber", False

        except Exception as exc:
            self._log.warning(
                "pdfplumber extraction failed; will try fallback",
                extra={"path": str(path), "error": str(exc)},
            )
            return None

    def _extract_pypdf(
        self,
        path: Path,
        page_sep: str,
    ) -> tuple[list[str], int, dict[str, Any], str, bool] | None:
        """
        Attempt text extraction via ``pypdf`` (formerly PyPDF2).

        Returns
        -------
        tuple | None
            ``(page_texts, page_count, pdf_meta, method, encrypted)``
            or ``None`` if pypdf is unavailable or fails.
        """
        try:
            import pypdf  # type: ignore[import]
        except ImportError:
            try:
                import PyPDF2 as pypdf  # type: ignore[import,no-redef]
            except ImportError:
                self._log.debug("pypdf / PyPDF2 not installed; skipping")
                return None

        try:
            with open(str(path), "rb") as f:
                reader = pypdf.PdfReader(f)
                encrypted = reader.is_encrypted

                if encrypted:
                    # Try decrypt with empty password.
                    try:
                        reader.decrypt("")
                    except Exception:
                        return [], 0, {}, "pypdf", True

                page_count = len(reader.pages)
                page_texts: list[str] = []
                for page in reader.pages:
                    try:
                        text = page.extract_text() or ""
                    except Exception:
                        text = ""
                    page_texts.append(text)

                pdf_meta: dict[str, Any] = {}
                try:
                    meta_obj = reader.metadata
                    if meta_obj:
                        pdf_meta = {
                            k.lstrip("/"): str(v)
                            for k, v in meta_obj.items()
                            if v is not None
                        }
                except Exception:
                    pass

                return page_texts, page_count, pdf_meta, "pypdf", encrypted

        except Exception as exc:
            self._log.warning(
                "pypdf extraction failed",
                extra={"path": str(path), "error": str(exc)},
            )
            return None
