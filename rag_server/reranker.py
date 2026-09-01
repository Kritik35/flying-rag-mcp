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
import re
import sys
import logging
from pathlib import Path

import httpx
import yaml

logger = logging.getLogger("flying_rag.reranker")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENDPOINT = "http://localhost:13305/api/v1/reranking"
DEFAULT_MODEL = "bge-reranker-v2-m3-GGUF"
# The cross-encoder runs behind a fixed physical batch (512 tokens on the
# default llama-server recipe), and the whole request fails when one pair does
# not fit. A character budget cannot express that: 2000 characters of Russian
# prose fit, 2000 characters of a dense technical table do not. This bit only
# once parent hydration started working and `text` became the ~1000-token
# parent instead of the ~150-token child.
DOC_TOKEN_LIMIT = 400
# Worst measured ratio on Russian technical text is ~1.4 characters per token;
# 1.5 keeps the character fallback on the safe side when tiktoken is missing.
CHARS_PER_TOKEN_FLOOR = 1.5
DOC_CHAR_FALLBACK = int(DOC_TOKEN_LIMIT * CHARS_PER_TOKEN_FLOOR)
REQUEST_TIMEOUT = 30.0
# A cross-encoder scores every (query, document) pair, so cost is linear in the
# pool. Cap what we send; the untouched tail keeps its retrieval order instead
# of disappearing.
DEFAULT_CANDIDATE_LIMIT = 64


def _rerank_config() -> tuple[str, str, int]:
    """(endpoint, model, candidate_limit) from config.yaml retrieval.rerank_*."""
    endpoint, model = DEFAULT_ENDPOINT, DEFAULT_MODEL
    candidate_limit = DEFAULT_CANDIDATE_LIMIT
    try:
        from config_loader import load_config

        rcfg = (load_config().get("retrieval") or {})
        endpoint = rcfg.get("rerank_endpoint", endpoint)
        model = rcfg.get("rerank_model", model)
        candidate_limit = int(rcfg.get("rerank_candidate_limit", candidate_limit))
    except Exception as e:
        logger.debug(f"[reranker] config read failed, using defaults: {e}")
    return endpoint, model, max(1, candidate_limit)


def _is_oversize(error: Exception) -> bool:
    """Did the server refuse because the input did not fit its batch?"""
    text = f"{error}".casefold()
    return "too large" in text or "batch size" in text


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


_ENCODING = None
_ENCODING_TRIED = False


def _encoding():
    """cl100k_base, or None when tiktoken cannot be loaded.

    This is not the cross-encoder's own tokenizer — bge-reranker-v2-m3 uses
    XLM-R — but on Russian technical text cl100k counts at least as many tokens,
    so a budget expressed in cl100k tokens stays on the safe side of the batch.
    """
    global _ENCODING, _ENCODING_TRIED
    if not _ENCODING_TRIED:
        _ENCODING_TRIED = True
        try:
            import tiktoken

            _ENCODING = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.warning(
                f"[reranker] tiktoken unavailable, cutting documents by characters: {e}"
            )
            _ENCODING = None
    return _ENCODING


def _doc_token_limit() -> int:
    """Per-document token budget from config retrieval.rerank_doc_token_limit."""
    try:
        from config_loader import load_config

        rcfg = load_config().get("retrieval") or {}
        return max(16, int(rcfg.get("rerank_doc_token_limit", DOC_TOKEN_LIMIT)))
    except Exception as e:
        logger.debug(f"[reranker] config read failed, using default budget: {e}")
        return DOC_TOKEN_LIMIT


# A contents line — "Гидравлический расчёт . . . . . . . . 20" — is cheap in
# cl100k, which merges the run into few tokens, and expensive in the server's
# XLM-R, which does not. One project document budgeted at 400 cl100k tokens
# arrived as 685 on the server and failed the whole request, so one golden case
# lost its rerank on every run. The runs carry nothing a relevance model can
# use, so they go before the budget is counted.
# Filler characters, optionally spaced apart, three or more in a row.
# A contents line is ". . . . . ." as often as "......", and only the
# spaced form was the one that broke the request.
_RUN_RE = re.compile(r"(?:[.\u2026\-_\u00b7\u2022*=~][ \t]*){3,}")


def normalise_for_scoring(text: str) -> str:
    """Collapse runs of filler punctuation; leave real text alone."""
    collapsed = _RUN_RE.sub(" ", str(text or ""))
    return re.sub(r"[ \t]{2,}", " ", collapsed)


def fit_to_budget(text: str, budget: int) -> str:
    """Cut a document to `budget` tokens, keeping its head."""
    enc = _encoding()
    if enc is None:
        return text[: max(16, int(budget * CHARS_PER_TOKEN_FLOOR))]
    ids = enc.encode(text)
    return text if len(ids) <= budget else enc.decode(ids[:budget])


def build_rerank_payload(
    query: str, chunks: list[dict], model: str, budget: int | None = None
) -> dict:
    if budget is None:
        budget = _doc_token_limit()
    return {
        "model": model,
        "query": query,
        "documents": [
            fit_to_budget(normalise_for_scoring(c.get("text") or ""), budget)
            for c in chunks
        ],
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
    doc_token_limit = _doc_token_limit()

    def _record(status: str, **fields) -> None:
        if trace is None:
            return
        trace.update({
            "status": status,
            "model": model,
            "pool_count": len(chunks),
            "candidate_limit": candidate_limit,
            "doc_token_limit": doc_token_limit,
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
    retried = False
    try:
        from http_local import httpx_client_kwargs
        # A local Lemonade is reached directly: httpx would otherwise take
        # the machine's SOCKS proxy out of the Windows registry and fail
        # every call to 127.0.0.1 the moment a VPN is switched on.
        client_kwargs = httpx_client_kwargs(endpoint)
        with httpx.Client(timeout=REQUEST_TIMEOUT, **client_kwargs) as client:
            budget = doc_token_limit
            while True:
                payload = build_rerank_payload(query, candidates, model, budget)
                try:
                    resp = client.post(endpoint, json=payload)
                    resp.raise_for_status()
                    break
                except Exception as send_err:
                    # No token count we can compute is the server's own.
                    # Collapsing punctuation removed the case we found; it
                    # cannot promise there is no other. Halving once turns a
                    # silent loss of reranking into a slower call.
                    if retried or not _is_oversize(send_err):
                        raise
                    retried = True
                    budget = max(64, budget // 2)
                    logger.warning(
                        f"[reranker] input rejected as too large, retrying at "
                        f"{budget} tokens per document"
                    )
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
            retried_smaller=retried,
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
            retried_smaller=retried,
        )
        return chunks[:top_k]


def rerank_sync(
    query: str, chunks: list[dict], top_k: int = 5, trace: dict | None = None
) -> list[dict]:
    """Public entry used by rag_server.tools (kept for API stability)."""
    return rerank_chunks(query, chunks, top_k, trace=trace)
