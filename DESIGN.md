# Technical Design Document — Candidate Transformer

**Version:** 1.0  
**Date:** 2026-06-30  
**Status:** Final

---

## 1. Problem Statement

Recruiting teams accumulate candidate data across multiple disconnected systems: Applicant Tracking Systems (ATS), uploaded CSV spreadsheets, parsed résumés, and public GitHub profiles. The same candidate appears in multiple sources with inconsistent formatting, spelling variations, and conflicting values.

**Goal:** Given N records from M sources, produce one canonical `CandidateProfile` per unique real-world person, with full provenance, confidence scores, and configurable output schema.

---

## 2. System Constraints

| Constraint | Decision |
|------------|----------|
| No black-box AI for core logic | All merge/identity decisions are deterministic and rule-based |
| SBERT allowed only for skills | Semantic similarity only for ontology matching |
| Never crash on bad input | Every stage has per-record error isolation |
| Full provenance required | Every field value traces back to its source record and extraction stage |
| Output must be configurable | Projection layer supports runtime YAML/JSON schema |

---

## 3. Data Models

### 3.1 RawRecord

Raw, untyped field-value pairs from a single source record. Schema-free — the extractor fills whatever fields it can find.

### 3.2 CanonicalRecord

Structured Pydantic model with all canonical fields (emails, phones, skills, experience, education, etc.). Produced by the mapper; normalised in-place by the normalization pipeline.

### 3.3 CandidateProfile (immutable)

Frozen Pydantic model. Produced by the merge engine. Contains:
- Merged scalar fields (full_name, headline, location, …)
- Union-deduplicated lists (emails, phones, skills, experience, education, links)
- Five-axis `QualityMetrics`
- Full per-field `Provenance` map

### 3.4 Provenance

```python
@dataclass
class Provenance:
    field:            str
    source:           SourceType
    method:           NormalizationMethod
    original_value:   Any
    normalized_value: Any
    processing_stage: ProcessingStage
    confidence:       float
    reason:           str
    timestamp:        datetime
```

Every field change across all 7 stages appends a `Provenance` entry.

---

## 4. Stage Design

### 4.1 Extraction

Each extractor produces `list[RawRecord]`. Extractors are registered in `ExtractorFactory` by source type. New extractors require only implementing `BaseExtractor.extract()`.

**Error isolation:** Each record is extracted independently; a malformed row produces a warning, not a crash.

### 4.2 Mapping

`FieldRegistry` defines all canonical fields with aliases, types, and priorities. Every mapper reads field definitions from the registry — no mapper contains hardcoded field names.

**Alias resolution:** e.g., `["name", "full_name", "candidate_name", "applicant_name"]` all map to `full_name`.

### 4.3 Normalization

9 independent `BaseNormalizer` subclasses, run in a configurable `NormalizationPipeline`. Each normalizer is stateless and idempotent.

| Normalizer | Key operations |
|------------|---------------|
| EmailNormalizer | Lowercase, strip whitespace, validate RFC regex |
| PhoneNormalizer | `phonenumbers` library → E.164 |
| DateNormalizer | 12 date format patterns → ISO 8601 |
| NameNormalizer | NFC, title-case, remove excess whitespace |
| CompanyNormalizer | Strip legal suffixes (Inc., Ltd., LLC) |
| LocationNormalizer | Parse city/state/country, map country name → ISO code |
| URLNormalizer | Ensure https://, lowercase, strip trailing slash |
| SkillNormalizer | Ontology → RapidFuzz → SBERT cascade |
| CountryNormalizer | Map country name variants → ISO 3166-1 alpha-2 |

### 4.4 Identity Resolution

**Algorithm:** Union-Find (disjoint-set) with path compression.

**Signals:**

| Signal | Type | Score contribution |
|--------|------|--------------------|
| Email exact match | Hard | `score = max(score, 0.85)` |
| Phone exact match | Hard | `score = max(score, 0.85)` |
| GitHub username | Hard | `score = max(score, 0.85)` |
| LinkedIn handle | Hard | `score = max(score, 0.85)` |
| Name + Company (fuzzy ≥ 0.85 + 0.80) | Soft | `+= NAME_WEIGHT × sim + CO_WEIGHT × co_sim` |
| Name + Location | Soft | `+= NAME_WEIGHT × 0.4 + LOC_WEIGHT × 0.6` |

**Thresholds:** `IDENTITY_MATCH_THRESHOLD = 0.85` (merge), `IDENTITY_REVIEW_THRESHOLD = 0.70` (flag for review).

