"""
src/extractors/factory.py
==========================

Extractor factory — selects the correct extractor for any source.

Usage
-----
::

    from src.extractors.factory import ExtractorFactory

    factory = ExtractorFactory()

    # Auto-select by file extension
    extractor = factory.get(Path("data/recruiter.csv"))
    records = extractor.extract(Path("data/recruiter.csv"))

    # Auto-select by GitHub URL
    extractor = factory.get("https://github.com/priya-sharma")
    records = extractor.extract("https://github.com/priya-sharma")

    # Override with explicit extractor type
    extractor = factory.get(Path("export.json"), source_type="ats")

Selection Rules
---------------
The factory asks each registered extractor (in priority order)
whether it :meth:`~src.extractors.base.BaseExtractor.supports` the
given source.  The first extractor that returns ``True`` is selected.

Registration order (lower index = higher priority):

1. :class:`~src.extractors.github_extractor.GithubExtractor`
2. :class:`~src.extractors.resume_pdf_extractor.ResumePdfExtractor`
3. :class:`~src.extractors.ats_json_extractor.ATSJsonExtractor`
4. :class:`~src.extractors.csv_extractor.CsvExtractor`

The :class:`GithubExtractor` is first because a URL like
``https://github.com/user`` should never accidentally match the CSV
extractor's path-based check.

Custom Extractors
-----------------
Call :meth:`ExtractorFactory.register` to add your own extractors::

    factory.register(MyCustomExtractor(), priority=0)  # highest priority
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.exceptions import ExtractionError
from src.extractors.ats_json_extractor import ATSJsonExtractor
from src.extractors.base import BaseExtractor
from src.extractors.csv_extractor import CsvExtractor
from src.extractors.github_extractor import GithubExtractor
from src.extractors.resume_pdf_extractor import ResumePdfExtractor
from src.logging_config import get_logger
from src.models import SourceType

log = get_logger(__name__)


class ExtractorFactory:
    """
    Registry and selector for :class:`~src.extractors.base.BaseExtractor`
    implementations.

    The factory holds an ordered list of extractor instances.  When
    :meth:`get` is called, each extractor's
    :meth:`~src.extractors.base.BaseExtractor.supports` method is
    queried in priority order until one returns ``True``.

    Parameters
    ----------
    config:
        Global extractor configuration dict forwarded to all extractors
        registered through this factory.

    Attributes
    ----------
    _extractors:
        Ordered list of registered extractor instances.

    Examples
    --------
    ::

        factory = ExtractorFactory()
        ext = factory.get("priya-sharma")      # → GithubExtractor
        ext = factory.get("resume.pdf")         # → ResumePdfExtractor
        ext = factory.get("candidates.json")    # → ATSJsonExtractor
        ext = factory.get("recruiter.csv")      # → CsvExtractor
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialise with the default set of extractors.

        Parameters
        ----------
        config:
            Optional configuration dict forwarded to each extractor.
        """
        self._config: dict[str, Any] = config or {}
        self._extractors: list[BaseExtractor] = [
            GithubExtractor(config=self._config),
            ResumePdfExtractor(config=self._config),
            ATSJsonExtractor(config=self._config),
            CsvExtractor(config=self._config),
        ]

    # ── Public API ────────────────────────────────────────────

    def get(
        self,
        source: str | Path,
        source_type: str | SourceType | None = None,
    ) -> BaseExtractor:
        """
        Return the appropriate extractor for ``source``.

        Parameters
        ----------
        source:
            File path, URL, or username string to select an extractor for.
        source_type:
            Optional explicit override.  Accepts a
            :class:`~src.models.SourceType` member or its string value
            (e.g. ``"csv"``, ``"github"``).  When set, bypasses the
            auto-detection logic and returns the extractor for that type.

        Returns
        -------
        BaseExtractor
            The selected extractor instance.

        Raises
        ------
        src.exceptions.ExtractionError
            If no registered extractor supports ``source`` (or if the
            explicit ``source_type`` does not match any registered
            extractor).

        Examples
        --------
        ::

            ext = factory.get(Path("data/candidates.csv"))
            # → CsvExtractor

            ext = factory.get("johndoe", source_type="github")
            # → GithubExtractor (explicit override)
        """
        if source_type is not None:
            return self._get_by_type(source_type, source)

        for extractor in self._extractors:
            if extractor.supports(source):
                log.debug(
                    "Extractor selected",
                    extra={
                        "extractor": extractor.__class__.__name__,
                        "source":    str(source),
                    },
                )
                return extractor

        raise ExtractionError(
            f"No registered extractor supports source: {source!r}. "
            f"Registered types: {self.registered_types()}",
            source_path=str(source),
        )

    def register(
        self,
        extractor: BaseExtractor,
        priority: int | None = None,
    ) -> None:
        """
        Register a new extractor with the factory.

        Parameters
        ----------
        extractor:
            The extractor instance to register.
        priority:
            0-based insertion index.  Lower index = higher priority.
            ``None`` appends to the end (lowest priority).

        Examples
        --------
        ::

            factory.register(MyCustomExtractor(), priority=0)
        """
        if priority is None:
            self._extractors.append(extractor)
        else:
            self._extractors.insert(priority, extractor)
        log.debug(
            "Extractor registered",
            extra={
                "extractor": extractor.__class__.__name__,
                "priority":  priority if priority is not None else len(self._extractors) - 1,
            },
        )

    def registered_types(self) -> list[str]:
        """
        Return a list of source type strings for all registered extractors.

        Returns
        -------
        list[str]
            E.g. ``["github", "resume", "ats", "csv"]``.
        """
        return [e.source_type.value for e in self._extractors]

    def extractors(self) -> list[BaseExtractor]:
        """
        Return the list of registered extractors in priority order.

        Returns
        -------
        list[BaseExtractor]
            Registered extractors (read-only copy).
        """
        return list(self._extractors)

    # ── Private helpers ───────────────────────────────────────

    def _get_by_type(
        self,
        source_type: str | SourceType,
        source: str | Path,
    ) -> BaseExtractor:
        """
        Return the registered extractor matching ``source_type``.

        Parameters
        ----------
        source_type:
            A :class:`~src.models.SourceType` member or its string value.
        source:
            Source string (used in error messages).

        Raises
        ------
        src.exceptions.ExtractionError
            If no extractor with the requested type is registered.
        """
        # Normalise to the enum value string.
        if isinstance(source_type, SourceType):
            target_value = source_type.value
        else:
            try:
                target_value = SourceType(str(source_type).lower()).value
            except ValueError:
                raise ExtractionError(
                    f"Unknown source_type {source_type!r}. "
                    f"Valid values: {[s.value for s in SourceType]}",
                    source_path=str(source),
                )

        for extractor in self._extractors:
            if extractor.source_type.value == target_value:
                return extractor

        raise ExtractionError(
            f"No registered extractor for source_type={target_value!r}. "
            f"Registered: {self.registered_types()}",
            source_path=str(source),
        )
