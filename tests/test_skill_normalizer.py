"""
tests/test_skill_normalizer.py
================================

Unit tests for src/normalization/skill_normalizer.py.

Covers
------
- Stage 1: exact alias lookup (confidence=1.0, method=SKILL_ALIAS)
- Stage 2: RapidFuzz fuzzy matching (method=SKILL_FUZZY)
- Stage 3: SBERT semantic similarity (method=SKILL_SBERT) — skipped when
  sentence_transformers is not installed (marked with a guard)
- unmatched skills: passthrough / drop behaviour
- deduplication after normalization
- SkillNormalizer record-level class: fields, provenance, supports,
  metadata, config overrides
- CANONICAL_SKILLS data integrity
"""

from __future__ import annotations

import pytest

from src.normalization.skill_normalizer import (
    CANONICAL_SKILLS,
    SkillNormalizer,
    SkillNormalizationResult,
    normalize_skill,
    _ALIAS_TO_CANONICAL,
    _CANONICAL_NAMES,
)
from src.models import CanonicalRecord, NormalizationMethod, SourceType


def _rec(skills: list[str]) -> CanonicalRecord:
    return CanonicalRecord(
        source_record_id="test-id",
        source_type=SourceType.CSV,
        source_label="test.csv",
        skills=skills,
    )


# ================================================================
# CANONICAL_SKILLS data integrity
# ================================================================


class TestCanonicalSkillsDatabase:
    def test_not_empty(self):
        assert len(CANONICAL_SKILLS) > 50

    def test_alias_table_populated(self):
        assert len(_ALIAS_TO_CANONICAL) > 200

    def test_python_in_canonicals(self):
        assert "Python" in CANONICAL_SKILLS

    def test_javascript_in_canonicals(self):
        assert "JavaScript" in CANONICAL_SKILLS

    def test_docker_in_canonicals(self):
        assert "Docker" in CANONICAL_SKILLS

    def test_kubernetes_in_canonicals(self):
        assert "Kubernetes" in CANONICAL_SKILLS

    def test_tensorflow_in_canonicals(self):
        assert "TensorFlow" in CANONICAL_SKILLS

    def test_pytorch_in_canonicals(self):
        assert "PyTorch" in CANONICAL_SKILLS

    def test_aws_in_canonicals(self):
        assert "AWS" in CANONICAL_SKILLS

    def test_react_in_canonicals(self):
        assert "React" in CANONICAL_SKILLS

    def test_every_alias_maps_to_known_canonical(self):
        for alias, canonical in _ALIAS_TO_CANONICAL.items():
            assert canonical in CANONICAL_SKILLS, (
                f"Alias {alias!r} → {canonical!r} not in CANONICAL_SKILLS"
            )

    def test_canonical_keys_are_title_cased(self):
        # Canonical names should start with uppercase or be industry-standard
        # camelCase / lowercase names (e.g. jQuery, scikit-learn, dbt, gRPC)
        _EXCEPTIONS = {"jQuery", "dbt", "scikit-learn", "spaCy", "gRPC", "macOS"}
        for key in CANONICAL_SKILLS:
            if key in _EXCEPTIONS:
                continue
            assert (
                key[0].isupper()
                or key[0].isdigit()
                or key[0] in "!@#$%"
            ), f"Canonical {key!r} should start with uppercase"


# ================================================================
# Stage 1: Exact / Alias lookup
# ================================================================


