"""
Standalone indexer - runs as a subprocess.
Incorporates self-healing hash caching, parent chunks, and rules extraction.
"""
from __future__ import annotations
import hashlib
import sys
import time
import argparse
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def configure_process_io() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_indexer_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index a file or folder into Flying RAG.")
    parser.add_argument("target", type=Path, help="File or folder to index")
    parser.add_argument("--force", action="store_true", help="Ignore SHA skip and reprocess unchanged files")
    parser.add_argument("--exclude-ext", type=str, nargs="*", help="File extensions to exclude (e.g. .dwg .exe)")
    parser.add_argument(
        "--max-file-mb",
        type=float,
        default=0.0,
        help="Skip files larger than this many MB (0 = no limit). Huge PDFs can "
             "stall the parser for hours; skipping keeps the run moving.",
    )
    parser.add_argument(
        "--no-cache",
        dest="use_cache",
        action="store_false",
        help="Do not reuse cached chunk vectors; recompute all embeddings",
    )
    parser.set_defaults(use_cache=True)
    return parser.parse_args(argv)


def should_skip_file(changed: bool, force: bool) -> bool:
    return (not force) and (not changed)


def get_file_cooldown_sec(cfg: dict) -> float:
    return max(0.0, float(cfg.get("indexing", {}).get("file_cooldown_sec", 0.0)))


def prepare_chunks_for_upsert(
    chunks: list,
    meta_path: Path,
    lance_path: Path,
    embed_fn,
    get_cached_chunk_fn,
    get_chunk_vector_fn,
    use_cache: bool = True,
) -> tuple[list, list, list[tuple]]:
    """Build a full-document upsert payload while reusing cached vectors."""
    from embedder.batcher import EmbeddingResult

    chunks_for_upsert = []
    embeddings_for_upsert = []
    chunks_to_embed = []
    new_cache_items = []

    for c in chunks:
        c_hash = _chunk_hash(c.text)
        cached = get_cached_chunk_fn(meta_path, c_hash) if use_cache else None
        cached_vector = None

        if cached:
            cached_vector = get_chunk_vector_fn(lance_path, cached["vector_id"])

        if cached and cached_vector is not None:
            c.chunk_id = cached["vector_id"]
            embeddings_for_upsert.append(
                EmbeddingResult(chunk_id=c.chunk_id, embedding=cached_vector)
            )
        else:
            chunks_to_embed.append((c, c_hash))

        chunks_for_upsert.append(c)

    if chunks_to_embed:
        new_embeddings = embed_fn([item[0] for item in chunks_to_embed])
        embeddings_for_upsert.extend(new_embeddings)
        new_cache_items.extend((c, c_hash) for c, c_hash in chunks_to_embed)

    return chunks_for_upsert, embeddings_for_upsert, new_cache_items


prepare_chunks_for_upsert.chunk_hash = _chunk_hash


