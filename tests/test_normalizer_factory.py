"""
tests/test_normalizer_factory.py
==================================

Unit tests for src/normalization/factory.py.
"""

from __future__ import annotations

import pytest

from src.normalization.factory import NormalizerFactory, _DEFAULT_ORDER, _NORMALIZER_REGISTRY
from src.normalization.pipeline import NormalizationPipeline
from src.normalization.email_normalizer import EmailNormalizer
from src.normalization.skill_normalizer import SkillNormalizer
from src.normalization.phone_normalizer import PhoneNormalizer
from src.normalization.country_normalizer import CountryNormalizer
from src.normalization.location_normalizer import LocationNormalizer
from src.models import CanonicalRecord, SourceType


def _rec(**kwargs) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="test-id",
        source_type=SourceType.CSV,
        source_label="test.csv",
        **kwargs,
    )


# ================================================================
# Registry
# ================================================================


class TestRegistry:
    def test_all_normalizers_registered(self):
        names = NormalizerFactory.available_normalizers()
        assert "EmailNormalizer"    in names
        assert "PhoneNormalizer"    in names
        assert "DateNormalizer"     in names
        assert "CountryNormalizer"  in names
        assert "LocationNormalizer" in names
        assert "UrlNormalizer"      in names
        assert "NameNormalizer"     in names
        assert "CompanyNormalizer"  in names
        assert "SkillNormalizer"    in names

    def test_available_normalizers_count(self):
        assert len(NormalizerFactory.available_normalizers()) == 9

    def test_default_order_respects_country_before_location(self):
        order = NormalizerFactory.default_order()
        assert order.index("CountryNormalizer") < order.index("LocationNormalizer")

    def test_default_order_respects_country_before_phone(self):
        order = NormalizerFactory.default_order()
        assert order.index("CountryNormalizer") < order.index("PhoneNormalizer")

    def test_default_order_returns_list(self):
        order = NormalizerFactory.default_order()
        assert isinstance(order, list)
        assert len(order) == 9


# ================================================================
# build_default_pipeline
# ================================================================


class TestBuildDefaultPipeline:
    def test_returns_pipeline_instance(self):
        p = NormalizerFactory.build_default_pipeline()
        assert isinstance(p, NormalizationPipeline)

    def test_all_nine_normalizers_registered(self):
        p = NormalizerFactory.build_default_pipeline()
        assert len(p) == 9

    def test_email_in_pipeline(self):
        p = NormalizerFactory.build_default_pipeline()
        assert "EmailNormalizer" in p.registered_names()

    def test_skill_in_pipeline(self):
        p = NormalizerFactory.build_default_pipeline()
        assert "SkillNormalizer" in p.registered_names()

    def test_default_pipeline_runs_on_record(self):
        p = NormalizerFactory.build_default_pipeline(config={
            "SkillNormalizer": {"use_sbert": False},
        })
        rec = _rec(
            emails=["ALICE@EXAMPLE.COM"],
            full_name="alice smith",
            skills=["py", "k8s"],
        )
        out = p.run(rec)
        assert "alice@example.com" in out.emails
        assert out.full_name == "Alice Smith"
        assert "Python" in out.skills

    def test_disabled_via_config(self):
        p = NormalizerFactory.build_default_pipeline(config={
            "pipeline": {"disabled": ["EmailNormalizer"]},
        })
        rec = _rec(emails=["ALICE@EXAMPLE.COM"])
        out = p.run(rec)
        # Email not normalized — EmailNormalizer is disabled
        assert "ALICE@EXAMPLE.COM" in out.emails

    def test_per_normalizer_config_passed_through(self):
        p = NormalizerFactory.build_default_pipeline(config={
            "PhoneNormalizer": {"default_region": "IN"},
        })
        phone_normalizer = next(
            n for n in p.normalizers
            if n.__class__.__name__ == "PhoneNormalizer"
        )
        assert phone_normalizer._config.get("default_region") == "IN"

    def test_skill_config_use_sbert_passed_through(self):
        p = NormalizerFactory.build_default_pipeline(config={
            "SkillNormalizer": {"use_sbert": False},
        })
        skill_n = next(
            n for n in p.normalizers
            if n.__class__.__name__ == "SkillNormalizer"
        )
        assert skill_n._config.get("use_sbert") is False

    def test_empty_config_uses_defaults(self):
        p = NormalizerFactory.build_default_pipeline()
        assert len(p) == 9

    def test_none_config_uses_defaults(self):
        p = NormalizerFactory.build_default_pipeline(config=None)
        assert len(p) == 9


