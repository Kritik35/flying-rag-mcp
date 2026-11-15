# Stage 4.2.2: Open Risks, Mitigations & Rollback Plan

**Project**: `Kritik35/flying-rag-mcp`  
**Date**: 2026-11-15  
**Branch**: `audit/stage4-2-verification`  
**Run ID**: `stage4_2_2_20261115_201431_1afb0803`  
**Target Release**: Controlled Opt-in Shadow Trial  

---

## 1. Residual Risks & Technical Constraints

### Risk 1: OOXML Equation Omission in Upstream Ingestion
- **Description**: Standard `python-docx` ingestion skips Office Open XML (OOXML) `<m:oMath>` tags and MathType OLE binary objects during document parsing. Consequently, mathematical equation bodies are omitted from indexed parent chunks, leaving only isolated formula labels like `(А.3)`.
- **EIG Behavior**: EIG safely detects `FORMULA_MISSING` and demotes the evidence status to `EVIDENCE_PARTIAL`, preventing false certification. Proven deterministically via `tests/test_ooxml_fidelity.py`.
- **Long-term Mitigation**: When full reindexing is authorized in a future major milestone, the ingestion parser can be updated to convert OMML tags to LaTeX/Unicode before chunking. Under current NO REINDEX constraints, `EVIDENCE_PARTIAL` accurately describes the limitation.

### Risk 2: Multi-Edition Ambiguity in Mixed Corpora
- **Description**: The corporate knowledge base contains multiple revisions of regulatory standards (e.g. SP 60.13330.2012 in PDF and SP 60.13330.2020 in DOCX). Queries that omit the year designation (e.g. "СП 60.13330 п. 7.1.1") cannot be unambiguously attributed to a legally binding norm.
- **EIG Behavior**: Correctly flags `AMBIGUOUS_SOURCE` and triggers `REFUSAL_REQUIRED`.
- **Mitigation**: Users and client frontends are prompted to specify the active edition year.

### Risk 3: Shadow Mode Telemetry Disk Growth & Queue Saturation
- **Description**: In high-throughput production environments, unhandled task growth could accumulate memory or disk space.
- **Implemented Mitigation (B1 / P1-09)**:
  - Bounded Queue: `rag_server/shadow_eig.py` caps in-flight tasks at `MAX_QUEUE_SIZE = 100`. Saturated requests increment `drop_count` without blocking callers or throwing unhandled errors.
  - Automatic Log Rotation: Enforces a `10 * 1024 * 1024` byte (10 MB) limit with `.jsonl.1` rotation.
  - Opt-in Precedence: Can be immediately and dynamically disabled at runtime by setting `FLYING_RAG_SHADOW_EIG=0`.

---

## 2. Production Rollback & Fail-Safe Plan

### Fast Rollback (Configuration & Dynamic Runtime Precedence)
The Stage 4.2.2 implementation is strictly fail-open and opt-in:
1. **Dynamic Disable**: Set environment variable `FLYING_RAG_SHADOW_EIG=0` (or `false`, `no`, `off`, `disable`). The shadow adapter dynamically evaluates this variable on every request without requiring process restart (`is_active() == False`).
2. **Immediate Effect**: The MCP server completely bypasses EIG execution in `_dispatch()`. Zero overhead and zero diagnostic logging occur.
3. **Clean Shutdown**: Added `shutdown_shadow_adapter(timeout=5.0)` to cleanly terminate background threads upon server stop.

### Complete Git Rollback
If a full rollback of code changes is required:
1. Snapshot branch `audit/stage4-1-snapshot-20261115` remains pinned at `4f43949aa9c03e7ccd99d1ce072d954f18f8c786`.
2. Baseline branch remains pinned at `9b498bf5dc09e964d035049a53582d52f13cdc95`.
3. To restore baseline in an isolated worktree:
   ```bash
   git checkout 9b498bf5dc09e964d035049a53582d52f13cdc95
   ```

### Fail-Safe Architecture
Even with shadow mode enabled:
- If `metadata.db` is missing, locked, or corrupt, the adapter catches the exception, logs a fail-visible warning to stderr, and disables itself (`_shadow_adapter = None`).
- If an individual query assessment encounters an unexpected exception, the shadow adapter catches it, logs a `SHADOW_ERROR` telemetry event, and returns untouched retrieval results.
- The MCP `search_documents()` output is never mutated and search requests never fail due to EIG.

---

## 3. Strict Operating Invariants (Maintained)
- **NO REINDEX**: No LanceDB tables were rebuilt, re-embedded, or modified.
- **PRODUCTION READ-ONLY**: `C:\RAG_Acer\repos\flying-rag-mcp` files were strictly accessed with read-only URIs (`file:...mode=ro` with `PRAGMA query_only = ON;`).
- **NO MASS VECTORS**: No mass GPU or CPU vector embeddings were generated.
- **IMMUTABLE SNAPSHOT**: Snapshot commit `4f43949` on `audit/stage4-1-snapshot-20261115` was never modified or force-pushed.
