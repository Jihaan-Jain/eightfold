"""
logging_config.py
=================

Production-quality structured logging configuration.

Features
--------
- **Console handler** — human-readable coloured output in development,
  plain text in production.
- **Rotating file handler** — JSON-formatted records with automatic
  rotation at configurable size, retaining a configurable number of
  backup files.  Suitable for ingestion by log aggregators (Datadog,
  Splunk, ELK).
- **JSON formatter** — every log record is a valid JSON object with a
  consistent schema so log aggregators can parse fields without regex.
- **Debug mode** — includes ``pathname``, ``lineno``, ``funcName``,
  and full ``exc_info`` chains.
- **Pipeline context** — :func:`bind_context` /
  :func:`clear_context` let any module attach ``candidate_id``,
  ``stage``, ``run_id`` etc. to a thread-local dict that is merged
  into every subsequent log record without passing it explicitly.
- **Zero global mutable state** — all state lives inside the returned
  :class:`logging.Logger` instances and the thread-local context dict.

Usage
-----
Call :func:`configure_logging` **once** at application startup before
importing any other module::

    from src.logging_config import configure_logging, get_logger, bind_context

    configure_logging(
        log_level="INFO",
        log_file="logs/pipeline.log",
        debug_mode=False,
        json_console=False,
    )
    log = get_logger(__name__)
    log.info("Pipeline started", extra={"run_id": "run-abc123"})

Every other module should call :func:`get_logger` and log with
``extra={}`` key-value pairs::

    log = get_logger(__name__)
    log.info("Record extracted", extra={"source": "csv", "count": 42})
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar


# ================================================================
# JSON Log Formatter
# ================================================================


class JsonFormatter(logging.Formatter):
    """
    Formats a :class:`logging.LogRecord` as a single-line JSON object.

    Every log record produced by this formatter has the following
    guaranteed fields::

        {
            "timestamp":  "2024-01-15T10:30:00.123456+00:00",
            "level":      "INFO",
            "logger":     "src.pipeline",
            "message":    "Pipeline started",
            "run_id":     "run-abc123",   ← from extra={} or context
            "stage":      "extraction",   ← from extra={} or context
            ...
        }

    Additional fields from ``extra={}`` and the thread-local pipeline
    context are merged into the top-level object.

    In debug mode (``include_location=True``), the record also
    contains::

        "file":     "src/pipeline.py",
        "line":     42,
        "function": "_extract",
        "exc_info": "Traceback (most recent call last): ..."

    Parameters
    ----------
    include_location:
        If ``True``, include source file, line number, and function name
        in every record.  Use in development; omit in production to
        reduce record size.
    """

    #: Fields that exist on every LogRecord but should not be promoted
    #: to top-level JSON keys because they are either redundant (after
    #: our own extraction) or internal to the logging machinery.
    _EXCLUDED_ATTRS: ClassVar[frozenset[str]] = frozenset(
        {
            "args", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "message",
            "module", "msecs", "msg", "name", "pathname", "process",
            "processName", "relativeCreated", "stack_info", "taskName",
            "thread", "threadName",
        }
    )

    def __init__(self, include_location: bool = False) -> None:
        super().__init__()
        self.include_location = include_location

    def format(self, record: logging.LogRecord) -> str:
        """
        Serialise ``record`` to a single-line JSON string.

        Parameters
        ----------
        record:
            The log record to format.

        Returns
        -------
        str
            A JSON-encoded string with no trailing newline.
        """
        # Build the base document.
        doc: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
        }

        # Merge thread-local pipeline context.
        doc.update(_pipeline_context.get_all())

        # Merge extra fields the caller passed via extra={...}.
        for key, value in record.__dict__.items():
            if key not in self._EXCLUDED_ATTRS and not key.startswith("_"):
                doc[key] = value

        # Source location (debug mode only).
        if self.include_location:
            doc["file"]     = record.pathname
            doc["line"]     = record.lineno
            doc["function"] = record.funcName

        # Exception chain.
        if record.exc_info:
            doc["exc_info"] = self.formatException(record.exc_info)

        if record.stack_info:
            doc["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(doc, default=str, ensure_ascii=False)


# ================================================================
# Plain-text Console Formatter
# ================================================================


class _ConsoleFormatter(logging.Formatter):
    """
    Human-readable log formatter for the console handler.

    Format::

        2024-01-15 10:30:00 | INFO     | src.pipeline | Pipeline started | stage=extraction run_id=abc

    Extra fields from ``extra={}`` and the pipeline context are
    appended as ``key=value`` pairs after the message.
    """

    _FMT: ClassVar[str] = (
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    _DATEFMT: ClassVar[str] = "%Y-%m-%d %H:%M:%S"

    #: Internal logging attrs that must not be echoed as extra pairs.
    _SKIP: ClassVar[frozenset[str]] = frozenset(
        {
            "args", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "message",
            "module", "msecs", "msg", "name", "pathname", "process",
            "processName", "relativeCreated", "stack_info", "taskName",
            "thread", "threadName", "asctime",
        }
    )

    def __init__(self) -> None:
        super().__init__(fmt=self._FMT, datefmt=self._DATEFMT)

    def format(self, record: logging.LogRecord) -> str:
        """Format the record, appending key=value context pairs."""
        base = super().format(record)

        pairs: dict[str, Any] = {}
        pairs.update(_pipeline_context.get_all())
        for key, value in record.__dict__.items():
            if key not in self._SKIP and not key.startswith("_"):
                pairs[key] = value

        if pairs:
            suffix = " | " + " ".join(f"{k}={v}" for k, v in pairs.items())
            base = base + suffix

        return base


# ================================================================
# Thread-local Pipeline Context
# ================================================================


class _PipelineContext:
    """
    Thread-local storage for pipeline context key-value pairs.

    Any module can bind fields once (e.g., ``run_id``, ``candidate_id``,
    ``stage``) and have them appear automatically on every subsequent
    log call in that thread without needing to pass ``extra={}``
    explicitly.

    This class is a singleton — the module-level ``_pipeline_context``
    instance is the only instance that should exist.
    """

    def __init__(self) -> None:
        self._local: threading.local = threading.local()

    def _store(self) -> dict[str, Any]:
        """Return (creating if needed) the per-thread context dict."""
        if not hasattr(self._local, "ctx"):
            self._local.ctx: dict[str, Any] = {}
        return self._local.ctx

    def bind(self, **kwargs: Any) -> None:
        """
        Bind key-value pairs to the current thread's context.

        These fields will be included in every log record emitted from
        this thread until :meth:`clear` is called.

        Parameters
        ----------
        **kwargs:
            Arbitrary key-value context fields.

        Examples
        --------
        ::

            bind_context(run_id="run-001", candidate_id="cand-42", stage="merge")
        """
        self._store().update(kwargs)

    def unbind(self, *keys: str) -> None:
        """
        Remove specific keys from the current thread's context.

        Parameters
        ----------
        *keys:
            Names of context fields to remove.
        """
        store = self._store()
        for key in keys:
            store.pop(key, None)

    def clear(self) -> None:
        """
        Remove all key-value pairs from the current thread's context.

        Call this at the end of processing each candidate (or in a
        ``finally`` block) to prevent context leaking between
        candidates in a thread pool.
        """
        self._store().clear()

    def get_all(self) -> dict[str, Any]:
        """
        Return a shallow copy of the current thread's context.

        Returns
        -------
        dict[str, Any]
            Current context key-value pairs, or empty dict if none are set.
        """
        return dict(self._store())


#: Module-level singleton — the only instance of _PipelineContext.
_pipeline_context: _PipelineContext = _PipelineContext()

#: Valid log level names accepted by :func:`configure_logging`.
_VALID_LOG_LEVELS: frozenset[str] = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)


# ================================================================
# Public Configuration API
# ================================================================


def configure_logging(
    log_level: str = "INFO",
    log_file: str | Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    debug_mode: bool = False,
    json_console: bool = False,
) -> None:
    """
    Configure the root logger with console and optional file handlers.

    Call this function **once** at application startup.  Calling it
    again is safe — existing handlers are removed and replaced.

    Parameters
    ----------
    log_level:
        Minimum severity for both handlers.
        Must be one of ``"DEBUG"``, ``"INFO"``, ``"WARNING"``,
        ``"ERROR"``, ``"CRITICAL"``.
    log_file:
        Path to the rotating log file.  Parent directories are created
        automatically.  If ``None``, no file handler is attached.
    max_bytes:
        Maximum size of the log file before rotation occurs.
        Default: 10 MB.  Set to ``0`` to disable rotation.
    backup_count:
        Number of rotated backup files to retain.
        Default: 5.  Total disk usage ≤ ``(backup_count + 1) × max_bytes``.
    debug_mode:
        If ``True``, log records include source file, line number, and
        function name, and exception tracebacks are always included.
        Use only in development.
    json_console:
        If ``True``, the console handler also outputs JSON instead of
        the human-readable format.  Useful when stdout is consumed by
        a log aggregator inside a container.

    Raises
    ------
    ValueError
        If ``log_level`` is not a recognised severity string.

    Examples
    --------
    Development setup::

        configure_logging(log_level="DEBUG", debug_mode=True)

    Production / container setup::

        configure_logging(
            log_level="INFO",
            log_file="logs/pipeline.log",
            json_console=True,
        )
    """
    level_upper = log_level.upper()
    if level_upper not in _VALID_LOG_LEVELS:
        raise ValueError(
            f"Invalid log_level {log_level!r}. "
            f"Choose from: {sorted(_VALID_LOG_LEVELS)}"
        )
    numeric_level: int = getattr(logging, level_upper)

    # ── Root logger ──────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove any previously attached handlers (idempotent re-config).
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)

    # ── Console handler ──────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    if json_console:
        console_handler.setFormatter(JsonFormatter(include_location=debug_mode))
    else:
        console_handler.setFormatter(_ConsoleFormatter())
    root.addHandler(console_handler)

    # ── Rotating file handler (JSON) ─────────────────────────
    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler: logging.handlers.RotatingFileHandler = (
            logging.handlers.RotatingFileHandler(
                filename=str(log_path),
                mode="a",
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
                delay=False,
            )
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(JsonFormatter(include_location=debug_mode))
        root.addHandler(file_handler)

    # Silence noisy third-party loggers.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Return a standard-library :class:`logging.Logger` for a module.

    All modules in the pipeline must obtain their loggers through this
    function.  Loggers created this way automatically inherit the
    handlers and formatters configured by :func:`configure_logging`.

    Parameters
    ----------
    name:
        Module name — conventionally ``__name__``.

    Returns
    -------
    logging.Logger
        A configured logger.  Use structured ``extra={}`` kwargs::

            log = get_logger(__name__)
            log.info("Record extracted", extra={"source": "csv", "count": 42})

    Examples
    --------
    ::

        from src.logging_config import get_logger

        log = get_logger(__name__)

        log.debug("Starting normalisation", extra={"field": "email"})
        log.warning("Unresolved skill", extra={"skill": "PyTorch Lightning"})
        log.error(
            "Extraction failed",
            extra={"source": "pdf", "path": "/tmp/resume.pdf"},
            exc_info=True,
        )
    """
    return logging.getLogger(name)


