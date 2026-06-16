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


def _rerank_config() -> tuple[str, str]:
    """(endpoint, model) from config.yaml retrieval.rerank_*, with defaults."""
    endpoint, model = DEFAULT_ENDPOINT, DEFAULT_MODEL
    cfg_path = ROOT / "config.yaml"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            rcfg = cfg.get("retrieval", {}) or {}
            endpoint = rcfg.get("rerank_endpoint", endpoint)
            model = rcfg.get("rerank_model", model)
        except Exception as e:
            logger.debug(f"[reranker] config read failed, using defaults: {e}")
    return endpoint, model


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


def rerank_chunks(query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """Rerank candidate chunks with the Lemonade cross-encoder. Sync, one call."""
    if not chunks:
        return []
    if len(chunks) <= top_k:
        for c in chunks:
            c.setdefault("rerank_score", round(c.get("score", 0.0), 4))
        return chunks

    endpoint, model = _rerank_config()
    try:
        payload = build_rerank_payload(query, chunks, model)
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(endpoint, json=payload)
            resp.raise_for_status()
            results = resp.json().get("results", [])
        ranked = apply_rerank_results(chunks, results, top_k)
        print(
            f"[reranker] {model} ranked {len(chunks)}->{top_k} "
            f"top={[c['rerank_score'] for c in ranked[:3]]}",
            file=sys.stderr,
        )
        return ranked
    except Exception as e:
        logger.warning(f"[reranker] failed, keeping original order: {e}")
        print(f"[reranker] failed, original order: {e}", file=sys.stderr)
        return chunks[:top_k]


def rerank_sync(query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """Public entry used by rag_server.tools (kept for API stability)."""
    return rerank_chunks(query, chunks, top_k)
