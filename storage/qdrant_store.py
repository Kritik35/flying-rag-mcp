"""The Les Qdrant collection as a second store for the same retrieval pipeline.

Les keeps its corpus in Qdrant (`les_rag`, an alias to the current generation):
a dense vector from the same model we use — Qwen3-Embedding-0.6B through
llama.cpp, checked: re-embedding Les points with our client gives cosine
0.9992-0.9995 — and a lexical sparse vector, plus a node hierarchy in which
only `evidence` nodes carry passages and `navigation` nodes are headings.

The bridge that stood here queried an unnamed vector, then one named "text";
the collection has neither, so every call came back empty, and had it worked it
would have returned navigation stubs like "Page 113 part 1/3" and bypassed the
planner, reranker and quality steps. `search` here has the signature and the
row and trace format of `storage.vector_store.search`, so `search_documents`
runs the same pipeline over either store.

Hybrid as Les does it: a dense prefetch and a sparse prefetch fused by RRF,
evidence nodes only. The sparse query is encoded exactly as Les encodes its
documents (`encode_bm25`, ported from Les `backend/inference/bm25_sparse.py`
and `proxy/services/lexical_index_service.py`): a different tokeniser would
produce term ids the collection has never seen.
"""
from __future__ import annotations

import re
import sys
import zlib
from collections import Counter
from functools import lru_cache
from typing import Any, Optional

# ── Les-compatible BM25 sparse encoding ────────────────────────────────────

_TOKEN_RE = re.compile(r"[0-9a-zа-яё.-]{2,}", re.IGNORECASE)
_NO_STEM_WORDS = {
    "какие", "какой", "какая", "какое", "каких", "каким", "какими",
    "где", "смотреть", "требования", "нормы", "норма", "требование",
    "найти", "пункт", "раздел", "свод", "правил", "гост", "сп",
    "случаях", "случае", "случай", "выполнять", "выполнение", "делать",
    "допускается", "допускать", "почему", "зачем", "что", "кто", "как",
    "когда", "куда", "откуда",
    "нужно", "должно", "следует", "необходимо", "быть", "может", "можно", "ли",
    "или", "для", "при", "под", "над", "все", "всех", "всеми", "чем", "тем", "только",
}
_ENDINGS = (
    "иями", "ям", "ыми", "ейший", "ейшая", "ейшее", "ейшие", "ейших",
    "ого", "его", "ому", "ему", "ыми", "ими", "ых", "их", "ою", "ею",
    "ая", "яя", "ое", "ее", "ые", "ие", "ым", "им", "ом", "ем", "ах", "ях",
    "ов", "ев", "ей", "ам", "ям", "ит", "ет", "ут", "ют", "ат", "ят", "ти",
    "а", "ев", "ов", "е", "и", "й", "о", "у", "ы", "ь", "я", "ю", "ию",
)
_DIGIT_RE = re.compile(r"\d")
_TECH_TOKEN_RE = re.compile(r"(?u)[A-ZА-ЯЁ0-9]+(?:[_./-][A-ZА-ЯЁ0-9]+)*")


def _stem(word: str) -> str:
    if not re.match(r"^[а-яё]+$", word):
        return word
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[:-len(ending)]
    return word


def les_tokenize(text: str) -> list[str]:
    out: list[str] = []
    source = str(text or "")
    for raw in _TOKEN_RE.findall(source.casefold().replace("ё", "е")):
        token = raw.strip(".-")
        if len(token) < 3 or token in _NO_STEM_WORDS:
            continue
        if _DIGIT_RE.search(token):
            out.append(token)
            continue
        stem = _stem(token) if len(token) >= 4 else token
        out.append(stem if len(stem) >= 3 and stem.isalpha() else token)
    if out:
        return out
    technical = []
    for raw in _TECH_TOKEN_RE.findall(source):
        token = raw.casefold().replace("ё", "е").strip("._/-")
        if token and any(ch.isalnum() for ch in token):
            technical.append(token)
    return technical


