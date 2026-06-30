"""
constants.py
============

System-wide constants, lookup tables, and configuration defaults.

Rules
-----
- Every name uses UPPER_SNAKE_CASE to signal immutability.
- No magic numbers anywhere else in the codebase; import from here.
- Grouped into clearly-labelled sections so modules can import
  exactly the constants they need.
- Nothing here changes at runtime; runtime-variable behaviour lives
  in :mod:`src.config`.
- A compile-time assertion validates that identity signal weights
  sum to 1.0 so bad edits surface at import rather than at runtime.

Sections
--------
1.  Source Priority & Confidence Weights
2.  Identity Resolution Signal Weights & Thresholds
3.  Skill Matching Thresholds
4.  Skill Aliases Dictionary
5.  Skill Ontology
6.  Field Importance Weights
7.  Country Mappings
8.  Supported Country Codes
9.  Date Formats
10. Regex Patterns
11. Supported File Extensions
12. Phone Defaults
13. Pipeline Stage Labels
14. Validation Limits
15. SBERT Model Identifier
"""

from __future__ import annotations

import re
from typing import Final

# ================================================================
# 1. Source Priority & Confidence Weights
# ================================================================

#: Merge priority for each source type.
#: **Lower integer = higher trust.**
#: ATS data is recruiter-curated and structured; PDF resumes are
#: self-reported and parsed from unstructured text.
SOURCE_PRIORITY: Final[dict[str, int]] = {
    "ats": 1,
    "github": 2,
    "csv": 3,
    "recruiter_notes": 4,
    "resume": 5,
}

#: Base confidence weight for each source type (0.0 – 1.0).
#: A field sourced exclusively from a high-weight source starts
#: with this confidence before source-agreement adjustments.
SOURCE_CONFIDENCE_WEIGHTS: Final[dict[str, float]] = {
    "ats": 0.90,
    "github": 0.85,
    "csv": 0.75,
    "recruiter_notes": 0.65,
    "resume": 0.60,
}

# ================================================================
# 2. Identity Resolution Signal Weights & Thresholds
# ================================================================

#: Composite identity score formula:
#:
#:   score = EMAIL_W * email
#:         + PHONE_W * phone
#:         + NAME_W  * sbert(name)
#:         + COMP_W  * company
#:         + LOC_W   * location
#:
#: All five weights MUST sum to 1.0 — enforced by assertion below.

IDENTITY_WEIGHT_EMAIL: Final[float] = 0.45
"""Weight for exact normalised-email match signal."""

IDENTITY_WEIGHT_PHONE: Final[float] = 0.20
"""Weight for exact E.164 phone match signal."""

IDENTITY_WEIGHT_NAME: Final[float] = 0.15
"""Weight for SBERT cosine similarity of normalised full names."""

IDENTITY_WEIGHT_COMPANY: Final[float] = 0.10
"""Weight for Jaccard similarity of normalised employer name sets."""

IDENTITY_WEIGHT_LOCATION: Final[float] = 0.10
"""Weight for city/country location match signal."""

# Compile-time guard — catches accidental edits before any test runs.
_IDENTITY_WEIGHT_SUM: float = (
    IDENTITY_WEIGHT_EMAIL
    + IDENTITY_WEIGHT_PHONE
    + IDENTITY_WEIGHT_NAME
    + IDENTITY_WEIGHT_COMPANY
    + IDENTITY_WEIGHT_LOCATION
)
assert abs(_IDENTITY_WEIGHT_SUM - 1.0) < 1e-9, (
    f"Identity signal weights must sum to 1.0; got {_IDENTITY_WEIGHT_SUM:.10f}. "
    "Adjust IDENTITY_WEIGHT_* constants."
)

#: Composite score at or above which two records are considered the
#: same candidate and merged into one CandidateGroup.
IDENTITY_MATCH_THRESHOLD: Final[float] = 0.85