# ================================================================
# build_custom_pipeline
# ================================================================


class TestBuildCustomPipeline:
    def test_single_normalizer(self):
        p = NormalizerFactory.build_custom_pipeline(["EmailNormalizer"])
        assert len(p) == 1
        assert "EmailNormalizer" in p.registered_names()

    def test_two_normalizers_in_order(self):
        p = NormalizerFactory.build_custom_pipeline(
            ["NameNormalizer", "EmailNormalizer"]
        )
        names = p.registered_names()
        assert names.index("NameNormalizer") < names.index("EmailNormalizer")

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown normalizer"):
            NormalizerFactory.build_custom_pipeline(["FakeNormalizer"])

    def test_empty_list_returns_empty_pipeline(self):
        p = NormalizerFactory.build_custom_pipeline([])
        assert len(p) == 0

    def test_per_normalizer_config(self):
        p = NormalizerFactory.build_custom_pipeline(
            ["SkillNormalizer"],
            config={"SkillNormalizer": {"use_sbert": False}},
        )
        skill_n = p.normalizers[0]
        assert skill_n._config.get("use_sbert") is False

    def test_custom_pipeline_runs(self):
        p = NormalizerFactory.build_custom_pipeline(
            ["EmailNormalizer", "NameNormalizer"],
        )
        rec = _rec(emails=["ALICE@EXAMPLE.COM"], full_name="alice smith")
        out = p.run(rec)
        assert "alice@example.com" in out.emails
        assert out.full_name == "Alice Smith"

    def test_all_normalizers_can_be_included(self):
        all_names = NormalizerFactory.available_normalizers()
        p = NormalizerFactory.build_custom_pipeline(all_names)
        assert len(p) == 9


# ================================================================
# End-to-end integration
# ================================================================


class TestEndToEndIntegration:
    def test_full_pipeline_email_phone_name(self):
        p = NormalizerFactory.build_default_pipeline(config={
            "SkillNormalizer": {"use_sbert": False},
            "PhoneNormalizer": {"default_region": "US"},
        })
        rec = _rec(
            emails=["BOB@EXAMPLE.COM", "bob@example.com"],
            full_name="bob jones",
            current_company="Google LLC",
            skills=["py", "golang", "k8s"],
            location="San Francisco, California, US",
        )
        out = p.run(rec)
        # Email
        assert "bob@example.com" in out.emails
        assert out.emails.count("bob@example.com") == 1  # deduped
        # Name
        assert out.full_name == "Bob Jones"
        # Company
        assert "Google" in out.current_company
        assert "LLC" not in out.current_company
        # Skills
        assert "Python" in out.skills
        assert "Go" in out.skills
        assert "Kubernetes" in out.skills
        # Location components
        assert out.mapping_metadata.get("country_code") is not None

    def test_pipeline_never_crashes_on_empty_record(self):
        p = NormalizerFactory.build_default_pipeline(config={
            "SkillNormalizer": {"use_sbert": False},
        })
        rec = _rec()
        out = p.run(rec)
        assert out is not None

    def test_pipeline_never_crashes_on_all_invalid(self):
        p = NormalizerFactory.build_default_pipeline(config={
            "SkillNormalizer": {"use_sbert": False},
        })
        rec = _rec(
            emails=["not-an-email", "also-bad"],
            phones=["not-a-phone"],
            full_name="",
            skills=[""],
        )
        out = p.run(rec)
        assert out is not None
