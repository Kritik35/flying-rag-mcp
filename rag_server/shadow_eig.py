"""
rag_server/shadow_eig.py

Shadow Integration Adapter for Evidence Integrity Gate (Stage 4.2.2 Hardening).
Executes EIG diagnostics side-by-side with production retrieval WITHOUT affecting
retrieval output or ranking.

Features:
- Non-blocking fire-and-forget async execution via bounded ThreadPoolExecutor (B1).
- Bounded queue with drop counting and backpressure protection (B1).
- Dynamic runtime activation/deactivation via is_active() and env checks (B8).
- Managed graceful executor shutdown (B8).
- Centralized recursive privacy sanitization (query_hash, no raw paths, no tokens) (B4).
- Safe log rotation at 10 MB (P1-09).
"""
from __future__ import annotations
import os
import sys
import re
import time
import json
import hashlib
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, Future

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    psutil = None
    _HAS_PSUTIL = False

from evidence_gate import EvidenceIntegrityGate, EvidenceGateResult

DEFAULT_LOG_PATH = Path("logs") / "eig_shadow_diagnostics.jsonl"
MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit before rotation
MAX_QUEUE_SIZE = 100                   # Maximum pending tasks before dropping
DEFAULT_CONTROL_FILE_ENV = "FLYING_RAG_SHADOW_CONTROL_FILE"


def read_shadow_control(control_path: Path | str | None) -> tuple[bool, str]:
    """
    Reads external control file atomically with fail-safe validation (S2).
    Schema: {"enabled": bool, "updated_at": str, "reason": str}
    Returns: (is_enabled, diagnostic_reason)
    Fail-safe: Any unreadable/corrupt/invalid file defaults to disabled.
    """
    if not control_path:
        return True, "no_control_file_configured"
    p = Path(control_path)
    if not p.exists():
        return False, f"control_file_missing_fail_safe ({p.name})"
    try:
        content = p.read_text(encoding="utf-8").strip()
        if not content:
            return False, "control_file_empty_fail_safe"
        data = json.loads(content)
        if not isinstance(data, dict):
            return False, "control_file_invalid_type_fail_safe"
        if "enabled" not in data or not isinstance(data["enabled"], bool):
            return False, "control_file_missing_enabled_bool_fail_safe"
        if not data["enabled"]:
            reason = data.get("reason", "manual_disable")
            return False, f"control_file_disabled: {reason}"
        return True, f"control_file_enabled: {data.get('reason', 'manual_enable')}"
    except Exception as e:
        return False, f"control_file_corrupt_fail_safe: {e}"


def write_shadow_control(control_path: Path | str, enabled: bool, reason: str = "") -> None:
    """Atomically writes external control file via temporary file replacement (S2)."""
    p = Path(control_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "enabled": bool(enabled),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "reason": str(reason)
    }
    tmp_p = p.with_suffix(f".tmp.{os.getpid()}.{time.time_ns()}")
    tmp_p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_p, p)


def _canonical_path(p: str | Path | None) -> str:
    """Normalize file paths for deterministic provenance comparison."""
    if not p:
        return ""
    posix_p = Path(p).as_posix().lower()
    return posix_p


def _sanitize_path(p: str | Path | None) -> str:
    """Redact absolute local paths to protect operator privacy (CR-03 / B4 / P1-10)."""
    if not p:
        return ""
    s = str(p).strip("'\"").replace("\\", "/")
    # UNC paths: //server/share/...
    if s.startswith("//"):
        return re.sub(r'^//[^/]+/[^/]+', '[UNC_SHARE]', s)
    # Normalize and redact known corpus drives or patterns (including spaces like 'Мой диск')
    s = re.sub(r'^[a-zA-Z]:[/]+(?:Мой\s+диск|Normative_Docs|normative_docs|Docs|docs|Corpus|corpus|НТД|нтд)[/]+', '[CORPUS]/', s, flags=re.IGNORECASE)
    s = re.sub(r'^[a-zA-Z]:[/]+(?:rag_acer|repos)[/]+flying-rag-mcp[/]+', '[REPO_ROOT]/', s, flags=re.IGNORECASE)
    s = re.sub(r'^[a-zA-Z]:[/]+Users[/]+[^/]+[/]+', '/Users/[USER]/', s, flags=re.IGNORECASE)
    s = re.sub(r'^[a-zA-Z]:[/]+', '[DRIVE]/', s)
    return s


