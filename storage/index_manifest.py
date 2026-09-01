"""Index manifest — what the corpus was actually built with.

The LanceDB table name only carries the vector dimension, and dimension is not
identity: two different embedding models with the same width produce vectors
that must never be compared. The manifest records the rest of the contract —
model, chunker and its parameters — next to the store, so a later run can prove
it is about to search a corpus it is compatible with.

Deliberately small: one JSON file, single writer, no attestation ceremony. The
runtime here has one indexer process and one MCP process on one machine.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from embedder.contract import models_compatible

MANIFEST_SCHEMA = "flying_rag.index_manifest.v1"
MANIFEST_NAME = "index_manifest.json"


def manifest_path(lance_path: Path) -> Path:
    return Path(lance_path) / MANIFEST_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_manifest(
    *,
    model: str,
    dimension: int,
    chunker: str,
    chunk_params: dict | None = None,
    created_at: str | None = None,
) -> dict:
    return {
        "schema": MANIFEST_SCHEMA,
        "model": str(model),
        "dimension": int(dimension),
        "chunker": str(chunker),
        "chunk_params": dict(chunk_params or {}),
        "created_at": created_at or _now(),
        "updated_at": _now(),
    }


def load_manifest(lance_path: Path) -> dict | None:
    path = manifest_path(lance_path)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def write_manifest(lance_path: Path, manifest: dict) -> Path:
    """Atomically replace the manifest (temp file + rename)."""
    path = manifest_path(lance_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(path)
    return path


def verify_manifest(
    manifest: dict | None,
    *,
    model: str,
    dimension: int,
    chunker: str | None = None,
) -> tuple[str, str, str]:
    """Compare a live runtime against a stored manifest.

    Returns ``(status, error_code, detail)``. Status is ``ok``, ``absent``
    (nothing indexed under a manifest yet — not an error) or ``mismatch``.
    A chunker change is reported through the same channel but as its own code,
    because it degrades context quality without invalidating the vectors.
    """
    if not manifest:
        return "absent", "", "no index manifest recorded yet"

    stored_model = str(manifest.get("model") or "")
    stored_dim = manifest.get("dimension")
    if not models_compatible(stored_model, model):
        return (
            "mismatch",
            "embedding_contract_mismatch",
            f"index built with {stored_model!r}, runtime uses {model!r}",
        )
    if isinstance(stored_dim, int) and int(dimension) != stored_dim:
        return (
            "mismatch",
            "embedding_dimension_mismatch",
            f"index built with dim {stored_dim}, runtime reports {dimension}",
        )
    stored_chunker = str(manifest.get("chunker") or "")
    if chunker and stored_chunker and stored_chunker != str(chunker):
        return (
            "mismatch",
            "chunker_contract_mismatch",
            f"index built with chunker {stored_chunker!r}, runtime uses {chunker!r}",
        )
    return "ok", "", stored_model


def ensure_manifest(
    lance_path: Path,
    *,
    model: str,
    dimension: int,
    chunker: str,
    chunk_params: dict | None = None,
) -> tuple[dict, str, str]:
    """Read-or-create the manifest for an indexing run.

    Returns ``(manifest, error_code, detail)``. On a mismatch nothing is
    written and the caller must stop: appending vectors from a second model
    into the same store is exactly the corruption this file exists to prevent.
    """
    existing = load_manifest(lance_path)
    status, code, detail = verify_manifest(
        existing, model=model, dimension=dimension, chunker=chunker
    )
    if status == "mismatch":
        return existing or {}, code, detail
    if status == "absent":
        manifest = build_manifest(
            model=model, dimension=dimension,
            chunker=chunker, chunk_params=chunk_params,
        )
        write_manifest(lance_path, manifest)
        return manifest, "", "manifest created"

    manifest = dict(existing or {})
    manifest["updated_at"] = _now()
    if chunk_params:
        manifest["chunk_params"] = dict(chunk_params)
    write_manifest(lance_path, manifest)
    return manifest, "", "manifest verified"
