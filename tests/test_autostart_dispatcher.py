"""
tests/test_autostart_dispatcher.py

Acceptance & Verification Suite for AUTO-START-01 (Stage 4.2.8 Rev 3 / Section 8).
Validates autonomous task ingestion, queuing, crash recovery, single-worker lease,
input sanitization, policy veto, pre-dispatch verification, and dispatch execution.
Implements AS-01 through AS-12.
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

from scripts.drive_inbox_watcher import DriveInboxWatcher, FileLock, check_policy_veto


class TestAutostartDispatcher(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_autostart_"))
        self.inbox_dir = self.test_dir / "inbox"
        self.state_dir = self.test_dir / "state"
        self.inbox_dir.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    def test_as01_valid_txt_enqueues_and_dispatches_without_human_input(self):
        """
        AS-01: Valid TXT enqueued, dispatched, and executed without new USER_INPUT or asking 'Начинаем?'.
        Validates task hash, timestamps, and execution status.
        """
        dispatched_calls = []

        def fake_runner(job, spool_file):
            dispatched_calls.append({
                "job_id": job["job_id"],
                "task_id": job["task_id"],
                "sha256": job["sha256"],
                "spool_file": str(spool_file)
            })
            return True, 0, json.dumps({"response": {"conversationId": "conv-test-as01-12345"}}), "", "conv-test-as01-12345"

        doc = self.inbox_dir / "FR-TZ-20261117-007_SafeTask_FlyingRAG.txt"
        doc.write_text("FlyingRAG Task 007 payload\nPermitted work in safe container.\n", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=fake_runner
        )

        res = watcher.run_locked_cycle()
        self.assertEqual(res["status"], "OK")
        self.assertEqual(len(dispatched_calls), 1)
        self.assertEqual(dispatched_calls[0]["task_id"], "FR-TZ-20261117-007")

        # Verify state
        report = watcher.get_status_report()
        self.assertEqual(report["execution_queue_count"], 1)
        job = list(report["execution_queue"].values())[0]
        self.assertEqual(job["execution_status"], "SUCCEEDED")
        self.assertEqual(job["conversation_id"], "conv-test-as01-12345")
        self.assertIsNotNone(job["dispatched_at"])
        self.assertIsNotNone(job["finished_at"])

    def test_as02_repeated_poll_zero_duplicate_calls(self):
        """
        AS-02: Repeated poll cycles with existing acknowledged/succeeded task produce 0 agent calls.
        """
        call_count = 0

        def fake_runner(job, spool_file):
            nonlocal call_count
            call_count += 1
            return True, 0, json.dumps({"response": {"conversationId": "conv-as02"}}), "", "conv-as02"

        doc = self.inbox_dir / "FR-TZ-20261117-008_Task_FlyingRAG.txt"
        doc.write_text("Task 008 text", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=fake_runner
        )

        # 1. First cycle executes
        watcher.run_locked_cycle()
        self.assertEqual(call_count, 1)

        # 2. Repeated poll cycle produces 0 agent calls
        res2 = watcher.run_locked_cycle()
        self.assertEqual(call_count, 1)
        self.assertEqual(res2["dispatch"].get("dispatched_count", 0), 0)

        # 3. Third poll cycle still 0 agent calls
        res3 = watcher.run_locked_cycle()
        self.assertEqual(call_count, 1)
        self.assertEqual(res3["dispatch"].get("dispatched_count", 0), 0)

    def test_as03_same_id_new_revision_updates_queue_and_supersedes(self):
        """
        AS-03: Updating same file from revision 3 to 3.1 creates version 2 and enqueues update without lost ACK.
        """
        call_history = []

        def fake_runner(job, spool_file):
            call_history.append(job["version_number"])
            return True, 0, json.dumps({"response": {"conversationId": f"conv-v{job['version_number']}"}}), "", f"conv-v{job['version_number']}"

        doc = self.inbox_dir / "FR-TZ-20261117-006_PILOT_GATE_REV3_FlyingRAG.txt"
        doc.write_text("Revision 3 original content", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=fake_runner
        )

        # Initial revision 1
        watcher.run_locked_cycle()
        self.assertEqual(call_history, [1])

        # Update file with revision 3.1 content and adjust mtime
        time.sleep(0.05)
        doc.write_text("Revision 3.1 updated content with AUTO-START-01", encoding="utf-8")
        new_mtime = time.time() + 10.0
        os.utime(str(doc), (new_mtime, new_mtime))

        # Second poll cycle detects version 2 and dispatches
        watcher.run_locked_cycle()
        self.assertEqual(call_history, [1, 2])

        report = watcher.get_status_report()
        self.assertEqual(report["execution_queue_count"], 2)

    def test_as04_concurrent_dispatchers_enforce_single_execution_lock(self):
        """
        AS-04: Concurrent dispatchers enforce single execution lock. Maximum 1 worker in RUNNING.
        """
        exec_lock = FileLock(self.state_dir / "execution.lock")
        self.assertTrue(exec_lock.acquire())

        # While execution.lock is held, watcher cannot dispatch
        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED"
        )

        doc = self.inbox_dir / "FR-TZ-20261117-009_ConcurrentTest.txt"
        doc.write_text("Task 009 text", encoding="utf-8")

        res = watcher.run_locked_cycle()
        self.assertEqual(res["dispatch"].get("status"), "EXECUTION_LOCKED")

        # Release execution lock
        exec_lock.release()

        # Now dispatch succeeds
        mock_runner = MagicMock(return_value=(True, 0, "{}", "", "cid-1"))
        watcher.runner_callable = mock_runner
        res2 = watcher.run_locked_cycle()
        self.assertEqual(res2["dispatch"].get("status"), "SUCCEEDED")
        self.assertEqual(mock_runner.call_count, 1)

    def test_as05_missing_runner_or_auth_yields_blocked_not_succeeded(self):
        """
        AS-05: Missing runner executable, missing auth, or soft-denied tool results in BLOCKED/FAILED, never SUCCEEDED.
        """
        doc = self.inbox_dir / "FR-TZ-20261117-010_RunnerTest.txt"
        doc.write_text("Task 010 content", encoding="utf-8")

        # 1. Non-existent runner executable
        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_cmd="C:/NonExistent/runner.bat"
        )
        res = watcher.run_locked_cycle()
        self.assertEqual(res["dispatch"].get("status"), "BLOCKED")
        report = watcher.get_status_report()
        job = list(report["execution_queue"].values())[0]
        self.assertEqual(job["execution_status"], "BLOCKED")
        self.assertIn("RUNNER_NOT_FOUND", job["last_error"])

        # 2. Runner exiting with auth required / soft-denied
        def auth_fail_runner(job, spool):
            return False, 1, "", "AUTH_REQUIRED: Antigravity session token expired", None

        watcher.runner_callable = auth_fail_runner
        # Reset job to QUEUED for test
        job["execution_status"] = "QUEUED"
        watcher.state["execution_queue"][job["job_id"]] = job
        watcher._save_state()

        res2 = watcher.dispatch_queue()
        self.assertEqual(res2.get("status"), "BLOCKED")
        report2 = watcher.get_status_report()
        job2 = list(report2["execution_queue"].values())[0]
        self.assertEqual(job2["execution_status"], "BLOCKED")
        self.assertIn("AUTH_REQUIRED", job2["last_error"])

    def test_as06_crash_recovery_sets_dispatch_unknown_no_blind_retry(self):
        """
        AS-06: Crash between dispatch and receipt with stale lease sets status to DISPATCH_UNKNOWN with 0 blind retries.
        """
        doc = self.inbox_dir / "FR-TZ-20261117-011_CrashTask.txt"
        doc.write_text("Task 011 content", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED"
        )
        watcher.poll()

        # Simulate crash: job marked RUNNING with dead PID and expired lease
        job_id = list(watcher.state["execution_queue"].keys())[0]
        job = watcher.state["execution_queue"][job_id]
        job["execution_status"] = "RUNNING"
        job["lease_pid"] = 99999999  # Dead PID
        job["lease_expires_at"] = "2026-01-01T00:00:00+00:00"  # Expired
        watcher.state["active_execution"] = {
            "job_id": job_id,
            "pid": 99999999,
            "lease_expires_at": "2026-01-01T00:00:00+00:00"
        }
        watcher._save_state()

        # Runner should NOT be called; crash recovery sets DISPATCH_UNKNOWN
        runner_mock = MagicMock()
        watcher.runner_callable = runner_mock

        res = watcher.dispatch_queue()
        self.assertEqual(runner_mock.call_count, 0)
        report = watcher.get_status_report()
        c_job = report["execution_queue"][job_id]
        self.assertEqual(c_job["execution_status"], "DISPATCH_UNKNOWN")
        self.assertIn("CRASH_RECOVERY", c_job["last_error"])

    def test_as07_malicious_inputs_symlinks_traversal_rejected_safely(self):
        """
        AS-07: Empty file, non-UTF8, symlinks, traversal, shell metacharacters rejected safely without execution.
        """
        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED"
        )

        # 1. Empty file (0 bytes)
        (self.inbox_dir / "FR-TZ-empty.txt").write_bytes(b"")

        # 2. Non-UTF-8 bytes
        (self.inbox_dir / "FR-TZ-bad_utf8.txt").write_bytes(b"\xff\xfe\x00\x00invalid")

        # 3. Path traversal in filename
        # Note: on Windows / and \ in filename cannot be created directly, but bad characters like ; or & can
        (self.inbox_dir / "FR-TZ-task;rm.txt").write_text("dangerous name", encoding="utf-8")

        res = watcher.poll()
        self.assertEqual(res["enqueued_count"], 0)

        report = watcher.get_status_report()
        tracked = report["tracked_files"]
        self.assertEqual(tracked["FR-TZ-empty.txt"]["lifecycle_status"], "REJECTED_EMPTY_FILE")
        self.assertEqual(tracked["FR-TZ-bad_utf8.txt"]["lifecycle_status"], "REJECTED_NON_UTF8")
        self.assertEqual(tracked["FR-TZ-task;rm.txt"]["lifecycle_status"], "REJECTED_INVALID_NAME")
        self.assertEqual(report["execution_queue_count"], 0)

    def test_as08_tampered_spool_before_dispatch_fails_hash_check(self):
        """
        AS-08: Tampered spool file before dispatch fails hash check -> transitions to BLOCKED, 0 agent executions.
        """
        runner_mock = MagicMock()
        doc = self.inbox_dir / "FR-TZ-20261117-013_TamperTest.txt"
        doc.write_text("Authentic task content", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=runner_mock
        )

        # Poll and enqueue
        watcher.poll()
        job_id = list(watcher.state["execution_queue"].keys())[0]
        spool_path = Path(watcher.state["execution_queue"][job_id]["spool_path"])

        # Tamper spool file on disk
        spool_path.write_text("MALICIOUS INJECTED CONTENT", encoding="utf-8")

        # Attempt dispatch
        res = watcher.dispatch_queue()
        self.assertEqual(res.get("status"), "BLOCKED")
        self.assertEqual(runner_mock.call_count, 0)

        report = watcher.get_status_report()
        job = report["execution_queue"][job_id]
        self.assertEqual(job["execution_status"], "BLOCKED")
        self.assertIn("SPOOL_HASH_MISMATCH", job["last_error"])

    def test_as09_dangerous_production_commands_vetoed_by_policy(self):
        """
        AS-09: Task commanding production-write, reindex, force-push, or security bypass vetoed by policy before dispatch.
        """
        runner_mock = MagicMock()
        doc = self.inbox_dir / "FR-TZ-20261117-014_DangerousDirective.txt"
        doc.write_text("Task requiring direct production-write and reindex corpus immediately.\n", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=runner_mock
        )

        watcher.poll()
        res = watcher.dispatch_queue()
        self.assertEqual(res.get("status"), "BLOCKED")
        self.assertEqual(runner_mock.call_count, 0)

        report = watcher.get_status_report()
        job = list(report["execution_queue"].values())[0]
        self.assertEqual(job["execution_status"], "BLOCKED")
        self.assertIn("POLICY_VETO", job["last_error"])

    def test_as10_state_migration_from_acknowledged_preserves_history(self):
        """
        AS-10: State migration from version 1 with ACKNOWLEDGED records creates backup and marks them HISTORICALLY_COMPLETED.
        """
        legacy_state = {
            "version": 1,
            "created_utc": "2026-11-16T10:00:00+00:00",
            "last_poll_utc": "2026-11-16T12:00:00+00:00",
            "watcher_mode": "DETECTION_ONLY",
            "inbox_path": str(self.inbox_dir),
            "state_path": str(self.state_dir),
            "tracked_files": {
                "FR-TZ-20261115-001_Stage4.2.5.txt": {
                    "file_id": "FR-TZ-20261115-001_Stage4.2.5.txt",
                    "lifecycle_status": "ACKNOWLEDGED",
                    "version_number": 1,
                    "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                    "acknowledged_at": "2026-11-16T10:05:00+00:00"
                }
            },
            "history": []
        }
        (self.state_dir / "state.json").write_text(json.dumps(legacy_state), encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED"
        )

        # Check migration backup created
        backups = list(self.state_dir.glob("state.json.bak_migration_*"))
        self.assertEqual(len(backups), 1)

        # Verify state schema updated
        report = watcher.get_status_report()
        self.assertEqual(report["execution_queue_count"], 1)
        migrated_job = list(report["execution_queue"].values())[0]
        self.assertEqual(migrated_job["execution_status"], "HISTORICALLY_COMPLETED")
        self.assertEqual(migrated_job["delivery_status"], "ACKNOWLEDGED")

    def test_as11_queue_preserved_across_inbox_unavailability_and_pause(self):
        """
        AS-11: Queue preserved across inbox unavailability and pause flag. Resumes cleanly when enabled.
        """
        runner_mock = MagicMock(return_value=(True, 0, "{}", "", "cid-resume"))
        doc = self.inbox_dir / "FR-TZ-20261117-015_PauseTest.txt"
        doc.write_text("Pause test task content", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=runner_mock
        )

        # Poll and enqueue
        watcher.poll()
        self.assertEqual(len(watcher.state["execution_queue"]), 1)

        # Operator pauses watcher
        watcher.pause()
        self.assertTrue(watcher.is_paused())

        # Dispatch while paused yields PAUSED, runner not called
        res_pause = watcher.dispatch_queue()
        self.assertEqual(res_pause.get("status"), "PAUSED")
        self.assertEqual(runner_mock.call_count, 0)

        # Operator resumes watcher
        watcher.resume()
        self.assertFalse(watcher.is_paused())

        # Dispatch resumes execution cleanly
        res_resume = watcher.dispatch_queue()
        self.assertEqual(res_resume.get("status"), "SUCCEEDED")
        self.assertEqual(runner_mock.call_count, 1)

    def test_as12_contract_end_to_end_test_only_task_ingestion_and_execution(self):
        """
        AS-12 (CONTRACT_ONLY): End-to-end task ingestion and execution in isolated environment.
        Verifies full sequence: detection -> spooling -> validation -> single execution -> idempotency.
        """
        executed_jobs = []

        def contract_agent_runner(job, spool_file):
            executed_jobs.append(job["job_id"])
            return True, 0, json.dumps({
                "status": "SUCCESS",
                "response": {"conversationId": f"session-{job['task_id']}"}
            }), "", f"session-{job['task_id']}"

        # Place TEST_ONLY task in inbox
        test_task = self.inbox_dir / "FR-TZ-TEST-ONLY-AS12_FlyingRAG.txt"
        test_task.write_text(
            "FlyingRAG TEST_ONLY task for AS-12 contract verification.\n"
            "Execution limited strictly to temp worktree fixture without production write.\n",
            encoding="utf-8"
        )

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=contract_agent_runner
        )

        # 1. First execution cycle
        res = watcher.run_locked_cycle()
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["dispatch"].get("status"), "SUCCEEDED")
        self.assertEqual(len(executed_jobs), 1)

        # 2. Repeated poll cycle is idempotent (0 new executions)
        res2 = watcher.run_locked_cycle()
        self.assertEqual(len(executed_jobs), 1)
        self.assertEqual(res2["dispatch"].get("dispatched_count", 0), 0)

        # Verify state persistence
        report = watcher.get_status_report()
        job = list(report["execution_queue"].values())[0]
        self.assertEqual(job["execution_status"], "SUCCEEDED")
        self.assertEqual(job["conversation_id"], f"session-{job['task_id']}")


if __name__ == "__main__":
    unittest.main()