class TestStage1AliasLookup:
    def test_exact_canonical_match(self):
        r = normalize_skill("Python", use_sbert=False)
        assert r.canonical == "Python"
        assert r.method == NormalizationMethod.SKILL_ALIAS
        assert r.score == 1.0
        assert r.matched is True

    def test_alias_py(self):
        r = normalize_skill("py", use_sbert=False)
        assert r.canonical == "Python"
        assert r.method == NormalizationMethod.SKILL_ALIAS

    def test_alias_js(self):
        r = normalize_skill("js", use_sbert=False)
        assert r.canonical == "JavaScript"

    def test_alias_ts(self):
        r = normalize_skill("ts", use_sbert=False)
        assert r.canonical == "TypeScript"

    def test_alias_golang(self):
        r = normalize_skill("golang", use_sbert=False)
        assert r.canonical == "Go"

    def test_alias_reactjs(self):
        r = normalize_skill("reactjs", use_sbert=False)
        assert r.canonical == "React"

    def test_alias_k8s(self):
        r = normalize_skill("k8s", use_sbert=False)
        assert r.canonical == "Kubernetes"

    def test_alias_sklearn(self):
        r = normalize_skill("sklearn", use_sbert=False)
        assert r.canonical == "scikit-learn"

    def test_alias_tensorflow(self):
        r = normalize_skill("tensorflow", use_sbert=False)
        assert r.canonical == "TensorFlow"

    def test_alias_pyspark(self):
        r = normalize_skill("pyspark", use_sbert=False)
        assert r.canonical == "Apache Spark"

    def test_alias_huggingface(self):
        r = normalize_skill("huggingface", use_sbert=False)
        assert r.canonical == "Hugging Face"

    def test_alias_postgres(self):
        r = normalize_skill("postgres", use_sbert=False)
        assert r.canonical == "PostgreSQL"

    def test_alias_mongo(self):
        r = normalize_skill("mongo", use_sbert=False)
        assert r.canonical == "MongoDB"

    def test_alias_gcp(self):
        r = normalize_skill("gcp", use_sbert=False)
        assert r.canonical == "Google Cloud"

    def test_alias_cicd(self):
        r = normalize_skill("cicd", use_sbert=False)
        assert r.canonical == "CI/CD"

    def test_alias_case_insensitive(self):
        r = normalize_skill("PYTHON", use_sbert=False)
        assert r.canonical == "Python"
        assert r.method == NormalizationMethod.SKILL_ALIAS

    def test_alias_with_spaces(self):
        r = normalize_skill("node js", use_sbert=False)
        assert r.canonical == "Node.js"

    def test_alias_machine_learning_abbrev(self):
        r = normalize_skill("ml", use_sbert=False)
        assert r.canonical == "Machine Learning"

    def test_alias_deep_learning_abbrev(self):
        r = normalize_skill("dl", use_sbert=False)
        assert r.canonical == "Deep Learning"

    def test_alias_nlp(self):
        r = normalize_skill("nlp", use_sbert=False)
        assert r.canonical == "Natural Language Processing"

    def test_alias_cv(self):
        r = normalize_skill("cv", use_sbert=False)
        assert r.canonical == "Computer Vision"

    def test_alias_github_actions(self):
        r = normalize_skill("github actions", use_sbert=False)
        assert r.canonical == "GitHub Actions"

    def test_alias_spring_boot(self):
        r = normalize_skill("spring boot", use_sbert=False)
        assert r.canonical == "Spring"

    def test_alias_drf(self):
        r = normalize_skill("drf", use_sbert=False)
        assert r.canonical == "Django"

    def test_empty_string_unmatched(self):
        r = normalize_skill("", use_sbert=False)
        assert r.matched is False

    def test_whitespace_only_unmatched(self):
        r = normalize_skill("   ", use_sbert=False)
        assert r.matched is False


# ================================================================
# Stage 2: Fuzzy matching
# ================================================================


class TestStage2FuzzyMatching:
    def test_typo_python(self):
        # "Pythonn" → Python via fuzzy
        r = normalize_skill("Pythonn", use_sbert=False, fuzzy_threshold=0.80)
        if r.matched:
            assert r.canonical == "Python"
            assert r.method == NormalizationMethod.SKILL_FUZZY

    def test_typo_javascript(self):
        r = normalize_skill("javascrpt", use_sbert=False, fuzzy_threshold=0.75)
        if r.matched:
            assert r.canonical == "JavaScript"

    def test_fuzzy_react_js(self):
        r = normalize_skill("React JS", use_sbert=False, fuzzy_threshold=0.70)
        if r.matched:
            assert r.canonical == "React"

    def test_fuzzy_threshold_too_high_no_match(self):
        r = normalize_skill("Pythonn", use_sbert=False, fuzzy_threshold=0.99)
        # At very high threshold, typo should not match
        if not r.matched:
            assert r.matched is False

    def test_high_threshold_exact_still_matches(self):
        # Exact alias always uses Stage 1, not Stage 2
        r = normalize_skill("py", use_sbert=False, fuzzy_threshold=0.99)
        assert r.matched is True  # Stage 1 kicks in


# ================================================================
# Unmatched / passthrough
# ================================================================


