"""
src/extractors/utils.py
=======================

Shared utilities for all extractor modules.

Provides
--------
- :func:`safe_read_bytes`       — read a file path to bytes, raising domain errors
- :func:`detect_encoding`       — guess the character encoding of raw bytes
- :func:`hash_bytes`            — SHA-256 digest of an in-memory buffer
- :func:`hash_file`             — SHA-256 digest of a file on disk
- :func:`detect_mime_type`      — guess MIME type from file extension + magic bytes
- :func:`retry`                 — decorator for automatic retry with back-off
- :func:`is_empty_row`          — check whether a CSV row dict is effectively empty
- :func:`normalise_source_label`— produce a consistent log-friendly source label
- :func:`build_standard_metadata` — produce the canonical 6-key metadata block
                                    shared by every extractor (checksum, file_size,
                                    mime, encoding, pages, language)

Design
------
- All functions are pure or depend only on stdlib / installed packages.
- Functions that touch the filesystem raise
  :class:`~src.exceptions.ExtractionError` on any OS / permission error,
  never letting raw ``OSError`` / ``IOError`` propagate to callers.
- The retry decorator catches only the exception types the caller
  specifies — it does not swallow unexpected exceptions.
"""

from __future__ import annotations

import functools
import hashlib
import mimetypes
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from src.exceptions import ExtractionError
from src.logging_config import get_logger

log = get_logger(__name__)

# Type variable for the retry decorator's function signature.
_F = TypeVar("_F", bound=Callable[..., Any])

# Magic-byte signatures for common binary file types used by MIME detection.
_MAGIC_BYTES: list[tuple[bytes, str]] = [
    (b"%PDF",          "application/pdf"),
    (b"PK\x03\x04",   "application/zip"),
    (b"\xff\xfe",      "text/plain"),   # UTF-16 LE BOM
    (b"\xfe\xff",      "text/plain"),   # UTF-16 BE BOM
    (b"\xef\xbb\xbf",  "text/plain"),  # UTF-8 BOM
    (b"\x89PNG",       "image/png"),
    (b"\xff\xd8\xff",  "image/jpeg"),
]


# ================================================================
# File I/O
# ================================================================


def safe_read_bytes(path: Path | str) -> bytes:
    """
    Read the entire contents of a file as raw bytes.

    Parameters
    ----------
    path:
        Filesystem path to the file.

    Returns
    -------
    bytes
        Raw file contents.

    Raises
    ------
    src.exceptions.ExtractionError
        If the file does not exist, is a directory, cannot be read
        due to permission restrictions, or any other OS-level error.

    Examples
    --------
    ::

        raw = safe_read_bytes(Path("data/recruiter.csv"))
    """
    p = Path(path)
    try:
        if not p.exists():
            raise ExtractionError(
                f"File not found: {p}",
                source_path=str(p),
            )
        if not p.is_file():
            raise ExtractionError(
                f"Path is not a regular file: {p}",
                source_path=str(p),
            )
        return p.read_bytes()
    except ExtractionError:
        raise
    except PermissionError as exc:
        raise ExtractionError(
            f"Permission denied reading file: {p}",
            source_path=str(p),
        ) from exc
    except OSError as exc:
        raise ExtractionError(
            f"OS error reading file {p}: {exc}",
            source_path=str(p),
        ) from exc


# ================================================================
# Encoding Detection
# ================================================================


def detect_encoding(raw: bytes, fallback: str = "utf-8") -> str:
    """
    Detect the character encoding of raw byte content.

    Tries, in order:

    1. **BOM sniffing** — UTF-8 BOM, UTF-16 LE/BE BOM
    2. **chardet** — if the ``chardet`` package is installed
    3. **charset_normalizer** — if ``charset_normalizer`` is installed
       (ships with ``requests``)
    4. ``fallback`` — used when all detection methods are unavailable
       or return ``None``

    Parameters
    ----------
    raw:
        Raw bytes to inspect.
    fallback:
        Encoding to use when detection fails.  Defaults to ``"utf-8"``.

    Returns
    -------
    str
        An encoding name recognised by Python's ``codecs`` module
        (e.g. ``"utf-8"``, ``"utf-8-sig"``, ``"latin-1"``).

    Examples
    --------
    ::

        enc = detect_encoding(Path("file.csv").read_bytes())
        text = raw.decode(enc, errors="replace")
    """
    # 1. BOM sniffing
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"

    # 2. chardet
    try:
        import chardet  # type: ignore[import]
        result = chardet.detect(raw[:4096])
        if result and result.get("encoding") and result.get("confidence", 0) > 0.5:
            return str(result["encoding"])
    except ImportError:
        pass

    # 3. charset_normalizer (bundled with requests)
    try:
        from charset_normalizer import from_bytes  # type: ignore[import]
        matches = from_bytes(raw[:4096])
        best = matches.best()
        if best is not None:
            return str(best.encoding)
    except (ImportError, Exception):
        pass

    return fallback