**Transitivity:** Union-Find gives A≡C when A≡B and B≡C, even with no direct A↔C signal.

### 4.5 Merge Engine

**Scalar fields** → `ConflictResolver` (SOURCE_PRIORITY by default)  
**List fields** → Union + deduplication by normalised key  
**Experience** → Union-dedup by `(normalized_company | title | start_date[:7])`  
**Education** → Union-dedup by `(normalized_institution | degree | end_date[:4])`  
**Skills** → Union-dedup by `clean_lower(name)`, tracks aliases + sources  
**Links** → Union-dedup by `url_key(url)`, sorted verified-first  
**years_experience** → `max()` across all sources  
**GitHub stats** → `max()` (stars, repos)

### 4.6 Confidence Engine

Per-field confidence:
```
fc = mean(source_weights) + min(0.15, 0.10 × (source_count − 1)) + (0.05 if agreed else −0.10)
```

Five axes:
```
overall_confidence = Σ(fc × importance_weight) / Σ(importance_weight)
completeness       = populated_expected_fields / total_expected_fields
consistency        = 1.0 − min(1.0, violations × 0.15)
agreement          = agreed_multi_source_fields / total_multi_source_fields
freshness          = mean(exp(−ln(2) × age_days / 90))
```

### 4.7 Projection

Runtime-configurable using YAML or JSON. Supports:
- Field rename (`source` → `output`)
- Dot-path traversal (`location.city`)
- Array element extraction (`skills[].normalized_name`)
- Named transforms (uppercase, lowercase, title, truncate:N, join:sep, first, last, count, str, int, float, bool)
- Default values for missing fields
- Conditional inclusion (`condition: "overall_confidence > 0.5"`)
- Flag-based suppression (`include_provenance: false`)
- Drop list

### 4.8 Validation

**Schema validation** (structural):
- Required fields present and non-empty
- String max length
- List minimum length
- Email format (RFC regex)
- Phone format (E.164)
- URL scheme check

**Business validation** (semantic):
- Experience dates ordered (start < end)
- Education dates ordered (start < end)
- No future graduation (end_year ≤ current_year + 10)
- Experience not before 1900
- No duplicate emails, phones, skills
- years_experience ∈ [0, 60]
- overall_confidence ≥ MIN_PROFILE_CONFIDENCE
- At least one email present
- GitHub username format

---

## 5. Error Handling Strategy

| Level | Strategy |
|-------|----------|
| Record extraction | Per-record try/except; failed records log a warning and are skipped |
| Normalization | Unknown values remain unchanged; warning logged with context |
| Merge | Per-group try/except; failed groups log an error; `stop_on_error=False` continues |
| Validation | Per-candidate try/except; exceptions produce an `internal_error` issue |
| CLI | Exit code 0 (success), 1 (validation failures), 2 (argument error) |

---

## 6. Logging

Structured JSON logging via `structlog`-compatible `logging_config.py`. All log entries include:
- `timestamp`, `level`, `module`, `function`
- Domain-specific `extra` fields (e.g., `candidate_id`, `stage`, `source`, `elapsed_ms`)

---

## 7. Testing Strategy

| Layer | Test count | Approach |
|-------|-----------|---------|
| Extractors | ~120 | Unit + file fixture |
| Mappers | ~150 | Unit with synthetic RawRecord |
| Normalizers | ~971 | Parametrized unit (known-good pairs) |
| Identity resolver | ~45 | Unit; synthetic CanonicalRecord pairs |
| Conflict resolver | ~35 | Unit; all 4 strategies + overrides |
| Merge engine | ~40 | Unit; single + multi-source groups |
| Merge pipeline | ~40 | Integration; factory presets |
| Projector | ~70 | Unit; all transforms, conditions, strategies |
| Validator | ~50 | Unit; all 12 business rules |
| CLI | ~35 | Black-box with temp files |
| Pipeline integration | ~35 | End-to-end with real CSV/JSON |
| **Total** | **~1200+** | |

---

## 8. Scalability Notes

See `BENCHMARKS.md` for detailed measurements.

- **Identity resolution** is O(n²) in pairwise comparisons. For n ≤ 10,000 records this is fast enough for batch processing. Above 10k, blocking on email domain prefix can reduce comparisons by 10–100×.
- **Normalisation** is O(n) and trivially parallelisable (`multiprocessing.Pool`).
- **SBERT** (optional) is the only GPU-acceleratable component.
- **Output** uses Python's built-in `json` with `default=str` for all non-serialisable types.