def encode_bm25(text: str) -> dict[int, float]:
    """Text → {crc32 term id: term frequency}; Qdrant applies IDF itself."""
    counts = Counter(zlib.crc32(t.encode("utf-8")) & 0x7FFFFFFF for t in les_tokenize(text))
    return {tid: float(tf) for tid, tf in counts.items()}


# ── store ──────────────────────────────────────────────────────────────────

DEFAULTS = {"qdrant_url": "http://127.0.0.1:6333", "collection_name": "les_rag"}


def settings() -> dict[str, Any]:
    from config_loader import load_config

    section = (load_config() or {}).get("les_integration") or {}
    return {**DEFAULTS, **section}


def is_enabled() -> bool:
    return bool(settings().get("enabled", False))


@lru_cache(maxsize=4)
def _client(url: str):
    from qdrant_client import QdrantClient

    # Local Qdrant: never through the machine's proxy (a VPN's SOCKS proxy in
    # the registry broke every call to 127.0.0.1). Scoped to this client
    # instead of rewriting the process environment as the old bridge did.
    return QdrantClient(url=url, timeout=15.0, check_compatibility=False, trust_env=False)


@lru_cache(maxsize=4)
def _vector_names(url: str, collection: str) -> tuple[str | None, str | None]:
    """(dense, sparse) vector names from the collection's own config."""
    info = _client(url).get_collection(collection)
    params = info.config.params
    vectors = params.vectors
    dense = None
    if isinstance(vectors, dict):
        dense = next(iter(vectors), None)
    sparse_cfg = params.sparse_vectors or {}
    sparse = next(iter(sparse_cfg), None) if isinstance(sparse_cfg, dict) else None
    return dense, sparse


def _dataset_filter(dataset: Optional[str]):
    """Our datasets mapped onto Les payload: norms are doc_type NORMATIVE."""
    from qdrant_client.http import models

    if not dataset:
        return [], []
    if dataset == "normative":
        return [models.FieldCondition(key="doc_type", match=models.MatchValue(value="NORMATIVE"))], []
    if dataset == "project":
        return [], [models.FieldCondition(key="doc_type", match=models.MatchValue(value="NORMATIVE"))]
    return [], []


def _row(point) -> dict:
    p = point.payload or {}
    text = str(p.get("text") or "")
    # Les stores the passage and a short window around it; the window is the
    # context Les itself shows, so it plays the part of our parent text.
    before, after = str(p.get("context_before") or ""), str(p.get("context_after") or "")
    context = "\n".join(s for s in (before, text, after) if s)
    file_path = str(p.get("file_name") or "")
    return {
        "chunk_id": str(point.id),
        "parent_id": str(p.get("parent_id") or point.id),
        "doc_id": str(p.get("doc_id") or ""),
        "text": context,
        "child_text": text,
        "context_source": "les_window" if (before or after) else "les_child",
        "context_chars": len(context),
        "source_path": file_path,
        "file_name": file_path.replace("\\", "/").rsplit("/", 1)[-1],
        "section": str(p.get("section_heading") or p.get("parent_heading") or ""),
        "score": round(float(point.score or 0.0), 4),
        "modified_at": None,
        "dataset": str(p.get("dataset_name") or ""),
    }