def main() -> None:
    configure_process_io()
    args = parse_indexer_args()

    target = args.target
    if not target.exists():
        log(f"[indexer] ERROR: path not found: {target}")
        sys.exit(1)

    from config_loader import require_config
    cfg = require_config()

    lance_path = ROOT / cfg["storage"]["lancedb_path"]
    meta_path  = ROOT / cfg["storage"]["metadata_db"]
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    lance_path.mkdir(parents=True, exist_ok=True)

    from parsers.dispatcher import get_parser
    from chunker.semantic import chunk_document
    from embedder.batcher import embed_chunks
    from storage.vector_store import upsert_chunks, get_chunk_vector
    from storage.metadata_db import (
        upsert_file, init_db, file_changed, update_indexing_progress,
        save_parent_chunk, save_cached_chunk, get_cached_chunk,
        save_engineering_rule, delete_file
    )
    from storage.rules_extractor import StructuredRulesExtractor

    init_db(meta_path)

    # Index contract: refuse to append vectors from a second embedding model or
    # a changed chunker into a store built with another one. Dimension alone is
    # not identity — Qwen3-Embedding-0.6B and bge-m3 are both 1024 wide.
    from chunker.semantic import CHUNKER_ID, chunk_params
    from embedder.client import _DEFAULT_PROVIDER
    from embedder.contract import EmbeddingContractError
    from storage.index_manifest import ensure_manifest

    try:
        _DEFAULT_PROVIDER.verify_contract()
    except EmbeddingContractError as ce:
        log(f"[indexer] BLOCKED {ce.code}: {ce.detail}")
        log("[indexer] load the configured model in the embedding server, or "
            "index into a separate store")
        sys.exit(2)

    manifest, manifest_code, manifest_detail = ensure_manifest(
        lance_path,
        model=_DEFAULT_PROVIDER.get_model_name(),
        dimension=_DEFAULT_PROVIDER.get_dimension(),
        chunker=CHUNKER_ID,
        chunk_params=chunk_params(),
    )
    if manifest_code:
        log(f"[indexer] BLOCKED {manifest_code}: {manifest_detail}")
        log("[indexer] rebuild the store, or point storage.lancedb_path at a new one")
        sys.exit(2)
    log(f"[indexer] index contract OK: {manifest.get('model')} "
        f"dim={manifest.get('dimension')} chunker={manifest.get('chunker')}")

    rules_extractor = StructuredRulesExtractor()
    file_cooldown_sec = get_file_cooldown_sec(cfg)

    # Determine dataset by path
    datasets_cfg = cfg.get("datasets", {})
    def detect_dataset(path: Path) -> str:
        path_str = str(path).replace("\\", "/")
        for ds_name, ds_cfg in datasets_cfg.items():
            if ds_name == "default":
                continue
            for p in ds_cfg.get("paths", []):
                if p.replace("\\", "/") in path_str:
                    return ds_name
        return datasets_cfg.get("default", "normative")

    target_dataset = detect_dataset(target)
    log(f"[indexer] dataset={target_dataset}")

    exclude_exts = set(ext.lower() if ext.startswith('.') else f".{ext.lower()}" for ext in args.exclude_ext) if args.exclude_ext else set()
    files = [target] if target.is_file() else sorted(
        f for f in target.rglob("*") if f.is_file() and f.suffix.lower() not in exclude_exts
    )

    # Size gate: huge PDFs can stall the parser (text+table extraction) for hours.
    if args.max_file_mb and args.max_file_mb > 0:
        kept = []
        for f in files:
            try:
                mb = f.stat().st_size / (1024 * 1024)
            except OSError:
                mb = 0.0
            if mb > args.max_file_mb:
                log(f"[indexer] skip oversized ({mb:.0f}MB > {args.max_file_mb:.0f}MB): {f.name[:50]}")
            else:
                kept.append(f)
        files = kept

    log(f"[indexer] target={target} files={len(files)}")
    update_indexing_progress(meta_path, str(target), len(files), 0, "indexing", "")
    total, skipped, errors = 0, 0, []
    t0 = time.time()

    for i, fp in enumerate(files, 1):
        parser = get_parser(fp)
        if parser is None:
            update_indexing_progress(meta_path, str(target), len(files), i, "indexing", fp.name)
            continue
        try:
            sha = hashlib.sha256(fp.read_bytes()).hexdigest()[:16]
            changed = file_changed(meta_path, str(fp), sha)
            if should_skip_file(changed=changed, force=args.force):
                skipped += 1
                log(f"[indexer] [{i}/{len(files)}] skip unchanged: {fp.name[:50]}")
                update_indexing_progress(meta_path, str(target), len(files), i, "indexing", fp.name)
                continue

            doc = parser(fp)
            if not doc or not doc.text.strip():
                log(f"[indexer] [{i}/{len(files)}] skip empty: {fp.name[:50]}")
                update_indexing_progress(meta_path, str(target), len(files), i, "indexing", fp.name)
                continue

            # Clear old records first
            delete_file(meta_path, str(fp))

            chunks = chunk_document(doc)
            file_dataset = detect_dataset(fp)
            
            # Save parent chunks first
            for c in chunks:
                c.metadata["namespace"] = file_dataset
                p_id = c.metadata.get("parent_id")
                p_text = c.metadata.get("parent_text")
                if p_id and p_text:
                    save_parent_chunk(meta_path, p_id, str(fp), p_text)

            chunks_for_upsert, embs, new_cache_items = prepare_chunks_for_upsert(
                chunks,
                meta_path,
                lance_path,
                embed_fn=embed_chunks,
                get_cached_chunk_fn=get_cached_chunk,
                get_chunk_vector_fn=get_chunk_vector,
                use_cache=args.use_cache,
            )

            new_n = upsert_chunks(lance_path, chunks_for_upsert, embs)
            for c, c_hash in new_cache_items:
                save_cached_chunk(meta_path, c_hash, c.chunk_id, c.metadata.get("parent_id", c.chunk_id))

            # Extract rules if normative in parallel
            # (skip entirely when disabled — must not delete existing rules)
            if file_dataset == "normative" and getattr(rules_extractor, "enabled", True):
                from concurrent.futures import ThreadPoolExecutor, as_completed
                try:
                    from storage.metadata_db import delete_engineering_rules
                    removed = delete_engineering_rules(meta_path, str(fp))
                    if removed:
                        log(f"[indexer] Cleared {removed} stale rules for {fp.name}")
                except Exception as de:
                    log(f"[indexer] Failed to clear stale rules: {de}")
                def process_chunk(c):
                    try:
                        return c, rules_extractor.extract_rules(c.text, c.doc_id, str(fp), c.chunk_id)
                    except Exception as re_err:
                        log(f"[indexer] Rules extraction failed for chunk {c.chunk_id}: {re_err}")
                        return c, []
                max_workers = getattr(rules_extractor, "max_workers", 1)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(process_chunk, c) for c in chunks]
                    for fut in as_completed(futures):
                        c, rules = fut.result()
                        for r in rules:
                            try:
                                save_engineering_rule(
                                    meta_path, str(fp), c.chunk_id, c.text,
                                    r.get("subject"), r.get("parameter"), r.get("operator"),
                                r.get("value"), r.get("unit"), r.get("condition")
                            )
                            except Exception as db_err:
                                log(f"[indexer] Failed to save rule: {db_err}")
            # A file whose scanned pages could not be recovered is indexed, but
            # it is not "indexed" in the same sense as a complete one — record
            # that, so an incomplete corpus is visible instead of assumed whole.
            ocr_report = (getattr(doc, "extra", None) or {}).get("ocr") or {}
            file_status = "indexed"
            if ocr_report.get("status") == "partial":
                file_status = "indexed_partial_ocr"
                log(f"[indexer] [{i}/{len(files)}] PARTIAL OCR {fp.name[:40]}: "
                    f"pages not recovered: {ocr_report.get('unrecovered_pages')}")
            elif ocr_report.get("status") == "failed":
                file_status = "indexed_ocr_failed"
                log(f"[indexer] [{i}/{len(files)}] OCR FAILED {fp.name[:40]}: "
                    f"{ocr_report.get('error_code', 'unknown')}")

            upsert_file(meta_path, str(fp), fp.name, doc.format, sha,
                        doc.created_at, doc.modified_at, len(chunks),
                        status=file_status, dataset=file_dataset)

            total += len(chunks)
            log(f"[indexer] [{i}/{len(files)}] OK {len(chunks):4d} chunks (new={new_n}) [{file_dataset}]: {fp.name[:50]}")

            # ColPali visual embeddings (dormant unless config colpali.enabled).
            # Isolated store; no-op for old files / non-PDF / missing deps.
            try:
                from embedder.colpali import maybe_index_visual
                pages = maybe_index_visual(fp)
                if pages:
                    log(f"[indexer] [{i}/{len(files)}] colpali: {pages} pages -> visual store")
            except Exception as ce:
                log(f"[indexer] colpali WARN: {ce}")

            # Structured table rows -> Parquet (for deterministic sum_table_values).
            # Enabled by default (config tables.parquet_enabled); no-op for non-tables.
            try:
                from rag_server.table_parquet import maybe_write_for_indexer
                n_tab = maybe_write_for_indexer(str(fp))
                if n_tab:
                    log(f"[indexer] [{i}/{len(files)}] tables: {n_tab} rows -> parquet")
            except Exception as te:
                log(f"[indexer] table parquet WARN: {te}")

            # Semantic graph build
            if len(chunks) > 0:
                try:
                    from storage.graph import add_document_edges, init_graph
                    init_graph(meta_path)
                    doc_id = chunks[0].doc_id
                    edges = add_document_edges(lance_path, meta_path, doc_id, top_k=5)
                    if edges:
                        log(f"[indexer] [{i}/{len(files)}] graph: {edges} edges for {doc_id}")
                except Exception as ge:
                    log(f"[indexer] graph WARN: {ge}")
            
            update_indexing_progress(meta_path, str(target), len(files), i, "indexing", fp.name)
            if file_cooldown_sec > 0:
                time.sleep(file_cooldown_sec)

        except Exception as e:
            errors.append(f"{fp.name}: {e}")
            log(f"[indexer] [{i}/{len(files)}] ERR {fp.name[:40]}: {e}")
            update_indexing_progress(meta_path, str(target), len(files), i, "indexing", fp.name)
            if file_cooldown_sec > 0:
                time.sleep(file_cooldown_sec)

    # Update FTS
    if total > 0:
        try:
            from storage.vector_store import ensure_fts_index
            ensure_fts_index(lance_path)
        except Exception as fe:
            log(f"[indexer] FTS index update WARN: {fe}")

    update_indexing_progress(meta_path, str(target), len(files), len(files), "completed", "")
    duration = int(time.time() - t0)
    log(f"[indexer] DONE chunks={total} skipped={skipped} errors={len(errors)} time={duration}s")


if __name__ == "__main__":
    main()
