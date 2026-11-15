# FlyingRAG — Stage 4.2: Independent Safety Acceptance & Source-Fidelity Audit Report

**Project**: `Kritik35/flying-rag-mcp`
**Date**: 2026-11-15
**Baseline Anchor**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (historical audit anchor)
**Snapshot Branch**: `audit/stage4-1-snapshot-20261115` (`4f43949aa9c03e7ccd99d1ce072d954f18f8c786`)
**Verification Branch**: `audit/stage4-2-verification`
**Worktree Location**: `C:\Acer_System_Audit\rag_quality_ab_20261113\worktree_stage3`
**Production Repository**: `C:\RAG_Acer\repos\flying-rag-mcp` (strictly READ-ONLY)
**Operating Mode**: STRICT OFFLINE FOR TESTS / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO MERGE

---

## Executive Summary & Acceptance Matrix

Stage 4.2 performed a rigorous, independent safety acceptance audit of the Stage 4.1 Evidence Integrity Gate (EIG), P0 chunk cache fix, and shadow adapter. All 9 identified blockers from the Code Review Addendum were formally resolved and verified with dedicated test coverage. Discrepancies between Stage 4.1 narrative tables and machine-readable artifacts have been mathematically reconciled.

| Gate ID | Gate Name | Scope & Requirement | Status | Tests Executed | Passed / Failed |
|:---|:---|:---|:---:|:---:|:---:|
| **G0** | Environment Isolation & Git Anchors | Independent worktree, read-only production repo, commit anchor lineage | **PASSED** | 1 | 1 / 0 |
| **G1** | P0 Indexer Fix & Vector Cache Integrity | No chunk_id overwrite, callback type-safety, all-row conflict detection, preflight embedding completeness, NaN/Inf rejection, missing text hash rejection | **PASSED** | 8 | 8 / 0 |
| **G2** | Multi-chunk Sequential Stitching | Dynamic overlap, zero-overlap broken chain rejection (`BROKEN_CHAIN_NO_OVERLAP`), explicit `parent_chunk_unicode_codepoints` coordinate system, mathematical slice invariant | **PASSED** | 8 | 8 / 0 |
| **G3** | Formula & Mathematical Integrity | Formula extraction, anti-bypass verification (excluding `где Ln = ...` explanations from formula equation validation), real corpus formula omission detection | **PASSED** | 1 | 1 / 0 |
| **G4** | Topic Alignment & Evidence Status Synthesis | Strict domain scoping for SP 7 / SP 1, absent query topic returns `TOPIC_NOT_EVALUATED` (not false assertion of match), unconfirmed lexical tokens return `TOPIC_UNCERTAIN` (avoiding false refusal) | **PASSED** | 10 | 10 / 0 |
| **G5** | Document Resolution & Read-only SQLite URI | Exact token-boundary matching (SP 7 vs SP 70), multi-edition ambiguity refusal (`AMBIGUOUS_SOURCE`), SQLite read-only URI (`mode=ro` with `PRAGMA query_only = ON;`) | **PASSED** | 1 | 1 / 0 |
| **G6** | Shadow Adapter Safety & MCP Isolation | Fail-open exception isolation, error counters, hardened congruence (exact parent_id & source match required), byte-for-byte identical MCP serialized output | **PASSED** | 8 | 8 / 0 |
| **G7** | Adversarial Matrix & Latency Benchmarks | Full 25 adversarial query evaluation across 8 error categories, latency percentiles (mean, p50, p95, p99, min, max) | **PASSED** | 25 | 25 / 0 |
| **G8** | Production Source Fidelity & OOXML Audit | Production `metadata.db` read-only evaluation: SP 7 clause 6.4 multi-chunk stitch verified; SP 60 formula (А.3) detected as `FORMULA_MISSING` / `EVIDENCE_PARTIAL`; OOXML OMML omission diagnosed | **PASSED** | 1 | 1 / 0 |
| **OVERALL** | **Full Stage 4.2 Acceptance** | **All acceptance criteria met without regressions** | **PASSED** | **63** | **63 / 0** |

---

## Part 1: Independent Discrepancy & Contradiction Audit

### Audit 1: Latency Discrepancy Reconciliation
In the Stage 4.1 report, three conflicting latency figures appeared:
1. `82.02 ms` in the JSON summary header of `04_evidence_gate/eig_adversarial_tests.json`.
2. `72.23 ms` as the true arithmetic mean of the 25 `elapsed_ms` values in the same JSON file.
3. `64.62 ms` as the sum/mean of individual rows in the markdown table of `STAGE4_1_SAFETY_GATE.md` (1615.38 ms / 25).