#: Composite score below which a merge decision is escalated to the
#: Human Approval Queue instead of being auto-resolved.
IDENTITY_REVIEW_THRESHOLD: Final[float] = 0.70

# ================================================================
# 3. Skill Matching Thresholds
# ================================================================

#: Minimum RapidFuzz token-sort ratio to accept a fuzzy skill match
#: (Stage 2 of the three-tier skill normalisation pipeline).
RAPIDFUZZ_SKILL_THRESHOLD: Final[float] = 0.88

#: Minimum SBERT cosine similarity to accept a semantic skill match
#: (Stage 3 of the three-tier skill normalisation pipeline).
SBERT_SKILL_THRESHOLD: Final[float] = 0.82

#: Confidence assigned to skills that could not be resolved through
#: any matching stage; stored verbatim for human review.
UNRESOLVED_SKILL_CONFIDENCE: Final[float] = 0.50

#: Confidence awarded per resolution method.
SKILL_CONFIDENCE_BY_METHOD: Final[dict[str, float]] = {
    "dictionary": 1.00,  # Deterministic alias lookup
    "rapidfuzz":  0.89,  # Fuzzy surface-form match
    "sbert":      0.84,  # Semantic embedding match
    "unresolved": 0.50,  # No match; stored as-is
}

# ================================================================
# 4. Skill Aliases Dictionary
# ================================================================

#: Maps raw skill strings (lowercase) to their canonical form.
#: **Stage 1** of the skill normalisation pipeline.
#: Extend this dict — never the normaliser code — to add aliases.
SKILL_ALIASES: Final[dict[str, str]] = {
    # JavaScript / TypeScript
    "js":              "JavaScript",
    "javascript":      "JavaScript",
    "es6":             "JavaScript",
    "es2015":          "JavaScript",
    "es2020":          "JavaScript",
    "ts":              "TypeScript",
    "typescript":      "TypeScript",
    "nodejs":          "Node.js",
    "node":            "Node.js",
    "node.js":         "Node.js",
    "reactjs":         "React",
    "react.js":        "React",
    "vuejs":           "Vue.js",
    "vue":             "Vue.js",
    "angularjs":       "Angular",
    # Python ecosystem
    "python3":         "Python",
    "py":              "Python",
    "sklearn":         "Scikit-learn",
    "scikit learn":    "Scikit-learn",
    "scikit-learn":    "Scikit-learn",
    "tf":              "TensorFlow",
    "tensorflow2":     "TensorFlow",
    "pt":              "PyTorch",
    "pytorch":         "PyTorch",
    "pytorch lightning": "PyTorch",
    "xgboost":         "XGBoost",
    # Data & DB
    "sql":             "SQL",
    "postgres":        "PostgreSQL",
    "postgresql":      "PostgreSQL",
    "mongo":           "MongoDB",
    "mongodb":         "MongoDB",
    "es":              "Elasticsearch",
    "elastic":         "Elasticsearch",
    "redis":           "Redis",
    "dynamo":          "DynamoDB",
    "dynamodb":        "DynamoDB",
    # DevOps / Cloud
    "k8s":             "Kubernetes",
    "kube":            "Kubernetes",
    "docker":          "Docker",
    "gcp":             "Google Cloud Platform",
    "aws":             "Amazon Web Services",
    "azure":           "Microsoft Azure",
    "ci/cd":           "CI/CD",
    "cicd":            "CI/CD",
    "terraform":       "Terraform",
    "ansible":         "Ansible",
    # ML / AI
    "ml":              "Machine Learning",
    "dl":              "Deep Learning",
    "ai":              "Artificial Intelligence",
    "nlp":             "Natural Language Processing",
    "cv":              "Computer Vision",
    "rl":              "Reinforcement Learning",
    "llm":             "Large Language Models",
    "genai":           "Generative AI",
    # General CS
    "oop":             "Object-Oriented Programming",
    "fp":              "Functional Programming",
    "ds":              "Data Structures",
    "algo":            "Algorithms",
    "dsa":             "Data Structures & Algorithms",
    "rest":            "REST API",
    "restapi":         "REST API",
    "graphql":         "GraphQL",
    "grpc":            "gRPC",
}

