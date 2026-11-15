# Stage 4.2: Open Risks, Mitigations & Rollback Plan

**Project**: `Kritik35/flying-rag-mcp`
**Date**: 2026-11-15
**Branch**: `audit/stage4-2-verification`
**Target Release**: Post-Audit Controlled Integration

---

## 1. Residual Risks & Technical Constraints

### Risk 1: OOXML Equation Omission in Upstream Ingestion
- **Description**: Standard `python-docx` ingestion skips Office Open XML (OOXML) `<m:oMath>` tags and MathType OLE binary objects during document parsing. Consequently, mathematical equation bodies are omitted from indexed parent chunks, leaving only isolated formula labels like `(А.3)`.
- **EIG Behavior**: EIG safely detects `FORMULA_MISSING` and demotes the evidence status to `EVIDENCE_PARTIAL`, preventing false certification.
- **Long-term Mitigation**: When full reindexing is authorized in a future major milestone, the ingestion parser can be updated to convert OMML tags to LaTeX/Unicode before chunking. Under current NO REINDEX constraints, `EVIDENCE_PARTIAL` accurately describes the limitation.

### Risk 2: Multi-Edition Ambiguity in Mixed Corpora
- **Description**: The corporate knowledge base contains multiple revisions of regulatory standards (e.g. SP 60.13330.2012 in PDF and SP 60.13330.2020 in DOCX). Queries that omit the year designation (e.g. "СП 60.13330 п. 7.1.1") cannot be unambiguously attributed to a legally binding norm.
- **EIG Behavior**: Correctly flags `AMBIGUOUS_SOURCE` and triggers `REFUSAL_REQUIRED`.
- **Mitigation**: Users and client frontends are prompted to specify the active edition year.

### Risk 3: Shadow Mode Telemetry Disk Growth
- **Description**: In high-throughput production environments, JSONL telemetry logged to `logs/eig_shadow_diagnostics.jsonl` could accumulate if unrotated.
- **Mitigation**: Default log path is configurable; log entries are lightweight (~500 bytes per event); production deployment should configure standard logrotate or use environment variable `FLYING_RAG_SHADOW_EIG=0` to disable when not actively auditing.

---

## 2. Production Rollback & Fail-Safe Plan

### Fast Rollback (Configuration-Only)
The Stage 4.2 implementation is strictly fail-open and opt-in:
1. **Disable Shadow Mode**: Set environment variable `FLYING_RAG_SHADOW_EIG=0` or set `evidence_gate.shadow_enabled = false` in `config.yaml`.
2. **Immediate Effect**: The MCP server completely bypasses EIG execution in `_dispatch()`. Zero overhead and zero diagnostic logging occur.

### Complete Git Rollback
If a full rollback of code changes is required:
1. Snapshot branch `audit/stage4-1-snapshot-20261115` remains pinned at `4f43949aa9c03e7ccd99d1ce072d954f18f8c786`.
2. Baseline branch remains pinned at `9b498bf5dc09e964d035049a53582d52f13cdc95`.
3. To restore baseline in an isolated worktree:
   ```bash
   git checkout master  # or checkout 9b498bf5dc09e964d035049a53582d52f13cdc95
   ```

### Fail-Safe Architecture
Even with shadow mode enabled:
- If `metadata.db` is missing, locked, or corrupt, the adapter catches the exception, increments an error counter, and logs `SHADOW_ERROR` to telemetry.
- The MCP `search_documents()` output is never mutated and search requests never fail due to EIG.

---

## 3. Strict Operating Invariants (Maintained)
- **NO REINDEX**: No LanceDB tables were rebuilt, re-embedded, or modified.
- **PRODUCTION READ-ONLY**: `C:\RAG_Acer\repos\flying-rag-mcp` files were strictly accessed with read-only URIs (`file:...mode=ro` with `PRAGMA query_only = ON;`).
- **NO MASS VECTORS**: No mass GPU or CPU vector embeddings were generated.