def _sanitize_text(s: str) -> str:
    """Recursively redacts filesystem paths, tokens, and secrets from arbitrary strings (CR-03 / B4)."""
    if not s:
        return ""
    # 1. Quoted Windows / Unix paths with possible spaces
    s = re.sub(r'["\']([a-zA-Z]:[\\/][^"\'\r\n<>]+)["\']', lambda m: f'"{_sanitize_path(m.group(1))}"', s)
    # 2. UNC network paths: \\server\share\... or //server/share/...
    s = re.sub(r'(?:\\\\|//)[^ \t\r\n"\'<>;]+', '[UNC_PATH]', s)
    # 3. Unquoted Windows paths (handling spaces in folder names like 'Мой диск')
    s = re.sub(r'\b[a-zA-Z]:[\\/](?:Мой\s+диск[\\/]|[^ \t\r\n"\'<>;]+[\\/])*[^ \t\r\n"\'<>;]*', lambda m: _sanitize_path(m.group(0)), s, flags=re.IGNORECASE)
    # 4. Standard User paths
    s = re.sub(r'/Users/[^/ \t\r\n"\'<>;]+', '/Users/[USER]', s)
    s = re.sub(r'\\Users\\[^\\ \t\r\n"\'<>;]+', r'\\Users\\[USER]', s)
    # 5. Sensitive keys/tokens
    s = re.sub(r'(?i)\b(api[_-]?key|token|bearer|secret|password)\s*[:=]\s*[^\s,;"]+', r'\1=[REDACTED]', s)
    # 6. Redact current user and usernames dynamically (B4, B9)
    import getpass
    users = set(filter(None, [
        os.environ.get("USERNAME"),
        os.environ.get("USER"),
        getpass.getuser(),
        Path.home().name
    ]))
    for u in users:
        s = re.sub(re.escape(u), "[USER]", s, flags=re.IGNORECASE)
    return s