def bind_context(**kwargs: Any) -> None:
    """
    Bind key-value pairs to the current thread's pipeline context.

    Bound fields appear automatically in every subsequent log record
    emitted from this thread without needing to pass them via
    ``extra={}`` on every call.

    Parameters
    ----------
    **kwargs:
        Arbitrary context fields.

    Examples
    --------
    ::

        from src.logging_config import bind_context, clear_context

        bind_context(run_id="run-001", stage="merge", candidate_id="cand-42")
        try:
            ...   # log calls here automatically include those fields
        finally:
            clear_context()
    """
    _pipeline_context.bind(**kwargs)


def unbind_context(*keys: str) -> None:
    """
    Remove specific keys from the current thread's pipeline context.

    Parameters
    ----------
    *keys:
        Names of context keys to remove.

    Examples
    --------
    ::

        unbind_context("candidate_id")   # remove one field between candidates
    """
    _pipeline_context.unbind(*keys)


def clear_context() -> None:
    """
    Clear all key-value pairs from the current thread's pipeline context.

    Call this at the end of processing each candidate (or in a
    ``finally`` block) when running in a thread pool, to prevent context
    from one candidate appearing in another's log records.

    Examples
    --------
    ::

        bind_context(candidate_id="cand-001", stage="merge")
        try:
            merge_candidate(profile)
        finally:
            clear_context()
    """
    _pipeline_context.clear()


def get_context() -> dict[str, Any]:
    """
    Return a snapshot of the current thread's pipeline context.

    Useful in tests to assert that the correct context fields have
    been bound without inspecting log output.

    Returns
    -------
    dict[str, Any]
        Current context key-value pairs.

    Examples
    --------
    ::

        bind_context(stage="extraction", run_id="run-001")
        ctx = get_context()
        assert ctx["stage"] == "extraction"
    """
    return _pipeline_context.get_all()
