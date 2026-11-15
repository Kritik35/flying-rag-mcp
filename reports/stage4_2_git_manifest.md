# Stage 4.2.2 Git Manifest & Integrity Verification

**Project**: `Kritik35/flying-rag-mcp`  
**Date**: 2026-11-15  
**Baseline Anchor**: `9b498bf5dc09e964d035049a53582d52f13cdc95`  
**Snapshot Anchor**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)  
**Development Branch**: `audit/stage4-2-verification`  
**Run ID**: `stage4_2_2_20261115_201431_1afb0803`  
**Remote**: `origin` (`git@github.com:Kritik35/flying-rag-mcp.git`)  

---

## 1. File Allowlist & Modification Roster

| File Path | Change Type | Purpose | Blocker Addressed |
|:---|:---:|:---|:---:|
| `storage/vector_store.py` | Modified | Truncation cap fix (`limit(101)`), NaN/Inf validation, preflight duplicate/finite/dimension checks, snapshot rollback on `table.add` crash, abort on >10,000 rows or snapshot read error, partial delete rollback | Blocker B2, P0-02 |
| `storage/metadata_db.py` | Modified | `file_changed()` returns True on quarantine/failed/partial status to allow automatic reprocessing | Blocker B3 |
| `indexer.py` | Modified | Defer `delete_file` post-commit, quarantine status preserves previous sha256 | Blocker B3, P0-02 |
| `evidence_gate/evidence_gate.py` | Modified | SQLite URI read-only (`mode=ro`, `PRAGMA query_only=ON`), `query_applicability` (`NON_NORMATIVE_QUERY`, `DOCUMENT_OVERVIEW`), path sanitization | Blocker B4, P1-07 |
| `evidence_gate/stitcher.py` | Modified | Renamed positive status to `FORMULA_TEXT_PRESENT_UNVERIFIED`, rejected scalar variable assignments (`B = 5`) as equations, formula check anti-bypass | Blocker B10, P1-08 |
| `rag_server/shadow_eig.py` | Modified | Async submission (`observe_async()`), bounded queue (max 100), drop counting, dynamic `is_active()` env check, graceful shutdown, recursive privacy sanitization (`query_hash`, `query_sanitized`) | Blocker B1, B4, B8 |
| `rag_server/server.py` | Modified | Async non-blocking shadow dispatch, `shutdown_shadow_adapter()`, dynamic check on dispatch | Blocker B1, B8 |
| `tests/test_p0_chunk_cache.py` | Modified | 8 unit tests covering P0 chunk_id preservation, all-row conflict detection, preflight embedding checks, NaN/Inf rejection | Blocker 1, Blocker 2 |
| `tests/test_upsert_atomic_recovery.py` | Modified | 8 unit/fault-injection tests verifying preflight validation, snapshot read error abort, >10,000 row abort, and real LanceDB crash recovery rollback | Blocker B2, P0-02 |
| `tests/test_indexer_quarantine_reprocess.py` | Added | 4 unit tests verifying quarantine state recovery, previous SHA preservation, and healthy file change detection | Blocker B3 |
| `tests/test_stitcher_provenance.py` | Modified | 9 unit tests covering boundary extraction, multi-chunk stitching, zero-overlap rejection, `FORMULA_TEXT_PRESENT_UNVERIFIED`, and scalar assignment rejection | Blocker B10, P1-08 |
| `tests/test_evidence_gate.py` | Modified | 12 unit tests covering document resolution, multi-edition ambiguity, topic alignment, read-only SQLite URI enforcement, non-normative query abstention | Blocker 5, Blocker 6, P1-07 |
| `tests/test_shadow_eig.py` | Modified | 15 unit tests covering passive zero-mutation, async execution, bounded queue drop, dynamic deactivation, privacy sanitization, and fail-open logging | Blocker B1, B4, B8 |
| `tests/test_mcp_shadow_integration.py` | Modified | 5 integration tests verifying real bootstrap, strict env precedence, byte-for-byte serialized MCP output equality, and async flush | Blocker B1, B8, P0-01 |
| `tests/test_ooxml_fidelity.py` | Modified | 3 fixture tests proving OOXML `<m:oMath>` omission at parser ingestion and detection as `FORMULA_MISSING`, removed hardcoded user paths | Blocker B9, P1-05 |
| `scripts/run_stage4_2_acceptance.py` | Modified | Unified acceptance test runner for Gates G0–G8, testing 107 checks, real Git ancestry verification, honest DB fingerprinting, removed user paths | Blocker B5, B6, B7, B9, B10 |
| `reports/stage4_2_gate_results.json` | Modified | Machine-readable gate evaluation records for Gates G0–G8 (107/107 PASSED) | Deliverable |
| `reports/stage4_2_test_matrix.json` | Modified | Complete 107-test execution matrix with individual latencies and outcomes | Deliverable |
| `reports/stage4_2_source_fidelity.json` | Modified | Production read-only evaluation for SP 7 clause 6.4, SP 60 formula (А.3), and synthetic OOXML fixture with honest source offline reporting | Deliverable |
| `reports/stage4_2_shadow_metrics.json` | Modified | Performance percentiles (wall and CPU latency), divergence taxonomy, and latency discrepancy reconciliation | Deliverable |
| `reports/STAGE4_2_INDEPENDENT_ACCEPTANCE.md` | Modified | Comprehensive gate-by-gate audit and acceptance report for Stage 4.2.2 | Deliverable |
| `reports/STAGE4_2_OPEN_RISKS.md` | Modified | Residual risks, mitigation strategies, and fail-safe rollback procedures | Deliverable |
| `reports/stage4_2_git_manifest.md` | Modified | Git manifest, commit hashes, file allowlist, and privacy certification | Deliverable |
| `.gitignore` | Modified | Added `logs/` ignore | Hygiene |

---

## 2. Privacy & Security Certification
- **Zero Secrets / Tokens**: No API keys, credentials, or private access tokens are contained in any added or modified files.
- **Zero Raw Corporate Data**: No customer data, proprietary corporate documents, or unredacted raw databases are committed.
- **Path Sanitization**: All production and corpus paths are sanitized using `[CORPUS]/...`, `[DRIVE]/...`, and `/Users/[USER]/...`.
- **Read-Only Guarantee**: Production databases and configuration files remain 100% untouched (`git status --porcelain` empty).
