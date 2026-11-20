# FlyingRAG — Stage 4.2.3: Independent Safety Acceptance & Reviewer Blocker Resolution Report

**Project**: `Kritik35/flying-rag-mcp`
**Date**: 2026-11-15
**Baseline Anchor**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (historical audit anchor)
**Snapshot Branch**: `audit/stage4-1-snapshot-20261115` (`4f43949aa9c03e7ccd99d1ce072d954f18f8c786`) — **STRICTLY IMMUTABLE**
**Verification Branch**: `audit/stage4-2-verification`
**Run ID**: `stage4_2_2_20261115_213530_e126f1cc`
**Tested Code Commit SHA**: `e126f1cc9064abb455cd5e065d726eb168388fa2`
**Git Tree SHA**: `99c6a5a0dd98ecbe713956b8b19802c93cec06eb`
**Worktree Location**: `<AUDIT_DIR>/worktree_stage3`
**Production Repository**: `<PRODUCTION_DIR>/flying-rag-mcp` (strictly READ-ONLY)
**Operating Mode**: STRICT OFFLINE FOR TESTS / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO MERGE

---

## Executive Summary & Acceptance Matrix

Stage 4.2.3 provides a rigorous, verified resolution of all 7 blocking issues (**CR-01 through CR-07**) raised during the independent audit of Stage 4.2.2. All code, test, and documentation improvements were committed in Phase A (`e126f1cc`), followed by an independent post-commit acceptance test pass executing all 9 Gates (G0 through G8) and recording the exact commit SHA and Git tree SHA across all machine-readable JSON artifacts (`stage4_2_gate_results.json`, `stage4_2_test_matrix.json`, `stage4_2_source_fidelity.json`, `stage4_2_shadow_metrics.json`).

| Gate ID | Gate Name | Scope & Verified Invariants | Status | Tests Executed | Passed / Failed |
|:---|:---|:---|:---:|:---:|:---:|
| **G0** | Environment Isolation & Git Anchors | Independent worktree, clean production repo verification (`git status --porcelain`), real `git merge-base --is-ancestor 4f43949 HEAD` verification, immutable remote ref tracking check (`origin/audit/stage4-1-snapshot-20261115`), pre/post SQLite fingerprinting with documented 64KB sample + WAL stats | **PASSED** | 6 | 6 / 0 |
| **G1** | P0 Indexer Fix, Upsert Atomicity & Vector Cache Integrity | No chunk_id overwrite, callback type-safety, all-row conflict detection, preflight duplicate/finite/dimension validation, deterministic document order, LanceDB partial add cleanup + count verification on rollback, multi-doc delete recovery without silent pass, atomic SQLite parent chunk & cache replacement in single transaction, quarantine state recovery without `--force` | **PASSED** | 27 | 27 / 0 |
| **G2** | Multi-chunk Sequential Stitching | Dynamic overlap, zero-overlap broken chain rejection (`BROKEN_CHAIN_NO_OVERLAP`), explicit `parent_chunk_unicode_codepoints` coordinate system, mathematical slice invariant | **PASSED** | 9 | 9 / 0 |
| **G3** | Formula & Mathematical Integrity | Inline formula citation check, rejection of unrelated scalar variable assignments (`B = 5`), formula status renamed to `FORMULA_TEXT_PRESENT_UNVERIFIED` | **PASSED** | 5 | 5 / 0 |
| **G4** | Topic Alignment & False Refusal Prevention | Strict domain scoping for SP 7 / SP 1, broad non-normative query abstention (`NON_NORMATIVE_QUERY` -> `NOT_APPLICABLE`), document overview query abstention (`DOCUMENT_OVERVIEW` -> `NOT_APPLICABLE`) | **PASSED** | 12 | 12 / 0 |
| **G5** | Document Resolution & Read-only SQLite URI | Exact token-boundary matching (SP 7 vs SP 70), multi-edition ambiguity refusal (`AMBIGUOUS_SOURCE`), SQLite read-only URI (`mode=ro` with `PRAGMA query_only = ON;`) | **PASSED** | 4 | 4 / 0 |
| **G6** | Shadow Adapter Safety, Congruence & MCP Isolation | Async non-blocking dispatch via `observe_async()`, bounded queue (max 100) with drop counting, bounded executor shutdown with timeout, live environment variable deactivation (`FLYING_RAG_SHADOW_EIG=0`), pairwise hit matching (CR-07), default exclusion of query text (CR-03), hardened path sanitization (UNC, quotes, Russian folders, dynamic user), byte-for-byte serialized output equality | **PASSED** | 22 | 22 / 0 |
| **G7** | Adversarial Matrix & Latency Benchmarks | Full 25 adversarial query evaluation across 8 error categories, separate wall-clock (`36.25 ms`) and CPU (`35.00 ms`) latency reporting | **PASSED** | 25 | 25 / 0 |
| **G8** | Production Source Fidelity & OOXML Audit | Honest distinction of `INDEX_SLICE_VERIFIED` from `SOURCE_NOT_VERIFIED (BLOCKED_BY_SOURCE_UNAVAILABLE)` when drive `H:` is offline; synthetic OOXML OMML fixture test proving `<m:oMath>` omission at ingestion | **PASSED** | 5 | 5 / 0 |
| **Post** | Database Postflight Integrity | Pre- and post-test metadata.db fingerprint bit-for-bit identity check (size, mtime, sample SHA256, 0-byte WAL identity) | **PASSED** | 1 | 1 / 0 |
| **OVERALL** | **Stage 4.2.3 Acceptance** | **All 7 reviewer blockers (CR-01–CR-07) resolved; 100% test pass rate (116/116); production database untouched** | **PASSED** | **116** | **116 / 0** |

