"""
tests/test_factory.py
======================

Unit tests for ExtractorFactory.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.exceptions import ExtractionError
from src.extractors.ats_json_extractor import ATSJsonExtractor
from src.extractors.base import BaseExtractor
from src.extractors.csv_extractor import CsvExtractor
from src.extractors.factory import ExtractorFactory
from src.extractors.github_extractor import GithubExtractor
from src.extractors.resume_pdf_extractor import ResumePdfExtractor
from src.models import SourceType


@pytest.fixture
def factory() -> ExtractorFactory:
    return ExtractorFactory()


# ── Auto-detection by source string ───────────────────────────


class TestAutoDetection:
    def test_csv_extension_selects_csv(self, factory) -> None:
        ext = factory.get(Path("data/recruiter.csv"))
        assert isinstance(ext, CsvExtractor)

    def test_tsv_extension_selects_csv(self, factory) -> None:
        ext = factory.get(Path("data/export.tsv"))
        assert isinstance(ext, CsvExtractor)

    def test_json_extension_selects_ats(self, factory) -> None:
        ext = factory.get(Path("ats_export.json"))
        assert isinstance(ext, ATSJsonExtractor)

    def test_jsonl_extension_selects_ats(self, factory) -> None:
        ext = factory.get(Path("candidates.jsonl"))
        assert isinstance(ext, ATSJsonExtractor)

    def test_pdf_extension_selects_resume(self, factory) -> None:
        ext = factory.get(Path("resume.pdf"))
        assert isinstance(ext, ResumePdfExtractor)

    def test_uppercase_pdf_selects_resume(self, factory) -> None:
        ext = factory.get(Path("RESUME.PDF"))
        assert isinstance(ext, ResumePdfExtractor)

    def test_github_username_selects_github(self, factory) -> None:
        ext = factory.get("priya-sharma")
        assert isinstance(ext, GithubExtractor)

    def test_github_profile_url_selects_github(self, factory) -> None:
        ext = factory.get("https://github.com/priya-sharma")
        assert isinstance(ext, GithubExtractor)

    def test_github_api_url_selects_github(self, factory) -> None:
        ext = factory.get("https://api.github.com/users/priya")
        assert isinstance(ext, GithubExtractor)

    def test_unsupported_extension_raises(self, factory) -> None:
        with pytest.raises(ExtractionError, match="No registered extractor"):
            factory.get(Path("data/file.xlsx"))

    def test_random_string_without_matches_raises(self, factory) -> None:
        # A string that looks like a file path with unknown extension.
        with pytest.raises(ExtractionError):
            factory.get("data/file.docx")


# ── Explicit source_type override ─────────────────────────────


class TestExplicitSourceType:
    def test_enum_override_csv(self, factory) -> None:
        ext = factory.get(Path("anything.txt"), source_type=SourceType.CSV)
        assert isinstance(ext, CsvExtractor)

    def test_string_override_github(self, factory) -> None:
        ext = factory.get("any_string", source_type="github")
        assert isinstance(ext, GithubExtractor)

    def test_string_override_ats(self, factory) -> None:
        ext = factory.get("file.csv", source_type="ats")
        assert isinstance(ext, ATSJsonExtractor)

    def test_string_override_resume(self, factory) -> None:
        ext = factory.get("file.json", source_type="resume")
        assert isinstance(ext, ResumePdfExtractor)

    def test_invalid_source_type_string_raises(self, factory) -> None:
        with pytest.raises(ExtractionError, match="Unknown source_type"):
            factory.get("file.csv", source_type="xml")

    def test_unknown_enum_style_string_raises(self, factory) -> None:
        with pytest.raises(ExtractionError):
            factory.get("file.csv", source_type="recruiter_csv")


# ── register() ────────────────────────────────────────────────


class TestRegister:
    def test_register_custom_extractor_at_lowest_priority(self, factory) -> None:
        """Custom extractor appended to end (lowest priority)."""
        custom = MagicMock(spec=BaseExtractor)
        custom.supports.return_value = True
        custom.source_type = MagicMock()
        custom.source_type.value = "csv"

        initial_count = len(factory.extractors())
        factory.register(custom)
        assert len(factory.extractors()) == initial_count + 1
        # Lowest priority — should be last.
        assert factory.extractors()[-1] is custom

    def test_register_custom_extractor_at_highest_priority(self, factory) -> None:
        """Custom extractor inserted at index 0 (highest priority)."""
        custom = MagicMock(spec=BaseExtractor)
        custom.supports.return_value = True
        custom.source_type = MagicMock()
        custom.source_type.value = "csv"

        factory.register(custom, priority=0)
        assert factory.extractors()[0] is custom

    def test_registered_custom_is_selected_first(self, factory) -> None:
        """A high-priority custom extractor wins over built-ins."""
        custom = MagicMock(spec=BaseExtractor)
        custom.supports.return_value = True
        custom.source_type = MagicMock()
        custom.source_type.value = "csv"

        factory.register(custom, priority=0)
        # Every source string matches because supports() returns True.
        selected = factory.get("any_source")
        assert selected is custom


# ── registered_types() ────────────────────────────────────────


class TestRegisteredTypes:
    def test_default_types_present(self, factory) -> None:
        types = factory.registered_types()
        assert "csv"    in types
        assert "ats"    in types
        assert "resume" in types
        assert "github" in types

    def test_returns_list_of_strings(self, factory) -> None:
        types = factory.registered_types()
        assert all(isinstance(t, str) for t in types)


# ── extractors() ──────────────────────────────────────────────


class TestExtractors:
    def test_returns_list(self, factory) -> None:
        exts = factory.extractors()
        assert isinstance(exts, list)
        assert len(exts) == 4  # 4 default extractors

    def test_returns_copy(self, factory) -> None:
        """Modifying the returned list must not affect the factory."""
        exts = factory.extractors()
        original_count = len(factory.extractors())
        exts.clear()
        assert len(factory.extractors()) == original_count


# ── config propagation ─────────────────────────────────────────


class TestConfigPropagation:
    def test_config_forwarded_to_extractors(self) -> None:
        """Config dict passed to factory is forwarded to all extractors."""
        factory = ExtractorFactory(config={"api_token": "ghp_test"})
        github_ext = factory.get("priya-sharma")
        assert isinstance(github_ext, GithubExtractor)
        # The config must be accessible on the extractor.
        assert github_ext._config.get("api_token") == "ghp_test"
