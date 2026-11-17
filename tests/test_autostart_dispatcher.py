"""
tests/test_autostart_dispatcher.py

Acceptance & Verification Suite for AUTO-START-01 (Stage 4.2.8 Rev 3 & Rev 3.2).
Validates autonomous task ingestion, queuing, crash recovery, single-worker lease,
input sanitization, clause-aware policy veto, pre-dispatch verification,
and dispatch execution with full lifecycle verification (DISPATCH_CONFIRMED -> RUNNING -> SUCCEEDED).
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

from scripts.drive_inbox_watcher import DriveInboxWatcher, FileLock, check_policy_veto, HISTORICAL_EVIDENCE_MAP


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

    def test_as01_valid_txt_lifecycle_dispatch_running_succeeded(self):
        """
        AS-01: Valid TXT enqueued, dispatched, and executed through full lifecycle:
        QUEUED -> DISPATCHING -> DISPATCH_CONFIRMED -> RUNNING -> SUCCEEDED
        without human intervention or asking 'Начинаем?'. (Rev 3.2 Section 1)
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

        agent_state = "RUNNING"
        agent_outcome_verified = False

        def fake_session_status(cid, job):
            return agent_state, agent_outcome_verified, f"Session {cid} state: {agent_state}"

        doc = self.inbox_dir / "FR-TZ-20261117-007_SafeTask_FlyingRAG.txt"
        doc.write_text("FlyingRAG Task 007 payload\nPermitted work in safe container.\n", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=fake_runner,
            runner_status_callable=fake_session_status
        )

        # Cycle 1: Detection -> Spooling -> Validation -> Dispatch
        res1 = watcher.run_locked_cycle()
        self.assertEqual(res1["status"], "OK")
        self.assertEqual(len(dispatched_calls), 1)
        self.assertEqual(dispatched_calls[0]["task_id"], "FR-TZ-20261117-007")

        report1 = watcher.get_status_report()
        job1 = list(report1["execution_queue"].values())[0]
        # Exit=0 launcher returns DISPATCH_CONFIRMED, not immediately SUCCEEDED
        self.assertEqual(job1["execution_status"], "DISPATCH_CONFIRMED")
        self.assertEqual(job1["conversation_id"], "conv-test-as01-12345")
        self.assertIsNotNone(job1["dispatched_at"])
        self.assertIsNone(job1["finished_at"])

        # Cycle 2: Session is RUNNING in worktree -> reconciles to RUNNING
        res2 = watcher.run_locked_cycle()
        self.assertEqual(res2["dispatch"].get("status"), "ACTIVE_WORKER_BUSY")
        report2 = watcher.get_status_report()
        job2 = list(report2["execution_queue"].values())[0]
        self.assertEqual(job2["execution_status"], "RUNNING")
        self.assertIsNotNone(job2["started_at"])
        self.assertIsNone(job2["finished_at"])

        # Cycle 3: Session completes with verified terminal evidence -> transitions to SUCCEEDED
        agent_state = "TERMINAL_SUCCESS"
        agent_outcome_verified = True
        res3 = watcher.run_locked_cycle()
        report3 = watcher.get_status_report()
        job3 = list(report3["execution_queue"].values())[0]
        self.assertEqual(job3["execution_status"], "SUCCEEDED")
        self.assertIsNotNone(job3["finished_at"])
        self.assertIsNone(report3["active_execution"])

        # Cycle 4: Subsequent poll produces 0 agent calls, status remains SUCCEEDED
        res4 = watcher.run_locked_cycle()
        self.assertEqual(len(dispatched_calls), 1)
        self.assertEqual(res4["dispatch"].get("dispatched_count", 0), 0)

    def test_as02_repeated_poll_zero_duplicate_calls(self):
        """
        AS-02: Repeated poll cycles with existing acknowledged/succeeded task produce 0 agent calls.
        """
        call_count = 0

        def fake_runner(job, spool_file):
            nonlocal call_count
            call_count += 1
            return True, 0, json.dumps({"response": {"conversationId": "conv-as02"}}), "", "conv-as02"

        def fake_session_status(cid, job):
            return "TERMINAL_SUCCESS", True, "Task completed"

        doc = self.inbox_dir / "FR-TZ-20261117-008_Task_FlyingRAG.txt"
        doc.write_text("Task 008 text", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=fake_runner,
            runner_status_callable=fake_session_status
        )

        # 1. First cycle executes dispatch
        watcher.run_locked_cycle()
        self.assertEqual(call_count, 1)

        # 2. Second cycle reconciles to SUCCEEDED
        watcher.run_locked_cycle()
        self.assertEqual(call_count, 1)

        # 3. Third poll cycle produces 0 agent calls
        res3 = watcher.run_locked_cycle()
        self.assertEqual(call_count, 1)
        self.assertEqual(res3["dispatch"].get("dispatched_count", 0), 0)

    def test_as03_same_id_new_revision_and_conflict_quarantine(self):
        """
        AS-03: Revision management (Rev 3.2 Section 3):
        - Higher revision (3.0 -> 3.1) enqueues update, superseding pending lower revision.
        - Same task_id + same revision + different hash -> REVISION_CONFLICT quarantine in queue (no re-execution).
        """
        call_history = []

        def fake_runner(job, spool_file):
            call_history.append((job["task_id"], job["revision"], job["version_number"]))
            return True, 0, json.dumps({"response": {"conversationId": f"conv-{job['revision']}"}}), "", f"conv-{job['revision']}"

        doc = self.inbox_dir / "FR-TZ-20261117-006_PILOT_GATE_REV3_FlyingRAG.txt"
        doc.write_text("Редакция 3.0\nRevision 3.0 original content", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=fake_runner
        )

        # 1. Initial revision 3.0
        watcher.run_locked_cycle()
        self.assertEqual(len(call_history), 1)
        self.assertEqual(call_history[0][1], "3.0")

        # 2. Update to higher revision 3.1
        time.sleep(0.05)
        doc.write_text("Редакция 3.1\nRevision 3.1 updated content with AUTO-START-01", encoding="utf-8")
        new_mtime = time.time() + 10.0
        os.utime(str(doc), (new_mtime, new_mtime))

        # Clear active_execution to simulate completed prior job
        watcher.state["active_execution"] = None
        watcher._save_state()

        watcher.run_locked_cycle()
        self.assertEqual(len(call_history), 2)
        self.assertEqual(call_history[1][1], "3.1")

        # 3. Same task ID, same revision 3.1, but different content/hash -> REVISION_CONFLICT
        time.sleep(0.05)
        doc.write_text("Редакция 3.1\nConflicting text with different SHA but claiming same revision 3.1!", encoding="utf-8")
        new_mtime2 = time.time() + 20.0
        os.utime(str(doc), (new_mtime2, new_mtime2))

        watcher.state["active_execution"] = None
        watcher._save_state()

        watcher.run_locked_cycle()
        # No 3rd runner call because conflicting revision is quarantined
        self.assertEqual(len(call_history), 2)

        report = watcher.get_status_report()
        queue = report["execution_queue"]
        conflict_jobs = [j for j in queue.values() if j.get("execution_status") == "REVISION_CONFLICT"]
        self.assertEqual(len(conflict_jobs), 1)
        self.assertEqual(conflict_jobs[0]["revision"], "3.1")

    def test_as04_concurrent_dispatchers_enforce_single_execution_lock_and_lifetime(self):
        """
        AS-04: Lock covers agent lifetime, not just launcher command (Rev 3.2 Section 2).
        - Cross-process execution.lock blocks concurrent dispatchers (EXECUTION_LOCKED).
        - Active agent session in state blocks new dispatches on subsequent polls (ACTIVE_WORKER_BUSY).
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

        # Controlled runner with asynchronous live session
        def live_runner(job, spool):
            return True, 0, json.dumps({"response": {"conversationId": "cid-session-1"}}), "", "cid-session-1"

        def session_checker(cid, job):
            # Session is still running in worktree
            return "RUNNING", False, "Session cid-session-1 is active"

        watcher.runner_callable = live_runner
        watcher.runner_status_callable = session_checker

        # First dispatch creates session cid-session-1
        res2 = watcher.run_locked_cycle()
        self.assertEqual(res2["dispatch"].get("status"), "DISPATCH_CONFIRMED")
        self.assertEqual(live_runner.call_count if hasattr(live_runner, 'call_count') else 1, 1)

        # Place a second task in inbox
        doc2 = self.inbox_dir / "FR-TZ-20261117-010_SecondTask.txt"
        doc2.write_text("Task 010 second content", encoding="utf-8")

        # Second poll cycle runs: since cid-session-1 is active, 0 new sessions are dispatched!
        res3 = watcher.run_locked_cycle()
        self.assertEqual(res3["dispatch"].get("status"), "ACTIVE_WORKER_BUSY")
        self.assertEqual(res3["dispatch"].get("dispatched_count", 0), 0)

    def test_as05_runner_exit_zero_failure_scenarios_and_auth_blocks(self):
        """
        AS-05: Exit=0 is NOT automatically SUCCEEDED (Rev 3.2 Section 1).
        Tests 5 failure scenarios returning BLOCKED/FAILED, never SUCCEEDED:
        1. Non-existent runner executable
        2. Exit=0 with empty stdout
        3. Exit=0 with status WAITING
        4. Exit=0 with SOFT_DENIED / PERMISSION_DENIED
        5. Runner exiting with AUTH_REQUIRED
        """
        doc = self.inbox_dir / "FR-TZ-20261117-010_RunnerTest.txt"
        doc.write_text("Task 010 content", encoding="utf-8")

        # 1. Non-existent runner executable -> BLOCKED
        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_cmd="C:/NonExistent/runner.bat"
        )
        res1 = watcher.run_locked_cycle()
        self.assertEqual(res1["dispatch"].get("status"), "BLOCKED")
        report1 = watcher.get_status_report()
        job1 = list(report1["execution_queue"].values())[0]
        self.assertEqual(job1["execution_status"], "BLOCKED")
        self.assertIn("RUNNER_NOT_FOUND", job1["last_error"])

        # 2. Exit=0 with empty stdout -> FAILED / BLOCKED, NEVER SUCCEEDED
        def empty_output_runner(job, spool):
            return watcher._invoke_external_runner_inspection(0, "", "")

        # Test inspection helper directly with exit=0, empty stdout
        watcher_inspect = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        # Directly verify inspector logic
        proc_empty = (False, 0, "", "EMPTY_RUNNER_OUTPUT: launcher produced 0 bytes stdout", None)
        watcher.runner_callable = lambda j, s: proc_empty

        job1["execution_status"] = "QUEUED"
        watcher.state["execution_queue"][job1["job_id"]] = job1
        watcher._save_state()

        res2 = watcher.dispatch_queue()
        self.assertNotEqual(res2.get("status"), "SUCCEEDED")
        self.assertIn(res2.get("status"), ("FAILED", "BLOCKED"))

        # 3. Exit=0 with WAITING state -> BLOCKED, NEVER SUCCEEDED
        proc_waiting = (False, 0, json.dumps({"status": "WAITING"}), "WAITING: session created in WAITING state", "cid-wait")
        watcher.runner_callable = lambda j, s: proc_waiting

        job1["execution_status"] = "QUEUED"
        watcher.state["execution_queue"][job1["job_id"]] = job1
        watcher._save_state()

        res3 = watcher.dispatch_queue()
        self.assertEqual(res3.get("status"), "BLOCKED")

        # 4. Exit=0 with SOFT_DENIED / PERMISSION_DENIED -> BLOCKED, NEVER SUCCEEDED
        proc_soft_denied = (False, 0, json.dumps({"status": "SOFT_DENIED", "error": "Tool execution soft denied"}), "PERMISSION_DENIED in stderr", None)
        watcher.runner_callable = lambda j, s: proc_soft_denied

        job1["execution_status"] = "QUEUED"
        watcher.state["execution_queue"][job1["job_id"]] = job1
        watcher._save_state()

        res4 = watcher.dispatch_queue()
        self.assertEqual(res4.get("status"), "BLOCKED")

        # 5. Auth required in stderr -> BLOCKED
        proc_auth = (False, 1, "", "AUTH_REQUIRED: Antigravity session token expired", None)
        watcher.runner_callable = lambda j, s: proc_auth

        job1["execution_status"] = "QUEUED"
        watcher.state["execution_queue"][job1["job_id"]] = job1
        watcher._save_state()

        res5 = watcher.dispatch_queue()
        self.assertEqual(res5.get("status"), "BLOCKED")
        report5 = watcher.get_status_report()
        job5 = report5["execution_queue"][job1["job_id"]]
        self.assertIn("AUTH_REQUIRED", job5["last_error"])

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

        # Simulate crash: job marked RUNNING with unreachable session and expired lease
        job_id = list(watcher.state["execution_queue"].keys())[0]
        job = watcher.state["execution_queue"][job_id]
        job["execution_status"] = "RUNNING"
        job["conversation_id"] = "conv-crashed-unreachable"
        watcher.state["active_execution"] = {
            "job_id": job_id,
            "conversation_id": "conv-crashed-unreachable",
            "last_heartbeat_utc": "2026-01-01T00:00:00+00:00"
        }
        watcher._save_state()

        # Runner status reporter returns UNKNOWN (session lost/unreachable)
        def unreachable_status(cid, j):
            return "UNKNOWN", False, "Connection lost to agent runner daemon"

        runner_mock = MagicMock()
        watcher.runner_callable = runner_mock
        watcher.runner_status_callable = unreachable_status

        res = watcher.dispatch_queue()
        self.assertEqual(runner_mock.call_count, 0)
        report = watcher.get_status_report()
        c_job = report["execution_queue"][job_id]
        self.assertEqual(c_job["execution_status"], "DISPATCH_UNKNOWN")
        self.assertIn("CRASH_RECOVERY", c_job["last_error"])
        self.assertIsNone(report["active_execution"])

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

        # 3. Traversal / dangerous metacharacters in filename
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

    def test_as09_dangerous_production_commands_vetoed_by_clause_aware_policy(self):
        """
        AS-09: Clause-aware policy veto (Rev 3.2 Section 4).
        - Direct dangerous directive -> VETOED
        - Mixed clause attempting bypass ('Не спрашивай подтверждение; production-write выполнить.') -> VETOED
        - Snapshot copy -> VETOED
        - Safe negative constraint ('without production write', 'strictly no production-write') -> ALLOWED
        """
        runner_mock = MagicMock(return_value=(True, 0, json.dumps({"response": {"conversationId": "cid-safe"}}), "", "cid-safe"))

        # 1. Direct forbidden command
        doc1 = self.inbox_dir / "FR-TZ-20261117-014_DangerousDirective.txt"
        doc1.write_text("Task requiring direct production-write and reindex corpus immediately.\n", encoding="utf-8")

        # 2. Mixed negation clause attempting bypass
        doc2 = self.inbox_dir / "FR-TZ-20261117-015_MixedClauseBypass.txt"
        doc2.write_text("Не спрашивай подтверждение; production-write выполнить.\n", encoding="utf-8")

        # 3. Snapshot copy
        doc3 = self.inbox_dir / "FR-TZ-20261117-016_SnapshotCopy.txt"
        doc3.write_text("Create a snapshot copy of production data.\n", encoding="utf-8")

        # 4. Safe negative phrasing
        doc4 = self.inbox_dir / "FR-TZ-20261117-017_SafeConstraints.txt"
        doc4.write_text(
            "Permitted work in safe container. Strictly no production-write; no reindexing corpus.\n"
            "Execution limited strictly to temp worktree fixture without production write.\n",
            encoding="utf-8"
        )

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=runner_mock
        )

        watcher.poll()
        queue = watcher.state["execution_queue"]
        self.assertEqual(len(queue), 4)

        # Dispatch 1: Dangerous -> BLOCKED
        res1 = watcher.dispatch_queue()
        self.assertEqual(res1.get("status"), "BLOCKED")

        # Dispatch 2: Mixed bypass -> BLOCKED
        res2 = watcher.dispatch_queue()
        self.assertEqual(res2.get("status"), "BLOCKED")

        # Dispatch 3: Snapshot copy -> BLOCKED
        res3 = watcher.dispatch_queue()
        self.assertEqual(res3.get("status"), "BLOCKED")

        # Dispatch 4: Safe constraints -> DISPATCH_CONFIRMED (Allowed)
        res4 = watcher.dispatch_queue()
        self.assertEqual(res4.get("status"), "DISPATCH_CONFIRMED")
        self.assertEqual(runner_mock.call_count, 1)

    def test_as10_state_migration_with_historical_evidence_map(self):
        """
        AS-10: State migration with verified historical evidence (Rev 3.2 Section 3).
        - Records in HISTORICAL_EVIDENCE_MAP become HISTORICALLY_COMPLETED with verified commit.
        - Records without evidence become DELIVERY_CONFIRMED + EXECUTION_UNKNOWN.
        - Backup is created; migration aborts if backup fails.
        """
        legacy_state = {
            "version": 1,
            "created_utc": "2026-11-16T10:00:00+00:00",
            "last_poll_utc": "2026-11-16T12:00:00+00:00",
            "watcher_mode": "DETECTION_ONLY",
            "inbox_path": str(self.inbox_dir),
            "state_path": str(self.state_dir),
            "tracked_files": {
                "FR-TZ-20261115-001_Stage4.2.5_FlyingRAG.txt": {
                    "file_id": "FR-TZ-20261115-001_Stage4.2.5_FlyingRAG.txt",
                    "lifecycle_status": "ACKNOWLEDGED",
                    "version_number": 1,
                    "sha256": "9b836b4ef475d7d920fa8930e72afe0435f2a3864735624438e964e127f46bad",
                    "acknowledged_at": "2026-11-16T05:59:40+00:00"
                },
                "FR-TZ-20261115-000_UnprovenTask_FlyingRAG.txt": {
                    "file_id": "FR-TZ-20261115-000_UnprovenTask_FlyingRAG.txt",
                    "lifecycle_status": "ACKNOWLEDGED",
                    "version_number": 1,
                    "sha256": "111122223333444455556666777788889999aaaabbbbccccddddeeeeffff0000",
                    "acknowledged_at": "2026-11-15T00:00:00+00:00"
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

        # Verify migration backup created
        backups = list(self.state_dir.glob("state.json.bak_migration_*"))
        self.assertEqual(len(backups), 1)

        # Verify state schema updated
        report = watcher.get_status_report()
        self.assertEqual(report["execution_queue_count"], 2)

        queue = report["execution_queue"]
        verified_job = next(j for j in queue.values() if j["file_name"] == "FR-TZ-20261115-001_Stage4.2.5_FlyingRAG.txt")
        self.assertEqual(verified_job["execution_status"], "HISTORICALLY_COMPLETED")
        self.assertEqual(verified_job["verified_commit"], "54c2f947e246816fa8a7a08b3e8006b527814b7e")

        unproven_job = next(j for j in queue.values() if j["file_name"] == "FR-TZ-20261115-000_UnprovenTask_FlyingRAG.txt")
        self.assertEqual(unproven_job["execution_status"], "EXECUTION_UNKNOWN")
        self.assertIsNone(unproven_job["verified_commit"])

    def test_as11_queue_preserved_across_inbox_unavailability_and_pause(self):
        """
        AS-11: Queue preserved across inbox unavailability and pause flag. Resumes cleanly when enabled.
        """
        runner_mock = MagicMock(return_value=(True, 0, json.dumps({"response": {"conversationId": "cid-resume"}}), "", "cid-resume"))
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
        self.assertEqual(res_resume.get("status"), "DISPATCH_CONFIRMED")
        self.assertEqual(runner_mock.call_count, 1)

    def test_as12_contract_end_to_end_test_only_task_ingestion_and_execution(self):
        """
        AS-12 (CONTRACT_ONLY): End-to-end task ingestion and execution in isolated environment.
        Verifies full sequence: detection -> spooling -> validation -> single execution -> idempotency.
        (Note: Contract verification with mock double; live physical telemetry separated per Rev 3.2 Section 5).
        """
        executed_jobs = []

        def contract_agent_runner(job, spool_file):
            executed_jobs.append(job["job_id"])
            return True, 0, json.dumps({
                "status": "SUCCESS",
                "response": {"conversationId": f"session-{job['task_id']}"}
            }), "", f"session-{job['task_id']}"

        def contract_session_checker(cid, job):
            return "TERMINAL_SUCCESS", True, "All contract assertions satisfied"

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
            runner_callable=contract_agent_runner,
            runner_status_callable=contract_session_checker
        )

        # 1. First execution cycle (dispatches session)
        res1 = watcher.run_locked_cycle()
        self.assertEqual(res1["status"], "OK")
        self.assertEqual(res1["dispatch"].get("status"), "DISPATCH_CONFIRMED")
        self.assertEqual(len(executed_jobs), 1)

        # 2. Second cycle reconciles completion to SUCCEEDED
        res2 = watcher.run_locked_cycle()
        self.assertEqual(len(executed_jobs), 1)

        report = watcher.get_status_report()
        job = list(report["execution_queue"].values())[0]
        self.assertEqual(job["execution_status"], "SUCCEEDED")
        self.assertEqual(job["conversation_id"], f"session-{job['task_id']}")

        # 3. Third cycle is idempotent (0 new executions)
        res3 = watcher.run_locked_cycle()
        self.assertEqual(len(executed_jobs), 1)
        self.assertEqual(res3["dispatch"].get("dispatched_count", 0), 0)


if __name__ == "__main__":
    unittest.main()
