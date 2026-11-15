# Stage 4.2.1 Git Manifest & Integrity Verification

**Project**: `Kritik35/flying-rag-mcp`  
**Date**: 2026-11-15  
**Baseline Anchor**: `9b498bf5dc09e964d035049a53582d52f13cdc95`  
**Snapshot Anchor**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)  
**Development Branch**: `audit/stage4-2-verification`  
**Remote**: `origin` (`git@github.com:Kritik35/flying-rag-mcp.git`)  

---

## 1. File Allowlist & Modification Roster

| File Path | Change Type | Purpose | Blocker Addressed |
|:---|:---:|:---|:---:|
| `storage/vector_store.py` | Modified | Truncation cap fix (`limit(101)`), NaN/Inf validation, preflight duplicate/finite/dimension checks, snapshot rollback on `table.add` crash | Blocker 1, Blocker 2, P0-02 |
| `indexer.py` | Modified | Defer `delete_file` and metadata update post-commit, quarantine status on failure | Blocker P0-02 |
| `evidence_gate/evidence_gate.py` | Modified | SQLite URI read-only (`mode=ro`, `PRAGMA query_only=ON`), `query_applicability` (`NON_NORMATIVE_QUERY`, `DOCUMENT_OVERVIEW`), non-normative query abstention | Blocker 5, Blocker 6, P1-07 |
| `evidence_gate/stitcher.py` | Modified | Formula check anti-bypass hardening (ignoring `где Ln = ...` preambles), formula regex restricted to true formula IDs (`А.3`, standalone numbers) excluding prose words in parentheses, inline formula check | Blocker 7, P1-08 |
| `rag_server/shadow_eig.py` | Modified | Real bootstrap via `_get_shadow_adapter()`, canonical path comparison (`_canonical_path`), path sanitization (`_sanitize_path`), separate wall/cpu latency, log rotation (10MB limit), `UNVERIFIABLE_PROVENANCE` / `RETRIEVAL_SOURCE_MISMATCH` divergence | Blocker 3, Blocker 4, P1-06, P1-09, P1-10 |
| `rag_server/server.py` | Modified | `config_loader.load_config` import fix, `FLYING_RAG_METADATA_DB` and config relative path resolution, fail-visible warning on missing DB, strict env var precedence (`FLYING_RAG_SHADOW_EIG=0` forces off) | Blocker 8, P0-01, P1-09 |
| `tests/test_p0_chunk_cache.py` | Modified | 8 unit tests covering P0 chunk_id preservation, all-row conflict detection, preflight embedding checks, NaN/Inf rejection, DummyChunk metadata safety | Blocker 1, Blocker 2 |
| `tests/test_upsert_atomic_recovery.py` | Added | 5 unit and fault-injection tests verifying preflight duplicate/finite/dimension validation and snapshot rollback | Blocker P0-02 |
| `tests/test_stitcher_provenance.py` | Modified | 13 unit tests covering boundary extraction, multi-chunk stitching, zero-overlap broken chain rejection, coordinate system slice invariants | Blocker 7 |
| `tests/test_evidence_gate.py` | Modified | 12 unit tests covering document resolution, multi-edition ambiguity, topic alignment, read-only SQLite URI enforcement, non-normative query abstention | Blocker 5, Blocker 6, P1-07 |
| `tests/test_shadow_eig.py` | Modified | 11 unit tests covering passive zero-mutation, parent_id mismatch, colliding basenames, unverifiable provenance, latency metrics, fail-open logging | Blocker 3, Blocker 4, P1-06, P1-09, P1-10 |
| `tests/test_mcp_shadow_integration.py` | Modified | Real bootstrap integration tests via `_get_shadow_adapter()` without mock bypass, strict env precedence, byte-for-byte serialized MCP output equality | Blocker 8, P0-01, P1-09 |
| `tests/test_ooxml_fidelity.py` | Added | 3 independent fixture tests proving OOXML `<m:oMath>` omission at parser ingestion and detection as `FORMULA_MISSING` | Blocker P1-05 |
| `scripts/run_stage4_2_acceptance.py` | Modified | Unified acceptance test runner for Gates G0–G8, testing all 98 checks with individual test_ids and postflight DB integrity | Blocker P1-03, P1-04, P1-12 |
| `reports/stage4_2_gate_results.json` | Modified | Machine-readable gate evaluation records for Gates G0–G8 | Deliverable |
| `reports/stage4_2_test_matrix.json` | Modified | Complete 98-test execution matrix with individual latencies and outcomes | Deliverable |
| `reports/stage4_2_source_fidelity.json` | Modified | Production read-only evaluation for SP 7 clause 6.4, SP 60 formula (А.3), and synthetic OOXML fixture | Deliverable |
| `reports/stage4_2_shadow_metrics.json` | Modified | Performance percentiles (wall and CPU latency), divergence taxonomy, and latency discrepancy reconciliation | Deliverable |
| `reports/STAGE4_2_INDEPENDENT_ACCEPTANCE.md` | Modified | Comprehensive gate-by-gate audit and acceptance report | Deliverable |
| `reports/STAGE4_2_OPEN_RISKS.md` | Modified | Residual risks, mitigation strategies, and fail-safe rollback procedures | Deliverable |
| `reports/stage4_2_git_manifest.md` | Modified | Git manifest, commit hashes, file allowlist, and privacy certification | Deliverable |
| `.gitignore` | Modified | Added `logs/` ignore | Hygiene |

---

## 2. Privacy & Security Certification
- **Zero Secrets / Tokens**: No API keys, credentials, or private access tokens are contained in any added or modified files.
- **Zero Raw Corporate Data**: No customer data, proprietary corporate documents, or unredacted raw databases are committed.
- **Path Sanitization**: All production and corpus paths are sanitized using `[CORPUS]/...`, `[DRIVE]/...`, and `/Users/[USER]/...`.
- **Read-Only Guarantee**: Production databases and configuration files remain 100% untouched (`git status --porcelain` empty).