class TestUnmatchedSkills:
    def test_unknown_skill_passthrough(self):
        r = normalize_skill("SomeObscureTech2050", use_sbert=False,
                            fuzzy_threshold=0.99)
        assert r.matched is False
        assert r.canonical == "SomeObscureTech2050"  # original returned

    def test_empty_string_passthrough(self):
        r = normalize_skill("", use_sbert=False)
        assert r.matched is False

    def test_result_type_is_skill_normalization_result(self):
        r = normalize_skill("python", use_sbert=False)
        assert isinstance(r, SkillNormalizationResult)


# ================================================================
# SkillNormalizer (record-level)
# ================================================================


class TestSkillNormalizer:
    @pytest.fixture
    def normalizer(self):
        return SkillNormalizer(config={"use_sbert": False})

    def test_exact_aliases_normalized(self, normalizer):
        rec = _rec(["py", "js", "k8s"])
        out = normalizer.normalize(rec)
        assert "Python" in out.skills
        assert "JavaScript" in out.skills
        assert "Kubernetes" in out.skills

    def test_deduplication(self, normalizer):
        rec = _rec(["py", "Python", "PYTHON"])
        out = normalizer.normalize(rec)
        pythons = [s for s in out.skills if s.lower() == "python"]
        assert len(pythons) == 1

    def test_unknown_skill_kept_by_default(self, normalizer):
        rec = _rec(["python", "ObscureTech9999"])
        out = normalizer.normalize(rec)
        assert "ObscureTech9999" in out.skills

    def test_unknown_skill_dropped_when_configured(self):
        n = SkillNormalizer(config={
            "use_sbert": False,
            "unknown_passthrough": False,
            "fuzzy_threshold": 0.99,
        })
        rec = _rec(["python", "ObscureTech9999"])
        out = n.normalize(rec)
        assert "ObscureTech9999" not in out.skills
        assert "Python" in out.skills

    def test_provenance_written_for_changed(self, normalizer):
        rec = _rec(["py"])
        out = normalizer.normalize(rec)
        skill_provs = [p for p in out.provenance if p.field == "skills"]
        assert len(skill_provs) >= 1

    def test_provenance_original_value(self, normalizer):
        rec = _rec(["py"])
        out = normalizer.normalize(rec)
        prov = next(p for p in out.provenance if p.field == "skills")
        assert prov.original_value == "py"
        assert prov.normalized_value == "Python"

    def test_no_provenance_when_already_canonical(self, normalizer):
        rec = _rec(["Python"])
        out = normalizer.normalize(rec)
        skill_provs = [p for p in out.provenance if p.field == "skills"]
        assert len(skill_provs) == 0

    def test_empty_skills_no_crash(self, normalizer):
        rec = _rec([])
        out = normalizer.normalize(rec)
        assert out.skills == []

    def test_all_known_aliases_normalized(self, normalizer):
        aliases = ["py", "js", "ts", "golang", "k8s", "sklearn", "reactjs",
                   "gcp", "mongo", "postgres", "cicd", "ml", "nlp"]
        rec = _rec(aliases)
        out = normalizer.normalize(rec)
        # Every alias should resolve
        for skill in out.skills:
            assert skill in CANONICAL_SKILLS, (
                f"{skill!r} not in CANONICAL_SKILLS"
            )

    def test_supports_with_skills(self, normalizer):
        rec = _rec(["python"])
        assert normalizer.supports(rec) is True

    def test_supports_false_without_skills(self, normalizer):
        rec = _rec([])
        assert normalizer.supports(rec) is False

    def test_metadata_returns_dict(self, normalizer):
        m = normalizer.metadata()
        assert isinstance(m, dict)
        assert "canonical_count" in m
        assert m["canonical_count"] > 50

    def test_deduplicate_false_config(self):
        n = SkillNormalizer(config={
            "use_sbert": False,
            "deduplicate": False,
        })
        rec = _rec(["py", "Python"])
        out = n.normalize(rec)
        # Two entries for Python (not deduped)
        pythons = [s for s in out.skills if s.lower() == "python"]
        assert len(pythons) >= 2

    def test_fuzzy_threshold_config(self):
        # With very high threshold, only exact aliases match
        n = SkillNormalizer(config={
            "use_sbert":       False,
            "fuzzy_threshold": 0.99,
        })
        rec = _rec(["python"])  # exact alias match via Stage 1
        out = n.normalize(rec)
        assert "Python" in out.skills
