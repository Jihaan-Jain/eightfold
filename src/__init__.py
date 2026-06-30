"""
src/__init__.py
===============

candidate-transformer — Multi-Source Candidate Data Transformer.

This package ingests candidate information from heterogeneous sources
(Recruiter CSV, ATS JSON, GitHub API, Resume PDF) and produces one
canonical :class:`~src.models.CandidateProfile` per unique person.

Public surface
--------------
- :mod:`src.models`         — Pydantic v2 canonical data models
- :mod:`src.config`         — Runtime configuration models
- :mod:`src.constants`      — System-wide constants and lookup tables
- :mod:`src.exceptions`     — Custom domain exception hierarchy
- :mod:`src.logging_config` — Structured logging with JSON + rotating file

Architecture
------------
The pipeline has nine ordered stages::

    Extraction → Mapping → Normalization → Identity Resolution →
    Merge → Conflict Resolution → Confidence Scoring →
    Projection → Validation → Output

Each stage is isolated behind its own sub-package and communicates
only through the typed models defined in :mod:`src.models`.

Version
-------
0.1.0 — foundation release (models, config, constants, exceptions, logging)
"""

__version__: str = "0.1.0"
__author__: str = "Eightfold AI Engineering"
__description__: str = "Multi-Source Candidate Data Transformer"
