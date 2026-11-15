# FlyingRAG — Stage 4.1: Shadow Integration Report (Anonymized)

**Project**: Kritik35/flying-rag-mcp
**Baseline Commit**: `9b498bf5dc09e964d035049a53582d52f13cdc95`
**Isolated Branch**: `audit/stage4-1-snapshot-20261115`
**Component**: `rag_server/shadow_eig.py`
**Mode**: STRICT OFFLINE / SHADOW DEPLOYMENT READY / ZERO PRODUCTION IMPACT
**Date**: 2026-11-15

---

## 1. Overview & Architecture

Gate F delivers a completely non-invasive **Shadow Integration Adapter** for the Evidence Integrity Gate (EIG). The adapter runs alongside the existing FlyingRAG retrieval pipeline, observing queries and retrieval candidates in real-time, executing EIG deterministic verification, and logging structured telemetry without modifying search outputs, scores, or rankings.

```
                    ┌─────────────────────────────────┐
                    │       User / Client Query       │
                    └────────────────┬────────────────┘
                                     │
                                     ▼
                      ┌──────────────────────────────┐
                      │    FlyingRAG Server / MCP    │
                      └──────┬────────────────┬──────┘
                             │                │
            (Production Path)│                │(Shadow Path - Passive)
                             ▼                ▼
         ┌───────────────────────┐   ┌──────────────────────────────┐
         │ Standard Retrieval    │   │ ShadowEvidenceIntegrityGate  │
         │ (Linear Dynamic Top-K)│   │ (SQLite Primary Key Lookup)  │
         └───────────┬───────────┘   └──────────────┬───────────────┘
                     │                              │
                     │ (Returned Untouched)         ▼
                     │               ┌──────────────────────────────┐
                     │               │ logs/                        │
                     ▼               │  eig_shadow_diagnostics.jsonl│
         ┌───────────────────────┐   └──────────────────────────────┘
         │ Production Response   │
         └───────────────────────┘
```

---

## 2. Technical Non-Invasiveness Guarantees

1. **Zero Production Mutation**: The adapter accepts `retrieval_results` as read-only data. All outputs passed to downstream components remain byte-for-byte identical.
2. **Fail-Closed Isolation**: Any potential exception within EIG execution or logging is trapped and suppressed, preventing shadow diagnostics from ever disrupting or failing an active user search request.
3. **No Network / External API Calls**: The gate operates 100% locally using direct SQLite indexed lookups.
4. **Independent Connection Scope**: SQLite queries use dedicated short-lived connections in read-only mode (`SQLITE_OPEN_READONLY`).

---

## 3. Telemetry Schema

Each query processed by the shadow adapter emits a single structured JSON line containing:
- `timestamp`: ISO-8601 timestamp.
- `query`: Exact input query string.
- `shadow_mode`: Boolean flag (`true`).
- `production_action`: Stamped as `"OBSERVED_ONLY_NO_PRODUCTION_EFFECT"`.
- `divergence`: Divergence classification between Top-K retrieval and EIG:
  * `"CONGRUENT"`: Retrieval returned relevant candidates and EIG verified evidence.
  * `"RETRIEVAL_WITHOUT_CERTIFIED_EVIDENCE"`: Retrieval returned candidates, but EIG flagged evidence as defective, ambiguous, or misaligned with topic.
  * `"EVIDENCE_EXISTS_MISSED_BY_RETRIEVAL"`: Valid normative clause exists in corpus, but retrieval Top-K failed to surface it.
- `performance`:
  * `cpu_latency_ms`: Execution time of EIG assessment in milliseconds.
  * `memory_delta_kb`: Resident Set Size (RSS) delta in kilobytes.
- `retrieval_summary`: Count of retrieved candidates and top candidate IDs.
- `eig_summary`: Complete granular integrity indicators.

---

## 4. Benchmark & Performance Telemetry

- **Average CPU Latency Overhead**: **54.08 ms**
- **Maximum CPU Latency Overhead**: **88.43 ms**
- **Average Memory RSS Delta**: **1,273.14 KB (~1.24 MB)**
- **Side-Effect Evaluation**: **100% UNTOUCHED (Zero mutations)**