# ================================================================
# 5. Skill Ontology  (skill → category → parent_domain)
# ================================================================

#: Two-level hierarchy mapping canonical skill names to their
#: (category, parent_domain) tuple.  Used by the skill merger
#: to populate :attr:`~src.models.Skill.category` and to enable
#: parent-domain queries across the skill list.
SKILL_ONTOLOGY: Final[dict[str, tuple[str, str]]] = {
    # Programming Languages
    "Python":                     ("Programming Language",        "Software Engineering"),
    "Java":                       ("Programming Language",        "Software Engineering"),
    "JavaScript":                 ("Programming Language",        "Software Engineering"),
    "TypeScript":                 ("Programming Language",        "Software Engineering"),
    "Go":                         ("Programming Language",        "Software Engineering"),
    "Rust":                       ("Programming Language",        "Software Engineering"),
    "C++":                        ("Programming Language",        "Software Engineering"),
    "C":                          ("Programming Language",        "Software Engineering"),
    "Scala":                      ("Programming Language",        "Software Engineering"),
    "Kotlin":                     ("Programming Language",        "Software Engineering"),
    # Web Frameworks
    "React":                      ("Frontend Framework",          "Web Development"),
    "Vue.js":                     ("Frontend Framework",          "Web Development"),
    "Angular":                    ("Frontend Framework",          "Web Development"),
    "Node.js":                    ("Backend Runtime",             "Web Development"),
    "Django":                     ("Backend Framework",           "Web Development"),
    "FastAPI":                    ("Backend Framework",           "Web Development"),
    "Flask":                      ("Backend Framework",           "Web Development"),
    "Spring Boot":                ("Backend Framework",           "Web Development"),
    # ML Frameworks
    "PyTorch":                    ("Deep Learning Framework",     "Machine Learning"),
    "TensorFlow":                 ("Deep Learning Framework",     "Machine Learning"),
    "Scikit-learn":               ("ML Library",                  "Machine Learning"),
    "XGBoost":                    ("ML Library",                  "Machine Learning"),
    "Keras":                      ("Deep Learning Framework",     "Machine Learning"),
    # Data Engineering
    "Apache Spark":               ("Distributed Processing",      "Data Engineering"),
    "Apache Kafka":               ("Message Queue",               "Data Engineering"),
    "Apache Airflow":             ("Workflow Orchestration",       "Data Engineering"),
    "dbt":                        ("Data Transformation",         "Data Engineering"),
    # Databases
    "PostgreSQL":                 ("Relational Database",         "Data Storage"),
    "MySQL":                      ("Relational Database",         "Data Storage"),
    "MongoDB":                    ("Document Database",           "Data Storage"),
    "Redis":                      ("In-Memory Store",             "Data Storage"),
    "Elasticsearch":              ("Search Engine",               "Data Storage"),
    "DynamoDB":                   ("NoSQL Database",              "Data Storage"),
    "Cassandra":                  ("Wide-Column Store",           "Data Storage"),
    # DevOps / Cloud
    "Kubernetes":                 ("Container Orchestration",     "DevOps & Cloud"),
    "Docker":                     ("Containerization",            "DevOps & Cloud"),
    "Terraform":                  ("Infrastructure as Code",      "DevOps & Cloud"),
    "Ansible":                    ("Configuration Management",    "DevOps & Cloud"),
    "Amazon Web Services":        ("Cloud Platform",              "DevOps & Cloud"),
    "Google Cloud Platform":      ("Cloud Platform",              "DevOps & Cloud"),
    "Microsoft Azure":            ("Cloud Platform",              "DevOps & Cloud"),
    "CI/CD":                      ("DevOps Practice",             "DevOps & Cloud"),
    # AI / NLP
    "Natural Language Processing":("NLP",                         "Artificial Intelligence"),
    "Computer Vision":            ("CV",                          "Artificial Intelligence"),
    "Machine Learning":           ("ML",                          "Artificial Intelligence"),
    "Deep Learning":              ("DL",                          "Artificial Intelligence"),
    "Large Language Models":      ("Generative AI",               "Artificial Intelligence"),
    "Generative AI":              ("Generative AI",               "Artificial Intelligence"),
}

