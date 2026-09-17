from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BackfillRulesConfigTests(unittest.TestCase):
    def test_api_key_env_resolves_without_putting_secret_in_argv(self):
        from backfill_rules import _resolve_api_key

        with patch.dict(os.environ, {"BACKFILL_KEY_1": "placeholder-value"}, clear=False):
            self.assertEqual(_resolve_api_key(None, "BACKFILL_KEY_1", None), "placeholder-value")

    def test_explicit_api_key_still_wins_for_compatibility(self):
        from backfill_rules import _resolve_api_key

        with patch.dict(os.environ, {"BACKFILL_KEY_1": "placeholder-env-value"}, clear=False):
            self.assertEqual(_resolve_api_key("arg-value", "BACKFILL_KEY_1", None), "arg-value")

    def test_api_key_file_reads_secret_from_ignored_file(self):
        from backfill_rules import _resolve_api_key

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write("file-secret\n")
            key_path = Path(f.name)
        try:
            self.assertEqual(_resolve_api_key(None, None, str(key_path)), "file-secret")
        finally:
            key_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