---

## Detailed Reviewer Blocker Resolutions (CR-01 through CR-07)

### CR-01 (P0): LanceDB Upsert Partial Add Cleanup, Count Verification & Multi-Doc Delete Recovery
- **Issue**: In `storage/vector_store.py:upsert_chunks()`, if `table.add(records)` failed, `table.add(backup_rows)` was executed directly without purging partially committed records from the failed add attempt, creating duplicate or orphaned records. Furthermore, post-rollback row count was never verified against the pre-delete snapshot. Finally, multi-doc delete failure swallowed exceptions via `except Exception: pass`.
- **Resolution**:
  1. **Purge Partial Records**: On `table.add(records)` failure, before restoring backup rows, `table.delete(f"doc_id = '{safe_did}'")` is executed for all document IDs in the batch to cleanly purge any partially written rows.
  2. **Backup Restoration**: Backup rows from the verified pre-delete snapshot are inserted back via `table.add(backup_rows)`. If restoration fails, `RuntimeError("CRITICAL: Vector upsert failed AND rollback restoration failed... State is unverified.")` is raised.
  3. **Post-Rollback Verification**: The table is queried for all `doc_ids` to verify that the active row count strictly equals `len(backup_rows)`. Any count mismatch or query error immediately raises a critical unverified state exception.
  4. **Multi-Doc Delete Hardening**: In multi-doc batches, if doc $N$ fails deletion, already-deleted records from docs $1..N-1$ are restored. If this restore fails, it no longer passes silently but raises `RuntimeError("CRITICAL: Deletion failed ... AND rollback of previously deleted documents failed ... Document state is uncertain.")`.
  5. **Deterministic Batch Ordering**: Replaced non-deterministic `doc_ids = list({c.doc_id for c in chunks})` with order-preserving `doc_ids = list(dict.fromkeys(c.doc_id for c in chunks))`.
  6. **Unit Tests**: Added 5 fault-injection tests in `tests/test_upsert_atomic_recovery.py`:
     - `test_rollback_failure_raises_critical_unverified_error`
     - `test_rollback_count_mismatch_raises_critical_unverified_error`
     - `test_multi_doc_delete_failure_restores_prior_deleted`
     - `test_multi_doc_delete_failure_with_rollback_failure_raises_critical`
     - `test_real_lancedb_rollback_cleans_partial_records`

