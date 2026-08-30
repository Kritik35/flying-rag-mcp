"""Index manifest: the store must refuse to mix two embedding contracts."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from storage.index_manifest import (
    MANIFEST_SCHEMA,
    build_manifest,
    ensure_manifest,
    load_manifest,
    manifest_path,
    verify_manifest,
    write_manifest,
)

MODEL = "Qwen3-Embedding-0.6B-GGUF"
CHUNKER = "parent-child-tiktoken-v1"


class ManifestRoundTripTests(unittest.TestCase):
    def test_write_then_load_returns_the_same_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            manifest = build_manifest(
                model=MODEL, dimension=1024, chunker=CHUNKER,
                chunk_params={"max_child_tokens": 150},
            )
            write_manifest(path, manifest)

            loaded = load_manifest(path)
            self.assertEqual(loaded["schema"], MANIFEST_SCHEMA)
            self.assertEqual(loaded["model"], MODEL)
            self.assertEqual(loaded["dimension"], 1024)
            self.assertEqual(loaded["chunk_params"]["max_child_tokens"], 150)

    def test_missing_manifest_loads_as_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_manifest(Path(tmp)))

    def test_corrupt_manifest_loads_as_none_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            manifest_path(path).write_text("{not json", encoding="utf-8")
            self.assertIsNone(load_manifest(path))


class VerifyManifestTests(unittest.TestCase):
    def _manifest(self, **overrides):
        base = build_manifest(model=MODEL, dimension=1024, chunker=CHUNKER)
        base.update(overrides)
        return base

    def test_absent_manifest_is_not_an_error(self):
        status, code, _ = verify_manifest(None, model=MODEL, dimension=1024)
        self.assertEqual(status, "absent")
        self.assertEqual(code, "")

    def test_same_model_named_differently_still_verifies(self):
        status, code, _ = verify_manifest(
            self._manifest(model="Qwen/Qwen3-Embedding-0.6B"),
            model=MODEL, dimension=1024,
        )
        self.assertEqual(status, "ok")
        self.assertEqual(code, "")

    def test_other_model_of_the_same_width_is_a_mismatch(self):
        # 1024 == 1024 is exactly the check that used to let this through.
        status, code, detail = verify_manifest(
            self._manifest(model="bge-m3"), model=MODEL, dimension=1024
        )
        self.assertEqual(status, "mismatch")
        self.assertEqual(code, "embedding_contract_mismatch")
        self.assertIn("bge-m3", detail)

    def test_dimension_change_is_a_mismatch(self):
        _status, code, _ = verify_manifest(
            self._manifest(), model=MODEL, dimension=768
        )
        self.assertEqual(code, "embedding_dimension_mismatch")

    def test_chunker_change_is_reported_under_its_own_code(self):
        _status, code, _ = verify_manifest(
            self._manifest(), model=MODEL, dimension=1024,
            chunker="parent-child-tiktoken-v2",
        )
        self.assertEqual(code, "chunker_contract_mismatch")


class EnsureManifestTests(unittest.TestCase):
    def test_first_run_creates_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            manifest, code, _ = ensure_manifest(
                path, model=MODEL, dimension=1024, chunker=CHUNKER
            )
            self.assertEqual(code, "")
            self.assertEqual(manifest["model"], MODEL)
            self.assertTrue(manifest_path(path).exists())

    def test_second_run_with_the_same_contract_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            ensure_manifest(path, model=MODEL, dimension=1024, chunker=CHUNKER)
            _manifest, code, _ = ensure_manifest(
                path, model=MODEL, dimension=1024, chunker=CHUNKER
            )
            self.assertEqual(code, "")

    def test_mismatch_returns_a_code_and_leaves_the_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            ensure_manifest(path, model=MODEL, dimension=1024, chunker=CHUNKER)
            before = manifest_path(path).read_text(encoding="utf-8")

            _manifest, code, detail = ensure_manifest(
                path, model="bge-m3", dimension=1024, chunker=CHUNKER
            )

            self.assertEqual(code, "embedding_contract_mismatch")
            self.assertIn("bge-m3", detail)
            after = manifest_path(path).read_text(encoding="utf-8")
            self.assertEqual(before, after)
            self.assertEqual(json.loads(after)["model"], MODEL)


if __name__ == "__main__":
    unittest.main()