**Independent Mathematical Diagnosis**:
- An exact calculation of the 25 entries in `04_evidence_gate/eig_adversarial_tests.json` yields a sum of `1805.65 ms`, which divided by 25 equals **`72.226 ms`**.
- Three queries in the adversarial test set are fast-refusals (invalid edition / absent doc / unparseable query) that exit in `0.05 ms` without querying SQLite.
- The remaining 22 queries that actually execute SQLite chunk searches sum to `1805.50 ms`. The arithmetic mean of these 22 queries is **`82.068 ms`** (which was recorded as `82.02 ms` in an earlier test iteration). The author of the preliminary script computed `avg_cpu_latency_ms` by dividing only by the count of SQLite-active queries ($N=22$), while labeling it as the overall average.
- The markdown table in `STAGE4_1_SAFETY_GATE.md` was copied from an earlier benchmark run where total latency was `1615.38 ms` (mean `64.62 ms`).
- **Stage 4.2 Benchmark Result (Measured on Live 25-Query Suite)**:
  - Mean CPU Latency: **`88.13 ms`**
  - Median ($p_{50}$): **`95.66 ms`**
  - $p_{95}$: **`116.32 ms`**
  - $p_{99}$: **`123.63 ms`**
  - Min: **`0.05 ms`** (instant syntax/edition rejection)
  - Max: **`124.41 ms`**
  - Total Wall-Clock Time: **`2203.35 ms`**

### Audit 2: P0 Real Callback Validation Artifact vs Narrative Table
In `STAGE4_1_SAFETY_GATE.md`, a table listed 5 tests for P0 validation, including a test named `mutated_text_rejected`. However, the artifact `04_evidence_gate/p0_real_callback_validation.json` contained only 4 tests:
1. `real_callback_legitimate_reuse` (`passed: true`)
2. `incompatible_callback_no_bypass` (`passed: true`)
3. `all_rows_conflict_detection` (`passed: true`)
4. `delete_failure_raises_runtime_error` (`passed: true`)

**Root Cause**: The test `mutated_text_rejected` was present in a draft script iteration but was omitted from the specific JSON generator run that wrote `p0_real_callback_validation.json`. The markdown report author pasted an earlier draft table without verifying parity against the emitted JSON.

**Stage 4.2 Resolution**:
In `tests/test_p0_chunk_cache.py`, 8 exhaustive unit tests were implemented and verified, explicitly testing all 5 original scenarios plus preflight missing embedding validation, non-finite vector rejection, and excessive collision caps.

### Audit 3: OOXML Source Fidelity Audit in `stitcher.py` and Real Normative Documents
An analysis was conducted on how formulas in DOCX files (such as SP 60.13330.2020 formula (А.3) and SP 7.13130.2013 clause 6.4) are processed from original file to index to EIG:
1. **Extraction Pipeline Limitation**: Standard `python-docx` extraction traverses `paragraph.text`. In Office Open XML (OOXML), mathematical equations are stored in `<m:oMath>` (OMML) or embedded MathType OLE binary objects. Because standard paragraph readers ignore XML tags outside `w:t`, the equation text (e.g. $Q = ...$) is omitted, leaving an empty line followed by the paragraph containing the label `(А.3)`.
2. **EIG Hardened Integrity Check**: In Stage 4.1, checking $\pm 100$ characters for `=` had an anti-bypass flaw: if the variable explanation section right after the label contained `где Ln = ...`, the presence of `=` in `где Ln = ...` could fool a naive search into thinking the formula was present.
3. **Stage 4.2 Hardening**: `stitcher.check_formula_integrity()` was refactored to inspect the line of the label and immediately adjacent lines, while strictly ignoring lines beginning with explanatory preambles (`где`, `в которой`, `здесь`). When evaluated on SP 60.13330.2020 formula (А.3), EIG correctly reports `formula_integrity = FORMULA_MISSING` and demotes the evidence to `EVIDENCE_PARTIAL`, preventing silent false-certifications.

---

## Part 2: Code Review Addendum — Blocker Resolutions

### Blocker 1: Vector Cache Ambiguity & Truncation (`storage/vector_store.py`)
- **Vulnerability**: `table.search().where(...).limit(100)` truncated inspection at 100 rows. If `row_text` was absent in LanceDB, `if row_text and expected_hash:` silently skipped hash verification and returned `CACHE_VERIFIED`. Only `rows[0]` was checked for text hash and dimensionality.
- **Resolution**:
  - Replaced `limit(100)` with `limit(101)`. If `len(rows) > 100`, lookup is rejected with `CACHE_UNVERIFIED: excessive_collisions (> 100 rows)`.
  - Added finite-number verification: `np.isfinite(vec).all()` rejects NaNs or Infs.
  - Verified ALL physical rows for identical vector data (`np.allclose(atol=1e-5)`), dimensionality, and text content.
  - If `expected_hash` is requested but `row_text` is missing or empty, returns `CACHE_UNVERIFIED: missing_row_text_for_hash_verification`.

