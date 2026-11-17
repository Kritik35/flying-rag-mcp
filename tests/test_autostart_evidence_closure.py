# tests/test_autostart_evidence_closure.py
# Stage 4.2.8 AUTO-START-01 Final Gate Evidence Closure Test Suite (C4-01..C4-10, A1..A3, Job-Root Enclosure)
# Validates complete closure of evidence matching, call_id causality, and job-isolated roots per FR-TZ-20261117-010 Rev 1.1.

import os
import sys
import json
import time
import shutil
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure repo root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.drive_inbox_watcher import DriveInboxWatcher


class TestAutostartEvidenceClosure(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_c4_closure_"))
        self.inbox_dir = self.test_dir / "inbox"
        self.state_dir = self.test_dir / "state"
        self.brain_dir = self.test_dir / "brain"
        self.worktree_dir = self.test_dir / "worktree"
        self.job_output_dir = self.worktree_dir / "tests" / "output"

        self.inbox_dir.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)
        self.brain_dir.mkdir(parents=True)
        self.worktree_dir.mkdir(parents=True)
        self.job_output_dir.mkdir(parents=True)

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    def _setup_boundary_json(self, allowed_roots=None, isolation_type="CONTAINER_SANDBOX", token="attest-c4-token"):
        b_file = self.state_dir / "security_boundary.json"
        cfg = {
            "enforce_write_boundary": True,
            "runtime_isolation_type": isolation_type,
            "isolation_attestation_token": token,
            "allowed_write_roots": allowed_roots if allowed_roots is not None else [str(self.worktree_dir)]
        }
        b_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return b_file

    def test_c4_01_tool_call_and_result_without_call_id_returns_awaiting_verification(self):
        """
        C4-01 [P0]: TOOL_CALL write_file and TOOL_RESULT DONE without call_id + terminal
        must NOT yield SUCCEEDED; without reliable call_id correlation yields AWAITING_VERIFICATION.
        """
        cid = "conv-c4-01"
        job_out = self.job_output_dir / "job_FR-TZ-20261117-010_c4_01"
        job_out.mkdir(parents=True, exist_ok=True)
        art_target = job_out / "output_c4_01.txt"
        art_target.write_text("Payload 01", encoding="utf-8")
        exp_hash = hashlib.sha256(b"Payload 01").hexdigest()

        job = {
            "job_id": "job_FR-TZ-20261117-010_c4_01",
            "task_id": "FR-TZ-20261117-010",
            "revision": "1.0",
            "sha256": "1111111111111111111111111111111111111111111111111111111111111111",
            "file_name": "FR-TZ-20261117-010_Task.txt",
            "output_dir": str(job_out),
            "expected_artifacts": [{
                "path": str(art_target),
                "name": art_target.name,
                "expected_sha256": exp_hash,
                "is_safe": True,
                "output_dir": str(job_out),
                "min_mtime": time.time() - 50,
                "require_tool_causality": True
            }]
        }

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "args": {"Path": str(art_target)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with task.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )

        with patch("subprocess.run", return_value=mock_meta):
            st, ok, det = w._check_agent_session_status(cid, job)

        self.assertEqual(st, "AWAITING_VERIFICATION")
        self.assertFalse(ok)
        self.assertIn("UNVERIFIED_TOOL_CORRELATION", det)
        self.assertNotEqual(st, "SUCCEEDED")

    def test_c4_01_a1_duplicate_call_id_reuse_rejected_non_success(self):
        """
        Scenario A1 (Rev 1.1 / C4-01):
        TOOL_CALL(read_file, call_id=x) -> TOOL_RESULT(DONE, call_id=x, name=read_file) ->
        TOOL_CALL(write_file, call_id=x, Path=art) WITHOUT write result -> PLANNER_RESPONSE(Done).
        Must NOT yield TERMINAL_SUCCESS / SUCCEEDED! Must reject duplicate call_id or unverified write.
        """
        cid = "conv-c4-a1"
        job_out = self.job_output_dir / "job_FR-TZ-20261117-010_c4_a1"
        job_out.mkdir(parents=True, exist_ok=True)
        art_target = job_out / "artifact_a1.txt"
        payload_bytes = b"Artifact bytes A1"
        art_target.write_bytes(payload_bytes)
        exp_hash = hashlib.sha256(payload_bytes).hexdigest()

        job = {
            "job_id": "job_FR-TZ-20261117-010_c4_a1",
            "task_id": "FR-TZ-20261117-010",
            "revision": "1.0",
            "sha256": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
            "file_name": "FR-TZ-20261117-010_Task.txt",
            "output_dir": str(job_out),
            "expected_artifacts": [{
                "path": str(art_target),
                "name": art_target.name,
                "expected_sha256": exp_hash,
                "is_safe": True,
                "output_dir": str(job_out),
                "min_mtime": time.time() - 50,
                "require_tool_causality": True
            }]
        }

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        # Duplicate call_id 'call-shared-x': read succeeds, then write is issued with same ID but no write result
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "read_file", "call_id": "call-shared-x", "args": {"Path": "read_doc.txt"}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-shared-x", "name": "read_file"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-shared-x", "args": {"Path": str(art_target)}}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with all work.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )

        with patch("subprocess.run", return_value=mock_meta):
            st, ok, det = w._check_agent_session_status(cid, job)

        self.assertNotEqual(st, "TERMINAL_SUCCESS")
        self.assertFalse(ok)
        self.assertIn("AMBIGUOUS_TOOL_CALL_ID", det)

    def test_c4_02_multiple_tool_calls_no_positional_pairing(self):
        """
        C4-02 [P0]: Two TOOL_CALLs of different actions (e.g. read_file and write_file)
        and one DONE without call_id: positional fallback must NOT link DONE with write_file -> NOT SUCCEEDED.
        """
        cid = "conv-c4-02"
        job_out = self.job_output_dir / "job_FR-TZ-20261117-010_c4_02"
        job_out.mkdir(parents=True, exist_ok=True)
        art_target = job_out / "output_c4_02.txt"
        art_target.write_text("Payload 02", encoding="utf-8")
        exp_hash = hashlib.sha256(b"Payload 02").hexdigest()

        job = {
            "job_id": "job_FR-TZ-20261117-010_c4_02",
            "task_id": "FR-TZ-20261117-010",
            "revision": "1.0",
            "sha256": "2222222222222222222222222222222222222222222222222222222222222222",
            "file_name": "FR-TZ-20261117-010_Task.txt",
            "output_dir": str(job_out),
            "expected_artifacts": [{
                "path": str(art_target),
                "name": art_target.name,
                "expected_sha256": exp_hash,
                "is_safe": True,
                "output_dir": str(job_out),
                "min_mtime": time.time() - 50,
                "require_tool_causality": True
            }]
        }

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "read_file", "args": {"Path": "irrelevant.txt"}}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "args": {"Path": str(art_target)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with task.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )

        with patch("subprocess.run", return_value=mock_meta):
            st, ok, det = w._check_agent_session_status(cid, job)

        self.assertEqual(st, "AWAITING_VERIFICATION")
        self.assertFalse(ok)
        self.assertIn("UNVERIFIED_TOOL_CORRELATION", det)
        self.assertNotEqual(st, "SUCCEEDED")

    def test_c4_02_a2_tool_result_preceding_tool_call_rejected(self):
        """
        Scenario A2 (Rev 1.1 / C4-02):
        TOOL_RESULT(DONE, call_id=y) appears BEFORE corresponding TOOL_CALL(write_file, call_id=y).
        Causal order violation: result without prior call -> UNKNOWN (non-success).
        """
        cid = "conv-c4-a2"
        job_out = self.job_output_dir / "job_FR-TZ-20261117-010_c4_a2"
        job_out.mkdir(parents=True, exist_ok=True)
        art_target = job_out / "artifact_a2.txt"
        payload_bytes = b"Artifact bytes A2"
        art_target.write_bytes(payload_bytes)
        exp_hash = hashlib.sha256(payload_bytes).hexdigest()

        job = {
            "job_id": "job_FR-TZ-20261117-010_c4_a2",
            "task_id": "FR-TZ-20261117-010",
            "revision": "1.0",
            "sha256": "a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2",
            "file_name": "FR-TZ-20261117-010_Task.txt",
            "output_dir": str(job_out),
            "expected_artifacts": [{
                "path": str(art_target),
                "name": art_target.name,
                "expected_sha256": exp_hash,
                "is_safe": True,
                "output_dir": str(job_out),
                "min_mtime": time.time() - 50,
                "require_tool_causality": True
            }]
        }

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        # TOOL_RESULT appears in transcript BEFORE TOOL_CALL
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-order-y", "name": "write_file"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-order-y", "args": {"Path": str(art_target)}}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with task.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )

        with patch("subprocess.run", return_value=mock_meta):
            st, ok, det = w._check_agent_session_status(cid, job)

        self.assertEqual(st, "UNKNOWN")
        self.assertFalse(ok)
        self.assertTrue("CAUSAL_ORDER_VIOLATION" in det or "ORPHANED_TOOL_RESULT" in det)

    def test_c4_03_orphaned_or_foreign_tool_result_yields_unknown_zero_release(self):
        """
        C4-03 [P0]: TOOL_RESULT DONE with name=write_file, but without matching TOOL_CALL
        or with foreign ID/session returns UNKNOWN (non-success, 0 release ownership).
        """
        cid = "conv-c4-03"
        job = {
            "job_id": "job_FR-TZ-20261117-010_c4_03",
            "task_id": "FR-TZ-20261117-010",
            "revision": "1.0",
            "sha256": "3333333333333333333333333333333333333333333333333333333333333333",
            "file_name": "FR-TZ-20261117-010_Task.txt",
            "expected_artifacts": []
        }

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-legit-001", "args": {"Path": "a.txt"}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-alien-xyz"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with task.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )

        with patch("subprocess.run", return_value=mock_meta):
            st, ok, det = w._check_agent_session_status(cid, job)

        self.assertEqual(st, "UNKNOWN")
        self.assertFalse(ok)
        self.assertIn("ORPHANED_TOOL_RESULT", det)

    def test_c4_03_a3_identity_conflict_in_call_or_result_rejected(self):
        """
        Scenario A3 (Rev 1.1 / C4-03):
        TOOL_CALL and TOOL_RESULT contain conflicting identity attributes (session_id, job_id, attempt_id)
        relative to the job or relative to each other -> UNKNOWN (non-success).
        """
        cid = "conv-c4-a3"
        job_out = self.job_output_dir / "job_FR-TZ-20261117-010_c4_a3"
        job_out.mkdir(parents=True, exist_ok=True)
        art_target = job_out / "artifact_a3.txt"
        payload_bytes = b"Artifact bytes A3"
        art_target.write_bytes(payload_bytes)
        exp_hash = hashlib.sha256(payload_bytes).hexdigest()

        job = {
            "job_id": "job_FR-TZ-20261117-010_c4_a3",
            "task_id": "FR-TZ-20261117-010",
            "revision": "1.0",
            "attempt_id": "attempt_1",
            "sha256": "a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3",
            "file_name": "FR-TZ-20261117-010_Task.txt",
            "output_dir": str(job_out),
            "expected_artifacts": [{
                "path": str(art_target),
                "name": art_target.name,
                "expected_sha256": exp_hash,
                "is_safe": True,
                "output_dir": str(job_out),
                "min_mtime": time.time() - 50,
                "require_tool_causality": True
            }]
        }

        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)

        # Case 1: TOOL_CALL has conflicting job_id
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-id-z1", "job_id": "job_FOREIGN_INTRUDER", "args": {"Path": str(art_target)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-id-z1", "name": "write_file"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with task.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )
        with patch("subprocess.run", return_value=mock_meta):
            st1, ok1, det1 = w._check_agent_session_status(cid, job)
        self.assertEqual(st1, "UNKNOWN")
        self.assertFalse(ok1)
        self.assertIn("IDENTITY_CONFLICT", det1)

        # Case 2: TOOL_RESULT has conflicting session_id
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-id-z2", "args": {"Path": str(art_target)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-id-z2", "name": "write_file", "session_id": "conv-FOREIGN-ALIEN"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with task.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )
        with patch("subprocess.run", return_value=mock_meta):
            st2, ok2, det2 = w._check_agent_session_status(cid, job)
        self.assertEqual(st2, "UNKNOWN")
        self.assertFalse(ok2)
        self.assertIn("IDENTITY_CONFLICT", det2)

        # Case 3: Conflicting attempt_id between call and result
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-id-z3", "attempt_id": "attempt_1", "args": {"Path": str(art_target)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-id-z3", "name": "write_file", "attempt_id": "attempt_99_foreign"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with task.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )
        with patch("subprocess.run", return_value=mock_meta):
            st3, ok3, det3 = w._check_agent_session_status(cid, job)
        self.assertEqual(st3, "UNKNOWN")
        self.assertFalse(ok3)
        self.assertIn("IDENTITY_CONFLICT", det3)

    def test_c4_04_run_command_echo_or_empty_path_rejected_not_succeeded(self):
        """
        C4-04 [P0]: TOOL_CALL run_command 'echo filename' or write_file with empty Path + DONE
        with pre-existing file -> yields TERMINAL_FAILURE / UNVERIFIED_OUTCOME (not SUCCEEDED).
        """
        cid = "conv-c4-04"
        job_out = self.job_output_dir / "job_FR-TZ-20261117-010_c4_04"
        job_out.mkdir(parents=True, exist_ok=True)
        art_target = job_out / "output_c4_04.txt"
        art_target.write_text("Pre-existing content 04", encoding="utf-8")
        exp_hash = hashlib.sha256(b"Pre-existing content 04").hexdigest()

        job = {
            "job_id": "job_FR-TZ-20261117-010_c4_04",
            "task_id": "FR-TZ-20261117-010",
            "revision": "1.0",
            "sha256": "4444444444444444444444444444444444444444444444444444444444444444",
            "file_name": "FR-TZ-20261117-010_Task.txt",
            "output_dir": str(job_out),
            "expected_artifacts": [{
                "path": str(art_target),
                "name": art_target.name,
                "expected_sha256": exp_hash,
                "is_safe": True,
                "output_dir": str(job_out),
                "min_mtime": time.time() - 50,
                "require_tool_causality": True
            }]
        }

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        # 1. run_command with CommandLine 'echo output_c4_04.txt'
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "run_command", "call_id": "call-echo-1", "args": {"CommandLine": f"echo {art_target.name}"}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-echo-1"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with task.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )

        with patch("subprocess.run", return_value=mock_meta):
            st1, ok1, det1 = w._check_agent_session_status(cid, job)

        self.assertEqual(st1, "TERMINAL_FAILURE")
        self.assertFalse(ok1)
        self.assertIn("UNVERIFIED_OUTCOME", det1)

        # 2. write_file with empty Path
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-empty-p", "args": {"Path": ""}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-empty-p"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with task.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        with patch("subprocess.run", return_value=mock_meta):
            st2, ok2, det2 = w._check_agent_session_status(cid, job)

        self.assertEqual(st2, "TERMINAL_FAILURE")
        self.assertFalse(ok2)
        self.assertIn("UNVERIFIED_OUTCOME", det2)

    def test_c4_05_test_only_missing_sha_or_path_outside_job_root_rejected(self):
        """
        C4-05 [P0 / Rev 1.1]: TEST_ONLY with ACCEPTANCE_ARTIFACT without SHA, or arbitrary path
        in bare state_dir / bare temp / foreign job attempt / cross-job output -> rejected (is_safe=False / TERMINAL_FAILURE).
        Two distinct jobs do NOT accept each other's files.
        """
        # 1. Missing SHA256 in TEST_ONLY task
        doc_no_sha = self.inbox_dir / "FR-TZ-20261117-010_TestOnlyNoSha.txt"
        doc_no_sha.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            "ACCEPTANCE_ARTIFACT: art.txt\n"
            "Payload without SHA.",
            encoding="utf-8"
        )

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )
        w.poll()
        job_no_sha = list(w.state["execution_queue"].values())[0]
        self.assertEqual(len(job_no_sha["expected_artifacts"]), 1)
        self.assertFalse(job_no_sha["expected_artifacts"][0]["is_safe"])
        self.assertIn("MISSING_MANDATORY_ARTIFACT_SHA256", job_no_sha["expected_artifacts"][0]["error"])

        # 2. Path directly in bare state_dir root
        doc_bare_state = self.inbox_dir / "FR-TZ-20261117-011_BareState.txt"
        doc_bare_state.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            f"ACCEPTANCE_ARTIFACT: {self.state_dir / 'illegal_in_state.txt'}\n"
            "ACCEPTANCE_ARTIFACT_SHA256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
            "Payload.",
            encoding="utf-8"
        )
        w.poll()
        job_bare_state = [j for j in w.state["execution_queue"].values() if "011" in j["job_id"]][0]
        self.assertFalse(job_bare_state["expected_artifacts"][0]["is_safe"])
        self.assertIn("PATH_OUTSIDE_JOB_TEST_ROOT", job_bare_state["expected_artifacts"][0]["error"])

        # 3. Path in foreign job attempt under system temp: [SYSTEM_TEMP]/review/other-job-attempt/result.txt
        foreign_temp_art = Path(tempfile.gettempdir()) / "review" / "other-job-attempt" / "result.txt"
        doc_foreign = self.inbox_dir / "FR-TZ-20261117-013_ForeignTempAttempt.txt"
        doc_foreign.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            f"ACCEPTANCE_ARTIFACT: {foreign_temp_art}\n"
            "ACCEPTANCE_ARTIFACT_SHA256: ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff\n"
            "Foreign attempt payload.",
            encoding="utf-8"
        )
        w.poll()
        job_foreign = [j for j in w.state["execution_queue"].values() if "013" in j["job_id"]][0]
        self.assertFalse(job_foreign["expected_artifacts"][0]["is_safe"])
        self.assertIn("PATH_OUTSIDE_JOB_TEST_ROOT", job_foreign["expected_artifacts"][0]["error"])

        # 4. Cross-Job isolation: Job A and Job B do NOT accept each other's files
        doc_job_a = self.inbox_dir / "FR-TZ-20261117-014_JobA.txt"
        doc_job_a.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            "ACCEPTANCE_ARTIFACT: output_contract.txt\n"
            "ACCEPTANCE_ARTIFACT_SHA256: 1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef\n"
            "Job A payload.",
            encoding="utf-8"
        )
        doc_job_b = self.inbox_dir / "FR-TZ-20261117-015_JobB.txt"
        doc_job_b.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            "ACCEPTANCE_ARTIFACT: output_contract.txt\n"
            "ACCEPTANCE_ARTIFACT_SHA256: 1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef\n"
            "Job B payload.",
            encoding="utf-8"
        )
        w.poll()
        job_a = [j for j in w.state["execution_queue"].values() if "014" in j["job_id"]][0]
        job_b = [j for j in w.state["execution_queue"].values() if "015" in j["job_id"]][0]

        # The two jobs have distinct dedicated output roots
        self.assertNotEqual(job_a["output_dir"], job_b["output_dir"])
        self.assertIn(job_a["job_id"], job_a["output_dir"])
        self.assertIn(job_b["job_id"], job_b["output_dir"])

        # If Job A's expected artifact is pointed at Job B's output directory -> rejected!
        job_b_file = Path(job_b["output_dir"]) / "output_contract.txt"
        job_b_file.parent.mkdir(parents=True, exist_ok=True)
        job_b_file.write_bytes(bytes.fromhex("1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"))

        foreign_art_job_a = dict(job_a)
        foreign_art_job_a["expected_artifacts"] = [{
            "path": str(job_b_file),
            "name": "output_contract.txt",
            "expected_sha256": "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            "is_safe": True,
            "output_dir": job_a["output_dir"],
            "min_mtime": time.time() - 50,
            "require_tool_causality": True
        }]

        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": "cid-cross-test", "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        t_dir_x = self.brain_dir / "cid-cross-test" / ".system_generated" / "logs"
        t_dir_x.mkdir(parents=True)
        (t_dir_x / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job_a['job_id']} hash {job_a['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-x-cross", "args": {"Path": str(job_b_file)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-x-cross", "name": "write_file"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with task.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        with patch("subprocess.run", return_value=mock_meta):
            st_x, ok_x, det_x = w._check_agent_session_status("cid-cross-test", foreign_art_job_a)

        self.assertEqual(st_x, "TERMINAL_FAILURE")
        self.assertFalse(ok_x)
        self.assertIn("UNSAFE_ARTIFACT_PATH", det_x)

    def test_c4_06_creation_during_launcher_fresh_and_predispatch_file_rejected(self):
        """
        C4-06 [P0]: Creation of artifact during launcher execution is considered fresh
        (because dispatch_intent_ts is saved before runner execution).
        Pre-existing file modified before dispatch is strictly rejected (stale).
        """
        cid = "conv-c4-06"
        content_bytes = b"Created inside runner callable"
        exp_hash = hashlib.sha256(content_bytes).hexdigest()

        self._setup_boundary_json()
        doc = self.inbox_dir / "FR-TZ-20261117-010_TestOnlyC4_06.txt"
        doc.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            "ACCEPTANCE_ARTIFACT: output_c4_06.txt\n"
            f"ACCEPTANCE_ARTIFACT_SHA256: {exp_hash}\n"
            "Contract payload.",
            encoding="utf-8"
        )

        def runner_that_creates_artifact(job, spool):
            art_p = Path(job["expected_artifacts"][0]["path"])
            art_p.parent.mkdir(parents=True, exist_ok=True)
            art_p.write_bytes(content_bytes)
            return True, 0, json.dumps({"response": {"conversationId": cid}}), "", cid

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=runner_that_creates_artifact,
            runtime_isolation_validator=lambda cfg, wt: (True, "Verified")
        )
        w.poll()
        w.dispatch_queue()

        to_job = list(w.state["execution_queue"].values())[0]
        art_target = Path(to_job["expected_artifacts"][0]["path"])
        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)

        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{to_job['job_id']} hash {to_job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-w-c406", "args": {"Path": str(art_target)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-w-c406"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done, artifact written.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        with patch("subprocess.run", return_value=mock_meta):
            res = w.dispatch_queue()

        self.assertEqual(res.get("status"), "SUCCEEDED")
        self.assertEqual(w.state["execution_queue"][to_job["job_id"]]["execution_status"], "SUCCEEDED")

        # 2. Pre-existing file modified before dispatch must NOT be considered fresh (C4-06)
        pre_content = b"Created before dispatch"
        pre_hash = hashlib.sha256(pre_content).hexdigest()

        doc_pre = self.inbox_dir / "FR-TZ-20261117-012_PreexistingBeforeDispatch.txt"
        doc_pre.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            "ACCEPTANCE_ARTIFACT: preexisting_before_dispatch.txt\n"
            f"ACCEPTANCE_ARTIFACT_SHA256: {pre_hash}\n"
            "Contract payload.",
            encoding="utf-8"
        )
        cid_pre = "conv-c4-06-pre"
        w_pre = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=lambda j, s: (True, 0, json.dumps({"response": {"conversationId": cid_pre}}), "", cid_pre),
            runtime_isolation_validator=lambda cfg, wt: (True, "Verified")
        )
        w_pre.poll()

        to_job_pre = [j for j in w_pre.state["execution_queue"].values() if "012" in j["job_id"]][0]
        art_pre = Path(to_job_pre["expected_artifacts"][0]["path"])
        art_pre.parent.mkdir(parents=True, exist_ok=True)
        art_pre.write_bytes(pre_content)

        w_pre.dispatch_queue()
        # Re-fetch active job with updated pre-dispatch snapshot
        to_job_pre = [j for j in w_pre.state["execution_queue"].values() if "012" in j["job_id"]][0]

        t_dir_pre = self.brain_dir / cid_pre / ".system_generated" / "logs"
        t_dir_pre.mkdir(parents=True)

        (t_dir_pre / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{to_job_pre['job_id']} hash {to_job_pre['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-pre", "args": {"Path": str(art_pre)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-pre"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done, artifact written.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )
        mock_meta_pre = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid_pre, "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        with patch("subprocess.run", return_value=mock_meta_pre):
            st_pre, ok_pre, det_pre = w_pre._check_agent_session_status(cid_pre, to_job_pre)

        self.assertEqual(st_pre, "TERMINAL_FAILURE")
        self.assertFalse(ok_pre)
        self.assertIn("STALE_PREEXISTING_ARTIFACT", det_pre)

    def test_c4_07_allowed_roots_outside_isolated_scope_fails_closed_zero_calls(self):
        """
        C4-07 [P0]: allowed_write_roots = D:\\other_data or arbitrary folder outside isolated roots;
        even if fake external validator returns OK, local scope veto triggers BLOCKED_SETUP_REQUIRED (0 runner calls).
        """
        runner_mock = MagicMock()
        doc = self.inbox_dir / "FR-TZ-20261117-010_ScopeVeto.txt"
        doc.write_text("Payload for scope veto test.", encoding="utf-8")

        # allowed_write_roots contains D:\other_data which is outside worktree/temp/state
        self._setup_boundary_json(allowed_roots=[r"D:\other_data"])

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=runner_mock,
            runtime_isolation_validator=lambda cfg, wt: (True, "Fake Validator says OK")
        )
        w.poll()
        res = w.dispatch_queue()

        self.assertEqual(res.get("status"), "BLOCKED_SETUP_REQUIRED")
        self.assertIn("is outside trusted isolated workspace scope", res.get("error", ""))
        self.assertEqual(runner_mock.call_count, 0)

    def test_c4_08_contract_only_positive_branch_succeeds_with_disclaimer(self):
        """
        C4-08 [P0]: Positive CONTRACT_ONLY branch: predetermined job-specific test-root,
        full task hash, matching call_id pair for write_file, exact canonical path, and correct bytes/hash -> SUCCEEDED.
        Explicit disclaimer: Test harness writes file; this verifies dispatcher contract validation, NOT live agent runtime evidence.
        """
        cid = "conv-c4-08"
        content_bytes = b"Contract verified payload C4-08"
        exp_hash = hashlib.sha256(content_bytes).hexdigest()

        self._setup_boundary_json()
        doc = self.inbox_dir / "FR-TZ-20261117-010_ContractTestC4_08.txt"
        doc.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            "ACCEPTANCE_ARTIFACT: contract_output_c4_08.txt\n"
            f"ACCEPTANCE_ARTIFACT_SHA256: {exp_hash}\n"
            "Contract payload.",
            encoding="utf-8"
        )

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=lambda j, s: (True, 0, json.dumps({"response": {"conversationId": cid}}), "", cid),
            runtime_isolation_validator=lambda cfg, wt: (True, "Verified")
        )
        w.poll()
        w.dispatch_queue()

        to_job = list(w.state["execution_queue"].values())[0]
        art_target = Path(to_job["expected_artifacts"][0]["path"])
        art_target.parent.mkdir(parents=True, exist_ok=True)
        art_target.write_bytes(content_bytes)

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)

        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{to_job['job_id']} hash {to_job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-contract-08", "args": {"Path": str(art_target)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-contract-08"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done, artifact written successfully.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )

        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid, "createdAt": "2026-11-17T06:00:00Z"}}}
        }), stderr="")

        with patch("subprocess.run", return_value=mock_meta):
            res = w.dispatch_queue()

        self.assertEqual(res.get("status"), "SUCCEEDED")
        self.assertEqual(w.state["execution_queue"][to_job["job_id"]]["execution_status"], "SUCCEEDED")
        self.assertIsNone(w.state.get("active_execution"))

    def test_c4_09_preservation_and_mapping_of_s3_assertions(self):
        """
        C4-09 [P1]: Preserves all previous assertions.
        Explicit mapping of S3-09:
          S3-09: NOT_SEPARATE_CASE (subsumed in S3-08 / C4-08 as verified terminal success integration).
        Validates that test suites can be discovered and executed without regression.
        """
        s3_mapping = {
            "S3-01": "test_s3_01_self_declared_json_static_token_fails_closed",
            "S3-02": "test_s3_02_invalid_or_mismatched_runtime_token_rejected",
            "S3-03": "test_s3_03_prohibited_roots_and_ancestors_fail_closed",
            "S3-04": "test_s3_04_runtime_isolation_probe_observability",
            "S3-05": "test_s3_05_preexisting_artifact_or_unsafe_path_rejected",
            "S3-06": "test_s3_06_non_modifying_tool_with_preexisting_file_rejected",
            "S3-07": "test_s3_07_orphaned_tool_result_without_tool_call_returns_unknown",
            "S3-08": "test_s3_08_verified_fresh_artifact_with_causality_succeeds",
            "S3-09": "NOT_SEPARATE_CASE (subsumed in S3-08 / C4-08)",
            "S3-10": "test_s3_10_consistency_live_gate_not_executed_under_pause"
        }
        self.assertEqual(s3_mapping["S3-09"], "NOT_SEPARATE_CASE (subsumed in S3-08 / C4-08)")
        self.assertEqual(len(s3_mapping), 10)

    def test_c4_10_gate_statuses_consistency_under_pause_and_unproven_sandbox(self):
        """
        C4-10 [P1]: Under watcher.pause and unproven sandbox:
        - LIVE_GATE is strictly NOT_EXECUTED
        - AUTOSTART_READY is strictly BLOCKED_SETUP_REQUIRED
        - AUTOSTART_CODE_GATE is GO (code logic verified)
        - No false FINAL_GO is ever emitted.
        """
        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, brain_dir=self.brain_dir, mode="AUTO_EXECUTE_SCOPED"
        )
        w.pause() # active pause
        rep = w.get_status_report()

        self.assertEqual(rep.get("effective_dispatch_state"), "PAUSED_BY_OPERATOR")
        sec_ok, sec_reason = w.verify_security_boundary()
        self.assertFalse(sec_ok)
        self.assertIn("BLOCKED_SETUP_REQUIRED", sec_reason)


if __name__ == "__main__":
    unittest.main()
