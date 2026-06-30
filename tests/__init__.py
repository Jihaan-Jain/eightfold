"""
tests
=====

Unit and integration test suite for the Candidate Data Transformer.

Test Structure
--------------
The test tree mirrors the source tree for discoverability::

    tests/
    ├── unit/
    │   ├── test_models.py          — Pydantic model construction + validation
    │   ├── test_config.py          — Config model validators (weight sums, thresholds)
    │   ├── test_constants.py       — Constant integrity (weight sum assertion, regex)
    │   ├── test_exceptions.py      — Exception hierarchy and structured fields
    │   ├── test_extractors/
    │   │   ├── test_csv_extractor.py
    │   │   ├── test_json_extractor.py
    │   │   ├── test_github_extractor.py
    │   │   └── test_pdf_extractor.py
    │   ├── test_normalization/
    │   │   ├── test_email_normalizer.py
    │   │   ├── test_phone_normalizer.py
    │   │   ├── test_date_normalizer.py
    │   │   ├── test_name_normalizer.py
    │   │   ├── test_skill_normalizer.py
    │   │   └── test_location_normalizer.py
    │   ├── test_merge/
    │   │   ├── test_identity_resolver.py
    │   │   ├── test_composite_scorer.py
    │   │   ├── test_merger.py
    │   │   ├── test_conflict_resolver.py
    │   │   ├── test_skill_merger.py
    │   │   ├── test_experience_merger.py
    │   │   └── test_confidence_scorer.py
    │   ├── test_projection/
    │   │   └── test_projector.py
    │   └── test_validation/
    │       ├── test_schema_validator.py
    │       └── test_business_validator.py
    └── integration/
        └── test_pipeline.py        — End-to-end pipeline run with fixture data

Fixtures
--------
All test fixtures (sample CSVs, JSON, PDFs, expected outputs) live in
``tests/fixtures/`` and are committed to the repository so CI runs are
fully deterministic without external I/O.
"""
