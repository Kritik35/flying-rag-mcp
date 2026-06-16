from __future__ import annotations
from dataclasses import dataclass, field

import sys
import time
import yaml
from pathlib import Path
from embedder.client import get_embeddings

BATCH_SIZE = 32
DEFAULT_BATCH_COOLDOWN_SEC = 0.0


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class EmbeddingResult:
    chunk_id: str
    embedding: list[float]


@dataclass(frozen=True)
class BatchSettings:
    batch_size: int = BATCH_SIZE
    cooldown_sec: float = DEFAULT_BATCH_COOLDOWN_SEC


def load_config() -> dict:
    config_path = Path("config.yaml")
    if not config_path.exists():
        config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}
    return {}


def get_batch_settings() -> BatchSettings:
    cfg = load_config()
    lemonade_cfg = cfg.get("lemonade", {})
    indexing_cfg = cfg.get("indexing", {})
    batch_size = int(lemonade_cfg.get("batch_size", BATCH_SIZE))
    cooldown_sec = float(indexing_cfg.get("batch_cooldown_sec", DEFAULT_BATCH_COOLDOWN_SEC))
    return BatchSettings(batch_size=max(1, batch_size), cooldown_sec=max(0.0, cooldown_sec))


def embed_chunks(chunks: list[Chunk]) -> list[EmbeddingResult]:
    """
    Разбить chunks на батчи по BATCH_SIZE.
    Если батч не удался — бросить исключение, чтобы остановить индексатор.
    """
    from embedder.thermal import ThermalController
    thermal_ctrl = ThermalController()

    results: list[EmbeddingResult] = []
    settings = get_batch_settings()
    batch_size = settings.batch_size
    total = (len(chunks) + batch_size - 1) // batch_size
    for i in range(total):
        batch = chunks[i * batch_size:(i + 1) * batch_size]
        print(f"Batch {i+1}/{total}: {len(batch)} chunks", file=sys.stderr)
        # get_embeddings already retries, so if it fails, it raises an error.
        embeddings = get_embeddings([c.text for c in batch])
        for chunk, emb in zip(batch, embeddings):
            results.append(EmbeddingResult(chunk_id=chunk.chunk_id, embedding=emb))
        
        # Determine cooldown dynamically (thermal/CPU load aware)
        cooldown = thermal_ctrl.get_cooldown()
        if cooldown > 0 and i < total - 1:
            time.sleep(cooldown)
    return results


if __name__ == "__main__":
    import inspect
    chunks = [Chunk("abc", f"abc_{i:03d}", f"text {i}") for i in range(70)]
    print(f"Input: {len(chunks)} chunks")
    print(f"Expected batches: {(len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE}")
    sig = inspect.signature(embed_chunks)
    assert "chunks" in sig.parameters
    print("OK embed_chunks signature correct")
    print("embedder/batcher.py ready")