# ================================================================
# Hashing
# ================================================================


def hash_bytes(data: bytes, algorithm: str = "sha256") -> str:
    """
    Compute the hex digest of a byte buffer.

    Parameters
    ----------
    data:
        Bytes to hash.
    algorithm:
        Hash algorithm name accepted by :func:`hashlib.new`.
        Defaults to ``"sha256"``.

    Returns
    -------
    str
        Lowercase hex digest string.

    Examples
    --------
    ::

        digest = hash_bytes(b"hello world")
        # "b94d27b9934d3e08a52e52d7da7dabfa..."
    """
    h = hashlib.new(algorithm)
    h.update(data)
    return h.hexdigest()


def hash_file(path: Path | str, algorithm: str = "sha256") -> str:
    """
    Compute the hex digest of a file on disk.

    Reads the file in 64 KB chunks to avoid loading large files into
    memory entirely.

    Parameters
    ----------
    path:
        Filesystem path to the file.
    algorithm:
        Hash algorithm name.  Defaults to ``"sha256"``.

    Returns
    -------
    str
        Lowercase hex digest string.

    Raises
    ------
    src.exceptions.ExtractionError
        If the file cannot be read.

    Examples
    --------
    ::

        digest = hash_file(Path("resume.pdf"))
    """
    p = Path(path)
    h = hashlib.new(algorithm)
    try:
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except FileNotFoundError as exc:
        raise ExtractionError(
            f"File not found while hashing: {p}",
            source_path=str(p),
        ) from exc
    except OSError as exc:
        raise ExtractionError(
            f"OS error hashing {p}: {exc}",
            source_path=str(p),
        ) from exc
    return h.hexdigest()


# ================================================================
# MIME Type Detection
# ================================================================


def detect_mime_type(path: Path | str) -> str:
    """
    Guess the MIME type of a file.

    Uses two strategies in order:

    1. **Extension-based lookup** via :mod:`mimetypes`
    2. **Magic-byte sniffing** of the first 16 bytes

    Falls back to ``"application/octet-stream"`` when neither strategy
    produces a result.

    Parameters
    ----------
    path:
        Filesystem path to inspect.

    Returns
    -------
    str
        MIME type string (e.g. ``"text/csv"``, ``"application/pdf"``).

    Examples
    --------
    ::

        mime = detect_mime_type(Path("recruiter.csv"))
        # "text/csv"
    """
    p = Path(path)

    # Strategy 1: extension
    mime, _ = mimetypes.guess_type(str(p))
    if mime:
        return mime

    # Strategy 2: magic bytes
    try:
        header = p.read_bytes()[:16]
        for magic, mime_type in _MAGIC_BYTES:
            if header.startswith(magic):
                return mime_type
    except OSError:
        pass

    return "application/octet-stream"