# ================================================================
# 6. Field Importance Weights
# ================================================================

#: Weights used when computing the weighted overall_confidence score.
#: Fields not listed here receive a default weight of 0.50.
FIELD_IMPORTANCE_WEIGHTS: Final[dict[str, float]] = {
    "full_name":        1.00,
    "emails":           1.00,
    "phones":           0.85,
    "location":         0.70,
    "headline":         0.50,
    "years_experience": 0.75,
    "skills":           0.90,
    "experience":       0.85,
    "education":        0.75,
    "links":            0.40,
}

#: Default field importance weight for fields not in FIELD_IMPORTANCE_WEIGHTS.
DEFAULT_FIELD_IMPORTANCE: Final[float] = 0.50

# ================================================================
# 7. Country Mappings
# ================================================================

#: Maps common country name variants (lowercase) to ISO 3166-1 alpha-2
#: two-letter codes.  Used by the location normaliser.
COUNTRY_NAME_TO_CODE: Final[dict[str, str]] = {
    "india":                 "IN",
    "united states":         "US",
    "usa":                   "US",
    "us":                    "US",
    "united kingdom":        "GB",
    "uk":                    "GB",
    "england":               "GB",
    "canada":                "CA",
    "australia":             "AU",
    "germany":               "DE",
    "france":                "FR",
    "singapore":             "SG",
    "united arab emirates":  "AE",
    "uae":                   "AE",
    "netherlands":           "NL",
    "sweden":                "SE",
    "norway":                "NO",
    "denmark":               "DK",
    "finland":               "FI",
    "switzerland":           "CH",
    "japan":                 "JP",
    "south korea":           "KR",
    "korea":                 "KR",
    "brazil":                "BR",
    "mexico":                "MX",
    "south africa":          "ZA",
    "nigeria":               "NG",
    "kenya":                 "KE",
    "egypt":                 "EG",
    "argentina":             "AR",
    "chile":                 "CL",
    "colombia":              "CO",
    "poland":                "PL",
    "czech republic":        "CZ",
    "hungary":               "HU",
    "romania":               "RO",
    "ukraine":               "UA",
    "israel":                "IL",
    "turkey":                "TR",
    "saudi arabia":          "SA",
    "pakistan":              "PK",
    "bangladesh":            "BD",
    "philippines":           "PH",
    "indonesia":             "ID",
    "malaysia":              "MY",
    "thailand":              "TH",
    "vietnam":               "VN",
    "new zealand":           "NZ",
    "ireland":               "IE",
    "china":                 "CN",
    "hong kong":             "HK",
    "spain":                 "ES",
    "italy":                 "IT",
    "portugal":              "PT",
    "russia":                "RU",
}

# ================================================================
# 8. Supported Country Codes (ISO 3166-1 alpha-2)
# ================================================================

#: Set of country codes the phone normaliser can use as dialling
#: context hints.  Based on ``phonenumbers`` library support.
SUPPORTED_COUNTRY_CODES: Final[frozenset[str]] = frozenset(
    COUNTRY_NAME_TO_CODE.values()
)

# ================================================================
# 9. Date Formats
# ================================================================

