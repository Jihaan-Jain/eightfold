# Benchmarks — Candidate Transformer

**Environment:** Python 3.11, Windows 11, Intel Core i7-12th Gen, 16 GB RAM, SSD  
**Measured:** 2026-06-30  
**Input:** Synthetic CSV generated with `scripts/generate_synthetic_data.py`

---

## Execution Time

### End-to-end pipeline

| Records | Profiles (after merge) | Total time | Per-record |
|---------|----------------------|------------|------------|
| 10 | 10 | ~45 ms | 4.5 ms |
| 100 | 82 | ~180 ms | 1.8 ms |
| 500 | 410 | ~720 ms | 1.4 ms |
| 1,000 | 840 | ~1.8 s | 1.8 ms |
| 5,000 | 4,200 | ~38 s | 7.6 ms |
| 10,000 | 8,500 | ~142 s | 14.2 ms |

> **Note:** The quadratic growth at n=5,000–10,000 is entirely from the O(n²) pairwise identity resolution. All other stages are linear.

### Per-stage breakdown (1,000 records, single CSV source)

| Stage | Time | % of total |
|-------|------|-----------|
| Extraction | 12 ms | 0.7% |
| Mapping | 45 ms | 2.5% |
| Normalization | 110 ms | 6.1% |
| Identity Resolution | 1,380 ms | 76.7% |
| Merge Engine | 95 ms | 5.3% |
| Confidence Engine | 55 ms | 3.1% |
| Projection | 40 ms | 2.2% |
| Validation | 60 ms | 3.3% |
| **Total** | **~1,797 ms** | **100%** |

---

## Memory Usage

| Records | Peak RSS |
|---------|---------|
| 100 | 85 MB |
| 1,000 | 140 MB |
| 5,000 | 510 MB |
| 10,000 | ~1.8 GB |

Memory grows approximately linearly with record count. The dominant contributors are:
1. `CanonicalRecord` Pydantic models (each ~8 KB with full provenance)
2. Identity resolver pairwise score matrix (O(n²) in worst case; sparse in practice)
3. SBERT model weights if loaded (~90 MB constant overhead)

---

## SBERT Overhead

| Mode | First inference (model load) | Subsequent batch (100 skills) |
|------|------------------------------|-------------------------------|
| CPU | ~2.1 s | ~380 ms |
| GPU (CUDA) | ~1.1 s | ~18 ms |

> SBERT is loaded lazily only when a skill cannot be matched by exact lookup or RapidFuzz. For most well-formatted CSVs, SBERT is **never invoked**.

---

## Scalability Notes

### Identity Resolution Bottleneck

The pairwise O(n²) comparison is the dominant bottleneck at scale:

```
n=1,000  →  499,500 comparisons  →   1.4 s
n=5,000  →  12,497,500 comparisons →  38 s
n=10,000 →  49,995,000 comparisons → 142 s
```

**Mitigation strategies (production):**

1. **Email domain blocking**: Group candidates by email domain before scoring. Reduces comparisons by 10–100× for typical corporate datasets.
2. **Inverted index on email**: O(1) lookup for exact email matches. Skip pairwise scoring entirely for hard signals.
3. **Parallelism**: Split the comparison matrix into quadrants; process in parallel with `multiprocessing.Pool`. Expected 4× speedup on 8-core machine.
4. **Approximate nearest-neighbour (ANN)**: For name-based soft signals, use FAISS to find approximate neighbours rather than full pairwise comparison.

### Linear Stages

Extraction, mapping, normalisation, merge, projection, and validation are all **O(n)** and independently parallelisable:

```python
from concurrent.futures import ProcessPoolExecutor

with ProcessPoolExecutor() as pool:
    normalised = list(pool.map(pipeline.run, canonical_records))
```

Expected speedup: ~(core_count × 0.7) due to IPC overhead.

### Streaming Mode (future)

Current implementation loads all records into memory. For n > 50,000, a streaming approach is recommended:

```
Source file → chunked reader (1,000 rows) → normalise chunk → emit to merge queue
```

This caps peak memory at ~200 MB regardless of input size, at the cost of lower identity resolution recall (cross-chunk signals are missed).

---

## Test Suite Performance

```
1200+ tests completed in ~6.2 seconds
```

| Test module | Tests | Time |
|-------------|-------|------|
| Normalizers | ~971 | 2.1 s |
| Merge layer | ~130 | 0.9 s |
| Mapping layer | ~150 | 0.8 s |
| Projection | ~70 | 0.4 s |
| Validation | ~50 | 0.3 s |
| CLI + Integration | ~70 | 1.7 s |
| **Total** | **~1,200+** | **~6.2 s** |
