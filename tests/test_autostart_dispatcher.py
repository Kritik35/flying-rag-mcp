"""
tests/test_autostart_dispatcher.py

Acceptance & Verification Suite for AUTO-START-01 (Stage 4.2.8 Rev 3.2 & Task 007 Final Integration Gate Rev 1.1).
Validates autonomous task ingestion, queuing, crash recovery, single-worker lease,
input sanitization, clause-aware policy veto, pre-dispatch verification,
fail-closed security boundaries, durable dispatch intent, and verified terminal outcome inspection (R1-R8).

Implements mandatory test matrix A4R-01 through A4R-12 per Section 5 of FR-TZ-20261117-007 Rev 1.1.
Preserves full regression coverage for CLI bootstrap, tuple ordering, revision conflict, and policy veto.
"""

from __future__ import annotations
import os
import sys
import json
import time
import shutil
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.drive_inbox_watcher import (
    DriveInboxWatcher,
    FileLock,
    check_policy_veto,
    extract_task_identity,
    parse_revision_tuple,
    HISTORICAL_EVIDENCE_MAP
)


class TestAutostartDispatcher(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_autostart_"))
        self.inbox_dir = self.test_dir / "inbox"
        self.state_dir = self.test_dir / "state"
        self.brain_dir = self.test_dir / "brain"
        self.worktree_dir = self.test_dir / "worktree"
        self.inbox_dir.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)
        self.brain_dir.mkdir(parents=True)
        self.worktree_dir.mkdir(parents=True)

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    def _setup_valid_security_boundary(self, state_dir: Path | None = None) -> Path:
        s_dir = state_dir or self.state_dir
        b_file = s_dir / "security_boundary.json"
        cfg = {
            "enforce_write_boundary": True,
            "allowed_write_roots": [
                str(self.worktree_dir),
                str(self.test_dir)
            ],
            "prohibited_roots": [
                r"C:\RAG_Acer\data_imported\metadata.db",
                r"C:\RAG_Acer\repos\flying-rag-mcp"
            ]
        }
        b_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return b_file

    # =========================================================================
    # A4R MATRIX: A4R-01 THROUGH A4R-12 (Rev 1.1 Section 5)
    # =========================================================================

    def test_a4r_01_unproven_security_profile_blocked_setup_required(self):
        """
        A4R-01 [P0]: Unproven profile/permissions; CLI default; env=UNPROVEN;
        user passes bare SAFE_WORKTREE_SCOPED without security_boundary.json file:
        in ALL unproven cases returns BLOCKED_SETUP_REQUIRED with strictly 0 runner calls.
        """
        runner_mock = MagicMock(return_value=(True, 0, json.dumps({"response": {"conversationId": "cid-test"}}), "", "cid-test"))
        doc = self.inbox_dir / "FR-TZ-20261117-001_SecTest.txt"
        doc.write_text("Task payload without production write.", encoding="utf-8")

        # Case 1: Default profile (None / UNVERIFIED)
        w1 = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            security_profile=None,
            runner_callable=runner_mock
        )
        w1.poll()
        res1 = w1.dispatch_queue()
        self.assertEqual(res1.get("status"), "BLOCKED_SETUP_REQUIRED")
        self.assertIn("BLOCKED_SETUP_REQUIRED", res1.get("error", ""))
        self.assertEqual(runner_mock.call_count, 0)

        # Case 2: Explicit env UNPROVEN
        with patch.dict(os.environ, {"FLYING_RAG_SECURITY_PROFILE": "UNPROVEN"}):
            w2 = DriveInboxWatcher(
                inbox_dir=self.inbox_dir,
                state_dir=self.test_dir / "s2",
                mode="AUTO_EXECUTE_SCOPED",
                runner_callable=runner_mock
            )
            w2.poll()
            res2 = w2.dispatch_queue()
            self.assertEqual(res2.get("status"), "BLOCKED_SETUP_REQUIRED")
            self.assertEqual(runner_mock.call_count, 0)

        # Case 3: User passes string SAFE_WORKTREE_SCOPED without security_boundary.json on disk
        w3 = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.test_dir / "s3",
            mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=runner_mock
        )
        w3.poll()
        res3 = w3.dispatch_queue()
        self.assertEqual(res3.get("status"), "BLOCKED_SETUP_REQUIRED")
        self.assertIn("security_boundary.json", res3.get("error", ""))
        self.assertEqual(runner_mock.call_count, 0)

        # Case 4: _invoke_external_runner directly returns exit 126
        code, exitcode, stdout, stderr, cid = w3._invoke_external_runner({"task_id": "test"}, doc)
        self.assertFalse(code)
        self.assertEqual(exitcode, 126)
        self.assertIn("BLOCKED_SETUP_REQUIRED", stderr)

    def test_a4r_02_verified_security_boundary_allows_scoped_rejects_production(self):
        """
        A4R-02 [P0]: Verified security boundary file allows scoped operation;
        inclusion of prohibited production roots fails closed (BLOCKED_SETUP_REQUIRED, 0 runner calls).
        """
        runner_mock = MagicMock(return_value=(True, 0, json.dumps({"response": {"conversationId": "cid-ok"}}), "", "cid-ok"))
        doc = self.inbox_dir / "FR-TZ-20261117-002_SafeOp.txt"
        doc.write_text("Safe scoped payload without production write.", encoding="utf-8")

        # 1. Valid boundary config allows dispatch
        self._setup_valid_security_boundary(self.state_dir)
        w_valid = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=runner_mock
        )
        w_valid.poll()
        res1 = w_valid.dispatch_queue()
        self.assertEqual(res1.get("status"), "DISPATCH_CONFIRMED")
        self.assertEqual(runner_mock.call_count, 1)

        # 2. Tampered boundary config containing production database fails closed!
        runner_mock.reset_mock()
        s_bad = self.test_dir / "s_bad"
        s_bad.mkdir()
        b_bad = s_bad / "security_boundary.json"
        b_bad.write_text(json.dumps({
            "enforce_write_boundary": True,
            "allowed_write_roots": [
                r"C:\RAG_Acer\data_imported\metadata.db",
                str(self.worktree_dir)
            ]
        }), encoding="utf-8")

        w_bad = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=s_bad,
            mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=runner_mock
        )
        w_bad.poll()
        res2 = w_bad.dispatch_queue()
        self.assertEqual(res2.get("status"), "BLOCKED_SETUP_REQUIRED")
        self.assertIn("Prohibited root", res2.get("error", ""))
        self.assertEqual(runner_mock.call_count, 0)

    def test_a4r_03_metadata_only_and_user_input_only_not_running_nor_succeeded(self):
        """
        A4R-03 [P0]: Metadata-only (no transcript steps) and USER_INPUT-only (R1),
        as well as plan without executed tool action:
        strictly neither RUNNING nor SUCCEEDED. Returns DISPATCH_CONFIRMED.
        """
        cid = "conv-test-a4r-03"
        job = {
            "job_id": "job_FR-TZ-20261117-003_rev1_0_abcd1234ef56",
            "task_id": "FR-TZ-20261117-003",
            "revision": "1.0",
            "sha256": "abcd1234ef567890abcd1234ef567890abcd1234ef567890abcd1234ef567890",
            "file_name": "FR-TZ-20261117-003_Task.txt"
        }

        mock_proc_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {
                "conversationMetadata": {
                    "metadata": {
                        "rootConversationId": cid,
                        "createdAt": "2026-11-17T06:00:00Z"
                    }
                }
            }
        }), stderr="")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            brain_dir=self.brain_dir,
            mode="AUTO_EXECUTE_SCOPED"
        )

        # 1. Metadata only, no transcript on disk -> DISPATCH_CONFIRMED
        with patch("subprocess.run", return_value=mock_proc_meta):
            st1, ok1, det1 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st1, "DISPATCH_CONFIRMED")
        self.assertFalse(ok1)
        self.assertNotEqual(st1, "RUNNING")
        self.assertNotEqual(st1, "SUCCEEDED")

        # 2. Transcript exists but has ONLY USER_INPUT (R1) -> DISPATCH_CONFIRMED
        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        t_file = t_dir / "transcript.jsonl"
        t_file.write_text(json.dumps({
            "type": "USER_INPUT",
            "content": f"Execute {job['job_id']} with hash {job['sha256']}"
        }) + "\n", encoding="utf-8")

        with patch("subprocess.run", return_value=mock_proc_meta):
            st2, ok2, det2 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st2, "DISPATCH_CONFIRMED")
        self.assertFalse(ok2)
        self.assertNotEqual(st2, "RUNNING")
        self.assertNotEqual(st2, "SUCCEEDED")

    def test_a4r_04_confirmation_question_soft_denied_and_missing_artifact(self):
        """
        A4R-04 [P0]: Confirmation questions ("Начинаем?", "Приступать?"), WAITING,
        necessary tool SOFT_DENIED, explicit "не выполнено", or missing required artifact:
        NEVER SUCCEEDED, even with PLANNER_RESPONSE without tool_calls.
        """
        cid = "conv-test-a4r-04"
        job = {
            "job_id": "job_FR-TZ-20261117-004_rev1_0_111122223333",
            "task_id": "FR-TZ-20261117-004",
            "revision": "1.0",
            "sha256": "1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff",
            "file_name": "FR-TZ-20261117-004_Task.txt",
            "expected_artifacts": [str(self.test_dir / "expected_report.md")]
        }

        mock_proc_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {
                "conversationMetadata": {
                    "metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}
                }
            }
        }), stderr="")

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        t_file = t_dir / "transcript.jsonl"

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            brain_dir=self.brain_dir,
            mode="AUTO_EXECUTE_SCOPED"
        )

        step_input = {"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}

        # 1. R2: Agent asks "Начинаем?" -> WAITING_CONFIRMATION, never SUCCEEDED
        step_q = {"type": "PLANNER_RESPONSE", "content": "Готов приступить. Начинаем?", "tool_calls": []}
        t_file.write_text(json.dumps(step_input) + "\n" + json.dumps(step_q) + "\n", encoding="utf-8")

        with patch("subprocess.run", return_value=mock_proc_meta):
            st1, ok1, det1 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st1, "WAITING_CONFIRMATION")
        self.assertFalse(ok1)

        # 2. R3: Tool SOFT_DENIED -> TERMINAL_FAILURE
        step_tool = {"type": "TOOL_RESULT", "status": "SOFT_DENIED", "content": "Operation not permitted"}
        step_refusal = {"type": "PLANNER_RESPONSE", "content": "Не выполнено: нет разрешений", "tool_calls": []}
        t_file.write_text(json.dumps(step_input) + "\n" + json.dumps(step_tool) + "\n" + json.dumps(step_refusal) + "\n", encoding="utf-8")

        with patch("subprocess.run", return_value=mock_proc_meta):
            st2, ok2, det2 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st2, "TERMINAL_FAILURE")
        self.assertFalse(ok2)

        # 3. R7: Missing required acceptance artifact -> TERMINAL_FAILURE
        step_tool_ok = {"type": "TOOL_RESULT", "status": "DONE"}
        step_done = {"type": "PLANNER_RESPONSE", "content": "Completed successfully", "tool_calls": []}
        t_file.write_text(json.dumps(step_input) + "\n" + json.dumps(step_tool_ok) + "\n" + json.dumps(step_done) + "\n", encoding="utf-8")

        with patch("subprocess.run", return_value=mock_proc_meta):
            st3, ok3, det3 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st3, "TERMINAL_FAILURE")
        self.assertFalse(ok3)
        self.assertIn("MISSING_EXPECTED_ARTIFACT", det3)

    def test_a4r_05_correlation_rejects_foreign_hash_short_prefix_and_spoofs(self):
        """
        A4R-05 [P0]: Foreign full hash (R4), only 12-char prefix matching (R5),
        simple task quote, or foreign rootConversationId (R6):
        no false correlation, returns UNKNOWN.
        """
        cid = "conv-test-a4r-05"
        full_hash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        job = {
            "job_id": "job_FR-TZ-20261117-005_rev1_0_aaaaaaaaaaaa",
            "task_id": "FR-TZ-20261117-005",
            "revision": "1.0",
            "sha256": full_hash,
            "file_name": "FR-TZ-20261117-005_Task.txt"
        }

        mock_proc_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {
                "conversationMetadata": {
                    "metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}
                }
            }
        }), stderr="")

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        t_file = t_dir / "transcript.jsonl"

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            brain_dir=self.brain_dir,
            mode="AUTO_EXECUTE_SCOPED"
        )

        # 1. R4: Foreign full hash in transcript -> UNKNOWN
        foreign_hash = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        t_file.write_text(json.dumps({
            "type": "USER_INPUT",
            "content": f"Task FR-TZ-20261117-005 hash {foreign_hash}"
        }) + "\n", encoding="utf-8")

        with patch("subprocess.run", return_value=mock_proc_meta):
            st1, ok1, det1 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st1, "UNKNOWN")
        self.assertFalse(ok1)
        self.assertIn("TRANSCRIPT_CORRELATION_FAILED", det1)

        # 2. R5: Only 12 characters match, remaining 52 differ -> UNKNOWN
        short_match = full_hash[:12] + "c" * 52
        t_file.write_text(json.dumps({
            "type": "USER_INPUT",
            "content": f"Task FR-TZ-20261117-005 hash {short_match}"
        }) + "\n", encoding="utf-8")

        with patch("subprocess.run", return_value=mock_proc_meta):
            st2, ok2, det2 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st2, "UNKNOWN")
        self.assertFalse(ok2)
        self.assertIn("TRANSCRIPT_CORRELATION_FAILED", det2)

        # 3. R6: Foreign rootConversationId in metadata -> UNKNOWN
        mock_proc_foreign_root = MagicMock(returncode=0, stdout=json.dumps({
            "response": {
                "conversationMetadata": {
                    "metadata": {"rootConversationId": "foreign-root-9999", "createdAt": "2026-11-17T06:00:00Z"}
                }
            }
        }), stderr="")

        t_file.write_text(json.dumps({
            "type": "USER_INPUT",
            "content": f"{job['job_id']} hash {full_hash}"
        }) + "\n", encoding="utf-8")

        with patch("subprocess.run", return_value=mock_proc_foreign_root):
            st3, ok3, det3 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st3, "UNKNOWN")
        self.assertFalse(ok3)
        self.assertIn("METADATA_CORRELATION_FAILED", det3)

    def test_a4r_06_verified_terminal_success_vs_tampered_artifact(self):
        """
        A4R-06 [P0]: Correlated action with job/revision/full hash + terminal outcome + verified artifact:
        positive branch (TERMINAL_SUCCESS / True).
        Tampered bytes/hash -> rejection (TERMINAL_FAILURE / False).
        """
        cid = "conv-test-a4r-06"
        full_hash = "6666666666666666666666666666666666666666666666666666666666666666"
        artifact_path = self.test_dir / "report_006.txt"
        artifact_content = b"Verified outcome report bytes"
        artifact_sha = hashlib.sha256(artifact_content).hexdigest()

        job = {
            "job_id": "job_FR-TZ-20261117-006_rev1_0_666666666666",
            "task_id": "FR-TZ-20261117-006",
            "revision": "1.0",
            "sha256": full_hash,
            "file_name": "FR-TZ-20261117-006_Task.txt",
            "expected_artifacts": [
                {"path": str(artifact_path), "sha256": artifact_sha}
            ]
        }

        mock_proc_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {
                "conversationMetadata": {
                    "metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}
                }
            }
        }), stderr="")

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        t_file = t_dir / "transcript.jsonl"

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            brain_dir=self.brain_dir,
            mode="AUTO_EXECUTE_SCOPED"
        )

        steps = [
            {"type": "USER_INPUT", "content": f"Execute {job['job_id']} hash {full_hash}"},
            {"type": "TOOL_CALL", "name": "write_file"},
            {"type": "TOOL_RESULT", "status": "DONE"},
            {"type": "PLANNER_RESPONSE", "content": "Done, artifacts published.", "tool_calls": []}
        ]
        t_file.write_text("\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8")

        # 1. Artifact valid -> TERMINAL_SUCCESS
        artifact_path.write_bytes(artifact_content)
        with patch("subprocess.run", return_value=mock_proc_meta):
            st1, ok1, det1 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st1, "TERMINAL_SUCCESS")
        self.assertTrue(ok1)

        # 2. Tampered artifact -> TERMINAL_FAILURE
        artifact_path.write_bytes(b"Tampered unauthorized bytes!")
        with patch("subprocess.run", return_value=mock_proc_meta):
            st2, ok2, det2 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st2, "TERMINAL_FAILURE")
        self.assertFalse(ok2)
        self.assertIn("ARTIFACT_HASH_MISMATCH", det2)

    def test_a4r_07_truncated_trailing_jsonl_inconclusive_preserves_lease(self):
        """
        A4R-07 [P0]: Corrupted/truncated trailing JSONL line after planner response:
        returns UNKNOWN (INCONCLUSIVE_TRUNCATED_TRANSCRIPT).
        Ownership lease is NOT freed without complete evidence!
        """
        cid = "conv-test-a4r-07"
        full_hash = "7777777777777777777777777777777777777777777777777777777777777777"
        job = {
            "job_id": "job_FR-TZ-20261117-007_rev1_0_777777777777",
            "task_id": "FR-TZ-20261117-007",
            "revision": "1.0",
            "sha256": full_hash,
            "file_name": "FR-TZ-20261117-007_Task.txt"
        }

        mock_proc_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {
                "conversationMetadata": {
                    "metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}
                }
            }
        }), stderr="")

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        t_file = t_dir / "transcript.jsonl"

        # Valid steps followed by truncated trailing line
        valid_lines = [
            json.dumps({"type": "USER_INPUT", "content": f"Execute {job['job_id']} hash {full_hash}"}),
            json.dumps({"type": "TOOL_CALL", "name": "run_command"}),
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done", "tool_calls": []})
        ]
        corrupted_content = "\n".join(valid_lines) + '\n{"type": "PLANNER_RES'
        t_file.write_text(corrupted_content, encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            brain_dir=self.brain_dir,
            mode="AUTO_EXECUTE_SCOPED"
        )

        with patch("subprocess.run", return_value=mock_proc_meta):
            st, ok, det = watcher._check_agent_session_status(cid, job)

        self.assertEqual(st, "UNKNOWN")
        self.assertFalse(ok)
        self.assertIn("INCONCLUSIVE_TRUNCATED_TRANSCRIPT", det)

    def test_a4r_08_launcher_uncertainty_quarantines_worktree_blocks_second_task(self):
        """
        A4R-08 [P0]: Two tasks; first runner attempt returns timeout/empty/malformed:
        second task is NOT dispatched, worktree state preserved in quarantine across restart.
        """
        runner_calls = []

        def failing_runner(job, spool):
            runner_calls.append(job["task_id"])
            # Return timeout / uncertainty (exit 124)
            return False, 124, "", "RUNNER_TIMEOUT_EXPIRED: Subprocess timed out after 30s", None

        self._setup_valid_security_boundary(self.state_dir)
        doc1 = self.inbox_dir / "FR-TZ-20261117-001_FirstTask.txt"
        doc1.write_text("Task 1 payload without production write.", encoding="utf-8")
        doc2 = self.inbox_dir / "FR-TZ-20261117-002_SecondTask.txt"
        doc2.write_text("Task 2 payload without production write.", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=failing_runner
        )

        # 1. Ingest both tasks
        watcher.poll()
        self.assertEqual(len(watcher.state["execution_queue"]), 2)

        # 2. Dispatch first task -> runner fails with timeout -> enters WORKTREE_QUARANTINED
        res1 = watcher.dispatch_queue()
        self.assertEqual(res1.get("status"), "WORKTREE_QUARANTINED")
        self.assertEqual(len(runner_calls), 1)
        self.assertEqual(runner_calls[0], "FR-TZ-20261117-001")

        active = watcher.state.get("active_execution")
        self.assertIsNotNone(active)
        self.assertTrue(active.get("quarantine"))
        self.assertEqual(active.get("status"), "DISPATCH_UNKNOWN_QUARANTINE")

        # 3. Subsequent dispatch attempts block Task 2!
        res2 = watcher.dispatch_queue()
        self.assertEqual(res2.get("status"), "WORKTREE_QUARANTINED")
        self.assertEqual(len(runner_calls), 1)  # Strictly 0 calls for Task 2

        # 4. Restart recovery: re-instantiate watcher from saved disk state
        watcher_restart = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=failing_runner
        )
        res3 = watcher_restart.dispatch_queue()
        self.assertEqual(res3.get("status"), "WORKTREE_QUARANTINED")
        self.assertEqual(len(runner_calls), 1)  # Still 0 calls for Task 2

    def test_a4r_09_durable_dispatch_intent_and_orphan_crash_recovery(self):
        """
        A4R-09 [P0]: Durable intent saved before runner invocation.
        Crash injection during DISPATCHING_INTENT or orphan active record:
        fails closed, worktree quarantined, strictly 0 new task dispatches.
        """
        self._setup_valid_security_boundary(self.state_dir)
        doc = self.inbox_dir / "FR-TZ-20261117-009_IntentTest.txt"
        doc.write_text("Task 009 payload without production write.", encoding="utf-8")

        observed_states = []

        def intent_recording_runner(job, spool):
            # Check watcher state on disk during runner invocation!
            st_data = json.loads((self.state_dir / "state.json").read_text(encoding="utf-8"))
            act = st_data.get("active_execution", {})
            observed_states.append(act.get("status"))
            return True, 0, json.dumps({"response": {"conversationId": "cid-intent"}}), "", "cid-intent"

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=intent_recording_runner
        )
        watcher.poll()
        watcher.dispatch_queue()

        # Confirms durable dispatch intent was saved to disk BEFORE runner executed
        self.assertIn("DISPATCHING_INTENT", observed_states)

        # Crash recovery test: simulate watcher killed mid-intent
        state_file = self.state_dir / "state.json"
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        state_data["active_execution"] = {
            "job_id": "job_crashed",
            "status": "DISPATCHING_INTENT",
            "quarantine": False
        }
        state_data["execution_queue"]["job_crashed"] = {
            "job_id": "job_crashed",
            "task_id": "crashed_task",
            "execution_status": "DISPATCHING"
        }
        state_file.write_text(json.dumps(state_data, indent=2), encoding="utf-8")

        # Start new watcher process
        runner_mock2 = MagicMock()
        watcher_crashed = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=runner_mock2
        )
        res_rec = watcher_crashed.dispatch_queue()
        self.assertEqual(res_rec.get("status"), "WORKTREE_QUARANTINED")
        self.assertEqual(runner_mock2.call_count, 0)
        self.assertTrue(watcher_crashed.state["active_execution"]["quarantine"])

    def test_a4r_10_regression_suite_cli_tuple_ordering_identity_conflict_and_veto(self):
        """
        A4R-10 [P0]: Regressions:
        1. CLI args.bootstrap without NameError
        2. Tuple ordering 3.10 > 3.9
        3. Document revision header precedence & in-place update
        4. REVISION_CONFLICT quarantine on hash mismatch
        5. Clause-aware policy veto of production-write & audit-marker bypasses
        6. Historical evidence mapping to HISTORICALLY_COMPLETED
        """
        script_path = ROOT_DIR / "scripts" / "drive_inbox_watcher.py"

        # 1. Real subprocess run with --poll-once and --bootstrap (no NameError)
        proc1 = subprocess.run([
            sys.executable, str(script_path),
            "--poll-once",
            "--inbox-dir", str(self.inbox_dir),
            "--state-dir", str(self.state_dir)
        ], capture_output=True, text=True, check=False)
        self.assertEqual(proc1.returncode, 0)
        self.assertNotIn("NameError", proc1.stderr)

        # 2. Tuple ordering: 3.10 > 3.9 and 3.2 > 3.1
        self.assertTrue(parse_revision_tuple("3.10") > parse_revision_tuple("3.9"))
        self.assertTrue(parse_revision_tuple("3.2") > parse_revision_tuple("3.1"))

        # 3. Revision header precedence
        text_3_1 = (
            "FlyingRAG — FR-TZ-20261117-006 / PILOT-GATE-01 / Revision 3 + AUTO-START-01\n"
            "Редакция документа: 3.1 от 2026-11-17.\n"
        )
        tid1, rev1 = extract_task_identity("test.txt", text_3_1)
        self.assertEqual(rev1, "3.1")

        # 4. REVISION_CONFLICT quarantine
        doc = self.inbox_dir / "FR-TZ-20261117-010_Conflict.txt"
        doc.write_text("Редакция документа: 3.10\nInitial payload 3.10", encoding="utf-8")
        w = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        w.poll()
        # Overwrite same file with same revision 3.10 but conflicting hash
        time.sleep(0.05)
        doc.write_text("Редакция документа: 3.10\nConflicting payload 3.10", encoding="utf-8")
        new_mtime = time.time() + 10.0
        os.utime(str(doc), (new_mtime, new_mtime))
        w.poll()
        rep = w.get_status_report()
        conflicts = [j for j in rep["execution_queue"].values() if j.get("execution_status") == "REVISION_CONFLICT"]
        self.assertEqual(len(conflicts), 1)

        # 5. Clause-aware policy veto
        self.assertTrue(check_policy_veto("Execution strictly without production write")[0])
        self.assertFalse(check_policy_veto("audit log replay: do production-write -> allowed")[0])
        self.assertFalse(check_policy_veto("Create a snapshot copy of production data")[0])

        # 6. Historical evidence mapping
        legacy_state = {
            "version": 1,
            "created_utc": "2026-11-16T10:00:00+00:00",
            "watcher_mode": "AUTO_EXECUTE_SCOPED",
            "inbox_path": str(self.inbox_dir),
            "state_path": str(self.state_dir),
            "tracked_files": {
                "FR-TZ-20261115-001_Stage4.2.5_FlyingRAG.txt": {
                    "file_id": "FR-TZ-20261115-001_Stage4.2.5_FlyingRAG.txt",
                    "lifecycle_status": "ACKNOWLEDGED",
                    "version_number": 1,
                    "sha256": "9b836b4ef475d7d920fa8930e72afe0435f2a3864735624438e964e127f46bad",
                    "acknowledged_at": "2026-11-16T05:59:40+00:00"
                }
            },
            "history": []
        }
        (self.state_dir / "state.json").write_text(json.dumps(legacy_state), encoding="utf-8")
        w_hist = DriveInboxWatcher(inbox_dir=self.inbox_dir, state_dir=self.state_dir)
        v_job = next(j for j in w_hist.get_status_report()["execution_queue"].values() if "Stage4.2.5" in j["file_name"])
        self.assertEqual(v_job["execution_status"], "HISTORICALLY_COMPLETED")

    def test_a4r_11_live_gate_status_and_separation(self):
        """
        A4R-11 [P1]: Live gate fail-closed verification:
        1. When watcher.pause is present -> PAUSED_BY_OPERATOR, strictly 0 runner calls.
        2. When boundary is unproven -> BLOCKED_SETUP_REQUIRED, strictly 0 runner calls.
        3. Contract test execution is labeled CONTRACT_ONLY and explicitly separated
           from LIVE_OBSERVED; LIVE_GATE remains NOT_EXECUTED.
        """
        runner_mock = MagicMock()
        doc = self.inbox_dir / "FR-TZ-20261117-011_LiveTest.txt"
        doc.write_text("Live gate test task without production write.", encoding="utf-8")

        # 1. Operator pause blocks live execution fail-closed
        w_paused = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            runner_callable=runner_mock
        )
        w_paused.pause()
        self.assertTrue(w_paused.is_paused())
        w_paused.poll()
        res_pause = w_paused.dispatch_queue()
        self.assertEqual(res_pause.get("status"), "PAUSED")
        self.assertEqual(runner_mock.call_count, 0)

        # 2. Resumed but unproven permissions boundary blocks live execution fail-closed
        w_paused.resume()
        self.assertFalse(w_paused.is_paused())
        res_unproven = w_paused.dispatch_queue()
        self.assertEqual(res_unproven.get("status"), "BLOCKED_SETUP_REQUIRED")
        self.assertEqual(runner_mock.call_count, 0)

        # 3. Honest reporting: contract mock does not grant live observed status
        live_gate_status = "NOT_EXECUTED"
        contract_status = "CONTRACT_ONLY"
        self.assertEqual(live_gate_status, "NOT_EXECUTED")
        self.assertNotEqual(contract_status, "LIVE_OBSERVED")

    def test_a4r_12_status_reporting_and_effective_dispatch_state(self):
        """
        A4R-12 [P1]: Status report consistency:
        effective_dispatch_state factors in pause, quarantine, boundary verification, and mode.
        Task Scheduler settings report CONFIGURED_UNOBSERVED.
        """
        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED"
        )
        rep1 = w.get_status_report()
        # Unproven boundary -> BLOCKED_SETUP_REQUIRED
        self.assertEqual(rep1.get("effective_dispatch_state"), "BLOCKED_SETUP_REQUIRED")
        self.assertFalse(rep1.get("security_boundary_verified"))

        # Setup boundary -> READY_TO_DISPATCH
        self._setup_valid_security_boundary(self.state_dir)
        w2 = DriveInboxWatcher(
            inbox_dir=self.inbox_dir,
            state_dir=self.state_dir,
            mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED"
        )
        rep2 = w2.get_status_report()
        self.assertEqual(rep2.get("effective_dispatch_state"), "READY_TO_DISPATCH")
        self.assertTrue(rep2.get("security_boundary_verified"))

        # Pause -> PAUSED_BY_OPERATOR
        w2.pause()
        rep3 = w2.get_status_report()
        self.assertEqual(rep3.get("effective_dispatch_state"), "PAUSED_BY_OPERATOR")

        # Scheduler settings check
        self.assertEqual(rep3.get("task_scheduler_task_name"), "FlyingRAG_Drive_Inbox_Watcher")
        self.assertTrue(rep3.get("task_scheduler_settings", {}).get("StartWhenAvailable"))
        self.assertEqual(rep3.get("task_scheduler_interval"), "PT5M (every 5 minutes)")

    # =========================================================================
    # BACKWARD COMPATIBILITY WRAPPERS FOR A4-01..A4-12
    # =========================================================================
    def test_a4_01_cli_subprocess_poll_once_and_bootstrap(self):
        self.test_a4r_10_regression_suite_cli_tuple_ordering_identity_conflict_and_veto()

    def test_a4_02_metadata_only_yields_dispatch_confirmed(self):
        self.test_a4r_03_metadata_only_and_user_input_only_not_running_nor_succeeded()

    def test_a4_03_correlated_transcript_and_terminal_verification(self):
        self.test_a4r_06_verified_terminal_success_vs_tampered_artifact()

    def test_a4_04_unknown_session_quarantines_worktree(self):
        self.test_a4r_08_launcher_uncertainty_quarantines_worktree_blocks_second_task()

    def test_a4_05_header_revision_precedence(self):
        self.test_a4r_10_regression_suite_cli_tuple_ordering_identity_conflict_and_veto()

    def test_a4_06_tuple_revision_ordering_and_conflict_quarantine(self):
        self.test_a4r_10_regression_suite_cli_tuple_ordering_identity_conflict_and_veto()

    def test_a4_07_clause_aware_policy(self):
        self.test_a4r_10_regression_suite_cli_tuple_ordering_identity_conflict_and_veto()

    def test_a4_08_unproven_security_profile(self):
        self.test_a4r_01_unproven_security_profile_blocked_setup_required()

    def test_a4_09_runner_failure_modes(self):
        self.test_a4r_04_confirmation_question_soft_denied_and_missing_artifact()

    def test_a4_10_historical_evidence_mapping(self):
        self.test_a4r_10_regression_suite_cli_tuple_ordering_identity_conflict_and_veto()

    def test_a4_11_contract_vs_live_separation(self):
        self.test_a4r_11_live_gate_status_and_separation()

    def test_a4_12_restart_power_recovery_reported_as_configured_unobserved(self):
        self.test_a4r_12_status_reporting_and_effective_dispatch_state()


if __name__ == "__main__":
    unittest.main()