def _sanitize_obj(obj: Any) -> Any:
    """Recursively sanitizes all strings and collections in an object (B4)."""
    if isinstance(obj, str):
        return _sanitize_text(obj)
    elif isinstance(obj, dict):
        return {k: _sanitize_obj(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_obj(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(_sanitize_obj(item) for item in obj)
    return obj


class ShadowEvidenceIntegrityGate:
    """
    Transparent shadow adapter for Evidence Integrity Gate (Stage 4.2.2 Hardening).
    Wraps retrieval pipelines or individual queries, executing EIG assessment
    passively and asynchronously.
    """

    def __init__(
        self,
        metadata_db_path: Path | str,
        log_path: Path | str = DEFAULT_LOG_PATH,
        enabled: bool = True,
        control_file_path: Optional[Path | str] = None
    ):
        self.enabled = enabled
        self.log_path = Path(log_path)
        self.metadata_db_path = Path(metadata_db_path)
        self.control_file_path: Optional[Path] = None
        if control_file_path:
            self.control_file_path = Path(control_file_path)
        elif DEFAULT_CONTROL_FILE_ENV in os.environ and os.environ[DEFAULT_CONTROL_FILE_ENV].strip():
            self.control_file_path = Path(os.environ[DEFAULT_CONTROL_FILE_ENV].strip())

        self.gate: Optional[EvidenceIntegrityGate] = None
        self.error_count = 0
        self.drop_count = 0
        self.submitted_count = 0
        self.processed_count = 0
        self._pending_count = 0
        self._lock = threading.Lock()
        self._shutdown = False
        self._active_futures: set[Future] = set()
        self._process = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shadow_eig")
        if _HAS_PSUTIL and psutil is not None:
            try:
                self._process = psutil.Process(os.getpid())
            except Exception:
                pass

        if self.enabled:
            try:
                self.gate = EvidenceIntegrityGate(self.metadata_db_path)
            except Exception as e:
                self.error_count += 1
                sys.stderr.write(f"[SHADOW_EIG_INIT_WARNING] Gate init failed: {e}\n")
                self.gate = None

    def is_active(self) -> bool:
        """Dynamic runtime check: checks shutdown status, startup env var, and external control file (S2 / B8)."""
        if self._shutdown or not self.enabled or not self.gate:
            return False

        # 1. Startup / process-level environment variable override
        env_val = os.environ.get("FLYING_RAG_SHADOW_EIG", "").strip().lower()
        if env_val in ("0", "false", "no", "off", "disable", "disabled"):
            return False

        # 2. External control file check (S2)
        if self.control_file_path:
            ctrl_ok, _ = read_shadow_control(self.control_file_path)
            if not ctrl_ok:
                # If external kill-switch fired, cancel pending unstarted tasks
                if self._pending_count > 0:
                    self.cancel_pending()
                return False

        return True

    def _write_event(self, event: Dict[str, Any]) -> None:
        """Rotates log file if it exceeds MAX_LOG_SIZE_BYTES and appends sanitized event."""
        try:
            # Ensure log directory exists
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

            if self.log_path.exists() and self.log_path.stat().st_size >= MAX_LOG_SIZE_BYTES:
                rot_path = self.log_path.with_name(self.log_path.name + ".1")
                if rot_path.exists():
                    try:
                        rot_path.unlink()
                    except Exception:
                        pass
                try:
                    self.log_path.rename(rot_path)
                except Exception:
                    pass

            sanitized_event = _sanitize_obj(event)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(sanitized_event, ensure_ascii=False) + "\n")
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
        if not self.is_active():
            return None

        try:
            mem_before_kb = 0.0
            if self._process:
                try:
                    mem_before_kb = self._process.memory_info().rss / 1024.0
                except Exception:
                    pass

            t0_wall = time.perf_counter()
            t0_cpu = time.process_time()
            eig_res = self.gate.assess_evidence(query, retrieval_results=retrieval_results)
            wall_elapsed_ms = (time.perf_counter() - t0_wall) * 1000.0
            cpu_elapsed_ms = (time.process_time() - t0_cpu) * 1000.0

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
            retrieved_has_source_info = False

            if retrieval_results:
                for r in retrieval_results:
                    pid = r.get("parent_id")
                    if pid:
                        retrieved_pids.add(pid)
                    src = r.get("source_path") or r.get("file_name")
                    if src:
                        retrieved_has_source_info = True
                        retrieved_sources.add(_canonical_path(src))

            has_retrieval = len(retrieved_pids) > 0
            evidence_usable = (eig_res.answer_evidence_status == "USABLE_FOR_ANSWER")
            eig_pids = set(eig_res.parent_ids or [])
            eig_canonical_source = _canonical_path(eig_res.source_path) if eig_res.source_path else ""

            # Hardened Divergence Classification (P1-06 & P1-07)
            if eig_res.answer_evidence_status == "NOT_APPLICABLE":
                divergence = "EIG_NOT_APPLICABLE"
            elif eig_res.source_integrity == "AMBIGUOUS_SOURCE":
                divergence = "SOURCE_AMBIGUOUS"
            elif evidence_usable:
                if not has_retrieval:
                    divergence = "EVIDENCE_EXISTS_MISSED_BY_RETRIEVAL"
                else:
                    if not eig_canonical_source or not retrieved_has_source_info:
                        divergence = "UNVERIFIABLE_PROVENANCE"
                    else:
                        # Pairwise hit verification (CR-07): hit must have matching parent_id AND source on the SAME hit
                        has_congruent_hit = False
                        has_source_match_any_hit = False
                        has_pid_match_any_hit = False

                        for r in retrieval_results:
                            r_pid = r.get("parent_id")
                            r_raw_src = r.get("source_path") or r.get("file_name")
                            r_src = _canonical_path(r_raw_src) if r_raw_src else ""

                            pid_ok = bool(r_pid and r_pid in eig_pids)
                            src_ok = bool(r_src and r_src == eig_canonical_source)

                            if pid_ok and src_ok:
                                has_congruent_hit = True
                                break
                            if src_ok:
                                has_source_match_any_hit = True
                            if pid_ok:
                                has_pid_match_any_hit = True

                        if has_congruent_hit:
                            divergence = "CONGRUENT"
                        elif has_source_match_any_hit and not has_pid_match_any_hit:
                            divergence = "RETRIEVAL_PARENT_ID_MISMATCH"
                        elif has_pid_match_any_hit and not has_source_match_any_hit:
                            divergence = "RETRIEVAL_SOURCE_MISMATCH"
                        else:
                            divergence = "RETRIEVAL_SOURCE_MISMATCH"
            else:
                if has_retrieval:
                    divergence = "RETRIEVAL_WITHOUT_CERTIFIED_EVIDENCE"
                else:
                    divergence = "CONGRUENT_REFUSAL"

            # Construct sanitized telemetry event (CR-03 / B4)
            # Default policy: store ONLY hash, length, and structured IDs; query text is strictly opt-in
            q_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
            event = {
                "timestamp": datetime.now().isoformat(),
                "query_hash": q_hash,
                "query_length": len(query),
                "shadow_mode": True,
                "production_action": "OBSERVED_ONLY_NO_PRODUCTION_EFFECT",
                "divergence": divergence,
                "performance": {
                    "wall_latency_ms": round(wall_elapsed_ms, 2),
                    "cpu_latency_ms": round(cpu_elapsed_ms, 2),
                    "memory_delta_kb": round(mem_delta_kb, 2)
                },
                "retrieval_summary": {
                    "retrieved_count": len(retrieval_results) if retrieval_results else 0,
                    "retrieved_pids": list(retrieved_pids)[:5]
                },
                "eig_summary": {
                    "query_applicability": getattr(eig_res, "query_applicability", "NORMATIVE_CITATION"),
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
                    "source_path": _sanitize_path(eig_res.source_path),
                    "parent_ids": eig_res.parent_ids,
                    "verification_reason": _sanitize_text(eig_res.verification_reason)
                }
            }

            # Optional query text logging: STRICTLY opt-in via env var (CR-03)
            log_query_text = os.environ.get("FLYING_RAG_SHADOW_LOG_QUERY_TEXT", "").strip().lower() in ("1", "true", "yes", "on")
            if log_query_text:
                event["query_sanitized"] = _sanitize_text(query)

            self._write_event(event)
            return eig_res

        except Exception as e:
            self.error_count += 1
            q_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
            error_event = {
                "timestamp": datetime.now().isoformat(),
                "query_hash": q_hash,
                "query_length": len(query),
                "shadow_mode": True,
                "production_action": "OBSERVED_ONLY_NO_PRODUCTION_EFFECT",
                "divergence": "SHADOW_ERROR",
                "error": _sanitize_text(str(e)),
                "error_type": type(e).__name__
            }
            log_query_text = os.environ.get("FLYING_RAG_SHADOW_LOG_QUERY_TEXT", "").strip().lower() in ("1", "true", "yes", "on")
            if log_query_text:
                error_event["query_sanitized"] = _sanitize_text(query)
            self._write_event(error_event)
            return None

    def stop_accepting(self) -> None:
        """Contract: immediately stops accepting new observation tasks (S1)."""
        with self._lock:
            self._shutdown = True

    def cancel_pending(self) -> int:
        """Contract: cancels all pending tasks currently queued in executor (S1).

        Decrements _pending_count and increments drop_count for every cancelled future.
        Does NOT interrupt an already running worker thread.
        """
        cancelled = 0
        with self._lock:
            for fut in list(self._active_futures):
                if not fut.running() and not fut.done():
                    if fut.cancel():
                        cancelled += 1
                        self._active_futures.discard(fut)
                        self._pending_count = max(0, self._pending_count - 1)
                        self.drop_count += 1
        return cancelled

    def observe_async(
        self,
        query: str,
        retrieval_results: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """
        Non-blocking fire-and-forget submission to background thread (Blocker B1 / S4).
        Enforces bounded queue with drop counting, snapshot isolation, and error resilience.
        """
        if not self.is_active():
            return False

        with self._lock:
            if self._shutdown or self._pending_count >= MAX_QUEUE_SIZE:
                self.drop_count += 1
                return False
            self.submitted_count += 1
            self._pending_count += 1

        # Immutable snapshot of retrieval results to guarantee zero caller/callee race conditions
        snapshot = [dict(r) for r in retrieval_results] if retrieval_results else []

        def _worker_task():
            try:
                self.observe(query, retrieval_results=snapshot)
            except Exception as e:
                with self._lock:
                    self.error_count += 1
                sys.stderr.write(f"[SHADOW_EIG_WORKER_ERROR] {e}\n")
            finally:
                with self._lock:
                    self._pending_count = max(0, self._pending_count - 1)
                    self.processed_count += 1

        try:
            future = self._executor.submit(_worker_task)
            with self._lock:
                self._active_futures.add(future)
            future.add_done_callback(lambda f: self._active_futures.discard(f))
            return True
        except Exception as e:
            with self._lock:
                self._pending_count = max(0, self._pending_count - 1)
                self.drop_count += 1
            sys.stderr.write(f"[SHADOW_EIG_SUBMIT_WARNING] Async submit failed: {e}\n")
            return False

    def shutdown(self, wait: bool = True, timeout: float = 5.0) -> dict:
        """
        Bounded shutdown contract (S1).
        1. Calls stop_accepting() -> rejects new tasks.
        2. Calls cancel_pending() -> cancels unstarted queued futures.
        3. If wait=True: waits up to `timeout` seconds for currently executing task.
           - If executing task finishes within timeout:
               hard_stop_status = "NORMAL_COMPLETION"
           - If executing task times out:
               hard_stop_status = "HARD_STOP_UNSUPPORTED"
               Logs warning and returns within bounded time without hanging the process.
        """
        self.stop_accepting()
        cancelled_count = self.cancel_pending()

        clean_exit = True
        hard_stop_status = "NORMAL_COMPLETION"
        t0 = time.perf_counter()

        if wait:
            with self._lock:
                running_futures = [f for f in self._active_futures if not f.done()]
            if running_futures:
                done, not_done = concurrent.futures.wait(running_futures, timeout=max(0.01, timeout))
                if not_done:
                    clean_exit = False
                    hard_stop_status = "HARD_STOP_UNSUPPORTED"
                    sys.stderr.write(
                        f"[SHADOW_EIG_SHUTDOWN_WARNING] Active task did not finish within timeout={timeout}s. "
                        f"HARD_STOP_UNSUPPORTED: Python thread pool cannot terminate running threads. "
                        f"Returning control to caller to prevent process hang.\n"
                    )

        # Non-blocking executor shutdown with cancel_futures
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "clean_exit": clean_exit,
            "hard_stop_status": hard_stop_status,
            "cancelled_count": cancelled_count,
            "elapsed_ms": elapsed_ms,
            "pending_count": self._pending_count,
            "processed_count": self.processed_count,
            "submitted_count": self.submitted_count,
            "drop_count": self.drop_count
        }
