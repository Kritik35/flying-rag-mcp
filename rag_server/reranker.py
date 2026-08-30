"""
rag_server/reranker.py — cross-encoder reranker for flying-rag.

Uses the Lemonade native reranking endpoint (Cohere-style):
    POST /api/v1/reranking  {model, query, documents:[...]}
    -> {"results": [{"index": i, "relevance_score": <logit>}, ...]}

Default model `bge-reranker-v2-m3-GGUF` is a multilingual cross-encoder (strong
on Russian). One batched call ranks the whole candidate pool — far faster and
more accurate than the previous per-chunk LLM-prompt approach.

`relevance_score` is an unbounded logit (e.g. +3.3 relevant, -10.3 irrelevant);
we map it to a 0..1 `rerank_score` via a numerically-stable sigmoid for display,
but ordering uses the raw logit.
"""
from __future__ import annotations

import math
import sys
import logging
from pathlib import Path

import httpx
import yaml

logger = logging.getLogger("flying_rag.reranker")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENDPOINT = "http://localhost:13305/api/v1/reranking"
DEFAULT_MODEL = "bge-reranker-v2-m3-GGUF"
DOC_CHAR_LIMIT = 2000
REQUEST_TIMEOUT = 30.0
# A cross-encoder scores every (query, document) pair, so cost is linear in the
# pool. Cap what we send; the untouched tail keeps its retrieval order instead
# of disappearing.
DEFAULT_CANDIDATE_LIMIT = 64


def _rerank_config() -> tuple[str, str, int]:
    """(endpoint, model, candidate_limit) from config.yaml retrieval.rerank_*."""
    endpoint, model = DEFAULT_ENDPOINT, DEFAULT_MODEL
    candidate_limit = DEFAULT_CANDIDATE_LIMIT
    cfg_path = ROOT / "config.yaml"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            rcfg = cfg.get("retrieval", {}) or {}
            endpoint = rcfg.get("rerank_endpoint", endpoint)
            model = rcfg.get("rerank_model", model)
            candidate_limit = int(rcfg.get("rerank_candidate_limit", candidate_limit))
        except Exception as e:
            logger.debug(f"[reranker] config read failed, using defaults: {e}")
    return endpoint, model, max(1, candidate_limit)


def head_changed(before: list[dict], after: list[dict]) -> bool:
    """Did reranking actually move the head of the list?

    Returning top_k items does not prove a reranker ran: a no-op that echoes the
    input order is indistinguishable by size alone. Compare identities.
    """
    def _key(chunk: dict) -> str:
        return str(chunk.get("chunk_id") or chunk.get("parent_id") or id(chunk))

    if not before or not after:
        return False
    return _key(before[0]) != _key(after[0])


def _sigmoid(x: float) -> float:
    """Numerically stable logistic; maps a logit to (0, 1)."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def build_rerank_payload(query: str, chunks: list[dict], model: str) -> dict:
    return {
        "model": model,
        "query": query,
        "documents": [(c.get("text") or "")[:DOC_CHAR_LIMIT] for c in chunks],
    }


def apply_rerank_results(
    chunks: list[dict], results: list[dict], top_k: int
) -> list[dict]:
    """Attach rerank_score, order by relevance logit (desc), return top_k.

    Pure function — no network. Chunks without a matching result rank last.
    """
    by_index = {
        int(r["index"]): float(r["relevance_score"])
        for r in results
        if "index" in r and "relevance_score" in r
    }
    ordered = []
    for i, chunk in enumerate(chunks):
        logit = by_index.get(i)
        chunk["rerank_score"] = round(_sigmoid(logit), 4) if logit is not None else 0.0
        ordered.append((logit if logit is not None else float("-inf"), i, chunk))
    # stable: sort by logit desc, original index asc to break ties deterministically
    ordered.sort(key=lambda t: (-t[0], t[1]))
    return [chunk for _, _, chunk in ordered[:top_k]]


def rerank_chunks(
    query: str,
    chunks: list[dict],
    top_k: int = 5,
    trace: dict | None = None,
) -> list[dict]:
    """Rerank candidate chunks with the Lemonade cross-encoder. Sync, one call.

    When ``trace`` is given it records the rerank contract: how big the pool was,
    how much of it was actually sent, how much came back, and whether the head
    of the list changed. Without that, a silently failing reranker looks exactly
    like a working one.
    """
    endpoint, model, candidate_limit = _rerank_config()

    def _record(status: str, **fields) -> None:
        if trace is None:
            return
        trace.update({
            "status": status,
            "model": model,
            "pool_count": len(chunks),
            "candidate_limit": candidate_limit,
            **fields,
        })

    if not chunks:
        _record("skipped", reason="empty_pool", input_count=0, returned_count=0,
                head_changed=False)
        return []
    if len(chunks) <= top_k:
        for c in chunks:
            c.setdefault("rerank_score", round(c.get("score", 0.0), 4))
        _record("skipped", reason="pool_not_larger_than_top_k",
                input_count=0, returned_count=len(chunks), head_changed=False)
        return chunks

    # Head of the pool goes to the cross-encoder; the tail keeps retrieval order
    # below it rather than being dropped.
    candidates = chunks[:candidate_limit]
    tail = chunks[candidate_limit:]
    try:
        payload = build_rerank_payload(query, candidates, model)
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(endpoint, json=payload)
            resp.raise_for_status()
            results = resp.json().get("results", [])
        ranked = apply_rerank_results(candidates, results, top_k)
        if len(ranked) < top_k and tail:
            ranked = ranked + tail[: top_k - len(ranked)]
        changed = head_changed(chunks, ranked)
        _record(
            "applied",
            input_count=len(candidates),
            returned_count=len(ranked),
            result_count=len(results),
            head_changed=changed,
        )
        print(
            f"[reranker] {model} ranked {len(candidates)}->{len(ranked)} "
            f"head_changed={changed} top={[c.get('rerank_score') for c in ranked[:3]]}",
            file=sys.stderr,
        )
        return ranked
    except Exception as e:
        logger.warning(f"[reranker] failed, keeping original order: {e}")
        print(f"[reranker] failed, original order: {e}", file=sys.stderr)
        _record(
            "failed",
            reason=f"{type(e).__name__}: {e}",
            input_count=len(candidates),
            returned_count=min(top_k, len(chunks)),
            head_changed=False,
        )
        return chunks[:top_k]


def rerank_sync(
    query: str, chunks: list[dict], top_k: int = 5, trace: dict | None = None
) -> list[dict]:
    """Public entry used by rag_server.tools (kept for API stability)."""
    return rerank_chunks(query, chunks, top_k, trace=trace)