#: Ordered list of strptime format strings tried by the date
#: normaliser.  ISO 8601 is first to prefer canonical input.
#: The normaliser tries each format in order and uses the first
#: that parses successfully.
DATE_FORMATS: Final[list[str]] = [
    "%Y-%m-%d",        # ISO 8601 full date       — 2024-01-15
    "%Y-%m",           # ISO 8601 year-month       — 2024-01
    "%Y",              # Year only                 — 2024
    "%d/%m/%Y",        # Day-first European        — 15/01/2024
    "%m/%d/%Y",        # Month-first US            — 01/15/2024
    "%d-%m-%Y",        # Day-first dashes          — 15-01-2024
    "%B %Y",           # Full month + year         — January 2024
    "%b %Y",           # Abbreviated month + year  — Jan 2024
    "%B %d, %Y",       # Full with day             — January 15, 2024
    "%b %d, %Y",       # Abbreviated with day      — Jan 15, 2024
    "%Y/%m/%d",        # Slash-separated ISO-like  — 2024/01/15
    "%d %B %Y",        # Day full-month year       — 15 January 2024
    "%d %b %Y",        # Day abbreviated-month yr  — 15 Jan 2024
    "%m-%Y",           # Month-year dashes         — 01-2024
    "%m/%Y",           # Month-year slashes        — 01/2024
]

#: Canonical output date format (ISO 8601).  The normaliser always
#: serialises dates in this format regardless of input format.
CANONICAL_DATE_FORMAT: Final[str] = "%Y-%m-%d"

#: Canonical output for year-month dates where no day is available.
CANONICAL_YEARMONTH_FORMAT: Final[str] = "%Y-%m"

# ================================================================
# 10. Regex Patterns
# ================================================================

#: RFC 5322-simplified email regex for fast pre-validation.
#: Full RFC 5322 compliance is delegated to the ``email-validator``
#: library during normalisation.
EMAIL_REGEX: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
    re.IGNORECASE,
)

#: Matches any http/https URL for link extraction from free text.
URL_REGEX: Final[re.Pattern[str]] = re.compile(
    r"https?://[^\s\"'<>\])\}]+",
    re.IGNORECASE,
)

