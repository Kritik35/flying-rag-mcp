"""The metadata DB path must not depend on the working directory.

An MCP server is launched by its client (Claude Desktop, Qwen Chat) with an
arbitrary working directory. `storage.metadata_db` is configured relative to the
repository, so a CWD-relative resolution pointed at a file that did not exist:
parent hydration found nothing and every hit silently degraded from its
1000-token parent to a 150-token child chunk. Nothing logged an error the
operator would see and results still looked plausible.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storage import vector_store


class MetadataPathResolutionTests(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.addCleanup(os.chdir, self.cwd)

    def test_relative_config_path_resolves_against_the_repository(self):
        with patch.object(
            vector_store, "load_config",
            return_value={"storage": {"metadata_db": "data/metadata.db"}},
        ):
            path = vector_store._get_sqlite_path()

        self.assertTrue(path.is_absolute())
        self.assertEqual(path, vector_store.ROOT / "data" / "metadata.db")

    def test_resolution_is_stable_when_the_client_sets_another_cwd(self):
        with patch.object(
            vector_store, "load_config",
            return_value={"storage": {"metadata_db": "data/metadata.db"}},
        ):
            from_repo = vector_store._get_sqlite_path()
            with tempfile.TemporaryDirectory() as elsewhere:
                os.chdir(elsewhere)
                from_elsewhere = vector_store._get_sqlite_path()

        self.assertEqual(from_repo, from_elsewhere)

    def test_absolute_config_path_is_left_alone(self):
        absolute = Path(tempfile.gettempdir()).resolve() / "custom" / "metadata.db"
        with patch.object(
            vector_store, "load_config",
            return_value={"storage": {"metadata_db": str(absolute)}},
        ):
            self.assertEqual(vector_store._get_sqlite_path(), absolute)

    def test_default_is_also_repository_relative(self):
        with patch.object(vector_store, "load_config", return_value={}):
            path = vector_store._get_sqlite_path()

        self.assertTrue(path.is_absolute())
        self.assertEqual(path, vector_store.ROOT / "data" / "metadata.db")


if __name__ == "__main__":
    unittest.main()
