"""
tests/test_json_extractor.py
=============================

Unit tests for ATSJsonExtractor.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.extractors.ats_json_extractor import ATSJsonExtractor
from src.exceptions import ExtractionError
from src.models import SourceType


def _write_json(data: object, suffix: str = ".json") -> Path:
    """Serialise data to a temp JSON file and return the path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return Path(path)


def _write_text(content: str, suffix: str = ".json") -> Path:
    """Write raw text to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return Path(path)


@pytest.fixture
def extractor() -> ATSJsonExtractor:
    return ATSJsonExtractor()


# ── supports() ────────────────────────────────────────────────


class TestSupports:
    def test_json_extension(self, extractor) -> None:
        assert extractor.supports(Path("file.json")) is True

    def test_jsonl_extension(self, extractor) -> None:
        assert extractor.supports(Path("file.jsonl")) is True

    def test_uppercase_json(self, extractor) -> None:
        assert extractor.supports(Path("FILE.JSON")) is True

    def test_csv_not_supported(self, extractor) -> None:
        assert extractor.supports(Path("file.csv")) is False

    def test_pdf_not_supported(self, extractor) -> None:
        assert extractor.supports(Path("file.pdf")) is False


# ── validate_source() ─────────────────────────────────────────


class TestValidateSource:
    def test_missing_file_raises(self, extractor) -> None:
        with pytest.raises(ExtractionError):
            extractor.validate_source(Path("nonexistent.json"))

    def test_valid_file_passes(self, extractor) -> None:
        path = _write_json({"name": "Alice"})
        try:
            extractor.validate_source(path)
        finally:
            path.unlink()


# ── extract() — Single Object ─────────────────────────────────


class TestExtractSingleObject:
    def test_single_dict_produces_one_record(self, extractor) -> None:
        path = _write_json({"name": "Alice", "email": "alice@x.com"})
        try:
            records = extractor.extract(path)
            assert len(records) == 1
            assert records[0].raw_fields["name"] == "Alice"
        finally:
            path.unlink()

    def test_source_type_is_ats(self, extractor) -> None:
        path = _write_json({"name": "Bob"})
        try:
            records = extractor.extract(path)
            assert records[0].source_type == SourceType.ATS
        finally:
            path.unlink()

    def test_json_structure_is_object(self, extractor) -> None:
        path = _write_json({"name": "Alice"})
        try:
            records = extractor.extract(path)
            assert records[0].metadata["json_structure"] == "object"
        finally:
            path.unlink()

    def test_record_index_is_zero(self, extractor) -> None:
        path = _write_json({"name": "Alice"})
        try:
            records = extractor.extract(path)
            assert records[0].metadata["record_index"] == 0
        finally:
            path.unlink()


# ── extract() — Array ─────────────────────────────────────────


class TestExtractArray:
    def test_array_produces_multiple_records(self, extractor) -> None:
        path = _write_json([
            {"name": "Alice", "email": "alice@x.com"},
            {"name": "Bob",   "email": "bob@x.com"},
            {"name": "Carol", "email": "carol@x.com"},
        ])
        try:
            records = extractor.extract(path)
            assert len(records) == 3
            assert records[2].raw_fields["name"] == "Carol"
        finally:
            path.unlink()

    def test_json_structure_is_array(self, extractor) -> None:
        path = _write_json([{"name": "Alice"}])
        try:
            records = extractor.extract(path)
            assert records[0].metadata["json_structure"] == "array"
        finally:
            path.unlink()

    def test_record_indices(self, extractor) -> None:
        path = _write_json([{"name": "A"}, {"name": "B"}])
        try:
            records = extractor.extract(path)
            assert records[0].metadata["record_index"] == 0
            assert records[1].metadata["record_index"] == 1
        finally:
            path.unlink()

    def test_total_records_in_file(self, extractor) -> None:
        path = _write_json([{"name": "A"}, {"name": "B"}, {"name": "C"}])
        try:
            records = extractor.extract(path)
            for rec in records:
                assert rec.metadata["total_records_in_file"] == 3
        finally:
            path.unlink()


# ── extract() — Nested Objects ────────────────────────────────


class TestExtractNested:
    def test_nested_dict_stored_verbatim(self, extractor) -> None:
        data = {
            "name": "Alice",
            "address": {"city": "Bangalore", "country": "India"},
            "skills": ["Python", "Java"],
        }
        path = _write_json(data)
        try:
            records = extractor.extract(path)
            assert isinstance(records[0].raw_fields["address"], dict)
            assert records[0].raw_fields["address"]["city"] == "Bangalore"
            assert isinstance(records[0].raw_fields["skills"], list)
        finally:
            path.unlink()

    def test_null_fields_preserved(self, extractor) -> None:
        path = _write_json({"name": "Alice", "phone": None, "email": ""})
        try:
            records = extractor.extract(path)
            assert records[0].raw_fields["phone"] is None
            assert records[0].raw_fields["email"] == ""
        finally:
            path.unlink()

    def test_missing_fields_not_added(self, extractor) -> None:
        path = _write_json({"name": "Alice"})
        try:
            records = extractor.extract(path)
            assert "email" not in records[0].raw_fields
        finally:
            path.unlink()


# ── extract() — JSONL ─────────────────────────────────────────


class TestExtractJsonl:
    def test_jsonl_two_lines(self, extractor) -> None:
        content = (
            '{"name":"Alice","email":"alice@x.com"}\n'
            '{"name":"Bob","email":"bob@x.com"}\n'
        )
        path = _write_text(content, suffix=".jsonl")
        try:
            records = extractor.extract(path)
            assert len(records) == 2
            assert records[0].metadata["json_structure"] == "jsonl"
        finally:
            path.unlink()

    def test_jsonl_ignores_blank_lines(self, extractor) -> None:
        content = '{"name":"Alice"}\n\n\n{"name":"Bob"}\n'
        path = _write_text(content, suffix=".jsonl")
        try:
            records = extractor.extract(path)
            assert len(records) == 2
        finally:
            path.unlink()

    def test_invalid_jsonl_line_raises(self, extractor) -> None:
        content = '{"name":"Alice"}\nNOT JSON\n'
        path = _write_text(content, suffix=".jsonl")
        try:
            with pytest.raises(ExtractionError, match="Invalid JSON"):
                extractor.extract(path)
        finally:
            path.unlink()


# ── extract() — records_key unwrapping ───────────────────────


class TestRecordsKeyUnwrap:
    def test_records_key_unwraps_nested_array(self) -> None:
        extractor = ATSJsonExtractor(config={"records_key": "candidates"})
        path = _write_json({
            "metadata": {"page": 1},
            "candidates": [
                {"name": "Alice"},
                {"name": "Bob"},
            ],
        })
        try:
            records = extractor.extract(path)
            assert len(records) == 2
            assert records[0].raw_fields["name"] == "Alice"
        finally:
            path.unlink()


# ── extract() — Errors ────────────────────────────────────────


class TestExtractErrors:
    def test_invalid_json_raises(self, extractor) -> None:
        path = _write_text("NOT VALID JSON {{{")
        try:
            with pytest.raises(ExtractionError, match="Invalid JSON"):
                extractor.extract(path)
        finally:
            path.unlink()

    def test_nonexistent_file_raises(self, extractor) -> None:
        with pytest.raises(ExtractionError):
            extractor.extract(Path("ghost.json"))

    def test_file_hash_in_metadata(self, extractor) -> None:
        path = _write_json({"name": "Alice"})
        try:
            records = extractor.extract(path)
            checksum = records[0].metadata["checksum"]
            assert isinstance(checksum, str)
            assert checksum.startswith("sha256:")
            assert len(checksum) == 71  # "sha256:" (7) + 64 hex
        finally:
            path.unlink()

    def test_standard_metadata_block(self, extractor) -> None:
        path = _write_json({"name": "Alice"})
        try:
            records = extractor.extract(path)
            meta = records[0].metadata
            for key in ("checksum", "file_size", "mime", "encoding", "pages", "language"):
                assert key in meta, f"Missing standard key: {key}"
            assert meta["pages"] is None
            assert meta["language"] is None
            assert isinstance(meta["file_size"], int) and meta["file_size"] > 0
        finally:
            path.unlink()

    def test_empty_array_returns_empty_list(self, extractor) -> None:
        path = _write_json([])
        try:
            records = extractor.extract(path)
            assert records == []
        finally:
            path.unlink()

    def test_metadata_method(self, extractor) -> None:
        m = extractor.metadata()
        assert m["source_type"] == "ats"
        assert ".json" in m["supported_extensions"]
