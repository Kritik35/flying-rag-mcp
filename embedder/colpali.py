# -*- coding: utf-8 -*-
"""ColPali — vision-based retrieval for drawings & scanned/visual PDFs.

DORMANT BY DEFAULT. Controlled by config.yaml -> colpali.enabled (false).
Everything here is ADDITIVE and isolated:

  * Visual embeddings go into a SEPARATE LanceDB store (data/lancedb_colpali),
    never into the text table documents_1024. The existing index and the old
    metadata.db keep working untouched — full backward compatibility.
  * The indexer hook maybe_index_visual() returns immediately when disabled, so
    old files are never reprocessed. Once enabled, only files indexed AFTER that
    point get visual embeddings ("new files processed with it").
  * Any missing dependency / model / key degrades to a logged skip — indexing
    never breaks.

WHAT MODEL DOES COLPALI NEED?
  ColPali is a family of late-interaction *vision* retrievers (ColBERT-style,
  but over image patches instead of tokens). Pick ONE:

  Local (GPU, via `pip install colpali-engine`):
    * vidore/colqwen2-v1.0   — Qwen2-VL-2B backbone. BEST for Russian drawings
                               (strong multilingual / Cyrillic, OCR-free).  <-- default
    * vidore/colpali-v1.3    — PaliGemma-3B backbone (the original).
    * vidore/colqwen2.5-v0.2 — newer Qwen2.5-VL backbone.
    NPU note: these are multi-vector PyTorch vision models; FastFlowLM/lemonade
    do not serve them today, so "local" here means GPU. The NPU stays dedicated
    to the rules/HyDE text LLM.

  API (no local GPU needed, multimodal embeddings):
    * voyage-multimodal-3  (Voyage AI)   — env VOYAGE_API_KEY
    * jina-embeddings-v4   (Jina)        — env JINA_API_KEY  (supports late-interaction)
    * embed-v4.0           (Cohere)      — env COHERE_API_KEY
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
_WARNED = False


def _cfg() -> dict:
    try:
        import yaml
        with open(ROOT / "config.yaml", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("colpali", {}) or {}
    except Exception:
        return {}


def is_enabled() -> bool:
    cfg = _cfg()
    return bool(cfg.get("enabled", False)) and cfg.get("backend", "off") != "off"


def _store_path() -> Path:
    cfg = _cfg()
    return ROOT / cfg.get("store", "data/lancedb_colpali")


def _render_pages(pdf_path: Path, max_pages: int, dpi: int):
    """Render the first `max_pages` pages to PIL images (PyMuPDF)."""
    import fitz  # pymupdf
    from PIL import Image

    images = []
    doc = fitz.open(str(pdf_path))
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    finally:
        doc.close()
    return images


def _embed_local(images, model_name: str):
    """Multi-vector embeddings via colpali-engine; mean-pooled for storage."""
    import torch
    from colpali_engine.models import ColQwen2, ColQwen2Processor

    model = ColQwen2.from_pretrained(
        model_name, torch_dtype=torch.float16, device_map="auto"
    ).eval()
    proc = ColQwen2Processor.from_pretrained(model_name)
    batch = proc.process_images(images).to(model.device)
    with torch.no_grad():
        out = model(**batch)              # (B, seq, dim) multi-vector
    pooled = out.mean(dim=1)              # (B, dim) — simplified single-vector store
    return [v.float().cpu().tolist() for v in pooled]


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _env_key(*names: str) -> str | None:
    """Read a key from os.environ or, as a fallback, directly from .env
    (the MCP/indexer process may not auto-load dotenv)."""
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    env_file = ROOT / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, _, val = line.partition("=")
                    if k.strip() in names:
                        return val.strip()
        except Exception:
            pass
    return None


def _img_to_b64(img, max_side: int = 768, quality: int = 80) -> str:
    """Downscale (drawings are huge) and JPEG-encode to base64 for upload."""
    import base64
    import io

    im = img.copy()
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def _jina_embed(items: list[dict], task: str, key: str, model: str,
                timeout: float = 60.0, retries: int = 3) -> list:
    """Call Jina embeddings API for a batch of {"text":..} / {"image":b64}.

    Uses urllib with an EXPLICIT empty ProxyHandler (the WinINET SOCKS proxy is
    dead — see lessons; requests' trust_env is not always enough on Windows and
    large uploads can hit WSAECONNABORTED 10053). Retries transient aborts.
    """
    import json
    import time
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    payload = json.dumps({"model": model, "task": task, "input": items}).encode()
    req = urllib.request.Request(
        "https://api.jina.ai/v1/embeddings", data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}", "User-Agent": _UA},
        method="POST",
    )
    last = None
    for attempt in range(retries):
        try:
            with opener.open(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            return [d["embedding"] for d in data["data"]]
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def _jina_multivec(items: list[dict], task: str, key: str, model: str,
                   timeout: float = 90.0, retries: int = 3):
    """Like _jina_embed but returns late-interaction multi-vectors:
    one (n_tokens|n_patches, 128) array per input item (true ColPali)."""
    import json
    import time
    import urllib.request

    import numpy as np

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    payload = json.dumps({"model": model, "task": task,
                          "return_multivector": True, "input": items}).encode()
    req = urllib.request.Request(
        "https://api.jina.ai/v1/embeddings", data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}", "User-Agent": _UA},
        method="POST",
    )
    last = None
    for attempt in range(retries):
        try:
            with opener.open(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            return [np.asarray(d["embeddings"], dtype="float32") for d in data["data"]]
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def _mv_dir() -> Path:
    return _store_path().parent / (_store_path().name + "_mv")


def _mv_manifest() -> Path:
    return _mv_dir() / "manifest.jsonl"


def _mv_index_pages(pdf_path: Path, mats: list) -> int:
    """Store one .npy multivector per page + a jsonl manifest line. Idempotent
    per source_path (drops previous pages for the same file first)."""
    import hashlib
    import json

    import numpy as np

    d = _mv_dir()
    d.mkdir(parents=True, exist_ok=True)
    man = _mv_manifest()
    # drop previous entries for this file
    kept = []
    if man.exists():
        for line in man.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("source_path") == str(pdf_path):
                npy = d / rec["npy"]
                if npy.exists():
                    npy.unlink()
            else:
                kept.append(line)
    lines = list(kept)
    for page, mat in enumerate(mats):
        h = hashlib.sha1(f"{pdf_path}:{page}".encode("utf-8")).hexdigest()[:16]
        np.save(d / f"{h}.npy", mat)
        lines.append(json.dumps({
            "source_path": str(pdf_path), "page": page,
            "file_name": pdf_path.name, "npy": f"{h}.npy",
        }, ensure_ascii=False))
    man.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(mats)


def _mv_search(query_mat, top_k: int) -> list[dict]:
    """Late-interaction MaxSim ranking over stored page multivectors:
    score(page) = sum_i max_j (q_i . p_j)."""
    import json

    import numpy as np

    man = _mv_manifest()
    if not man.exists():
        return []
    def _l2norm(m):
        m = np.asarray(m, dtype="float32")
        n = np.linalg.norm(m, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return m / n

    q = _l2norm(query_mat)                               # (Q,128) unit rows
    scored = []
    d = _mv_dir()
    for line in man.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        npy = d / rec["npy"]
        if not npy.exists():
            continue
        p = _l2norm(np.load(npy))                        # (P,128) unit rows
        sim = q @ p.T                                    # (Q,P) cosines
        # ColBERT MaxSim, mean over query tokens -> comparable across pages.
        score = float(sim.max(axis=1).mean())
        scored.append((score, rec))
    scored.sort(key=lambda x: -x[0])
    return [
        {"source_path": r["source_path"], "page": r["page"],
         "file_name": r["file_name"], "score": s}
        for s, r in scored[:top_k]
    ]


def _embed_api(images, cfg: dict):
    """Multimodal page embeddings via a provider API. Returns None on no key /
    unsupported provider so the caller skips gracefully."""
    provider = (cfg.get("api_provider") or "jina").lower()
    if provider == "jina":
        key = cfg.get("api_key") or _env_key("JINA_API_KEY")
        if not key:
            print("[colpali] jina: no JINA_API_KEY; skipping", file=sys.stderr)
            return None
        model = cfg.get("api_model", "jina-embeddings-v4")
        items = [{"image": _img_to_b64(im)} for im in images]
        # Jina caps inputs per request; chunk to be safe.
        out = []
        for i in range(0, len(items), 8):
            out.extend(_jina_embed(items[i:i + 8], "retrieval.passage", key, model))
        return out
    # voyage / cohere: not wired yet — refuse rather than send a bad request.
    print(f"[colpali] api provider '{provider}' not wired yet; skipping", file=sys.stderr)
    return None


def search_visual(query: str, top_k: int = 5) -> list[dict]:
    """Query the isolated ColPali visual store with a text query (cross-modal).
    Returns [] if the store/backend is unavailable."""
    cfg = _cfg()
    provider = (cfg.get("api_provider") or "jina").lower()
    store = _store_path()
    if not store.exists():
        return []
    try:
        if provider == "jina":
            key = cfg.get("api_key") or _env_key("JINA_API_KEY")
            if not key:
                return []
            model = cfg.get("api_model", "jina-embeddings-v4")
            # Late-interaction (true ColPali): MaxSim over stored multivectors.
            if cfg.get("late_interaction"):
                qmat = _jina_multivec([{"text": query}], "retrieval.query", key, model)[0]
                return _mv_search(qmat, top_k)
            qv = _jina_embed([{"text": query}], "retrieval.query", key, model)[0]
        else:
            return []
        import lancedb
        db = lancedb.connect(str(store))
        if "colpali_pages" not in db.table_names():
            return []
        tbl = db.open_table("colpali_pages")
        # Jina embeddings are direction-based -> compare with cosine, not L2
        # (L2 conflates vector magnitude and mis-ranks cross-modal hits).
        res = tbl.search(qv).metric("cosine").limit(top_k).to_list()
        return [
            {"source_path": r.get("source_path"), "page": r.get("page"),
             "file_name": r.get("file_name"), "score": r.get("_distance")}
            for r in res
        ]
    except Exception as e:
        print(f"[colpali] search_visual skipped: {e}", file=sys.stderr)
        return []


def maybe_index_visual(pdf_path: Path) -> int:
    """Index a PDF's pages into the visual store. Returns #pages indexed.

    No-op (returns 0) when ColPali is disabled or the file is not a PDF, or on
    any failure. Safe to call from the indexer for every file.
    """
    global _WARNED
    if not is_enabled():
        return 0
    pdf_path = Path(pdf_path)
    if pdf_path.suffix.lower() != ".pdf":
        return 0

    cfg = _cfg()
    backend = cfg.get("backend", "off")
    model_name = cfg.get("model", "vidore/colqwen2-v1.0")
    max_pages = int(cfg.get("max_pages", 30))
    dpi = int(cfg.get("dpi", 120))

    try:
        images = _render_pages(pdf_path, max_pages=max_pages, dpi=dpi)
        if not images:
            return 0
        # Late-interaction (true ColPali): store per-page multivectors for MaxSim.
        if backend == "api" and cfg.get("late_interaction") \
                and (cfg.get("api_provider") or "jina").lower() == "jina":
            key = cfg.get("api_key") or _env_key("JINA_API_KEY")
            if not key:
                print("[colpali] jina: no JINA_API_KEY; skipping", file=sys.stderr)
                return 0
            model = cfg.get("api_model", "jina-embeddings-v4")
            side = int(cfg.get("img_max_side", 768))     # higher preserves drawing text
            mats = []
            items = [{"image": _img_to_b64(im, max_side=side)} for im in images]
            for i in range(0, len(items), 4):
                mats.extend(_jina_multivec(items[i:i + 4], "retrieval.passage", key, model))
            return _mv_index_pages(pdf_path, mats)
        if backend == "local":
            vectors = _embed_local(images, model_name)
        elif backend == "api":
            vectors = _embed_api(images, cfg)
        else:
            return 0
        if not vectors:
            return 0
        return _write_store(pdf_path, vectors)
    except ImportError as e:
        if not _WARNED:
            print(f"[colpali] backend '{backend}' deps missing ({e}); "
                  f"install colpali-engine/torch or use api backend. Skipping.",
                  file=sys.stderr)
            _WARNED = True
        return 0
    except Exception as e:
        print(f"[colpali] visual index skipped for {pdf_path.name}: {e}", file=sys.stderr)
        return 0


def _write_store(pdf_path: Path, vectors: list) -> int:
    """Append one row per page to the isolated visual LanceDB store."""
    import lancedb
    import pyarrow as pa

    store = _store_path()
    store.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(store))
    rows = [
        {"source_path": str(pdf_path), "page": i,
         "file_name": pdf_path.name, "vector": vec}
        for i, vec in enumerate(vectors)
    ]
    if "colpali_pages" in db.table_names():
        tbl = db.open_table("colpali_pages")
        # replace any previous pages for this file (idempotent re-index).
        # Filter via parameterised-safe literal; Windows backslashes must be
        # doubled for the Lance SQL string literal. Never let delete break add.
        try:
            safe = str(pdf_path).replace("\\", "\\\\").replace("'", "''")
            tbl.delete(f"source_path = '{safe}'")
        except Exception as de:
            print(f"[colpali] store delete skipped: {de}", file=sys.stderr)
        tbl.add(rows)
    else:
        db.create_table("colpali_pages", data=rows)
    return len(rows)