### CR-02 (P0): Single SQLite Transaction for Parent Chunks & Vector Cache Replacement
- **Issue**: `indexer.py` previously executed `delete_file(meta_path, str(fp), preserve_rules=True)` followed by separate per-chunk autocommit calls `save_parent_chunk()` and `save_cached_chunk()` inside loops. A mid-loop failure or crash left parent chunks deleted or partially inserted, and cache partially updated.
- **Resolution**:
  1. **New Atomic Function**: Implemented `storage.metadata_db:atomic_replace_parent_chunks_and_cache(db_path, source_path, parent_records, cache_records, doc_id=None)` wrapping all parent chunk deletions, parent chunk bulk insertions (`executemany`), cache updates, and corpus generation bumps into a single SQLite transaction with WAL and foreign key enforcement.
  2. **Atomic Indexer Integration**: Updated `indexer.py` to prepare all `parent_records` and `cache_records` in memory and invoke `atomic_replace_parent_chunks_and_cache()` once. If any error occurs, SQLite automatically rolls back the entire transaction.
  3. **Fault-Injection Test**: Added `test_atomic_parent_chunks_rollback_on_failure` and `test_atomic_parent_chunks_and_cache_success` in `tests/test_indexer_quarantine_reprocess.py` using SQLite triggers (`BEFORE INSERT ON chunk_cache BEGIN SELECT RAISE(ABORT, ...); END;`) proving that mid-process failure leaves prior state completely untouched.

### CR-03 (P1/Security): Privacy Default Policy & Path/Text Sanitization Hardening
- **Issue**: Telemetry logged `query_sanitized` containing scrubbed query text, which still posed privacy risks. Path regex did not handle Windows quoted paths with spaces, UNC network paths (`<UNC_SHARE>`), and Cyrillic directory names with spaces.
- **Resolution**:
  1. **Default Privacy Policy**: `query_sanitized` is now omitted by default from all telemetry events. Only `query_hash` (first 16 hex chars) and `query_length` are recorded.
  2. **Explicit Opt-In**: Logging sanitized query text requires explicit configuration via `FLYING_RAG_SHADOW_LOG_QUERY_TEXT=1`.
  3. **Regex Hardening**: Hardened `_sanitize_path()` and `_sanitize_text()` to handle UNC paths (`<UNC_SHARE>` -> `[UNC_SHARE]/...`), quoted paths with spaces (`"<PATH_REDACTED>/name with spaces\..."` -> `"[DIR]/..."`), Cyrillic folders with spaces (`Мой диск`, `Архив документов`), and dynamic user redaction via `getpass.getuser()`.
  4. **Verified by Unit Tests**: Added `test_shadow_adapter_privacy_sanitization` and `test_sanitize_path_and_text_robustness` in `tests/test_shadow_eig.py`.

### CR-04 (P1): Bounded Executor Shutdown with Explicit Timeout
- **Issue**: `ShadowEvidenceIntegrityGate.shutdown(wait=wait)` lacked a timeout parameter on Python 3.9+ thread pool executor shutdown, risking hangs during process termination if background tasks stalled.
- **Resolution**:
  1. Added `timeout: float | None = 5.0` to `shutdown()`.
  2. Utilized `self._executor.shutdown(wait=wait, timeout=timeout, cancel_futures=True)` with proper exception handling for `TimeoutError`.
  3. Verified in `tests/test_shadow_eig.py`.

### CR-05 (P1): Test Shadow Adapter Async Non-Blocking Divergence Assertion
- **Issue**: `test_shadow_adapter_async_non_blocking` imported `EvidenceAssessmentResult` (which did not exist), causing the background task to swallow a `ModuleNotFoundError` and log `SHADOW_ERROR`. The test passed only because it never asserted on divergence.
- **Resolution**:
  1. Updated test to use real `evidence_gate.evidence_gate:EvidenceGateResult`.
  2. Added explicit assertions:
     - `self.assertNotEqual(last_event.get("divergence"), "SHADOW_ERROR")`
     - `self.assertEqual(last_event.get("divergence"), "CONGRUENT")`
     - `self.assertEqual(self.adapter.error_count, 0)`
     - `self.assertGreaterEqual(self.adapter.processed_count, 1)`

