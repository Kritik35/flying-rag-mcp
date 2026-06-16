from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FakeChunk:
    doc_id: str
    chunk_id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class FakeEmbedding:
    chunk_id: str
    embedding: list[float]


class ParentChildPipelineTests(unittest.TestCase):
    def test_parent_child_constants_are_project_standard(self):
        from chunker.semantic import (
            MAX_CHILD_TOKENS,
            MAX_PARENT_TOKENS,
            MAX_TOKENS,
            OVERLAP_CHILD_TOKENS,
            OVERLAP_PARENT_TOKENS,
            OVERLAP_TOKENS,
        )

        self.assertEqual(MAX_PARENT_TOKENS, 1000)
        self.assertEqual(OVERLAP_PARENT_TOKENS, 100)
        self.assertEqual(MAX_CHILD_TOKENS, 150)
        self.assertEqual(OVERLAP_CHILD_TOKENS, 20)
        self.assertEqual(MAX_TOKENS, MAX_CHILD_TOKENS)
        self.assertEqual(OVERLAP_TOKENS, OVERLAP_CHILD_TOKENS)

    def test_prepare_chunks_for_upsert_includes_cached_and_new_chunks(self):
        from indexer import prepare_chunks_for_upsert

        cached_chunk = FakeChunk(
            "doc-a",
            "doc-a_c_0000",
            "cached text",
            {"parent_id": "doc-a_p_0000"},
        )
        new_chunk = FakeChunk(
            "doc-a",
            "doc-a_c_0001",
            "new text",
            {"parent_id": "doc-a_p_0000"},
        )
        chunks = [cached_chunk, new_chunk]

        calls = {"embed": []}

        def fake_get_cached_chunk(_meta_path, chunk_hash):
            if chunk_hash == prepare_chunks_for_upsert.chunk_hash("cached text"):
                return {"vector_id": "doc-a_c_cached", "parent_id": "doc-a_p_0000"}
            return None

        def fake_get_chunk_vector(_lance_path, vector_id):
            if vector_id == "doc-a_c_cached":
                return [0.25, 0.5, 0.75]
            return None

        def fake_embed_chunks(chunks_to_embed):
            calls["embed"].append([c.text for c in chunks_to_embed])
            return [FakeEmbedding(c.chunk_id, [1.0, 1.0, 1.0]) for c in chunks_to_embed]

        chunks_for_upsert, embeddings, new_cache_items = prepare_chunks_for_upsert(
            chunks,
            Path("meta.db"),
            Path("lancedb"),
            embed_fn=fake_embed_chunks,
            get_cached_chunk_fn=fake_get_cached_chunk,
            get_chunk_vector_fn=fake_get_chunk_vector,
        )

        self.assertEqual([c.text for c in chunks_for_upsert], ["cached text", "new text"])
        self.assertEqual(chunks_for_upsert[0].chunk_id, "doc-a_c_cached")
        self.assertEqual([e.chunk_id for e in embeddings], ["doc-a_c_cached", "doc-a_c_0001"])
        self.assertEqual(embeddings[0].embedding, [0.25, 0.5, 0.75])
        self.assertEqual(embeddings[1].embedding, [1.0, 1.0, 1.0])
        self.assertEqual(calls["embed"], [["new text"]])
        self.assertEqual([(c.text, h) for c, h in new_cache_items], [
            ("new text", prepare_chunks_for_upsert.chunk_hash("new text"))
        ])

    def test_prepare_chunks_for_upsert_no_cache_reembeds_cached_text(self):
        from indexer import prepare_chunks_for_upsert

        chunk = FakeChunk(
            "doc-a",
            "doc-a_c_0000",
            "cached text",
            {"parent_id": "doc-a_p_0000"},
        )
        calls = {"cache": 0, "vectors": 0, "embed": []}

        def fake_get_cached_chunk(_meta_path, _chunk_hash):
            calls["cache"] += 1
            return {"vector_id": "doc-a_c_cached", "parent_id": "doc-a_p_0000"}

        def fake_get_chunk_vector(_lance_path, _vector_id):
            calls["vectors"] += 1
            return [0.25, 0.5, 0.75]

        def fake_embed_chunks(chunks_to_embed):
            calls["embed"].append([c.text for c in chunks_to_embed])
            return [FakeEmbedding(c.chunk_id, [1.0, 1.0, 1.0]) for c in chunks_to_embed]

        _chunks_for_upsert, embeddings, new_cache_items = prepare_chunks_for_upsert(
            [chunk],
            Path("meta.db"),
            Path("lancedb"),
            embed_fn=fake_embed_chunks,
            get_cached_chunk_fn=fake_get_cached_chunk,
            get_chunk_vector_fn=fake_get_chunk_vector,
            use_cache=False,
        )

        self.assertEqual(calls["cache"], 0)
        self.assertEqual(calls["vectors"], 0)
        self.assertEqual(calls["embed"], [["cached text"]])
        self.assertEqual([e.chunk_id for e in embeddings], ["doc-a_c_0000"])
        self.assertEqual([(c.text, h) for c, h in new_cache_items], [
            ("cached text", prepare_chunks_for_upsert.chunk_hash("cached text"))
        ])

    def test_graph_uses_dimensional_documents_table_name(self):
        from storage.graph import _documents_table_name

        self.assertEqual(_documents_table_name(1024), "documents_1024")

    def test_indexer_force_flags_are_parsed(self):
        from indexer import parse_indexer_args

        args = parse_indexer_args(["--force", "--no-cache", r"C:\docs"])

        self.assertTrue(args.force)
        self.assertFalse(args.use_cache)
        self.assertEqual(str(args.target), r"C:\docs")

    def test_force_mode_disables_sha_skip(self):
        from indexer import should_skip_file

        self.assertTrue(should_skip_file(changed=False, force=False))
        self.assertFalse(should_skip_file(changed=False, force=True))
        self.assertFalse(should_skip_file(changed=True, force=False))

    def test_reindex_all_builds_forced_child_command(self):
        from reindex_all import build_indexer_command

        command = build_indexer_command(
            python_exe="python.exe",
            indexer_script="indexer.py",
            folder_path=Path(r"C:\docs"),
            force=True,
            use_cache=False,
        )

        self.assertEqual(command, [
            "python.exe",
            "indexer.py",
            "--force",
            "--no-cache",
            r"C:\docs",
        ])

    def test_lemonade_provider_reads_lemonade_config_section(self):
        import embedder.client as client

        original_load_config = client.load_config
        try:
            client.load_config = lambda: {
                "lemonade": {
                    "base_url": "http://localhost:13305/api/v1",
                    "model": "Qwen3-Embedding-0.6B-GGUF",
                    "timeout_sec": 45,
                }
            }

            provider = client.LemonadeEmbeddingProvider()
        finally:
            client.load_config = original_load_config

        self.assertEqual(provider.url, "http://localhost:13305/api/v1/embeddings")
        self.assertEqual(provider.model, "Qwen3-Embedding-0.6B-GGUF")
        self.assertEqual(provider.timeout, 45)

    def test_qwen_query_instruction_is_applied_only_to_queries(self):
        import embedder.client as client

        provider = client.LemonadeEmbeddingProvider()
        provider.model = "Qwen3-Embedding-0.6B-GGUF"

        query_texts = provider.prepare_texts(["противодымная вентиляция"], is_query=True)
        doc_texts = provider.prepare_texts(["противодымная вентиляция"], is_query=False)

        self.assertIn("Instruct:", query_texts[0])
        self.assertIn("Query:", query_texts[0])
        self.assertIn("противодымная вентиляция", query_texts[0])
        self.assertEqual(doc_texts, ["противодымная вентиляция"])

    def test_batcher_reads_safe_batch_settings_from_config(self):
        import embedder.batcher as batcher

        original_load_config = batcher.load_config
        try:
            batcher.load_config = lambda: {
                "lemonade": {"batch_size": 8},
                "indexing": {"batch_cooldown_sec": 1.25},
            }

            settings = batcher.get_batch_settings()
        finally:
            batcher.load_config = original_load_config

        self.assertEqual(settings.batch_size, 8)
        self.assertEqual(settings.cooldown_sec, 1.25)

    def test_embed_chunks_uses_configured_batch_size_and_cooldown(self):
        import embedder.batcher as batcher
        from embedder.thermal import ThermalController

        chunks = [FakeChunk("doc-a", f"c{i}", f"text {i}") for i in range(5)]
        original_get_embeddings = batcher.get_embeddings
        original_load_config = batcher.load_config
        original_sleep = batcher.time.sleep
        original_get_cooldown = ThermalController.get_cooldown
        calls = {"inputs": [], "sleeps": []}

        def fake_get_embeddings(texts):
            calls["inputs"].append(texts)
            return [[float(len(texts))] for _ in texts]

        try:
            batcher.load_config = lambda: {
                "lemonade": {"batch_size": 2},
                "indexing": {"batch_cooldown_sec": 0.5},
            }
            batcher.get_embeddings = fake_get_embeddings
            batcher.time.sleep = lambda seconds: calls["sleeps"].append(seconds)
            ThermalController.get_cooldown = lambda self: 0.5

            embeddings = batcher.embed_chunks(chunks)
        finally:
            batcher.get_embeddings = original_get_embeddings
            batcher.load_config = original_load_config
            batcher.time.sleep = original_sleep
            ThermalController.get_cooldown = original_get_cooldown

        self.assertEqual(calls["inputs"], [
            ["text 0", "text 1"],
            ["text 2", "text 3"],
            ["text 4"],
        ])
        self.assertEqual(calls["sleeps"], [0.5, 0.5])
        self.assertEqual([e.chunk_id for e in embeddings], ["c0", "c1", "c2", "c3", "c4"])


if __name__ == "__main__":
    unittest.main()
