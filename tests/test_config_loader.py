"""Config resolution must not depend on the working directory.

Same failure family as the metadata DB path: modules resolved `config.yaml`
against the current directory first, so an MCP server started by its client
from another folder either missed the project config or picked up an unrelated
one that happened to sit there.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config_loader


class ConfigPathTests(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.addCleanup(os.chdir, self.cwd)

    def test_defaults_to_the_repository_config(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(config_loader.CONFIG_ENV, None)
            self.assertEqual(
                config_loader.config_path(), config_loader.ROOT / "config.yaml"
            )

    def test_repository_config_wins_over_one_in_the_working_directory(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            decoy = Path(elsewhere) / "config.yaml"
            decoy.write_text("storage: {metadata_db: decoy.db}\n", encoding="utf-8")
            try:
                os.chdir(elsewhere)
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop(config_loader.CONFIG_ENV, None)
                    resolved = config_loader.config_path()
            finally:
                # Windows refuses to remove a directory that is still
                # the current one, so leave it before cleanup runs.
                os.chdir(self.cwd)

        self.assertEqual(resolved, config_loader.ROOT / "config.yaml")
        self.assertNotEqual(resolved, decoy)

    def test_env_override_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "other.yaml"
            path.write_text("storage: {}\n", encoding="utf-8")
            with patch.dict(os.environ, {config_loader.CONFIG_ENV: str(path)}):
                self.assertEqual(config_loader.config_path(), path)

    def test_relative_override_resolves_against_the_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected = Path(tmp).resolve() / "local.yaml"
            try:
                os.chdir(tmp)
                with patch.dict(os.environ, {config_loader.CONFIG_ENV: "local.yaml"}):
                    resolved = config_loader.config_path()
            finally:
                # Windows refuses to remove a directory that is still
                # the current one, so leave it before cleanup runs.
                os.chdir(self.cwd)

        self.assertEqual(resolved, expected)


class LoadConfigTests(unittest.TestCase):
    def test_missing_file_loads_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent.yaml"
            with patch.dict(os.environ, {config_loader.CONFIG_ENV: str(missing)}):
                self.assertEqual(config_loader.load_config(), {})

    def test_broken_yaml_loads_as_empty_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.yaml"
            path.write_text("storage: [unclosed\n", encoding="utf-8")
            with patch.dict(os.environ, {config_loader.CONFIG_ENV: str(path)}):
                self.assertEqual(config_loader.load_config(), {})

    def test_values_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.yaml"
            path.write_text(
                "storage:\n  metadata_db: some/where.db\n", encoding="utf-8"
            )
            with patch.dict(os.environ, {config_loader.CONFIG_ENV: str(path)}):
                cfg = config_loader.load_config()
        self.assertEqual(cfg["storage"]["metadata_db"], "some/where.db")

    def test_require_config_raises_on_a_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent.yaml"
            with patch.dict(os.environ, {config_loader.CONFIG_ENV: str(missing)}):
                with self.assertRaises(FileNotFoundError):
                    config_loader.require_config()


class ConsumersUseTheResolverTests(unittest.TestCase):
    """The runtime search/index path must all read the same file."""

    def test_every_runtime_loader_follows_the_override(self):
        import embedder.batcher as batcher
        import embedder.client as client
        import storage.vector_store as vector_store

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.yaml"
            path.write_text(
                "lemonade:\n  model: marker-model\n"
                "storage:\n  metadata_db: marker.db\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {config_loader.CONFIG_ENV: str(path)}):
                self.assertEqual(
                    client.load_config()["lemonade"]["model"], "marker-model"
                )
                self.assertEqual(
                    batcher.load_config()["lemonade"]["model"], "marker-model"
                )
                self.assertEqual(
                    vector_store.load_config()["storage"]["metadata_db"], "marker.db"
                )

    def test_reranker_reads_its_endpoint_through_the_resolver(self):
        from rag_server.reranker import _rerank_config

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.yaml"
            path.write_text(
                "retrieval:\n"
                "  rerank_endpoint: http://example.invalid/rerank\n"
                "  rerank_model: marker-reranker\n"
                "  rerank_candidate_limit: 7\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {config_loader.CONFIG_ENV: str(path)}):
                endpoint, model, limit = _rerank_config()

        self.assertEqual(endpoint, "http://example.invalid/rerank")
        self.assertEqual(model, "marker-reranker")
        self.assertEqual(limit, 7)


if __name__ == "__main__":
    unittest.main()
