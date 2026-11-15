"""
rag_server/shadow_eig.py

Shadow Integration Adapter for Evidence Integrity Gate (Stage 4.1).
Executes EIG diagnostics side-by-side with production retrieval WITHOUT affecting
retrieval output or ranking.

Logs structured telemetry to a configurable JSONL log path.
Measures latency overhead and memory footprints.
"""
from __future__ import annotations
import os
import sys
import time
import json
import psutil
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from evidence_gate import EvidenceIntegrityGate, EvidenceGateResult

DEFAULT_LOG_PATH = Path("logs") / "eig_shadow_diagnostics.jsonl"


class ShadowEvidenceIntegrityGate:
    """
    Transparent shadow adapter for Evidence Integrity Gate (Stage 4.1 / 4.2).
    Wraps retrieval pipelines or individual queries, executing EIG assessment
    passively.
    """

    def __init__(
        self,
        metadata_db_path: Path | str,
        log_path: Path | str = DEFAULT_LOG_PATH,
        enabled: bool = True
    ):
        self.enabled = enabled
        self.log_path = Path(log_path)
        self.metadata_db_path = Path(metadata_db_path)
        self.gate: Optional[EvidenceIntegrityGate] = None
        self.error_count = 0
        self._process = None
        try:
            self._process = psutil.Process(os.getpid())
        except Exception:
            pass

        if self.enabled:
            try:
                self.gate = EvidenceIntegrityGate(self.metadata_db_path)
            except Exception as e:
                self.error_count += 1
                sys.stderr.write(f"[SHADOW_EIG_INIT_WARNING] Failed to initialize EIG gate: {e}\n")
                self.gate = None

    def _write_event(self, event: Dict[str, Any]) -> None:
        """Process-safe append to JSONL log."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            sys.stderr.write(f"[SHADOW_EIG_LOG_WARNING] Failed to write event: {e}\n")

    def observe(
        self,
        query: str,
        retrieval_results: Optional[List[Dict[str, Any]]] = None,
        context_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[EvidenceGateResult]:
        """
        Passive shadow execution of EIG.
        Does NOT modify retrieval_results.
        Returns EvidenceGateResult for monitoring, while guaranteeing zero side-effects.
        """
        if not self.enabled or not self.gate:
            return None

        try:
            mem_before_kb = 0.0
            if self._process:
                try:
                    mem_before_kb = self._process.memory_info().rss / 1024.0
                except Exception:
                    pass

            t0 = time.perf_counter()
            eig_res = self.gate.assess_evidence(query, retrieval_results=retrieval_results)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            mem_after_kb = mem_before_kb
            if self._process:
                try:
                    mem_after_kb = self._process.memory_info().rss / 1024.0
                except Exception:
                    pass
            mem_delta_kb = max(0.0, mem_after_kb - mem_before_kb)

            # Extract retrieved parent IDs and source document names
            retrieved_pids = set()
            retrieved_sources = set()
            if retrieval_results:
                for r in retrieval_results:
                    pid = r.get("parent_id")
                    if pid:
                        retrieved_pids.add(pid)
                    src = r.get("source_path") or r.get("file_name")
                    if src:
                        retrieved_sources.add(Path(src).name.lower())

            has_retrieval = len(retrieved_pids) > 0
            evidence_usable = (eig_res.answer_evidence_status == "USABLE_FOR_ANSWER")
            eig_pids = set(eig_res.parent_ids or [])
            eig_source = Path(eig_res.source_path).name.lower() if eig_res.source_path else ""

            # Hardened Divergence Classification (Blocker 4)
            if eig_res.source_integrity == "AMBIGUOUS_SOURCE":
                divergence = "SOURCE_AMBIGUOUS"
            elif eig_res.source_integrity == "NOT_APPLICABLE" or eig_res.document_status == "NOT_APPLICABLE":
                divergence = "EIG_NOT_APPLICABLE"
            elif evidence_usable:
                if not has_retrieval:
                    divergence = "EVIDENCE_EXISTS_MISSED_BY_RETRIEVAL"
                else:
                    pid_overlap = retrieved_pids.intersection(eig_pids)
                    source_match = (eig_source in retrieved_sources) if eig_source and retrieved_sources else True
                    if pid_overlap and source_match:
                        divergence = "CONGRUENT"
                    else:
                        divergence = "RETRIEVAL_PARENT_ID_MISMATCH"
            else:
                if has_retrieval:
                    divergence = "RETRIEVAL_WITHOUT_CERTIFIED_EVIDENCE"
                else:
                    divergence = "CONGRUENT_REFUSAL"

            # Construct structured telemetry event
            event = {
                "timestamp": datetime.now().isoformat(),
                "query": query,
                "shadow_mode": True,
                "production_action": "OBSERVED_ONLY_NO_PRODUCTION_EFFECT",
                "divergence": divergence,
                "performance": {
                    "cpu_latency_ms": round(elapsed_ms, 2),
                    "memory_delta_kb": round(mem_delta_kb, 2)
                },
                "retrieval_summary": {
                    "retrieved_count": len(retrieval_results) if retrieval_results else 0,
                    "retrieved_pids": list(retrieved_pids)[:5]
                },
                "eig_summary": {
                    "answer_evidence_status": eig_res.answer_evidence_status,
                    "source_integrity": eig_res.source_integrity,
                    "boundary_integrity": eig_res.boundary_integrity,
                    "text_integrity": eig_res.text_integrity,
                    "formula_integrity": eig_res.formula_integrity,
                    "missing_formulas": eig_res.missing_formulas,
                    "topic_alignment": eig_res.topic_alignment,
                    "document_status": eig_res.document_status,
                    "edition_status": eig_res.edition_status,
                    "clause_status": eig_res.clause_status,
                    "source_path": eig_res.source_path,
                    "parent_ids": eig_res.parent_ids,
                    "verification_reason": eig_res.verification_reason
                }
            }

            self._write_event(event)
            return eig_res

        except Exception as e:
            self.error_count += 1
            error_event = {
                "timestamp": datetime.now().isoformat(),
                "query": query,
                "shadow_mode": True,
                "production_action": "OBSERVED_ONLY_NO_PRODUCTION_EFFECT",
                "divergence": "SHADOW_ERROR",
                "error": str(e),
                "error_type": type(e).__name__
            }
            self._write_event(error_event)
            return None
