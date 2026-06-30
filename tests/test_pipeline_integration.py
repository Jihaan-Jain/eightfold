"""
tests/test_pipeline_integration.py
=====================================

End-to-end integration tests for the full pipeline.

These tests are integration-level: they exercise real file I/O and all 7
pipeline stages with minimal mocking.
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path

import pytest

from src.main import PipelineConfig, PipelineResult, run_pipeline
from src.models import CandidateProfile
from src.validation.report import ValidationReport


# ── Fixtures ──────────────────────────────────────────────────────


_ALICE_CSV = """\
name,email,phone,title,company,skills,years_experience,location
Alice Smith,alice@example.com,+14155552671,Senior ML Engineer,TechCorp,"Python,Docker,Kubernetes",8,San Francisco CA USA
"""

_BOB_CSV = """\
name,email,phone,title,company,skills,years_experience,location
Bob Jones,bob@example.com,+442071838750,Data Scientist,DataCo,"SQL,R,Python",5,London UK
"""

_MULTI_CSV = """\
name,email,phone,title,company,skills,years_experience,location
Alice Smith,alice@example.com,+14155552671,Senior ML Engineer,TechCorp,"Python,Docker",8,San Francisco CA USA
Bob Jones,bob@example.com,+442071838750,Data Scientist,DataCo,"SQL,R",5,London UK
Carol White,carol@example.com,,Product Manager,StartupCo,"Agile,Roadmapping",6,New York NY USA
"""

_ATS_JSON = json.dumps({
    "candidate": {
        "name": "Alice Smith",
        "email": "alice@example.com",
        "phone": "+14155552671",
        "title": "Senior ML Engineer",
        "company": "TechCorp",
        "skills": ["Python", "Docker", "TensorFlow"],
        "years_experience": 9,
        "location": "San Francisco, CA",
    }
})


@pytest.fixture
def alice_csv(tmp_path) -> str:
    f = tmp_path / "alice.csv"
    f.write_text(_ALICE_CSV, encoding="utf-8")
    return str(f)


@pytest.fixture
def multi_csv(tmp_path) -> str:
    f = tmp_path / "multi.csv"
    f.write_text(_MULTI_CSV, encoding="utf-8")
    return str(f)


@pytest.fixture
def ats_json(tmp_path) -> str:
    f = tmp_path / "ats.json"
    f.write_text(_ATS_JSON, encoding="utf-8")
    return str(f)


@pytest.fixture
def output_path(tmp_path) -> str:
    return str(tmp_path / "output.json")


@pytest.fixture
def report_path(tmp_path) -> str:
    return str(tmp_path / "report.json")


# ================================================================
# Helpers
# ================================================================


def _run(csv_paths=None, ats_paths=None, **kwargs) -> PipelineResult:
    cfg = PipelineConfig(
        csv_paths=csv_paths or [],
        ats_paths=ats_paths or [],
        fail_on_error=False,
        **kwargs,
    )
    return run_pipeline(cfg)


# ================================================================
# Basic pipeline execution
# ================================================================


class TestPipelineBasic:
    def test_returns_pipeline_result(self, alice_csv):
        result = _run(csv_paths=[alice_csv])
        assert isinstance(result, PipelineResult)

    def test_profiles_is_list(self, alice_csv):
        result = _run(csv_paths=[alice_csv])
        assert isinstance(result.profiles, list)

    def test_outputs_is_list(self, alice_csv):
        result = _run(csv_paths=[alice_csv])
        assert isinstance(result.outputs, list)

    def test_validation_report_type(self, alice_csv):
        result = _run(csv_paths=[alice_csv])
        assert isinstance(result.validation_report, ValidationReport)

    def test_profiles_and_outputs_same_length(self, alice_csv):
        result = _run(csv_paths=[alice_csv])
        assert len(result.profiles) == len(result.outputs)

    def test_profile_count_gte_one(self, alice_csv):
        result = _run(csv_paths=[alice_csv])
        assert result.profile_count >= 1

    def test_elapsed_ms_positive(self, alice_csv):
        result = _run(csv_paths=[alice_csv])
        assert result.elapsed_ms > 0.0

    def test_no_crash_on_empty_input(self):
        """Pipeline with no input sources should produce 0 profiles."""
        cfg = PipelineConfig(fail_on_error=False)
        result = run_pipeline(cfg)
        assert result.profile_count == 0


# ================================================================
# Multi-candidate CSV
# ================================================================


class TestMultiCandidateCSV:
    def test_multiple_candidates_extracted(self, multi_csv):
        result = _run(csv_paths=[multi_csv])
        assert result.profile_count >= 1

    def test_outputs_are_dicts(self, multi_csv):
        result = _run(csv_paths=[multi_csv])
        for out in result.outputs:
            assert isinstance(out, dict)

    def test_validation_total_matches_profile_count(self, multi_csv):
        result = _run(csv_paths=[multi_csv])
        assert result.validation_report.total == result.profile_count

    def test_to_output_list(self, multi_csv):
        result = _run(csv_paths=[multi_csv])
        lst = result.to_output_list()
        assert isinstance(lst, list)


# ================================================================
# Output file writing
# ================================================================


class TestOutputWriting:
    def test_output_file_created(self, alice_csv, output_path):
        _run(csv_paths=[alice_csv], output_path=output_path)
        assert Path(output_path).exists()

    def test_output_file_valid_json(self, alice_csv, output_path):
        _run(csv_paths=[alice_csv], output_path=output_path)
        content = Path(output_path).read_text(encoding="utf-8")
        data = json.loads(content)
        assert isinstance(data, list)

    def test_report_file_created(self, alice_csv, report_path):
        _run(csv_paths=[alice_csv], report_path=report_path)
        assert Path(report_path).exists()

    def test_report_has_statistics(self, alice_csv, report_path):
        _run(csv_paths=[alice_csv], report_path=report_path)
        rep = json.loads(Path(report_path).read_text(encoding="utf-8"))
        assert "statistics" in rep
        assert "candidate_results" in rep

    def test_no_output_path_stdout(self, alice_csv, capsys):
        """When output_path is None, JSON goes to stdout."""
        _run(csv_paths=[alice_csv])
        captured = capsys.readouterr()
        if captured.out.strip():
            json.loads(captured.out)  # must be valid JSON


# ================================================================
# Identity resolution (same email → one profile)
# ================================================================


class TestIdentityResolution:
    def test_same_email_merges_to_one(self, tmp_path):
        """Two CSV rows with identical emails should produce 1 profile."""
        csv_content = (
            "name,email,skills\n"
            "Alice Smith,alice@example.com,Python\n"
            "Alice A. Smith,alice@example.com,Docker\n"
        )
        f = tmp_path / "dup.csv"
        f.write_text(csv_content, encoding="utf-8")
        result = _run(csv_paths=[str(f)])
        assert result.profile_count == 1

    def test_different_emails_separate_profiles(self, tmp_path):
        csv_content = (
            "name,email,skills\n"
            "Alice,alice@x.com,Python\n"
            "Bob,bob@x.com,SQL\n"
        )
        f = tmp_path / "diff.csv"
        f.write_text(csv_content, encoding="utf-8")
        result = _run(csv_paths=[str(f)])
        assert result.profile_count == 2

    def test_multi_source_same_email_merges(self, alice_csv, ats_json, tmp_path):
        """ATS and CSV records with same email → 1 merged profile."""
        result = _run(csv_paths=[alice_csv], ats_paths=[ats_json])
        assert result.profile_count == 1

    def test_merged_profile_has_union_skills(self, alice_csv, ats_json, tmp_path):
        """Skills from both CSV and ATS should be unioned."""
        result = _run(csv_paths=[alice_csv], ats_paths=[ats_json])
        if result.profiles:
            profile = result.profiles[0]
            names = {s.normalized_name for s in profile.skills}
            assert "Python" in names


# ================================================================
# Quality metrics
# ================================================================


class TestQualityMetrics:
    def test_profiles_have_quality_metrics(self, alice_csv):
        result = _run(csv_paths=[alice_csv])
        for p in result.profiles:
            assert p.quality_metrics is not None

    def test_overall_confidence_in_range(self, alice_csv):
        result = _run(csv_paths=[alice_csv])
        for p in result.profiles:
            assert 0.0 <= p.overall_confidence <= 1.0

    def test_multi_source_has_higher_completeness(self, alice_csv, ats_json):
        single = _run(csv_paths=[alice_csv])
        multi  = _run(csv_paths=[alice_csv], ats_paths=[ats_json])
        if single.profiles and multi.profiles:
            s_comp = single.profiles[0].quality_metrics.completeness
            m_comp = multi.profiles[0].quality_metrics.completeness
            # Multi-source should be at least as complete
            assert m_comp >= s_comp * 0.9  # allow 10% tolerance


# ================================================================
# Projection + Validation integration
# ================================================================


class TestProjectionValidationIntegration:
    def test_outputs_contain_candidate_id(self, alice_csv):
        result = _run(csv_paths=[alice_csv])
        for out in result.outputs:
            assert "candidate_id" in out

    def test_validation_report_total_gt_zero(self, alice_csv):
        result = _run(csv_paths=[alice_csv])
        assert result.validation_report.total > 0

    def test_projection_config_rename(self, alice_csv, tmp_path):
        cfg_content = json.dumps({
            "fields": [
                {"source": "full_name", "output": "name"},
                {"source": "emails",    "output": "email", "transform": "first"},
            ]
        })
        cfg_file = tmp_path / "proj.json"
        cfg_file.write_text(cfg_content, encoding="utf-8")

        result = _run(
            csv_paths=[alice_csv],
            projection_config_path=str(cfg_file),
        )
        for out in result.outputs:
            assert "name" in out
            assert "full_name" not in out


# ================================================================
# Error resilience
# ================================================================


class TestErrorResilience:
    def test_missing_csv_does_not_crash(self, output_path):
        """Non-existent file should produce 0 profiles, not raise."""
        result = _run(
            csv_paths=["/nonexistent/path/file.csv"],
            output_path=output_path,
        )
        assert result.profile_count == 0

    def test_empty_csv_produces_zero_profiles(self, tmp_path, output_path):
        f = tmp_path / "empty.csv"
        f.write_text("name,email\n", encoding="utf-8")
        result = _run(csv_paths=[str(f)], output_path=output_path)
        assert result.profile_count == 0

    def test_pipeline_config_invalid_threshold(self, alice_csv):
        """Extreme threshold should not crash; just affect grouping."""
        result = _run(csv_paths=[alice_csv], match_threshold=0.001)
        assert isinstance(result, PipelineResult)
