"""Opt-in, data-free phase markers for bounded FlyingRAG diagnostics.

Emits only a fixed stage name, a monotonic timestamp and a thread identifier.
Never emits queries, document paths, excerpts, configuration or exceptions.
The parent harness parses the markers from stderr, including after timeout.
No search, model, storage or filesystem access is performed by this module.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from typing import Any

_ENV = "FLYING_RAG_STAGE_TIMING"
_PREFIX = "[FR_STAGE_V1]"
_ALLOWED = frozenset({
    "worker_started", "imports_ready", "dispatch_start", "dispatch_done",
    "worker_done", "worker_error", "observer_start", "observer_done",
    "search_started", "search_imports_ready", "enr_start", "enr_done",
    "embedding_start", "embedding_done", "retrieval_start", "retrieval_done",
    "subquery_start", "subquery_done", "quality_start", "quality_done",
    "named_guard_start", "named_guard_done", "norm_start", "norm_done",
    "rerank_start", "rerank_done", "search_complete", "vector_start",
    "vector_table_ready", "fts_start", "fts_done", "ann_start", "ann_done",
    "hybrid_start", "hybrid_done", "ann_fallback_start",
    "ann_fallback_done", "hydration_start", "hydration_done",
    "vector_done",
})
_PATTERN = re.compile(
    r"^\[FR_STAGE_V1\] ([a-z][a-z0-9_]*) (\d{1,24}) (\d{1,24})$"
)


def mark(stage: str) -> None:
    """Emit one flushed marker only if explicitly enabled by the isolated worker."""
    if os.environ.get(_ENV) != "1" or stage not in _ALLOWED:
        return
    try:
        sys.stderr.write(
            f"{_PREFIX} {stage} {time.perf_counter_ns()} {threading.get_ident()}\n"
        )
        sys.stderr.flush()
    except (OSError, ValueError):
        # Telemetry must never break an engineering search.
        pass


def collect(raw_stderr: str | bytes | None, *, limit: int = 128) -> list[dict[str, Any]]:
    """Keep only validated, bounded markers; discard all raw stderr content.

    The timestamps are monotonic offsets within ONE worker process. Parallel
    subqueries can interleave; do not infer exclusive stage durations by simply
    summing adjacent markers from different threads.
    """
    if raw_stderr is None or limit <= 0:
        return []
    if isinstance(raw_stderr, bytes):
        raw_stderr = raw_stderr.decode("utf-8", errors="replace")
    if not isinstance(raw_stderr, str):
        return []

    parsed: list[tuple[str, int, int]] = []
    # Bound input size; raw logs, queries and paths are never emitted.
    for line in raw_stderr[-200_000:].splitlines():
        match = _PATTERN.fullmatch(line.strip())
        if not match or match.group(1) not in _ALLOWED:
            continue
        try:
            parsed.append((
                match.group(1),
                int(match.group(2)),
                int(match.group(3)),
            ))
        except ValueError:
            continue
    if not parsed:
        return []

    origin_ns = parsed[0][1]
    return [
        {
            "stage": stage,
            "since_first_ms": round((ns - origin_ns) / 1_000_000, 3),
            "thread": thread_id,
        }
        for stage, ns, thread_id in parsed[-limit:]
    ]