### Blocker 2: Destructive Delete-Before-Write Without Rollback (`storage/vector_store.py`, `indexer.py`)
- **Vulnerability**: `upsert_chunks()` executed `table.delete(f"doc_id = '{did}'")` before creating records. If chunks had missing embeddings, `for chunk in chunks: if emb is None: continue` silently dropped chunks, resulting in permanent data loss.
- **Resolution**:
  - Added strict preflight completeness check in `upsert_chunks()`:
    ```python
    emb_map = {e.chunk_id: e.embedding for e in embeddings if hasattr(e, "chunk_id")}
    missing = [c.chunk_id for c in chunks if c.chunk_id not in emb_map or emb_map[c.chunk_id] is None]
    if missing:
        raise ValueError(f"Preflight check failed in upsert_chunks: {len(missing)} chunk(s) missing embeddings: {missing[:5]}")
    ```
  - Preflight validates 100% embedding coverage BEFORE executing `table.delete()`. If any embedding is missing, the operation aborts with `ValueError` and vectors in LanceDB remain untouched.

### Blocker 3: Exception Isolation in Shadow Adapter (`rag_server/shadow_eig.py`)
- **Vulnerability**: `EvidenceIntegrityGate` constructor and `observe()` method had unhandled exception paths that could propagate into `server.py` and crash retrieval.
- **Resolution**:
  - Constructor wraps gate initialization in `try...except`, setting `self.gate = None` and incrementing `self.error_count` on failure.
  - `observe()` wraps entire assessment in `try...except`. On error, it increments `self.error_count`, logs a structured telemetry event with `divergence: "SHADOW_ERROR"`, and returns `None` without raising.

### Blocker 4: False Congruence in Shadow Adapter (`rag_server/shadow_eig.py`)
- **Vulnerability**: `CONGRUENT` was assigned whenever `len(retrieval_results) > 0` and EIG marked evidence as usable, even if retrieval returned chunks from a completely different clause or document.
- **Resolution**:
  - Hardened divergence logic now checks:
    ```python
    pid_overlap = retrieved_pids.intersection(eig_pids)
    source_match = (eig_source in retrieved_sources) if eig_source and retrieved_sources else True
    if pid_overlap and source_match:
        divergence = "CONGRUENT"
    else:
        divergence = "RETRIEVAL_PARENT_ID_MISMATCH"
    ```
  - Added dedicated divergence classifications: `SOURCE_AMBIGUOUS`, `EIG_NOT_APPLICABLE`, `RETRIEVAL_PARENT_ID_MISMATCH`, `CONGRUENT_REFUSAL`, and `SHADOW_ERROR`.

### Blocker 5: Unenforced Read-Only SQLite Connection (`evidence_gate/evidence_gate.py`)
- **Vulnerability**: Standard `sqlite3.connect(str(self.db_path))` opened databases in read-write mode by default.
- **Resolution**:
  - Updated `_connect()` to enforce SQLite URI read-only connection:
    ```python
    uri = f"file:{self.db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON;")
    ```
  - Verified that write operations are rejected with `OperationalError: attempt to write a readonly database`.

### Blocker 6: Topic Alignment Mismatches & False Refusals (`evidence_gate/evidence_gate.py`)
- **Vulnerability**:
  - If no query topic was specified, `verify_topic_alignment()` returned `TOPIC_MATCH`, falsely asserting topic confirmation.
  - Clause 8.1 / 8.2 domain checks were applied across all documents regardless of whether the document was SP 7.
  - Lexical mismatches triggered immediate `TOPIC_MISMATCH` and `REFUSAL_REQUIRED`.
- **Resolution**:
  - If no query topic is supplied: returns `TOPIC_NOT_EVALUATED` and permits `USABLE_FOR_ANSWER` when structural elements are verified.
  - Domain checks are strictly scoped to the target document: `("СП 7" in norm_doc) and element_id == "8.1"`.
  - General lexical token mismatches return `TOPIC_UNCERTAIN` and set status to `EVIDENCE_PARTIAL` rather than triggering a fatal refusal.

### Blocker 7: Formula Checking & Coordinate Invariants (`evidence_gate/stitcher.py`)
- **Vulnerability**:
  - Formula check searched $\pm 100$ characters for `=`.
  - Coordinates in `source_spans` were not explicitly documented or verified against stored parent chunk text.
