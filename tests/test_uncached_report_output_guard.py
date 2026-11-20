"""Offline safety gates for a new, uniquely named uncached diagnostic report.

No corpus, embedding service, worker, or search dispatch is accessed.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import postfix_pilot_harness_015 as harness


class OneShotReportOutputGuardTests(unittest.TestCase):
    def test_new_report_name_is_unique_and_not_historical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = harness.prepare_uncached_result_target("FR-CHECK-20261120-UNCACHED", reports_dir=root)
            # Windows TEMP may expose a short (8.3) alias; compare filesystem identity.
            self.assertTrue(p.parent.samefile(root))
            self.assertEqual(p.name, "postfix_uncached_confirmation_FR-CHECK-20261120-UNCACHED.json")
            self.assertNotEqual(p.name, "postfix_pilot_results_015.json")
            p.write_text("previous result", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                harness.prepare_uncached_result_target("FR-CHECK-20261120-UNCACHED", reports_dir=root)
            self.assertEqual(p.read_text(encoding="utf-8"), "previous result")

    def test_invalid_report_ids_and_symlinked_report_dir_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for bad in ("", "short", "../reports", "..", "FR-CHECK/unsafe", "A" * 65):
                with self.subTest(report_id=bad):
                    with self.assertRaises(ValueError):
                        harness.prepare_uncached_result_target(bad, reports_dir=root)
            missing = root / "missing"
            with self.assertRaises(ValueError):
                harness.prepare_uncached_result_target("FR-CHECK-20261120-UNCACHED", reports_dir=missing)

    def test_exclusive_sanitized_output_cannot_overwrite_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = {"task_id": "FR-CHECK-20261120-UNCACHED", "calls": [], "overall_status": "DRY_FIXTURE"}
            target = root / "postfix_uncached_confirmation_FR-CHECK-20261120-UNCACHED.json"
            with patch.object(harness.tempfile, "gettempdir", return_value=str(root)):
                first, raw, sha = harness.save_separated_results(
                    result, target, exclusive_target=True
                )
                self.assertTrue(raw.is_file())
                self.assertEqual(len(sha), 64)
                saved = target.read_bytes()
                self.assertEqual(json.loads(saved)["task_id"], result["task_id"])
                with self.assertRaises(FileExistsError):
                    harness.save_separated_results(result, target, exclusive_target=True)
                self.assertEqual(target.read_bytes(), saved)

    def test_live_cli_fails_before_any_dispatch_without_unique_report_id(self):
        with patch.object(sys, "argv", [
            "postfix_pilot_harness_015.py",
            "--execute-approved-pilot", "--no-cache"
        ]):
            with patch.object(harness, "run_postfix_pilot", side_effect=AssertionError("NO SEARCH")) as run:
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as err:
                        harness.main()
            self.assertEqual(err.exception.code, 2)
            run.assert_not_called()

    def test_live_cli_fails_before_dispatch_if_report_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_id = "FR-CHECK-20261120-UNCACHED"
            # Offline collision precondition; no live search or production file.
            with patch.object(harness, "prepare_uncached_result_target", side_effect=FileExistsError("exists")):
                with patch.object(sys, "argv", [
                    "postfix_pilot_harness_015.py",
                    "--execute-approved-pilot", "--no-cache", "--report-id", target_id
                ]):
                    with patch.object(harness, "run_postfix_pilot", side_effect=AssertionError("NO SEARCH")) as run:
                        with contextlib.redirect_stderr(io.StringIO()):
                            with self.assertRaises(SystemExit) as err:
                                harness.main()
                    self.assertEqual(err.exception.code, 2)
                    run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