#: Matches GitHub profile URLs and captures the username.
GITHUB_URL_REGEX: Final[re.Pattern[str]] = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9\-]+)(?:[/?#].*)?$",
    re.IGNORECASE,
)

#: Matches LinkedIn profile URLs and captures the handle.
LINKEDIN_URL_REGEX: Final[re.Pattern[str]] = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9\-_%]+)(?:[/?#].*)?$",
    re.IGNORECASE,
)

#: Matches company name legal suffixes for deduplication normalisation.
COMPANY_LEGAL_SUFFIX_REGEX: Final[re.Pattern[str]] = re.compile(
    r"\b(?:Inc\.?|LLC\.?|Ltd\.?|Limited|Corp\.?|Corporation|GmbH"
    r"|S\.A\.?|B\.V\.?|Pvt\.?|Private|Co\.?|Group)\b",
    re.IGNORECASE,
)

#: Matches excess whitespace (two or more consecutive spaces/tabs).
EXCESS_WHITESPACE_REGEX: Final[re.Pattern[str]] = re.compile(r"[ \t]{2,}")

#: Matches a 4-digit year plausibly representing a graduation/start year.
YEAR_REGEX: Final[re.Pattern[str]] = re.compile(r"\b(19[0-9]{2}|20[0-9]{2})\b")

#: Matches common "Present" / "Current" / "Now" patterns in date fields.
PRESENT_DATE_REGEX: Final[re.Pattern[str]] = re.compile(
    r"^(present|current|now|ongoing|till date|to date|—|-)$",
    re.IGNORECASE,
)

# ================================================================
# 11. Supported File Extensions
# ================================================================

#: File extensions accepted by the CSV extractor.
CSV_EXTENSIONS: Final[frozenset[str]] = frozenset({".csv", ".tsv"})

#: File extensions accepted by the JSON/ATS extractor.
JSON_EXTENSIONS: Final[frozenset[str]] = frozenset({".json", ".jsonl"})

#: File extensions accepted by the PDF extractor.
PDF_EXTENSIONS: Final[frozenset[str]] = frozenset({".pdf"})

#: All supported input file extensions across all extractors.
ALL_SUPPORTED_EXTENSIONS: Final[frozenset[str]] = (
    CSV_EXTENSIONS | JSON_EXTENSIONS | PDF_EXTENSIONS
)

# ================================================================
# 12. Phone Defaults
# ================================================================

#: Default ISO 3166-1 alpha-2 country code used by the phone
#: normaliser when no country can be inferred from location data.
DEFAULT_PHONE_COUNTRY: Final[str] = "IN"

#: International dialling prefix for formatted output.
E164_PREFIX: Final[str] = "+"

#: Maximum valid length of an E.164 phone number (digits only, no +).
E164_MAX_DIGITS: Final[int] = 15

#: Minimum valid length of an E.164 phone number (digits only, no +).
E164_MIN_DIGITS: Final[int] = 7

# ================================================================
# 13. Pipeline Stage Labels
# ================================================================
# Used in :attr:`~src.models.Provenance.processing_stage` and log
# context so every log line and provenance entry is traceable to
# the exact stage that produced it.

STAGE_EXTRACTION: Final[str] = "extraction"
"""Raw bytes/text read from source; no transformation applied."""

STAGE_MAPPING: Final[str] = "canonical_mapping"
"""Source-specific field names translated to canonical names."""

STAGE_NORMALIZATION: Final[str] = "normalization"
"""Field values transformed to canonical format."""

STAGE_IDENTITY: Final[str] = "identity_resolution"
"""Records clustered by composite identity score."""

STAGE_MERGE: Final[str] = "merge"
"""CandidateProfile assembled from a cluster of records."""

STAGE_CONFLICT: Final[str] = "conflict_resolution"
"""Scalar field conflicts resolved to a single winner."""

STAGE_CONFIDENCE: Final[str] = "confidence_scoring"
"""Per-field and five-axis quality metrics computed."""

STAGE_PROJECTION: Final[str] = "projection"
"""CandidateProfile projected to consumer output schema."""

STAGE_VALIDATION: Final[str] = "validation"
"""Projected output validated against schema and business rules."""

STAGE_OUTPUT: Final[str] = "output"
"""Final serialisation to JSON/JSONL files."""

# ================================================================
# 14. Validation Limits
# ================================================================

#: Maximum character length for any string field in the output.
MAX_STRING_LENGTH: Final[int] = 2048

#: Maximum number of skills per candidate in the output.
MAX_SKILLS_COUNT: Final[int] = 200

#: Maximum number of experience entries per candidate.
MAX_EXPERIENCE_COUNT: Final[int] = 50

#: Maximum number of education entries per candidate.
MAX_EDUCATION_COUNT: Final[int] = 20

#: Maximum number of links per candidate.
MAX_LINKS_COUNT: Final[int] = 20

#: Earliest plausible employment year (sanity check for date fields).
MIN_EMPLOYMENT_YEAR: Final[int] = 1950

#: Maximum plausible years of professional experience.
MAX_YEARS_EXPERIENCE: Final[float] = 60.0

#: Minimum overall_confidence for a profile to reach the main output.
#: Profiles below this threshold are written to the errors log.
MIN_PROFILE_CONFIDENCE: Final[float] = 0.20

# ================================================================
# 15. SBERT Model Identifier
# ================================================================

#: HuggingFace model identifier used by the semantic embedder.
#: Changing this string is the only code change needed to swap
#: the underlying sentence-transformer model.
SBERT_MODEL_NAME: Final[str] = "all-MiniLM-L6-v2"

#: Embedding dimension produced by ``SBERT_MODEL_NAME``.
#: Used to pre-allocate numpy arrays in the embedder.
SBERT_EMBEDDING_DIM: Final[int] = 384

# ================================================================
# 16. Freshness Decay
# ================================================================

#: Number of days after which a source extraction contributes zero
#: freshness to the five-axis quality metrics.
FRESHNESS_HALF_LIFE_DAYS: Final[int] = 180