def search(db_path, query_embedding: list[float], top_k: int = 10,
           folder_filter: str | None = None, query_text: str | None = None,
           hybrid: bool = True, dataset: str | None = None, alpha: float = 0.7,
           trace: dict | None = None, meta_path=None, **_ignored) -> list[dict]:
    """Same contract as storage.vector_store.search, over the Les collection.

    `db_path`, `alpha` and `meta_path` belong to the LanceDB path and are
    ignored: fusion is RRF, as in Les, and the context comes with the point.
    `folder_filter` is applied to the file path after retrieval (the path is a
    keyword field in Les, which matches whole values only), over a wider pool.
    """
    from qdrant_client.http import models

    cfg = settings()
    url, collection = str(cfg["qdrant_url"]), str(cfg["collection_name"])
    client = _client(url)
    dense_name, sparse_name = _vector_names(url, collection)

    must, must_not = _dataset_filter(dataset)
    must.append(models.FieldCondition(key="node_role", match=models.MatchValue(value="evidence")))
    qfilter = models.Filter(must=must, must_not=must_not or None)
    wanted = top_k * (4 if folder_filter else 1)
    prefetch_limit = max(wanted * 2, 24)

    sparse = encode_bm25(query_text or "") if (hybrid and sparse_name) else {}
    channels = ["dense"]
    if sparse:
        points = client.query_points(
            collection_name=collection,
            prefetch=[
                models.Prefetch(query=query_embedding, using=dense_name,
                                filter=qfilter, limit=prefetch_limit),
                models.Prefetch(query=models.SparseVector(indices=list(sparse),
                                                          values=list(sparse.values())),
                                using=sparse_name, filter=qfilter, limit=prefetch_limit),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=wanted, with_payload=True,
        ).points
        channels.append("bm25_sparse")
        fusion, score_kind = "rrf", "rrf"
    else:
        points = client.query_points(
            collection_name=collection, query=query_embedding, using=dense_name,
            query_filter=qfilter, limit=wanted, with_payload=True,
        ).points
        fusion, score_kind = "none", "cosine"

    rows = [_row(p) for p in points if (p.payload or {}).get("text")]
    if folder_filter:
        needle = folder_filter.casefold()
        rows = [r for r in rows if needle in r["source_path"].casefold()]
    rows = rows[:top_k]

    if trace is not None:
        trace["store"] = "qdrant"
        trace["collection"] = collection
        trace["channels"] = channels
        trace["fusion"] = fusion
        trace["score_kind"] = score_kind
        trace["hybrid_requested"] = bool(hybrid)
        # A query with no indexable term (all stop words) has no sparse leg;
        # that is the query's shape, not a failing channel.
        trace["degraded"] = False
        trace["degraded_reason"] = "" if sparse or not hybrid else "no sparse terms in query"
        trace["parent_hydration"] = {
            "hydrated": sum(1 for r in rows if r["context_source"] == "les_window"),
            "fell_back_to_child": sum(1 for r in rows if r["context_source"] == "les_child"),
            "error": "",
        }
    return rows


@lru_cache(maxsize=8)
def _collection_model(url: str, collection: str) -> str:
    from qdrant_client.http import models

    points, _ = _client(url).scroll(
        collection_name=collection, limit=1, with_payload=["embedding_model_id"],
        scroll_filter=models.Filter(must=[models.FieldCondition(
            key="node_role", match=models.MatchValue(value="evidence"))]),
    )
    return str((points[0].payload or {}).get("embedding_model_id") or "") if points else ""


def verify_contract(model_name: str) -> tuple[str, str]:
    """('ok'|'unknown'|'mismatch', detail): the collection's model against ours.

    Les records the embedding model on every point; a collection built with
    another model must not be queried with our vectors.
    """
    from embedder.contract import models_compatible

    cfg = settings()
    stored = _collection_model(str(cfg["qdrant_url"]), str(cfg["collection_name"]))
    if not stored:
        return "unknown", "collection does not record its embedding model"
    if models_compatible(model_name, stored):
        return "ok", stored
    return "mismatch", f"collection built with {stored}, queries use {model_name}"


def health() -> dict:
    """What the store answers: reachable, collection behind the alias, layout."""
    cfg = settings()
    url, collection = str(cfg["qdrant_url"]), str(cfg["collection_name"])
    try:
        client = _client(url)
        info = client.get_collection(collection)
        dense, sparse = _vector_names(url, collection)
        return {"enabled": bool(cfg.get("enabled")), "url": url, "collection": collection,
                "points": info.points_count, "dense": dense, "sparse": sparse, "ok": True}
    except Exception as exc:  # noqa: BLE001 — reported, not raised
        print(f"[qdrant_store] health check failed: {exc}", file=sys.stderr)
        return {"enabled": bool(cfg.get("enabled")), "url": url, "collection": collection,
                "ok": False, "error": str(exc)}