# ================================================================
# Retry Decorator
# ================================================================


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    reraise_as: type[Exception] | None = None,
) -> Callable[[_F], _F]:
    """
    Decorator that retries a function call on specified exceptions.

    Waits ``delay`` seconds before the first retry, doubling each time
    (exponential back-off controlled by ``backoff``).

    Parameters
    ----------
    max_attempts:
        Total number of attempts (1 = no retries, 3 = 2 retries).
    delay:
        Initial wait time in seconds between attempts.
    backoff:
        Multiplier applied to ``delay`` after each failure.
        Set to ``1.0`` for constant delay.
    exceptions:
        Tuple of exception types to catch and retry on.
        Exceptions not in this tuple propagate immediately.
    reraise_as:
        If all attempts fail and this is set, the final exception
        is wrapped in ``reraise_as``.  Pass ``None`` to re-raise
        the original exception unchanged.

    Returns
    -------
    Callable
        A wrapped function with the same signature.

    Examples
    --------
    ::

        @retry(max_attempts=3, delay=0.5, exceptions=(requests.Timeout,))
        def fetch_github_profile(username: str) -> dict:
            ...
    """
    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_exc: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    log.warning(
                        "Retry %d/%d for %s: %s",
                        attempt,
                        max_attempts,
                        func.__qualname__,
                        exc,
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff

            # All attempts exhausted.
            assert last_exc is not None
            if reraise_as is not None and not isinstance(last_exc, reraise_as):
                raise reraise_as(str(last_exc)) from last_exc
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator


# ================================================================
# CSV Helpers
# ================================================================


def is_empty_row(row: dict[str, Any]) -> bool:
    """
    Return ``True`` when every value in a CSV row dict is blank.

    A value is considered blank if it is ``None``, the empty string,
    or a string of only whitespace.

    Parameters
    ----------
    row:
        A dict representing one CSV row (as returned by
        :class:`csv.DictReader`).

    Returns
    -------
    bool
        ``True`` when the row has no meaningful data.

    Examples
    --------
    ::

        is_empty_row({"name": "", "email": None})   # True
        is_empty_row({"name": "Alice", "email": ""}) # False
    """
    return all(
        (v is None or (isinstance(v, str) and not v.strip()))
        for v in row.values()
    )


def hash_row(row: dict[str, Any]) -> str:
    """
    Compute a stable hash string for a CSV row dict.

    Used to detect duplicate rows without storing the full content.
    Sorting keys before hashing ensures that column-reordering
    does not produce a different hash for the same logical row.

    Parameters
    ----------
    row:
        A dict representing one CSV row.

    Returns
    -------
    str
        8-character hex prefix of the SHA-256 digest.
    """
    canonical = "|".join(
        f"{k}={v}" for k, v in sorted(row.items())
    ).encode("utf-8", errors="replace")
    return hashlib.sha256(canonical).hexdigest()[:8]


# ================================================================
# Source Label
# ================================================================


def normalise_source_label(source: str | Path) -> str:
    """
    Produce a consistent, log-friendly label for a source.

    For filesystem paths, returns the POSIX-style path string.
    For URLs and other strings, returns the string as-is.

    Parameters
    ----------
    source:
        A filesystem path or URL string.

    Returns
    -------
    str
        A clean label string for use in log messages and
        :attr:`~src.models.RawRecord.source`.

    Examples
    --------
    ::

        normalise_source_label(Path("data/recruiter.csv"))
        # "data/recruiter.csv"
        normalise_source_label("https://api.github.com/users/priya")
        # "https://api.github.com/users/priya"
    """
    if isinstance(source, Path):
        return source.as_posix()
    return str(source)


# ================================================================
# Standard Metadata Block
# ================================================================


def build_standard_metadata(
    *,
    checksum: str | None,
    file_size: int | None,
    mime: str | None,
    encoding: str | None,
    pages: int | None,
    language: str | None,
) -> dict[str, str | int | None]:
    """
    Build the **canonical 6-key metadata block** included by every
    extractor in every :class:`~src.models.RawRecord` it produces.

    Having a fixed schema here means downstream stages can read
    ``record.metadata["checksum"]`` without guarding against
    key-not-found errors, regardless of which extractor produced
    the record.

    Parameters
    ----------
    checksum:
        SHA-256 digest of the source file, prefixed with the algorithm
        name: ``"sha256:<hexdigest>"``.  ``None`` for API-sourced
        records (e.g. GitHub) where there is no local file to hash.
    file_size:
        Size of the source file in bytes.  ``None`` for API records.
    mime:
        MIME type string (e.g. ``"text/csv"``, ``"application/pdf"``,
        ``"application/json"``).  For API records use
        ``"application/json"`` (the format of the wire response).
    encoding:
        Character encoding string (e.g. ``"utf-8"``, ``"latin-1"``).
        ``None`` for inherently binary formats that were not decoded
        to text (e.g. encrypted PDFs where extraction failed).
    pages:
        Total page count.  Non-``None`` only for PDF records.
        ``None`` for CSV, JSON, and GitHub records.
    language:
        Primary programming / human language detected in the source.
        For GitHub records, the most-used programming language across
        public repos.  ``None`` for all other extractor types.

    Returns
    -------
    dict[str, str | int | None]
        Mapping with exactly the six keys listed above.

    Examples
    --------
    CSV extractor::

        std = build_standard_metadata(
            checksum="sha256:" + hash_file(p),
            file_size=p.stat().st_size,
            mime="text/csv",
            encoding="utf-8",
            pages=None,
            language=None,
        )
        # {"checksum": "sha256:abc...", "file_size": 4096,
        #  "mime": "text/csv", "encoding": "utf-8",
        #  "pages": None, "language": None}

    GitHub extractor::

        std = build_standard_metadata(
            checksum=None,
            file_size=None,
            mime="application/json",
            encoding="utf-8",
            pages=None,
            language="Python",
        )
    """
    return {
        "checksum":  checksum,
        "file_size": file_size,
        "mime":      mime,
        "encoding":  encoding,
        "pages":     pages,
        "language":  language,
    }
