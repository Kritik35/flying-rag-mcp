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
from unittest.mock import MagicMock

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

    def test_m1_01_transient_read_error_retries_unchanged_file_and_succeeds(self):
        doc = self.inbox_dir / "FR-TZ-20261116-006_TransientRead.txt"
        doc.write_text("Real content for transient test", encoding="utf-8")

        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)

        # Cycle 1: Simulate transient read error
        orig_read_bytes = Path.read_bytes
        call_count = [0]
        def faulty_read(path_self):
            if path_self.name == doc.name and call_count[0] == 0:
                call_count[0] += 1
                raise OSError("Simulated transient lock [WinError 32] / DriveFS busy")
            return orig_read_bytes(path_self)

        Path.read_bytes = faulty_read
        try:
            res1 = watcher.run_locked_cycle()
            self.assertEqual(res1["failed_retry_count"], 1)
            self.assertEqual(res1["acknowledged_count"], 0)
            status1 = watcher.get_status_report()["tracked_files"][doc.name]
            self.assertEqual(status1["lifecycle_status"], "FAILED_RETRY")
        finally:
            Path.read_bytes = orig_read_bytes

        # Cycle 2: File remains completely UNCHANGED (same mtime, same size)
        # Watcher must NOT skip it; it must retry and succeed
        res2 = watcher.run_locked_cycle()
        self.assertEqual(res2["acknowledged_count"], 1)
        self.assertEqual(len(res2["new_events"]), 1)
        status2 = watcher.get_status_report()["tracked_files"][doc.name]
        self.assertEqual(status2["lifecycle_status"], "ACKNOWLEDGED")
        self.assertEqual(status2["version_number"], 1)

    def test_m1_02_transient_spool_write_error_recovers_without_loss_or_duplicate(self):
        doc = self.inbox_dir / "FR-TZ-20261116-007_SpoolError.txt"
        doc.write_text("Spool resilience content", encoding="utf-8")

        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)

        # Cycle 1: Spool dir temporarily read-only / failing
        orig_write_bytes = Path.write_bytes
        spool_fails = [True]
        def faulty_write_bytes(path_self, data):
            if "inbox_spool" in str(path_self) and spool_fails[0]:
                spool_fails[0] = False
                raise PermissionError("Simulated disk write permission error")
            return orig_write_bytes(path_self, data)

        Path.write_bytes = faulty_write_bytes
        try:
            res1 = watcher.run_locked_cycle()
            self.assertEqual(res1["failed_retry_count"], 1)
            self.assertEqual(res1["acknowledged_count"], 0)
        finally:
            Path.write_bytes = orig_write_bytes

        # Cycle 2: Recovered write, file unchanged
        res2 = watcher.run_locked_cycle()
        self.assertEqual(res2["acknowledged_count"], 1)
        self.assertEqual(len(res2["new_events"]), 1)
        # Check spool file exists
        spool_files = list(watcher.spool_dir.glob(f"{doc.stem}*"))
        self.assertEqual(len(spool_files), 1)

    def test_m1_03_unreadable_bootstrap_records_baseline_unreadable_and_subsequent_poll_reads_correctly(self):
        doc = self.inbox_dir / "FR-TZ-20261116-008_UnreadableBootstrap.txt"
        doc.write_text("Bootstrap content", encoding="utf-8")

        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)

        # Simulate read error during bootstrap
        orig_read_bytes = Path.read_bytes
        def faulty_read(path_self):
            if path_self.name == doc.name:
                raise OSError("Virtual file placeholder unreadable at bootstrap")
            return orig_read_bytes(path_self)

        Path.read_bytes = faulty_read
        try:
            res_boot = watcher.run_locked_cycle(bootstrap=True)
            self.assertEqual(res_boot["failed_retry_count"], 1)
            self.assertEqual(res_boot["acknowledged_count"], 0)
            status_boot = watcher.get_status_report()["tracked_files"][doc.name]
            self.assertEqual(status_boot["lifecycle_status"], "BASELINE_UNREADABLE")
        finally:
            Path.read_bytes = orig_read_bytes

        # Subsequent standard poll cycle with access restored
        res_poll = watcher.run_locked_cycle()
        self.assertEqual(res_poll["acknowledged_count"], 1)
        self.assertEqual(len(res_poll["new_events"]), 1)
        status_poll = watcher.get_status_report()["tracked_files"][doc.name]
        self.assertEqual(status_poll["lifecycle_status"], "ACKNOWLEDGED")
        self.assertIsNotNone(status_poll["sha256"])

    def test_m1_04_two_processes_with_stale_preinstantiated_state_emit_exactly_one_event(self):
        doc = self.inbox_dir / "FR-TZ-20261116-009_Concurrency.txt"
        doc.write_text("Concurrency test data", encoding="utf-8")

        # Two instances created BEFORE either acquires lock (both hold empty in-memory state)
        w1 = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        w2 = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)

        # w1 runs first
        res1 = w1.run_locked_cycle()
        self.assertEqual(res1["acknowledged_count"], 1)
        self.assertEqual(len(res1["new_events"]), 1)

        # w2 runs next: it MUST reload state from disk inside lock and skip duplicate
        res2 = w2.run_locked_cycle()
        self.assertEqual(res2["acknowledged_count"], 0)
        self.assertEqual(len(res2["new_events"]), 0)

    def test_m1_05_corrupt_state_preserves_corrupted_backup_without_silent_overwrite(self):
        state_file = self.state_dir / "state.json"
        state_file.write_text("INVALID_JSON_CORRUPTED_BYTES{{{", encoding="utf-8")

        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        # Check corrupt backup was created
        corrupt_backups = list(self.state_dir.glob("state.json.corrupt_*"))
        self.assertGreaterEqual(len(corrupt_backups), 1)
        self.assertEqual(corrupt_backups[0].read_text(encoding="utf-8"), "INVALID_JSON_CORRUPTED_BYTES{{{")

    def test_m1_06_real_live_drive_inbox_scheduled_detection_verified(self):
        real_state_file = Path(r"C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher\state.json")
        if not real_state_file.exists():
            self.skipTest("Live state file not present on this machine")

        with open(real_state_file, "r", encoding="utf-8") as f:
            live_state = json.load(f)

        tracked = live_state.get("tracked_files", {})
        self.assertIn("FR-TZ-20261116-002_Stage4.2.6_54c2f947_FlyingRAG.txt", tracked)
        doc = tracked["FR-TZ-20261116-002_Stage4.2.6_54c2f947_FlyingRAG.txt"]
        self.assertEqual(doc["lifecycle_status"], "ACKNOWLEDGED")
        self.assertEqual(doc["version_number"], 1)
        self.assertEqual(doc["sha256"], "a336606633ea4bdd57be6f06e1a667bcd70a6dd78c10d222e4b7f6c2ade4b87c")
        self.assertEqual(doc["size_bytes"], 23676)
        # Verify spool file exists on disk
        spool_path = Path(r"C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher\inbox_spool\FR-TZ-20261116-002_Stage4.2.6_54c2f947_FlyingRAG_v1_a3366066.txt")
        self.assertTrue(spool_path.exists())
        self.assertEqual(spool_path.stat().st_size, 23676)


    def test_m2_01_corrupt_state_halts_safely_without_reemitting_events_or_overwriting_state(self):
        # 1. Process an initial file to create legitimate spool and notification
        doc = self.inbox_dir / "FR-TZ-20261116-010_CorruptSafe.txt"
        doc.write_text("Legitimate task content", encoding="utf-8")
        w1 = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        res1 = w1.run_locked_cycle()
        self.assertEqual(res1["acknowledged_count"], 1)
        self.assertEqual(len(res1["new_events"]), 1)

        # 2. Corrupt state.json with truncated/invalid bytes
        state_file = self.state_dir / "state.json"
        state_file.write_text("CORRUPTED_JSON_TRUNCATED_EOF{{{", encoding="utf-8")

        # 3. New watcher instance polls under corrupt state
        w2 = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        res2 = w2.poll()
        self.assertEqual(res2["status"], "STATE_CORRUPT_HALTED")
        self.assertEqual(res2["acknowledged_count"], 0)
        self.assertEqual(len(res2["new_events"]), 0)

        # 4. State file was NOT overwritten with blank state
        self.assertEqual(state_file.read_text(encoding="utf-8"), "CORRUPTED_JSON_TRUNCATED_EOF{{{")

        # 5. Safe recovery from artifacts restores previous ACK without re-emitting events
        recovered_state = w2.reconstruct_state_from_artifacts()
        self.assertIn("FR-TZ-20261116-010_CorruptSafe.txt", recovered_state["tracked_files"])
        self.assertEqual(recovered_state["tracked_files"]["FR-TZ-20261116-010_CorruptSafe.txt"]["lifecycle_status"], "ACKNOWLEDGED")
        self.assertEqual(len(recovered_state["history"]), 1)

        # Subsequent poll after recovery emits 0 duplicate events
        res3 = w2.poll()
        self.assertEqual(res3["acknowledged_count"], 0)
        self.assertEqual(len(res3["new_events"]), 0)

    def test_m2_02_deterministic_event_id_prevents_duplicate_on_crash_restart(self):
        doc = self.inbox_dir / "FR-TZ-20261116-011_CrashRestart.txt"
        doc.write_text("Crash restart payload", encoding="utf-8")

        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)

        # Run first cycle: emits event
        res1 = watcher.poll()
        self.assertEqual(res1["acknowledged_count"], 1)
        self.assertEqual(len(res1["new_events"]), 1)
        event_id = res1["new_events"][0]["event_id"]

        # Simulate crash before state commit: state.json is deleted or rolled back to empty
        watcher.state["history"] = []
        watcher.state["tracked_files"] = {}
        # But notification file already exists in notifications/
        event_file = watcher.notifications_dir / f"{event_id}.json"
        self.assertTrue(event_file.exists())

        # Restart poll: deterministic ID ensures event_path.exists() is respected
        res2 = watcher.poll()
        # Event is added to history once, not duplicated
        self.assertEqual(len(watcher.state["history"]), 1)
        self.assertEqual(watcher.state["history"][0]["event_id"], event_id)
        # Exactly one notification JSON file exists on disk
        notification_files = list(watcher.notifications_dir.glob("*.json"))
        self.assertEqual(len(notification_files), 1)

    def test_m2_03_retry_count_increments_and_max_attempts_marks_failed_permanent(self):
        doc = self.inbox_dir / "FR-TZ-20261116-012_RetryExhaust.txt"
        doc.write_text("Retry test content", encoding="utf-8")

        watcher = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)

        orig_read_bytes = Path.read_bytes
        try:
            # Force read failure
            Path.read_bytes = MagicMock(side_effect=IOError("Persistent I/O failure"))

            for cycle in range(1, 5):
                res = watcher.poll()
                self.assertEqual(res["failed_retry_count"], 1)
                rec = watcher.state["tracked_files"][doc.name]
                self.assertEqual(rec["lifecycle_status"], "FAILED_RETRY")
                self.assertEqual(rec["retry_count"], cycle)
                self.assertEqual(rec["version_number"], 1)  # Version NOT incremented

            # 5th attempt: exhausts budget (MAX_RETRIES = 5) -> FAILED_PERMANENT
            res5 = watcher.poll()
            self.assertEqual(res5["failed_retry_count"], 1)
            rec5 = watcher.state["tracked_files"][doc.name]
            self.assertEqual(rec5["lifecycle_status"], "FAILED_PERMANENT")
            self.assertEqual(rec5["retry_count"], 5)

            # 6th attempt with unchanged file: skipped, 0 retry attempts
            res6 = watcher.poll()
            self.assertEqual(res6["failed_retry_count"], 0)
            self.assertEqual(watcher.state["tracked_files"][doc.name]["lifecycle_status"], "FAILED_PERMANENT")

        finally:
            Path.read_bytes = orig_read_bytes

        # Modifying the file resets retry_count and enables fresh retry
        time.sleep(0.01)
        doc.write_text("Modified new content for recovery", encoding="utf-8")
        res_mod = watcher.poll()
        self.assertEqual(res_mod["acknowledged_count"], 1)
        self.assertEqual(watcher.state["tracked_files"][doc.name]["lifecycle_status"], "ACKNOWLEDGED")
        self.assertEqual(watcher.state["tracked_files"][doc.name]["retry_count"], 0)

    def test_m2_04_real_live_drive_inbox_scheduled_detection_stage4_2_7_verified(self):
        real_state_file = Path(r"C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher\state.json")
        if not real_state_file.exists():
            self.skipTest("Live state file not present on this machine")

        with open(real_state_file, "r", encoding="utf-8") as f:
            live_state = json.load(f)

        tracked = live_state.get("tracked_files", {})
        self.assertIn("FR-TZ-20261116-003_Stage4.2.7_cf2fb139_FlyingRAG.txt", tracked)
        doc = tracked["FR-TZ-20261116-003_Stage4.2.7_cf2fb139_FlyingRAG.txt"]
        self.assertEqual(doc["lifecycle_status"], "ACKNOWLEDGED")
        self.assertEqual(doc["version_number"], 1)
        self.assertEqual(doc["sha256"], "21b452efe5d873067d6b60c0b07f2ede37ae08d0bd5b2c241fd5478eba477e32")
        self.assertEqual(doc["size_bytes"], 18178)
        # Verify spool file exists on disk
        spool_path = Path(r"C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher\inbox_spool\FR-TZ-20261116-003_Stage4.2.7_cf2fb139_FlyingRAG_v1_21b452ef.txt")
        self.assertTrue(spool_path.exists())
        self.assertEqual(spool_path.stat().st_size, 18178)


if __name__ == "__main__":
    unittest.main()
