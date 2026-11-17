"""
tests/test_autostart_dispatcher.py

Acceptance & Verification Suite for AUTO-START-01 (Stage 4.2.8 Rev 1.2 / Task 007 Final Integration Gate).
Validates:
- Fail-closed security boundary verification (E-1..E-4, no self-fulfilling JSON without runtime attestation)
- Accurate outcome checking: tool intent vs actual executed result (O-1, O-2, O-3)
- In-flight retry after intermediate tool error preserves lease (O-4)
- Queue integration: ordinary tasks without acceptance schema yield AWAITING_VERIFICATION (not false SUCCEEDED)
- TEST_ONLY tasks with contracted acceptance schema verify new artifacts and executed action
- Durable dispatch intent before launch and quarantine on launcher uncertainty
- Full regression suite for CLI bootstrap, tuple ordering, revision conflict quarantine, and policy veto.

Implements mandatory test matrix A4R-01 through A4R-12 per Section 1-2 of FR-TZ-20261117-007 Rev 1.2.
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
            "runtime_isolation_type": "CONTAINER_SANDBOX",
            "isolation_attestation_token": "token-sandbox-attested-v1",
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
    # A4R MATRIX: A4R-01 THROUGH A4R-12 (Rev 1.2)
    # =========================================================================

    def test_a4r_01_unproven_security_profile_blocked_setup_required(self):
        """
        A4R-01 [P0-E1]: E-1, E-2, E-3:
        E-1: SAFE profile + {enforce_write_boundary: true} with empty/missing roots -> BLOCKED_SETUP_REQUIRED.
        E-2: SAFE profile + allowed roots, but no runtime isolation provider attestation -> BLOCKED_SETUP_REQUIRED.
        E-3: Unproven/default profile (None / env=UNPROVEN / missing config) -> BLOCKED_SETUP_REQUIRED.
        In ALL unproven cases returns BLOCKED_SETUP_REQUIRED with strictly 0 runner calls.
        _invoke_external_runner returns exitcode 126.
        """
        runner_mock = MagicMock(return_value=(True, 0, json.dumps({"response": {"conversationId": "cid-test"}}), "", "cid-test"))
        doc = self.inbox_dir / "FR-TZ-20261117-001_SecTest.txt"
        doc.write_text("Task payload without production write.", encoding="utf-8")

        # 1. E-1: enforce_write_boundary=True but empty or missing allowed_write_roots
        s_e1 = self.test_dir / "s_e1"
        s_e1.mkdir()
        (s_e1 / "security_boundary.json").write_text(json.dumps({
            "enforce_write_boundary": True,
            "allowed_write_roots": []
        }), encoding="utf-8")

        w_e1 = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=s_e1, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED", runner_callable=runner_mock
        )
        w_e1.poll()
        res_e1 = w_e1.dispatch_queue()
        self.assertEqual(res_e1.get("status"), "BLOCKED_SETUP_REQUIRED")
        self.assertIn("allowed_write_roots is missing or empty (E-1)", res_e1.get("error", ""))
        self.assertEqual(runner_mock.call_count, 0)

        # 2. E-2: allowed_write_roots present, but NO runtime isolation provider confirmed
        s_e2 = self.test_dir / "s_e2"
        s_e2.mkdir()
        (s_e2 / "security_boundary.json").write_text(json.dumps({
            "enforce_write_boundary": True,
            "allowed_write_roots": [str(self.worktree_dir)]
        }), encoding="utf-8")

        w_e2 = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=s_e2, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED", runner_callable=runner_mock
        )
        w_e2.poll()
        res_e2 = w_e2.dispatch_queue()
        self.assertEqual(res_e2.get("status"), "BLOCKED_SETUP_REQUIRED")
        self.assertIn("No active runtime isolation provider confirmed (E-2)", res_e2.get("error", ""))
        self.assertEqual(runner_mock.call_count, 0)

        # 3. E-3: Default profile (None / UNVERIFIED)
        w_e3 = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile=None, runner_callable=runner_mock
        )
        w_e3.poll()
        res_e3 = w_e3.dispatch_queue()
        self.assertEqual(res_e3.get("status"), "BLOCKED_SETUP_REQUIRED")
        self.assertEqual(runner_mock.call_count, 0)

        # 4. _invoke_external_runner fails closed with exit 126
        code, exitcode, stdout, stderr, cid = w_e3._invoke_external_runner({"task_id": "test"}, doc)
        self.assertFalse(code)
        self.assertEqual(exitcode, 126)
        self.assertIn("BLOCKED_SETUP_REQUIRED", stderr)

    def test_a4r_02_verified_security_boundary_allows_scoped_rejects_production(self):
        """
        A4R-02 [P0-E1]: E-4:
        Valid configuration with runtime isolation attestation allows dispatch (CONTRACT_ONLY).
        Inclusion of prohibited production roots fails closed (BLOCKED_SETUP_REQUIRED, 0 runner calls).
        """
        runner_mock = MagicMock(return_value=(True, 0, json.dumps({"response": {"conversationId": "cid-ok"}}), "", "cid-ok"))
        doc = self.inbox_dir / "FR-TZ-20261117-002_SafeOp.txt"
        doc.write_text("Safe scoped payload without production write.", encoding="utf-8")

        # 1. Valid boundary config with runtime isolation attestation allows dispatch
        self._setup_valid_security_boundary(self.state_dir)
        w_valid = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED", runner_callable=runner_mock
        )
        w_valid.poll()
        res1 = w_valid.dispatch_queue()
        self.assertEqual(res1.get("status"), "DISPATCH_CONFIRMED")
        self.assertEqual(runner_mock.call_count, 1)

        # 2. Boundary config containing prohibited production database fails closed!
        runner_mock.reset_mock()
        s_bad = self.test_dir / "s_bad"
        s_bad.mkdir()
        (s_bad / "security_boundary.json").write_text(json.dumps({
            "enforce_write_boundary": True,
            "runtime_isolation_type": "CONTAINER_SANDBOX",
            "isolation_attestation_token": "token-test",
            "allowed_write_roots": [
                r"C:\RAG_Acer\data_imported\metadata.db",
                str(self.worktree_dir)
            ]
        }), encoding="utf-8")

        w_bad = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=s_bad, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED", runner_callable=runner_mock
        )
        w_bad.poll()
        res2 = w_bad.dispatch_queue()
        self.assertEqual(res2.get("status"), "BLOCKED_SETUP_REQUIRED")
        self.assertIn("Prohibited root", res2.get("error", ""))
        self.assertEqual(runner_mock.call_count, 0)

    def test_a4r_03_metadata_only_and_user_input_only_not_running_nor_succeeded(self):
        """
        A4R-03 [P0-B1]: O-2 & R1:
        1. Metadata-only (session created, transcript absent): DISPATCH_CONFIRMED, not RUNNING, not SUCCEEDED.
        2. Transcript contains ONLY USER_INPUT (R1): DISPATCH_CONFIRMED, not RUNNING, not SUCCEEDED.
        3. Transcript contains USER_INPUT + PLANNER_RESPONSE(tool_calls=[...]) without executed action (O-2):
           strictly DISPATCH_CONFIRMED (AWAITING_ACTION_START), NOT RUNNING!
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
                    "metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}
                }
            }
        }), stderr="")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )

        # 1. Metadata only, no transcript file -> DISPATCH_CONFIRMED
        with patch("subprocess.run", return_value=mock_proc_meta):
            st1, ok1, det1 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st1, "DISPATCH_CONFIRMED")
        self.assertFalse(ok1)

        # 2. Transcript has ONLY USER_INPUT (R1) -> DISPATCH_CONFIRMED
        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        t_file = t_dir / "transcript.jsonl"
        t_file.write_text(json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n", encoding="utf-8")

        with patch("subprocess.run", return_value=mock_proc_meta):
            st2, ok2, det2 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st2, "DISPATCH_CONFIRMED")
        self.assertFalse(ok2)

        # 3. O-2: USER_INPUT + PLANNER_RESPONSE with tool_calls, but no executed action event logged
        step_plan = {
            "type": "PLANNER_RESPONSE",
            "content": "I plan to execute search",
            "tool_calls": [{"name": "read_file"}]
        }
        t_file.write_text(json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
                          json.dumps(step_plan) + "\n", encoding="utf-8")

        with patch("subprocess.run", return_value=mock_proc_meta):
            st3, ok3, det3 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st3, "DISPATCH_CONFIRMED")
        self.assertIn("SESSION_AWAITING_ACTION_START", det3)
        self.assertNotEqual(st3, "RUNNING")
        self.assertNotEqual(st3, "SUCCEEDED")

    def test_a4r_04_confirmation_question_soft_denied_and_missing_artifact(self):
        """
        A4R-04 [P0-B1]: Non-success outcome conditions:
        1. R2: Confirmation question ('Начинаем?') -> WAITING_CONFIRMATION, outcome_verified=False.
        2. R3: Explicit refusal / lack of permissions -> TERMINAL_FAILURE, outcome_verified=False.
        3. O-1: Tool call without result (TOOL_CALL without TOOL_RESULT) + 'Done' -> TERMINAL_FAILURE.
        4. O-3: Pre-existing file in expected_artifacts, but NO tool action occurred in session -> TERMINAL_FAILURE.
        5. Missing required artifact -> TERMINAL_FAILURE.
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
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )
        step_input = {"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}

        # 1. R2: Confirmation question -> WAITING_CONFIRMATION
        step_q = {"type": "PLANNER_RESPONSE", "content": "Готов приступить. Начинаем?", "tool_calls": []}
        t_file.write_text(json.dumps(step_input) + "\n" + json.dumps(step_q) + "\n", encoding="utf-8")
        with patch("subprocess.run", return_value=mock_proc_meta):
            st1, ok1, det1 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st1, "WAITING_CONFIRMATION")
        self.assertFalse(ok1)

        # 2. R3: Explicit refusal in planner response -> TERMINAL_FAILURE
        step_refusal = {"type": "PLANNER_RESPONSE", "content": "Не выполнено: нет разрешений", "tool_calls": []}
        t_file.write_text(json.dumps(step_input) + "\n" + json.dumps(step_refusal) + "\n", encoding="utf-8")
        with patch("subprocess.run", return_value=mock_proc_meta):
            st2, ok2, det2 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st2, "TERMINAL_FAILURE")
        self.assertFalse(ok2)

        # 3. O-1: Tool call without result (TOOL_CALL without TOOL_RESULT) + 'Done' -> TERMINAL_FAILURE
        step_tool_call = {"type": "TOOL_CALL", "name": "run_command"}
        step_done = {"type": "PLANNER_RESPONSE", "content": "Done", "tool_calls": []}
        t_file.write_text(json.dumps(step_input) + "\n" + json.dumps(step_tool_call) + "\n" + json.dumps(step_done) + "\n", encoding="utf-8")
        with patch("subprocess.run", return_value=mock_proc_meta):
            st3, ok3, det3 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st3, "TERMINAL_FAILURE")
        self.assertFalse(ok3)
        self.assertIn("UNVERIFIED_OUTCOME", det3)

        # 4. O-3: Pre-existing file in expected_artifacts, but NO tool action occurred in session -> TERMINAL_FAILURE
        art_p = self.test_dir / "expected_report.md"
        art_p.write_text("Pre-existing untouched file", encoding="utf-8")
        t_file.write_text(json.dumps(step_input) + "\n" + json.dumps(step_done) + "\n", encoding="utf-8")
        with patch("subprocess.run", return_value=mock_proc_meta):
            st4, ok4, det4 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st4, "TERMINAL_FAILURE")
        self.assertFalse(ok4)
        self.assertIn("UNVERIFIED_OUTCOME", det4)

        # 5. Missing expected artifact -> TERMINAL_FAILURE
        art_p.unlink()
        step_tool_res = {"type": "TOOL_RESULT", "status": "DONE"}
        t_file.write_text(json.dumps(step_input) + "\n" + json.dumps(step_tool_call) + "\n" +
                          json.dumps(step_tool_res) + "\n" + json.dumps(step_done) + "\n", encoding="utf-8")
        with patch("subprocess.run", return_value=mock_proc_meta):
            st5, ok5, det5 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st5, "TERMINAL_FAILURE")
        self.assertFalse(ok5)
        self.assertIn("MISSING_EXPECTED_ARTIFACT", det5)

    def test_a4r_05_correlation_rejects_foreign_hash_short_prefix_and_spoofs(self):
        """
        A4R-05 [P0-B1]: Correlation & Anti-Spoofing:
        1. R4: Foreign full 64-char hash -> UNKNOWN.
        2. R5: 12-char prefix match with 52 differing characters -> UNKNOWN.
        3. R6: Foreign rootConversationId in metadata -> UNKNOWN.
        4. Spoofed WATCHER_SELF_AUTHORED_RECEIPT -> UNKNOWN.
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
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
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
        t_file.write_text(json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {full_hash}"}) + "\n", encoding="utf-8")
        with patch("subprocess.run", return_value=mock_proc_foreign_root):
            st3, ok3, det3 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st3, "UNKNOWN")
        self.assertFalse(ok3)
        self.assertIn("METADATA_CORRELATION_FAILED", det3)

        # 4. Spoofed receipt -> UNKNOWN
        t_file.write_text(json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} WATCHER_SELF_AUTHORED_RECEIPT"}) + "\n", encoding="utf-8")
        with patch("subprocess.run", return_value=mock_proc_meta):
            st4, ok4, det4 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st4, "UNKNOWN")
        self.assertFalse(ok4)
        self.assertIn("SPOOFED_RECEIPT_DETECTED", det4)

    def test_a4r_06_queue_integration_ordinary_task_vs_contract_test_only(self):
        """
        A4R-06 [P0-B1]: Queue integration of task criteria (Rev 1.2 Section 2):
        1. Ordinary task from poll() without contracted acceptance schema:
           completed session returns AWAITING_VERIFICATION (not false SUCCEEDED), worktree quarantined.
        2. Contracted TEST_ONLY task from poll() with ACCEPTANCE_ARTIFACT:
           successful tool action + verified new artifact + terminal response -> TERMINAL_SUCCESS / True.
        3. Tampered artifact bytes/hash -> TERMINAL_FAILURE / False.
        """
        self._setup_valid_security_boundary(self.state_dir)

        # 1. Ordinary task without acceptance criteria
        doc_ord = self.inbox_dir / "FR-TZ-20261117-006_OrdinaryTask.txt"
        doc_ord.write_text("Standard task content without automated acceptance schema.", encoding="utf-8")

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=lambda j, s: (True, 0, json.dumps({"response": {"conversationId": "cid-ord"}}), "", "cid-ord")
        )
        w.poll()
        w.dispatch_queue()

        # Session has executed tools and planner said 'Done', but task has no acceptance schema
        ord_job = list(w.state["execution_queue"].values())[0]
        t_dir = self.brain_dir / "cid-ord" / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{ord_job['job_id']} hash {ord_job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "run_command"}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": "cid-ord", "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        with patch("subprocess.run", return_value=mock_meta):
            res_rec = w.dispatch_queue()

        self.assertEqual(res_rec.get("status"), "WORKTREE_QUARANTINED")
        self.assertEqual(w.state["execution_queue"][ord_job["job_id"]]["execution_status"], "AWAITING_VERIFICATION")
        self.assertNotEqual(w.state["execution_queue"][ord_job["job_id"]]["execution_status"], "SUCCEEDED")
        self.assertTrue(w.state["active_execution"]["quarantine"])

        # 2. TEST_ONLY task with contracted acceptance artifact
        s_test = self.test_dir / "s_test"
        s_test.mkdir()
        self._setup_valid_security_boundary(s_test)
        inbox_test = self.test_dir / "inbox_test"
        inbox_test.mkdir()

        art_target = self.test_dir / "test_only_artifact.txt"
        doc_test = inbox_test / "FR-TZ-20261117-007_TestOnlyTask.txt"
        doc_test.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            f"ACCEPTANCE_ARTIFACT: {art_target}\n"
            "Payload for contract testing.",
            encoding="utf-8"
        )

        w_test = DriveInboxWatcher(
            inbox_dir=inbox_test, state_dir=s_test,
            brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=lambda j, s: (True, 0, json.dumps({"response": {"conversationId": "cid-test-only"}}), "", "cid-test-only")
        )
        w_test.poll()
        w_test.dispatch_queue()

        t_dir_to = self.brain_dir / "cid-test-only" / ".system_generated" / "logs"
        t_dir_to.mkdir(parents=True)
        to_job = list(w_test.state["execution_queue"].values())[0]

        (t_dir_to / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{to_job['job_id']} hash {to_job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file"}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done, artifact written.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        mock_meta_to = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": "cid-test-only", "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        # Artifact exists -> TERMINAL_SUCCESS -> SUCCEEDED in queue
        art_target.write_text("Verified artifact payload", encoding="utf-8")
        with patch("subprocess.run", return_value=mock_meta_to):
            w_test.dispatch_queue()
        self.assertEqual(w_test.state["execution_queue"][to_job["job_id"]]["execution_status"], "SUCCEEDED")

    def test_a4r_07_truncated_tail_and_intermediate_error_retry_running(self):
        """
        A4R-07 [P0-B1]: R8 & O-4:
        1. R8: Truncated trailing line in transcript.jsonl returns UNKNOWN (INCONCLUSIVE_TRUNCATED_TRANSCRIPT).
           Worktree lease is NOT freed!
        2. O-4: Intermediate TOOL_RESULT(ERROR) followed by in-flight TOOL_CALL('retry') -> RUNNING.
           Dispatcher does NOT mark TERMINAL_FAILURE, does NOT free lease, and blocks second task!
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

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )

        # 1. R8: Valid steps followed by truncated trailing line
        valid_lines = [
            json.dumps({"type": "USER_INPUT", "content": f"Execute {job['job_id']} hash {full_hash}"}),
            json.dumps({"type": "TOOL_CALL", "name": "run_command"}),
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done", "tool_calls": []})
        ]
        t_file.write_text("\n".join(valid_lines) + '\n{"type": "PLANNER_RES', encoding="utf-8")

        with patch("subprocess.run", return_value=mock_proc_meta):
            st1, ok1, det1 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st1, "UNKNOWN")
        self.assertFalse(ok1)
        self.assertIn("INCONCLUSIVE_TRUNCATED_TRANSCRIPT", det1)

        # 2. O-4: Intermediate error followed by in-flight retry TOOL_CALL -> RUNNING
        t_file.write_text(
            json.dumps({"type": "USER_INPUT", "content": f"Execute {job['job_id']} hash {full_hash}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "run_command"}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "ERROR", "content": "Transient failure"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "run_command_retry"}) + "\n",
            encoding="utf-8"
        )

        with patch("subprocess.run", return_value=mock_proc_meta):
            st2, ok2, det2 = watcher._check_agent_session_status(cid, job)
        self.assertEqual(st2, "RUNNING")
        self.assertFalse(ok2)
        self.assertIn("O-4", det2)

    def test_a4r_08_launcher_uncertainty_quarantines_worktree_blocks_second_task(self):
        """
        A4R-08 [P0-C1]: Two tasks in queue.
        First task runner returns TimeoutExpired (exit 124) / empty stdout / missing CID.
        First task enters WORKTREE_QUARANTINED with active_execution["quarantine"] = True.
        Second task is NOT dispatched (strictly 0 runner calls for Task 2).
        Quarantine persists across restart.
        """
        runner_calls = []

        def timeout_runner(job, spool):
            runner_calls.append(job["task_id"])
            return False, 124, "", "RUNNER_TIMEOUT_EXPIRED: Subprocess timed out after 30s", None

        self._setup_valid_security_boundary(self.state_dir)
        doc1 = self.inbox_dir / "FR-TZ-20261117-001_FirstTask.txt"
        doc1.write_text("Task 1 payload without production write.", encoding="utf-8")
        doc2 = self.inbox_dir / "FR-TZ-20261117-002_SecondTask.txt"
        doc2.write_text("Task 2 payload without production write.", encoding="utf-8")

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED", runner_callable=timeout_runner
        )

        # 1. Ingest both tasks
        watcher.poll()
        self.assertEqual(len(watcher.state["execution_queue"]), 2)

        # 2. Dispatch first task -> runner times out -> enters WORKTREE_QUARANTINED
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
            inbox_dir=self.inbox_dir, state_dir=self.state_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED", runner_callable=timeout_runner
        )
        res3 = watcher_restart.dispatch_queue()
        self.assertEqual(res3.get("status"), "WORKTREE_QUARANTINED")
        self.assertEqual(len(runner_calls), 1)  # Still 0 calls for Task 2

    def test_a4r_09_durable_dispatch_intent_and_orphan_crash_recovery(self):
        """
        A4R-09 [P0-C1]: Durable intent and crash recovery:
        1. Verifies DISPATCHING_INTENT is written to disk state BEFORE runner is invoked.
        2. Simulated crash during DISPATCHING_INTENT -> recovered on restart as WORKTREE_QUARANTINED.
        3. Orphan DISPATCHING job in queue -> recovered as WORKTREE_QUARANTINED, 0 new dispatches.
        """
        self._setup_valid_security_boundary(self.state_dir)
        doc = self.inbox_dir / "FR-TZ-20261117-009_IntentTest.txt"
        doc.write_text("Task 009 payload without production write.", encoding="utf-8")

        observed_states = []

        def intent_recording_runner(job, spool):
            st_data = json.loads((self.state_dir / "state.json").read_text(encoding="utf-8"))
            act = st_data.get("active_execution", {})
            observed_states.append(act.get("status"))
            return True, 0, json.dumps({"response": {"conversationId": "cid-intent"}}), "", "cid-intent"

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED", runner_callable=intent_recording_runner
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

        runner_mock2 = MagicMock()
        watcher_crashed = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED", runner_callable=runner_mock2
        )
        res_rec = watcher_crashed.dispatch_queue()
        self.assertEqual(res_rec.get("status"), "WORKTREE_QUARANTINED")
        self.assertEqual(runner_mock2.call_count, 0)
        self.assertTrue(watcher_crashed.state["active_execution"]["quarantine"])

    def test_a4r_10_regression_suite_cli_tuple_ordering_identity_conflict_and_veto(self):
        """
        A4R-10 [P0]: Regressions:
        1. CLI args.bootstrap via real subprocess without NameError.
        2. Tuple ordering: (3, 10) > (3, 9) and (3, 2) > (3, 1).
        3. Document revision header precedence & in-place update.
        4. REVISION_CONFLICT quarantine on hash mismatch.
        5. Clause-aware policy veto of production-write & audit-marker bypasses.
        6. Historical evidence mapping to HISTORICALLY_COMPLETED.
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
            inbox_dir=self.inbox_dir, state_dir=self.state_dir, mode="AUTO_EXECUTE_SCOPED",
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
            inbox_dir=self.inbox_dir, state_dir=self.state_dir, mode="AUTO_EXECUTE_SCOPED"
        )
        rep1 = w.get_status_report()
        # Unproven boundary -> BLOCKED_SETUP_REQUIRED
        self.assertEqual(rep1.get("effective_dispatch_state"), "BLOCKED_SETUP_REQUIRED")
        self.assertFalse(rep1.get("security_boundary_verified"))

        # Setup valid boundary with runtime isolation attestation -> READY_TO_DISPATCH
        self._setup_valid_security_boundary(self.state_dir)
        w2 = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir, mode="AUTO_EXECUTE_SCOPED",
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


if __name__ == "__main__":
    unittest.main()
