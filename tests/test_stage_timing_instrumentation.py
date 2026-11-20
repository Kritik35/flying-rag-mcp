"""Offline-only regression tests for phase markers and timeout preservation.

Synthetic stderr and fake child processes only; no FlyingRAG search, model,
corpus, SQLite, LanceDB, production files or active worker is used.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import MagicMock, patch

from stage_timing import collect, mark
from tests import postfix_pilot_harness_015 as harness


class StageTimingInstrumentationTests(unittest.TestCase):
    def test_marker_is_opt_in_allowlisted_and_flushes_without_sensitive_text(self):
        with patch.dict(os.environ, {"FLYING_RAG_STAGE_TIMING": "0"}):
            with contextlib.redirect_stderr(io.StringIO()) as disabled:
                mark("worker_started")
            self.assertEqual(disabled.getvalue(), "")

        with patch.dict(os.environ, {"FLYING_RAG_STAGE_TIMING": "1"}):
            with patch("stage_timing.time.perf_counter_ns", return_value=1000000000):
                with patch("stage_timing.threading.get_ident", return_value=12345):
                    with contextlib.redirect_stderr(io.StringIO()) as stream:
                        mark("worker_started")
                        mark("query=SECRET/Windows/path")
        self.assertEqual(stream.getvalue(), "[FR_STAGE_V1] worker_started 1000000000 12345\n")

    def test_parser_filters_untrusted_stderr_and_only_emits_relative_timing(self):
        logs = (
            "HTTPError: request says private=SECRET_DOCUMENT_PATH\n"
            "[FR_STAGE_V1] worker_started 1000000000 111\n"
            "[FR_STAGE_V1] unexpected_stage 1000000123 111\n"
            "[FR_STAGE_V1] dispatch_start 1001000000 111\n"
            "C:\\Users\\operator\\private\\document.docx\n"
        )
        events = collect(logs.encode("utf-8"))
        self.assertEqual(events, [
            {"stage": "worker_started", "since_first_ms": 0.0, "thread": 111},
            {"stage": "dispatch_start", "since_first_ms": 1.0, "thread": 111},
        ])
        self.assertNotIn("SECRET", json.dumps(events))
        self.assertNotIn("document.docx", json.dumps(events))

    def test_timeout_preserves_flushed_markers_without_republishing_raw_stderr(self):
        logs = (
            "[FR_STAGE_V1] worker_started 1000000000 201\n"
            "PRIVATE_CORPUS_TEXT_SHOULD_NEVER_LEAK\n"
            "[FR_STAGE_V1] imports_ready 1600000000 201\n"
        )
        fake = MagicMock()
        fake.communicate.side_effect = [
            TimeoutExpired(cmd=["python", "worker"], timeout=60, stderr=logs.encode("utf-8")),
            ("", logs),
        ]
        fake.poll.return_value = -15
        with patch.object(harness.subprocess, "Popen", return_value=fake) as proc:
            outcome = harness.execute_bounded_search(
                "synthetic", shadow_mode=False, no_cache=True, timeout_sec=60.0
            )
        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["error"], "EXECUTION_TIMEOUT_EXPIRED (60.0s)")
        self.assertEqual([x["stage"] for x in outcome["stage_trace"]],
                         ["worker_started", "imports_ready"])
        self.assertNotIn("PRIVATE_CORPUS", json.dumps(outcome))
        command = proc.call_args.args[0]
        self.assertIn("--no-cache", command)
        self.assertIn("--trace-stages", command)
        fake.terminate.assert_called_once()

    def test_successful_worker_envelope_retains_only_sanitized_stages(self):
        raw = {
            "success": True,
            "result": [{"chunk_id": "fixture_001", "text": "synthetic"}],
            "cache_disabled": True,
            "error": "",
        }
        stderr = "[FR_STAGE_V1] dispatch_start 1000000000 888\n"
        fake = MagicMock()
        fake.returncode = 0
        fake.communicate.return_value = (json.dumps(raw), stderr)
        with patch.object(harness.subprocess, "Popen", return_value=fake):
            outcome = harness.execute_bounded_search("synthetic", shadow_mode=False, no_cache=True)
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["stage_trace"][0]["stage"], "dispatch_start")
        self.assertEqual(outcome["stage_trace"][0]["since_first_ms"], 0.0)

    def test_timeout_result_halts_after_one_attempt_and_keeps_stage_trace(self):
        failure = {
            "success": False,
            "result": None,
            "elapsed_ms": 60091.13,
            "error": "EXECUTION_TIMEOUT_EXPIRED (60.0s)",
            "exitcode": -15,
            "spawned": True,
            "stage_trace": [{"stage": "worker_started", "since_first_ms": 0.0, "thread": 123}],
        }
        with patch.object(harness, "preflight_check", return_value={"checks_passed": True}):
            with patch.object(harness, "execute_bounded_search", return_value=failure) as fake_search:
                with patch.object(harness.PRODUCTION_DB_PATH.__class__, "exists", return_value=False):
                    report = harness.run_postfix_pilot(
                        execute_approved_pilot=True, synthetic_test=False, no_cache=True
                    )
        self.assertEqual(fake_search.call_count, 1)
        self.assertEqual(report["attempted_calls"], 1)
        self.assertEqual(report["completed_calls"], 0)
        self.assertEqual(report["calls"][0]["stage_trace"][0]["stage"], "worker_started")
        self.assertIn("EXECUTION_TIMEOUT_EXPIRED", report["overall_status"])

    def test_sanitized_report_excludes_raw_search_results(self):
        synthetic = {
            "task_id": "stage-trace-synthetic",
            "calls": [{
                "stage_trace": [{"stage": "worker_started", "since_first_ms": 0.0, "thread": 123}],
                "raw_result": [{"text": "PRIVATE_CORPUS_TEXT_SHOULD_NEVER_LEAK"}],
                "top_hit": {"snippet": "fixture"},
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sanitized.json"
            with patch.object(harness.tempfile, "gettempdir", return_value=tmp):
                clean, private_path, _digest = harness.save_separated_results(synthetic, out)
            saved = out.read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE_CORPUS_TEXT_SHOULD_NEVER_LEAK", saved)
            self.assertNotIn("raw_result", saved)
            self.assertTrue(private_path.exists())
            self.assertEqual(clean["calls"][0]["stage_trace"][0]["stage"], "worker_started")


if __name__ == "__main__":
    unittest.main()