- **Resolution**:
  - Enforced structured line inspection in `check_formula_integrity()`: checks current line, preceding line, and following non-explanation lines, ignoring variable explanations (`где Ln = ...`).
  - Added explicit coordinate fields: `parent_text_char_start`, `parent_text_char_end`, and `coordinate_system: "parent_chunk_unicode_codepoints"`.
  - Implemented `verify_source_spans_invariants()` which verifies `parent_text[start:end] == span_text` and validates SHA-256 hashes for 100% of spans.

### Blocker 8: Real MCP Dispatch Path Integration Test (`tests/test_mcp_shadow_integration.py`, `rag_server/server.py`)
- **Vulnerability**: `server.py` had no direct call to shadow adapter, and no end-to-end test proved byte-for-byte serialization immutability.
- **Resolution**:
  - Integrated `_get_shadow_adapter()` and safe observation into `server._dispatch("search_documents", ...)`.
  - Created `tests/test_mcp_shadow_integration.py` comparing serialized MCP JSON output with shadow enabled vs disabled. Verified byte-for-byte identity.
  - Verified fail-open behavior: when shadow adapter raises an exception, search results remain identical and search never crashes.

### Blocker 9: Acceptance Runner Reproducibility (`scripts/run_stage4_2_acceptance.py`)
- **Resolution**:
  - Created unified runner executing all Gates G0–G8.
  - Automatically emits structured JSON deliverables: `reports/stage4_2_gate_results.json`, `reports/stage4_2_test_matrix.json`, `reports/stage4_2_source_fidelity.json`, `reports/stage4_2_shadow_metrics.json`.

---

## Part 3: Operational Taxonomy & Semantics

To prevent conflation between retrieved index chunks, original source fidelity, and answer sufficiency, Stage 4.2 establishes clear boundaries:

### 1. Evidence Status Taxonomy (`answer_evidence_status`)
- **`USABLE_FOR_ANSWER`**: Document edition verified, structural boundaries complete (`EXACT_BOUNDARIES`), text continuity confirmed (`COMPLETE`), formula expressions verified, and topic aligns or has no restriction.
- **`EVIDENCE_PARTIAL`**: Clause was located, but structural elements are incomplete (e.g. chunk truncated at boundary, mathematical formula expression omitted in DOCX conversion, or topic alignment uncertain). The system may provide context with an explicit disclaimer.
- **`REFUSAL_REQUIRED`**: Document not in corpus, requested edition invalid/missing, multiple conflicting editions present without clarification (`AMBIGUOUS_SOURCE`), requested clause absent, broken text chain without overlap, or explicit topic mismatch.

### 2. Topic Alignment Taxonomy (`topic_alignment`)
- **`TOPIC_MATCH`**: Query topic keywords match certified clause text with stemming.
- **`TOPIC_NOT_EVALUATED`**: Query contains only structural citation (e.g. "СП 7.13130 п. 6.4") without topic restriction.
- **`TOPIC_UNCERTAIN`**: General lexical keywords did not match, but no established domain contradiction exists.
- **`TOPIC_MISMATCH`**: Known domain mismatch confirmed (e.g. asking for "подпор воздуха" in SP 7 clause 8.1). Forces refusal.

### 3. Shadow Divergence Taxonomy (`divergence`)
- **`CONGRUENT`**: Retrieval returned the exact certified parent_id and source document identified by EIG.
- **`RETRIEVAL_PARENT_ID_MISMATCH`**: Retrieval returned results, but for a different clause or chunk than certified by EIG.
- **`RETRIEVAL_WITHOUT_CERTIFIED_EVIDENCE`**: Retrieval returned chunks, but EIG determined refusal is required.
- **`EVIDENCE_EXISTS_MISSED_BY_RETRIEVAL`**: EIG certified valid evidence, but retrieval returned zero results.
- **`SOURCE_AMBIGUOUS`**: Multi-edition ambiguity prevented certification.
- **`EIG_NOT_APPLICABLE`**: Non-normative or unparseable query.
- **`SHADOW_ERROR`**: Shadow adapter encountered an exception, logged fail-visible without impacting search.

---

## Part 4: Production Read-Only Invariant Verification

During the entirety of Stage 4.2:
- The production directory `C:\RAG_Acer\repos\flying-rag-mcp` was treated strictly as READ-ONLY.
- All tests ran against isolated temporary directories or read-only SQLite URIs (`file:...mode=ro` with `PRAGMA query_only = ON;`).
- No reindexing, no vector generation, and no database writes were performed on production data.
- The snapshot commit `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` on `audit/stage4-1-snapshot-20261115` remains immutable.
- All Stage 4.2 development and acceptance artifacts reside in branch `audit/stage4-2-verification`.

---

## Acceptance Verdict

**Stage 4.2 Status**: **PASSED (ACCEPTANCE CERTIFIED)**
All 9 blockers resolved, all 63 acceptance tests passed, and all deliverables generated.