### CR-06 (P1): Cryptographic Binding of Test Artifacts & Two-Phase Commit
- **Issue**: Acceptance runner previously recorded `git_head_sha` and `git_tree_sha` before committing test fixes, resulting in reports attesting a commit SHA that did not actually contain the changes.
- **Resolution**:
  1. **Two-Phase Commit Protocol**:
     - Phase A: All code, test, and documentation fixes are staged and committed (`git commit -m "fix(stage4.2.3): resolve reviewer blockers CR-01-CR-07"`).
     - Phase B: Acceptance runner executes on the committed checkout where `HEAD` is the exact commit SHA (`e126f1cc`).
     - Phase C: Final JSON and markdown report artifacts are committed (`git commit -m "docs(stage4.2.3): publish verified acceptance artifacts for commit <SHA>"`).
  2. **JSON Attestation Fields**: `stage4_2_gate_results.json`, `stage4_2_test_matrix.json`, `stage4_2_source_fidelity.json`, and `stage4_2_shadow_metrics.json` all explicitly record `tested_commit_sha`, `tested_tree_sha`, `working_tree_sha`, and `working_tree_clean`.

### CR-07 (P1): Pairwise Hit Verification for True Congruence
- **Issue**: `shadow_eig.py` compared `retrieved_sources.intersection(...)` and `retrieved_pids.intersection(...)` independently. If Hit 1 had matching `parent_id` from Doc A, and Hit 2 had Doc B with matching source path from Doc B, the query was falsely classified as `CONGRUENT`.
- **Resolution**:
  1. Replaced independent set intersection with pairwise hit inspection:
     - Iterates through `retrieval_results` and requires `r_pid in eig_pids` AND `r_src == eig_canonical_source` on the *same individual retrieval hit*.
     - If both conditions are satisfied on at least one hit, `CONGRUENT` is assigned.
     - If parent IDs match on one hit and sources match on another hit without a single hit satisfying both, the divergence is correctly classified as `RETRIEVAL_PARENT_ID_MISMATCH` or `RETRIEVAL_SOURCE_MISMATCH`.
  2. Added unit test `test_shadow_adapter_cross_hit_false_congruence_rejected` in `tests/test_shadow_eig.py`.

---

## Performance Profile (Gate G7)

Measured across the 25 adversarial queries in `run_id=stage4_2_2_20261115_213530_e126f1cc`:

- **Sample Count**: 25 queries
- **Mean Wall-Clock Latency**: **`36.25 ms`**
- **Mean CPU Latency**: **`35.00 ms`**
- **Median ($p_{50}$)**: **`31.29 ms`**
- **95th Percentile ($p_{95}$)**: **`53.02 ms`**
- **99th Percentile ($p_{99}$)**: **`105.11 ms`**
- **Minimum Latency**: **`19.53 ms`**
- **Maximum Latency**: **`121.52 ms`**
- **Total Wall-Clock Time**: **`906.32 ms`**

---

## Production Invariants Verification

1. **Production Read-Only Invariant**: Production repository `<PRODUCTION_DIR>/flying-rag-mcp` is 100% clean (`git status --porcelain` empty) at commit `9b498bf5dc09e964d035049a53582d52f13cdc95`.
2. **Snapshot Immutability**: Historical snapshot commit `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` on `audit/stage4-1-snapshot-20261115` has not been modified or force-pushed.
3. **Database Integrity**: Pre- and post-test metadata.db fingerprints are identical (`size_bytes=1,485,103,104`, `sample_sha256=9d1c73641bf...`, `wal_size_bytes=0`).
4. **Byte-for-Byte MCP Output Equality**: MCP serialized JSON output with shadow enabled is bit-for-bit identical to output with shadow disabled.

---

## Final Acceptance Verdict

**Verdict**: **GO FOR CONTROLLED OPT-IN SHADOW TRIAL**
- All 7 reviewer blockers (CR-01–CR-07) and prior blockers (B1–B10) are 100% resolved with verifiable, comprehensive unit, fault-injection, and integration test coverage.
- All 116 acceptance checks passed (100.0% pass rate).
- Two-phase commit ensures 100% cryptographic binding between the tested code SHA (`e126f1cc9064abb455cd5e065d726eb168388fa2`) and the published JSON artifacts.
- Production active evidence filtering remains strictly disabled until shadow divergence telemetry is audited.
