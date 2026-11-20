"""Offline-only proof of the explicitly uncached post-fix diagnostic path.

Uses fake dispatch modules and mocked subprocess. Does not import a model, open
the real corpus, or call search_documents against any storage.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from tests import shadow_pilot_worker as worker
from tests import postfix_pilot_harness_015 as harness


class CacheBypassConfirmationTests(unittest.TestCase):
    def _run_mock_worker(self, no_cache: bool):
        calls = []
        server = types.ModuleType("rag_server.server")
        server._dispatch = lambda tool, arguments: (
            calls.append((tool, dict(arguments))) or
            [{"chunk_id": "fixture_c1", "text": "synthetic local fixture"}]
        )
        server.reset_shadow_adapter = lambda: None

        toolmod = types.ModuleType("rag_server.tools")
        normmod = types.ModuleType("rag_server.norm_resolver")
        toolmod.__file__ = __file__
        normmod.__file__ = __file__
        package = types.ModuleType("rag_server")
        package.__path__ = []
        package.tools = toolmod
        package.norm_resolver = normmod

        args = ["shadow_pilot_worker.py", "--query", "synthetic query", "--shadow-mode", "0"]
        if no_cache:
            args.append("--no-cache")

        output = io.StringIO()
        with patch.dict(sys.modules, {
            "rag_server": package,
            "rag_server.server": server,
            "rag_server.tools": toolmod,
            "rag_server.norm_resolver": normmod
        }):
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(sys, "argv", args):
                    with contextlib.redirect_stdout(output):
                        with self.assertRaises(SystemExit) as e:
                            worker.main()
        self.assertEqual(e.exception.code, 0)
        return calls, json.loads(output.getvalue())

    def test_worker_forwards_explicit_cache_bypass_and_runtime_code_fingerprint(self):
        calls, output = self._run_mock_worker(no_cache=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "search_documents")
        self.assertIs(calls[0][1]["use_cache"], False)
        self.assertIs(output["cache_disabled"], True)
        expected_sha = hashlib.sha256(__import__("pathlib").Path(__file__).read_bytes()).hexdigest()
        self.assertEqual(output["runtime_code_sha256"]["rag_server_tools"], expected_sha)
        self.assertEqual(output["runtime_code_sha256"]["rag_server_norm_resolver"], expected_sha)

    def test_worker_legacy_mode_defaults_to_cache_enabled(self):
        calls, output = self._run_mock_worker(no_cache=False)
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][1]["use_cache"], True)
        self.assertIs(output["cache_disabled"], False)

    def test_harness_appends_no_cache_flag_to_child_command(self):
        fake = MagicMock()
        fake.communicate.return_value = (
            json.dumps({
                "success": True,
                "result": [{"chunk_id": "fixture_c1"}],
                "error": "",
                "cache_disabled": True,
                "runtime_code_sha256": {"rag_server_tools": "a" * 64}
            }),
            ""
        )
        fake.returncode = 0
        with patch.object(harness.subprocess, "Popen", return_value=fake) as popen:
            res = harness.execute_bounded_search("synthetic query", shadow_mode=False, no_cache=True)
        cmd = popen.call_args.args[0]
        self.assertIn("--no-cache", cmd)
        self.assertTrue(res["cache_disabled"])
        self.assertEqual(res["runtime_code_sha256"]["rag_server_tools"], "a" * 64)

    def test_harness_halts_if_worker_does_not_confirm_bypass(self):
        synthetic_hit = [{"chunk_id": "fixture_c1", "text": "synthetic"}]
        fake_result = {
            "success": True,
            "result": synthetic_hit,
            "elapsed_ms": 1.0,
            "exitcode": 0,
            "spawned": True,
            "shadow_stats": None,
            "cache_disabled": False
        }
        with patch.object(harness, "preflight_check", return_value={"checks_passed": True}):
            with patch.object(harness, "execute_bounded_search", return_value=fake_result) as execute:
                with patch.object(harness.PRODUCTION_DB_PATH.__class__, "exists", return_value=False):
                    report = harness.run_postfix_pilot(
                        execute_approved_pilot=True,
                        synthetic_test=False,
                        no_cache=True
                    )
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(report["attempted_calls"], 1)
        self.assertEqual(report["actual_corpus_search_calls"], 0)
        self.assertFalse(report["calls"][0]["success"])
        self.assertEqual(report["calls"][0]["error"], "CACHE_BYPASS_NOT_CONFIRMED")
        self.assertIn("HALTED_AFTER_FAILURE_CALL_1", report["overall_status"])


if __name__ == "__main__":
    unittest.main()
