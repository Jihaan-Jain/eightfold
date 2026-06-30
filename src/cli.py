"""
src/cli.py
===========

Command-line interface for candidate-transformer.

Usage
-----
::

    candidate-transform \\
        --csv  data/candidates.csv \\
        --ats  data/ats_export.json \\
        --config config/pipeline.yaml \\
        --output output/candidates.json \\
        --report output/validation_report.json \\
        --verbose

All flags are optional.  If no input source is specified, the CLI
reads from stdin (one JSON record per line).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.logging_config import get_logger, configure_logging

_log = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="candidate-transform",
        description=(
            "Transform candidate data from multiple sources "
            "into unified CandidateProfile JSON."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic CSV transform
  candidate-transform --csv data/candidates.csv --output out/profiles.json

  # Multiple sources with validation report
  candidate-transform \\
      --csv data/candidates.csv \\
      --ats data/ats.json \\
      --github johndoe \\
      --output out/profiles.json \\
      --report out/report.json \\
      --verbose

  # Custom projection config
  candidate-transform --csv data/in.csv --config config/slim.yaml
""",
    )

    # ── Input sources ─────────────────────────────────────────
    sources = parser.add_argument_group("Input Sources")
    sources.add_argument(
        "--csv",
        dest="csv",
        action="append",
        metavar="PATH",
        default=[],
        help="Path to a CSV candidate file. Repeatable.",
    )
    sources.add_argument(
        "--ats",
        dest="ats",
        action="append",
        metavar="PATH",
        default=[],
        help="Path to an ATS JSON export. Repeatable.",
    )
    sources.add_argument(
        "--resume",
        dest="resume",
        action="append",
        metavar="PATH",
        default=[],
        help="Path to a resume file (PDF/TXT/DOCX). Repeatable.",
    )
    sources.add_argument(
        "--github",
        dest="github",
        action="append",
        metavar="USERNAME",
        default=[],
        help="GitHub username to pull profile from. Repeatable.",
    )

    # ── Configuration ─────────────────────────────────────────
    config_grp = parser.add_argument_group("Configuration")
    config_grp.add_argument(
        "--config",
        dest="config",
        metavar="PATH",
        default=None,
        help="Path to projection config YAML/JSON.",
    )
    config_grp.add_argument(
        "--merge-strategy",
        dest="merge_strategy",
        choices=["source_priority", "majority_vote", "most_recent", "manual"],
        default="source_priority",
        help="Conflict resolution strategy (default: source_priority).",
    )
    config_grp.add_argument(
        "--match-threshold",
        dest="match_threshold",
        type=float,
        default=0.85,
        metavar="FLOAT",
        help="Identity match threshold 0.0–1.0 (default: 0.85).",
    )

    # ── Output ────────────────────────────────────────────────
    output_grp = parser.add_argument_group("Output")
    output_grp.add_argument(
        "--output",
        dest="output",
        metavar="PATH",
        default=None,
        help="Write JSON output to this file (default: stdout).",
    )
    output_grp.add_argument(
        "--report",
        dest="report",
        metavar="PATH",
        default=None,
        help="Write ValidationReport JSON to this file.",
    )
    output_grp.add_argument(
        "--format",
        dest="format",
        choices=["json", "jsonl", "pretty"],
        default="pretty",
        help="Output format (default: pretty JSON).",
    )

    # ── Behaviour ─────────────────────────────────────────────
    behaviour = parser.add_argument_group("Behaviour")
    behaviour.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable verbose logging.",
    )
    behaviour.add_argument(
        "--no-fail-on-error",
        action="store_true",
        dest="no_fail_on_error",
        default=False,
        help="Do not treat validation errors as pipeline failures.",
    )
    behaviour.add_argument(
        "--minimal",
        action="store_true",
        default=False,
        help="Use minimal projection (id, name, email, skills only).",
    )

    return parser


def _format_output(outputs: list[dict], fmt: str) -> str:
    if fmt == "jsonl":
        return "\n".join(json.dumps(o, default=str, ensure_ascii=False) for o in outputs)
    if fmt == "json":
        return json.dumps(outputs, default=str, ensure_ascii=False)
    # "pretty"
    return json.dumps(outputs, indent=2, default=str, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    """
    CLI entry point.

    Parameters
    ----------
    argv:
        Override ``sys.argv[1:]`` (used in tests).

    Returns
    -------
    int
        Exit code: 0 = success, 1 = pipeline error, 2 = argument error.
    """
    parser = build_parser()
    args   = parser.parse_args(argv)

    # ── Logging setup ─────────────────────────────────────────
    configure_logging(log_level="DEBUG" if args.verbose else "INFO")

    # ── Validate at least one source ─────────────────────────
    has_input = any([args.csv, args.ats, args.resume, args.github])
    if not has_input:
        parser.print_help(sys.stderr)
        sys.stderr.write(
            "\nerror: At least one input source is required "
            "(--csv, --ats, --resume, --github).\n"
        )
        return 2

    # ── Build pipeline config ─────────────────────────────────
    from src.main import PipelineConfig, PipelineResult, run_pipeline

    cfg = PipelineConfig(
        csv_paths=args.csv,
        ats_paths=args.ats,
        resume_paths=args.resume,
        github_users=args.github,
        projection_config_path=args.config,
        output_path=None,          # we handle output ourselves for format control
        report_path=args.report,
        verbose=args.verbose,
        merge_strategy=args.merge_strategy,
        match_threshold=args.match_threshold,
        fail_on_error=not args.no_fail_on_error,
    )

    # Use minimal projector if requested
    if args.minimal:
        from src.projection.factory import ProjectorFactory
        cfg_with_output = PipelineConfig(
            csv_paths=args.csv,
            ats_paths=args.ats,
            resume_paths=args.resume,
            github_users=args.github,
            projection_config_path=None,  # overridden below
            report_path=args.report,
            verbose=args.verbose,
            merge_strategy=args.merge_strategy,
            match_threshold=args.match_threshold,
            fail_on_error=not args.no_fail_on_error,
        )
        result = run_pipeline(cfg_with_output)
        # Re-project with minimal projector
        projector = ProjectorFactory.build_minimal()
        result = PipelineResult(
            profiles=result.profiles,
            outputs=projector.project_many(result.profiles),
            validation_report=result.validation_report,
            elapsed_ms=result.elapsed_ms,
        )
    else:
        result = run_pipeline(cfg)

    # ── Write output ──────────────────────────────────────────
    formatted = _format_output(result.outputs, args.format)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(formatted, encoding="utf-8")
        if args.verbose:
            _log.info("Output written", extra={"path": args.output})
    else:
        sys.stdout.write(formatted + "\n")

    # ── Summary ───────────────────────────────────────────────
    stats = result.validation_report.statistics
    sys.stderr.write(
        f"\n✓ {stats['total']} candidates processed  "
        f"· {stats['valid']} valid  "
        f"· {stats['invalid']} invalid  "
        f"· {stats['warning_count']} warnings  "
        f"· {result.elapsed_ms:.0f}ms\n"
    )

    # Return non-zero exit code if any invalid + fail_on_error
    if not args.no_fail_on_error and stats["invalid"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
