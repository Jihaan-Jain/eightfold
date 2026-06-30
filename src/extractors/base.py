"""
src/extractors/base.py
======================

Abstract base class for all source extractors.

Every concrete extractor must inherit from :class:`BaseExtractor` and
implement all four abstract methods.  The base class provides:

- A shared structured logger (``self._log``) bound to the subclass name.
- :meth:`_timed_extract` — a timing wrapper that logs start, finish,
  duration, and record count automatically.  Subclasses call this
  instead of :meth:`extract` to get structured logs for free.
- :meth:`_build_source_label` — produces a consistent source label
  string for :attr:`~src.models.RawRecord.source`.

Contract
--------
- :meth:`extract` MUST return ``List[RawRecord]`` — no other type.
- :meth:`extract` MUST NOT normalise, merge, or otherwise transform
  field values.  It stores raw bytes / native Python types only.
- :meth:`extract` MUST raise :class:`~src.exceptions.ExtractionError`
  on unrecoverable failures — never propagate raw ``OSError``,
  ``json.JSONDecodeError``, or ``requests.RequestException``.
- :meth:`validate_source` MUST be called inside :meth:`extract` before
  reading any bytes.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from src.exceptions import ExtractionError
from src.logging_config import get_logger
from src.models import RawRecord, SourceType


class BaseExtractor(ABC):
    """
    Abstract base class for all candidate data source extractors.

    All extractors share the same external interface:
    ``extractor.extract(source) → List[RawRecord]``.

    Subclasses must implement
    -------------------------
    - :meth:`extract`          — parse source and return RawRecord list
    - :meth:`validate_source`  — check that source is usable before extraction
    - :meth:`supports`         — return True if this extractor handles the source
    - :meth:`source_type`      — the :class:`~src.models.SourceType` enum value

    Attributes
    ----------
    _config:
        Extractor-specific configuration dict.  May be empty.
    _log:
        Structured logger bound to ``src.extractors.<ClassName>``.

    Examples
    --------
    ::

        class MyCsvExtractor(BaseExtractor):
            @property
            def source_type(self) -> SourceType:
                return SourceType.CSV

            def supports(self, source: str | Path) -> bool:
                return Path(source).suffix.lower() in (".csv", ".tsv")

            def validate_source(self, source: str | Path) -> None:
                if not Path(source).exists():
                    raise ExtractionError("File not found", source_path=str(source))

            def extract(self, source: str | Path) -> list[RawRecord]:
                self.validate_source(source)
                return self._timed_extract(source, self._do_extract)

            def _do_extract(self, source: str | Path) -> list[RawRecord]:
                ...
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialise the extractor with optional configuration.

        Parameters
        ----------
        config:
            Extractor-specific settings dict.  Each concrete extractor
            documents the keys it reads.  ``None`` is treated as ``{}``.
        """
        self._config: dict[str, Any] = config or {}
        self._log = get_logger(
            f"src.extractors.{self.__class__.__name__}"
        )

    # ── Abstract interface ────────────────────────────────────

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """
        The :class:`~src.models.SourceType` enum value for this extractor.

        Used by :class:`~src.extractors.factory.ExtractorFactory` to
        annotate every :class:`~src.models.RawRecord` it creates.
        """
        ...

    @abstractmethod
    def supports(self, source: str | Path) -> bool:
        """
        Return ``True`` when this extractor can handle ``source``.

        Called by :class:`~src.extractors.factory.ExtractorFactory`
        to automatically select the correct extractor.

        Parameters
        ----------
        source:
            File path or URL string to test.

        Returns
        -------
        bool
            ``True`` if this extractor should be used for ``source``.
        """
        ...

    @abstractmethod
    def validate_source(self, source: str | Path) -> None:
        """
        Validate that ``source`` is usable before reading any bytes.

        Called at the very start of :meth:`extract`.  Should raise
        :class:`~src.exceptions.ExtractionError` if the source is
        missing, unreadable, or structurally invalid (e.g. wrong file
        format based on magic bytes).

        Parameters
        ----------
        source:
            File path or URL string to validate.

        Raises
        ------
        src.exceptions.ExtractionError
            If ``source`` cannot be used for extraction.
        """
        ...

    @abstractmethod
    def extract(self, source: str | Path) -> list[RawRecord]:
        """
        Parse ``source`` and return a list of :class:`~src.models.RawRecord`.

        Contract
        --------
        - Must call :meth:`validate_source` before reading any bytes.
        - Must store raw, un-transformed field values in
          :attr:`~src.models.RawRecord.raw_fields`.
        - Must never normalise, merge, or parse domain entities.
        - Must raise :class:`~src.exceptions.ExtractionError` on
          unrecoverable failures.

        Parameters
        ----------
        source:
            File path or URL string to extract from.

        Returns
        -------
        list[RawRecord]
            Zero or more raw records.  An empty list is valid when the
            source contains no candidate data.
        """
        ...

    @abstractmethod
    def metadata(self) -> dict[str, Any]:
        """
        Return a dict of extractor metadata for debugging / monitoring.

        The dict should include at minimum:

        - ``"extractor"``   — class name
        - ``"source_type"`` — the :attr:`source_type` value
        - ``"version"``     — extractor implementation version string

        Additional keys are extractor-specific.

        Returns
        -------
        dict[str, Any]
            Static metadata about this extractor instance.
        """
        ...

    # ── Protected helpers ─────────────────────────────────────

    def _timed_extract(
        self,
        source: str | Path,
        _extract_fn: Any,
        *args: Any,
        **kwargs: Any,
    ) -> list[RawRecord]:
        """
        Run ``_extract_fn(source, *args, **kwargs)`` with automatic
        structured logging for start, finish, duration, and record count.

        Concrete extractors should call this method from their
        :meth:`extract` implementation instead of calling ``_extract_fn``
        directly, so all extractors produce consistent telemetry without
        duplicated code.

        Parameters
        ----------
        source:
            The source being extracted (used in log messages only).
        _extract_fn:
            A callable with signature
            ``(source: str | Path, *args, **kwargs) → list[RawRecord]``.
        *args, **kwargs:
            Forwarded to ``_extract_fn``.

        Returns
        -------
        list[RawRecord]
            Whatever ``_extract_fn`` returns.

        Raises
        ------
        src.exceptions.ExtractionError
            Re-raises any :class:`~src.exceptions.ExtractionError`
            raised by ``_extract_fn``.
        """
        label = str(source)
        self._log.info(
            "Extraction started",
            extra={
                "extractor": self.__class__.__name__,
                "source": label,
                "source_type": self.source_type.value,
            },
        )
        t0 = time.perf_counter()
        try:
            records: list[RawRecord] = _extract_fn(source, *args, **kwargs)
        except ExtractionError:
            raise
        except Exception as exc:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            self._log.error(
                "Extraction failed",
                extra={
                    "extractor": self.__class__.__name__,
                    "source": label,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise ExtractionError(
                f"{self.__class__.__name__} failed on {label}: {exc}",
                source_type=self.source_type.value,
                source_path=label,
            ) from exc

        duration_ms = int((time.perf_counter() - t0) * 1000)
        self._log.info(
            "Extraction complete",
            extra={
                "extractor": self.__class__.__name__,
                "source": label,
                "source_type": self.source_type.value,
                "records_extracted": len(records),
                "duration_ms": duration_ms,
            },
        )
        return records

    def _make_source_label(self, source: str | Path) -> str:
        """
        Return a consistent, log-friendly source label string.

        Parameters
        ----------
        source:
            File path or URL.

        Returns
        -------
        str
            POSIX path string for :class:`~pathlib.Path` inputs;
            the string as-is for URL strings.
        """
        if isinstance(source, Path):
            return source.as_posix()
        return str(source)
