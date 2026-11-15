# Stage 4.2 Git Manifest & Integrity Verification

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
| `storage/vector_store.py` | Modified | Truncation cap fix (`limit(101)`), NaN/Inf validation, preflight embedding check in `upsert_chunks()` | Blocker 1, Blocker 2 |
| `evidence_gate/evidence_gate.py` | Modified | SQLite URI read-only connection (`mode=ro`, `PRAGMA query_only = ON;`), topic alignment fixes (`TOPIC_NOT_EVALUATED`, `TOPIC_UNCERTAIN`), strict domain scoping | Blocker 5, Blocker 6 |
| `evidence_gate/stitcher.py` | Modified | Formula check anti-bypass hardening (ignoring `где Ln = ...` preambles), explicit `parent_chunk_unicode_codepoints` coordinates, slice invariant check | Blocker 7 |
| `rag_server/shadow_eig.py` | Modified | Complete fail-open exception isolation, error counters, hardened congruence logic (exact parent_id & source match required), divergence taxonomy | Blocker 3, Blocker 4 |
| `rag_server/server.py` | Modified | Direct MCP hook to shadow adapter in `_dispatch()`, fail-safe invocation | Blocker 8 |
| `rag_server/tools.py` | Modified | Safe fallback attribute access on provider mock objects | Blocker 8 |
| `tests/test_p0_chunk_cache.py` | Modified | 8 unit tests covering P0 chunk_id preservation, all-row conflict detection, preflight embedding checks, NaN/Inf rejection | Blocker 1, Blocker 2 |
| `tests/test_stitcher_provenance.py` | Modified | 8 unit tests covering boundary extraction, multi-chunk stitching, zero-overlap broken chain rejection, coordinate system slice invariants | Blocker 7 |
| `tests/test_evidence_gate.py` | Modified | 10 unit tests covering document resolution, multi-edition ambiguity, topic alignment, read-only SQLite URI enforcement | Blocker 5, Blocker 6 |
| `tests/test_shadow_eig.py` | Modified | 6 unit tests covering passive zero-mutation, parent_id mismatch detection, congruence verification, fail-open error logging | Blocker 3, Blocker 4 |
| `tests/test_mcp_shadow_integration.py` | Added | End-to-end integration test proving byte-for-byte identical MCP serialized output with shadow enabled vs disabled | Blocker 8 |
| `scripts/run_stage4_2_acceptance.py` | Added | Unified acceptance test runner for Gates G0–G8 | Blocker 9 |
| `reports/stage4_2_gate_results.json` | Added | Machine-readable gate evaluation records for Gates G0–G8 | Deliverable |
| `reports/stage4_2_test_matrix.json` | Added | Complete 60-test execution matrix with individual latencies and outcomes | Deliverable |
| `reports/stage4_2_source_fidelity.json` | Added | Production read-only evaluation for SP 7 clause 6.4 and SP 60 formula (А.3) | Deliverable |
| `reports/stage4_2_shadow_metrics.json` | Added | Performance percentiles, divergence taxonomy, and latency discrepancy reconciliation | Deliverable |
| `reports/STAGE4_2_INDEPENDENT_ACCEPTANCE.md` | Added | Comprehensive gate-by-gate audit and acceptance report | Deliverable |
| `reports/STAGE4_2_OPEN_RISKS.md` | Added | Residual risks, mitigation strategies, and fail-safe rollback procedures | Deliverable |
| `reports/stage4_2_git_manifest.md` | Added | Git manifest, commit hashes, file allowlist, and privacy certification | Deliverable |

---

## 2. Privacy & Security Certification
- **Zero Secrets / Tokens**: No API keys, credentials, or private access tokens are contained in any added or modified files.
- **Zero Raw Corporate Data**: No customer data, proprietary corporate documents, or unredacted raw databases are committed.
- **Path Sanitization**: All production paths are referenced using abstract or standard read-only identifiers.
- **Read-Only Guarantee**: Production databases and configuration files remain 100% untouched.
