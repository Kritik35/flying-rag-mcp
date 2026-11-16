"""
tests/test_drive_inbox_watcher.py

Independent Acceptance & Verification Unit Tests for Block M0 (Drive Inbox Watcher).
Tests all edge cases, state transitions, locking invariants, and safety boundaries.
"""

import os
import sys
import json
import time
import shutil
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.drive_inbox_watcher import DriveInboxWatcher, FileLock


class TestDriveInboxWatcher(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_drive_watcher_"))
        self.inbox_dir = self.test_dir / "inbox"
        self.state_dir = self.test_dir / "state"
        self.inbox_dir.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    def test_first_bootstrap_creates_baseline_without_retrigger(self):
        # Create pre-existing file in inbox
        existing_doc = self.inbox_dir / "FR-TZ-20261115-001_Stage4.2.5_FlyingRAG.txt"
        existing_doc.write_text("Stage 4.2.5 initial text content", encoding="utf-8")

        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        res = watcher.run_locked_cycle(bootstrap=True)

        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["detected_count"], 0)
        self.assertEqual(res["acknowledged_count"], 1)
        self.assertEqual(len(res["new_events"]), 0)

        # Verify state
        status = watcher.get_status_report()
        self.assertEqual(status["tracked_files_count"], 1)
        doc_record = status["tracked_files"]["FR-TZ-20261115-001_Stage4.2.5_FlyingRAG.txt"]
        self.assertEqual(doc_record["lifecycle_status"], "ACKNOWLEDGED")
        self.assertEqual(doc_record["version_number"], 1)
        self.assertIn("Baseline task", doc_record["notes"])

    def test_file_appeared_in_two_cycles_not_duplicated(self):
        # 1. Bootstrap on empty inbox
        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        watcher.run_locked_cycle(bootstrap=True)

        # 2. Add new file
        new_file = self.inbox_dir / "FR-TZ-20261116-002_NextTask.txt"
        new_file.write_text("Next task payload", encoding="utf-8")

        res1 = watcher.run_locked_cycle()
        self.assertEqual(res1["detected_count"], 1)
        self.assertEqual(res1["fetched_count"], 1)
        self.assertEqual(res1["acknowledged_count"], 1)
        self.assertEqual(len(res1["new_events"]), 1)
        self.assertEqual(res1["new_events"][0]["event_type"], "NEW_TZ_DETECTED")

        # 3. Next poll cycle: same file must not trigger duplicate event
        res2 = watcher.run_locked_cycle()
        self.assertEqual(res2["detected_count"], 0)
        self.assertEqual(res2["fetched_count"], 0)
        self.assertEqual(res2["acknowledged_count"], 0)
        self.assertEqual(len(res2["new_events"]), 0)

    def test_file_edit_generates_new_version_event(self):
        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        doc = self.inbox_dir / "FR-TZ-20261116-003_Revision.txt"
        doc.write_text("Version 1 content", encoding="utf-8")

        # Initial detection
        res1 = watcher.run_locked_cycle()
        self.assertEqual(res1["acknowledged_count"], 1)
        self.assertEqual(res1["new_events"][0]["version_number"], 1)

        # Modify file and adjust mtime
        time.sleep(0.05)
        doc.write_text("Version 2 updated content with new directives", encoding="utf-8")
        new_mtime = time.time() + 10.0
        os.utime(str(doc), (new_mtime, new_mtime))

        res2 = watcher.run_locked_cycle()
        self.assertEqual(res2["detected_count"], 1)
        self.assertEqual(res2["acknowledged_count"], 1)
        self.assertEqual(len(res2["new_events"]), 1)
        event = res2["new_events"][0]
        self.assertEqual(event["event_type"], "TZ_VERSION_UPDATED")
        self.assertEqual(event["version_number"], 2)

    def test_unsupported_mime_gdoc_ignored_without_crash(self):
        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)

        # Add .gdoc and temp files
        (self.inbox_dir / "cloud_shortcut.gdoc").write_text("dummy", encoding="utf-8")
        (self.inbox_dir / "cloud_sheet.gsheet").write_text("dummy", encoding="utf-8")
        (self.inbox_dir / "~$temp_office.tmp").write_text("temp", encoding="utf-8")

        res = watcher.run_locked_cycle()
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["detected_count"], 0)
        self.assertEqual(len(res["new_events"]), 0)

        status = watcher.get_status_report()
        self.assertEqual(status["ignored_cloud_shortcuts_count"], 2)
        self.assertEqual(status["tracked_files_count"], 0)

    def test_concurrent_watchers_mutex_prevent_parallel_run(self):
        lock_file = self.state_dir / "watcher.lock"
        lock1 = FileLock(lock_file)
        self.assertTrue(lock1.acquire())

        # Second lock attempt must fail
        lock2 = FileLock(lock_file)
        self.assertFalse(lock2.acquire())

        # Watcher running with active lock must skip cycle
        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        res = watcher.run_locked_cycle()
        self.assertEqual(res["status"], "SKIPPED_LOCKED")

        # Release first lock
        lock1.release()

        # Now watcher can acquire and run
        res2 = watcher.run_locked_cycle()
        self.assertEqual(res2["status"], "OK")

    def test_inbox_temporarily_unavailable_fail_safe(self):
        missing_inbox = self.test_dir / "non_existent_folder"
        watcher = DriveInboxWatcher(inbox_dir=missing_inbox, state_dir=self.state_dir)

        res = watcher.run_locked_cycle()
        self.assertEqual(res["status"], "INBOX_NOT_FOUND")
        self.assertFalse(res["inbox_exists"])

    def test_detection_only_mode_never_executes_external_commands(self):
        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir, mode="DETECTION_ONLY")
        doc = self.inbox_dir / "FR-TZ-20261116-004_PureDetection.txt"
        doc.write_text("Content requiring review", encoding="utf-8")

        res = watcher.run_locked_cycle()
        self.assertEqual(res["detected_count"], 1)
        event = res["new_events"][0]
        self.assertEqual(event["watcher_mode"], "DETECTION_ONLY")
        self.assertIn("Operator review required", event["action_required"])

    def test_state_persistence_and_recovery_after_restart(self):
        # Session 1: bootstrap
        doc = self.inbox_dir / "FR-TZ-20261116-005_Persistent.txt"
        doc.write_text("Persistent task text", encoding="utf-8")

        w1 = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        w1.run_locked_cycle(bootstrap=True)

        # Session 2: new watcher instance pointing to same state_dir
        w2 = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        status = w2.get_status_report()
        self.assertEqual(status["tracked_files_count"], 1)
        self.assertIn("FR-TZ-20261116-005_Persistent.txt", status["tracked_files"])
        self.assertEqual(status["tracked_files"]["FR-TZ-20261116-005_Persistent.txt"]["lifecycle_status"], "ACKNOWLEDGED")


if __name__ == "__main__":
    unittest.main()
