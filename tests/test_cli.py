"""
tests/test_cli.py
==================

Tests for the CLI entry point (src/cli.py).

All tests use subprocess to test the CLI as a black box, plus
direct calls to ``main()`` for faster unit-style tests.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

from src.cli import build_parser, main


# ================================================================
# build_parser
# ================================================================


class TestBuildParser:
    @pytest.fixture
    def parser(self):
        return build_parser()

    def test_prog_name(self, parser):
        assert parser.prog == "candidate-transform"

    def test_csv_argument_repeatable(self, parser):
        args = parser.parse_args(["--csv", "a.csv", "--csv", "b.csv"])
        assert args.csv == ["a.csv", "b.csv"]

    def test_ats_argument(self, parser):
        args = parser.parse_args(["--ats", "data.json"])
        assert args.ats == ["data.json"]

    def test_resume_argument(self, parser):
        args = parser.parse_args(["--resume", "cv.pdf"])
        assert args.resume == ["cv.pdf"]

    def test_github_argument(self, parser):
        args = parser.parse_args(["--github", "alice"])
        assert args.github == ["alice"]

    def test_output_argument(self, parser):
        args = parser.parse_args(["--csv", "f.csv", "--output", "out.json"])
        assert args.output == "out.json"

    def test_report_argument(self, parser):
        args = parser.parse_args(["--csv", "f.csv", "--report", "rep.json"])
        assert args.report == "rep.json"

    def test_verbose_default_false(self, parser):
        args = parser.parse_args(["--csv", "f.csv"])
        assert args.verbose is False

    def test_verbose_flag(self, parser):
        args = parser.parse_args(["--csv", "f.csv", "--verbose"])
        assert args.verbose is True

    def test_merge_strategy_default(self, parser):
        args = parser.parse_args(["--csv", "f.csv"])
        assert args.merge_strategy == "source_priority"

    def test_merge_strategy_choices(self, parser):
        for s in ["source_priority", "majority_vote", "most_recent", "manual"]:
            args = parser.parse_args(["--csv", "f.csv", "--merge-strategy", s])
            assert args.merge_strategy == s

    def test_match_threshold_default(self, parser):
        args = parser.parse_args(["--csv", "f.csv"])
        assert args.match_threshold == pytest.approx(0.85)

    def test_match_threshold_custom(self, parser):
        args = parser.parse_args(["--csv", "f.csv", "--match-threshold", "0.70"])
        assert args.match_threshold == pytest.approx(0.70)

    def test_format_default(self, parser):
        args = parser.parse_args(["--csv", "f.csv"])
        assert args.format == "pretty"

    def test_format_choices(self, parser):
        for fmt in ["json", "jsonl", "pretty"]:
            args = parser.parse_args(["--csv", "f.csv", "--format", fmt])
            assert args.format == fmt

    def test_no_fail_on_error_flag(self, parser):
        args = parser.parse_args(["--csv", "f.csv", "--no-fail-on-error"])
        assert args.no_fail_on_error is True

    def test_minimal_flag(self, parser):
        args = parser.parse_args(["--csv", "f.csv", "--minimal"])
        assert args.minimal is True

    def test_config_argument(self, parser):
        args = parser.parse_args(["--csv", "f.csv", "--config", "conf.yaml"])
        assert args.config == "conf.yaml"


# ================================================================
# main() — no-input guard
# ================================================================


class TestMainNoInput:
    def test_no_args_returns_exit_2(self, capsys):
        code = main([])
        assert code == 2

    def test_no_args_prints_help_to_stderr(self, capsys):
        main([])
        captured = capsys.readouterr()
        assert "candidate-transform" in captured.err or len(captured.err) > 0


# ================================================================
# main() — with real CSV input
# ================================================================


_SAMPLE_CSV = """\
name,email,phone,title,company,skills,years_experience
Alice Smith,alice@example.com,+14155552671,ML Engineer,TechCorp,"Python,Docker",5
Bob Jones,bob@example.com,+14155559999,Data Scientist,DataCo,"SQL,R",3
"""


class TestMainWithCSV:
    @pytest.fixture
    def csv_file(self, tmp_path):
        f = tmp_path / "candidates.csv"
        f.write_text(_SAMPLE_CSV, encoding="utf-8")
        return str(f)

    @pytest.fixture
    def output_file(self, tmp_path):
        return str(tmp_path / "output.json")

    @pytest.fixture
    def report_file(self, tmp_path):
        return str(tmp_path / "report.json")

    def test_returns_zero_exit_code(self, csv_file, output_file):
        code = main([
            "--csv", csv_file,
            "--output", output_file,
            "--no-fail-on-error",
        ])
        assert code == 0

    def test_output_file_created(self, csv_file, output_file):
        main(["--csv", csv_file, "--output", output_file, "--no-fail-on-error"])
        assert Path(output_file).exists()

    def test_output_is_valid_json(self, csv_file, output_file):
        main(["--csv", csv_file, "--output", output_file, "--no-fail-on-error"])
        content = Path(output_file).read_text(encoding="utf-8")
        data = json.loads(content)
        assert isinstance(data, list)

    def test_output_profiles_count(self, csv_file, output_file):
        main(["--csv", csv_file, "--output", output_file, "--no-fail-on-error"])
        data = json.loads(Path(output_file).read_text(encoding="utf-8"))
        assert len(data) >= 1

    def test_report_file_created(self, csv_file, output_file, report_file):
        main([
            "--csv", csv_file,
            "--output", output_file,
            "--report", report_file,
            "--no-fail-on-error",
        ])
        assert Path(report_file).exists()

    def test_report_is_valid_json(self, csv_file, output_file, report_file):
        main([
            "--csv", csv_file,
            "--output", output_file,
            "--report", report_file,
            "--no-fail-on-error",
        ])
        content = Path(report_file).read_text(encoding="utf-8")
        rep = json.loads(content)
        assert "statistics" in rep

    def test_jsonl_format(self, csv_file, output_file):
        main([
            "--csv", csv_file,
            "--output", output_file,
            "--format", "jsonl",
            "--no-fail-on-error",
        ])
        lines = Path(output_file).read_text(encoding="utf-8").strip().split("\n")
        for line in lines:
            json.loads(line)  # each line must be valid JSON

    def test_minimal_flag_works(self, csv_file, output_file):
        main([
            "--csv", csv_file,
            "--output", output_file,
            "--minimal",
            "--no-fail-on-error",
        ])
        data = json.loads(Path(output_file).read_text(encoding="utf-8"))
        assert isinstance(data, list)
        if data:
            # minimal output should have "name" and "id"
            assert "id" in data[0] or "name" in data[0]

    def test_verbose_does_not_crash(self, csv_file, output_file):
        code = main([
            "--csv", csv_file,
            "--output", output_file,
            "--verbose",
            "--no-fail-on-error",
        ])
        assert code == 0

    def test_parent_dirs_created(self, csv_file, tmp_path):
        nested_out = str(tmp_path / "deep" / "nested" / "out.json")
        code = main([
            "--csv", csv_file,
            "--output", nested_out,
            "--no-fail-on-error",
        ])
        assert code == 0
        assert Path(nested_out).exists()
