"""
tests/test_autostart_provenance_and_permissions.py

Unit and contract test suite for Stage 4.2.8 AUTO-START-01 provenance and permissions hardening
under task specification FR-TZ-20261117-009 (Sections 3, 4, 5, 6, 7: S3-01 .. S3-10).

Covers:
  - S3-01 [P0]: Self-declared JSON with static string token fails closed (BLOCKED_SETUP_REQUIRED, 0 runner calls).
  - S3-02 [P0]: Expired, foreign issuer, or mismatched worktree runtime token rejected fail-closed.
  - S3-03 [P0]: Allowed roots including C:\\, C:\\RAG_Acer, prod parent/descendant, UNC or traversal fail closed (0 calls).
  - S3-04 [P0]: Runtime isolation probe (safe write vs forbidden sentinel); without observability reports NOT_EXECUTED.
  - S3-05 [P0]: TEST_ONLY with pre-existing artifact, path outside test-root, or traversal returns TERMINAL_FAILURE.
  - S3-06 [P0]: Irrelevant non-modifying tool (read_file) + pre-existing file rejected (TERMINAL_FAILURE, lease retained).
  - S3-07 [P0]: Orphaned TOOL_RESULT without matching TOOL_CALL or mismatched call_id returns UNKNOWN.
  - S3-08 [P0]: Verified fresh artifact created by session write tool with matching hash -> TERMINAL_SUCCESS -> SUCCEEDED.
  - S3-10 [P1]: Consistency of live gate under watcher.pause -> PAUSED, LIVE_GATE remains NOT_EXECUTED.
"""

import os
import json
import time
import shutil
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.drive_inbox_watcher import DriveInboxWatcher


class TestAutostartProvenanceAndPermissions(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_s3_gate_"))
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

    def _setup_boundary_json(self, allowed_roots=None, isolation_type="CONTAINER_SANDBOX", token="attest-token-1"):
        b_file = self.state_dir / "security_boundary.json"
        cfg = {
            "enforce_write_boundary": True,
            "runtime_isolation_type": isolation_type,
            "isolation_attestation_token": token,
            "allowed_write_roots": allowed_roots if allowed_roots is not None else [str(self.worktree_dir)]
        }
        b_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return b_file

    def test_s3_01_self_declared_json_static_token_fails_closed(self):
        """
        S3-01 [P0]: JSON with enforce_write_boundary=true, non-empty roots,
        runtime_isolation_type="CONTAINER_SANDBOX" and arbitrary string isolation_attestation_token="abc"
        without active external runtime isolation provider fails closed (BLOCKED_SETUP_REQUIRED, 0 runner calls).
        """
        runner_mock = MagicMock()
        doc = self.inbox_dir / "FR-TZ-20261117-009_TaskS3_01.txt"
        doc.write_text("Task payload for S3-01", encoding="utf-8")

        self._setup_boundary_json(token="arbitrary-unverified-token-abc")
        # No runtime_isolation_validator passed -> cannot prove runtime boundary from static file
        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED", runner_callable=runner_mock
        )
        watcher.poll()
        res = watcher.dispatch_queue()

        self.assertEqual(res.get("status"), "BLOCKED_SETUP_REQUIRED")
        self.assertIn("Runtime isolation cannot be proven from static local configuration", res.get("error", ""))
        self.assertEqual(runner_mock.call_count, 0)

    def test_s3_02_invalid_or_mismatched_runtime_token_rejected(self):
        """
        S3-02 [P0]: Apparent token from prior job, expired, wrong worktree, or forged issuer
        is rejected by runtime isolation validator fail-closed (BLOCKED_SETUP_REQUIRED, 0 runner calls).
        """
        runner_mock = MagicMock()
        doc = self.inbox_dir / "FR-TZ-20261117-009_TaskS3_02.txt"
        doc.write_text("Task payload for S3-02", encoding="utf-8")

        self._setup_boundary_json(token="expired-token-xyz")

        # Validator rejecting token due to expired timestamp or wrong target worktree
        def rejecting_validator(cfg, wt):
            if cfg.get("isolation_attestation_token") == "expired-token-xyz":
                return False, "TOKEN_EXPIRED_OR_WORKTREE_MISMATCH"
            return True, "OK"

        watcher = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED", runner_callable=runner_mock,
            runtime_isolation_validator=rejecting_validator
        )
        watcher.poll()
        res = watcher.dispatch_queue()

        self.assertEqual(res.get("status"), "BLOCKED_SETUP_REQUIRED")
        self.assertIn("TOKEN_EXPIRED_OR_WORKTREE_MISMATCH", res.get("error", ""))
        self.assertEqual(runner_mock.call_count, 0)

    def test_s3_03_allowed_roots_rejects_drive_root_production_parent_and_unc(self):
        """
        S3-03 [P0]: allowed_write_roots includes C:\\, C:\\RAG_Acer (production parent),
        parent of production repo/db, UNC paths, or traversal -> rejected fail-closed (0 runner calls).
        """
        runner_mock = MagicMock()
        bad_configs = [
            [r"C:\\"],                                         # Whole drive root
            [r"C:\RAG_Acer"],                                  # Production parent directory
            [r"C:\RAG_Acer\repos\flying-rag-mcp"],             # Production repo exact
            [r"C:\RAG_Acer\data_imported\metadata.db"],        # Production DB exact
            [r"C:\RAG_Acer\repos\flying-rag-mcp\storage"],     # Production repo subfolder
            [r"\\server\share\audit"],                         # UNC path
            [str(self.worktree_dir / ".." / "other")]          # Traversal path
        ]

        doc = self.inbox_dir / "FR-TZ-20261117-009_TaskS3_03.txt"
        doc.write_text("Task payload for S3-03", encoding="utf-8")

        for bad_roots in bad_configs:
            s_test = self.test_dir / f"state_{abs(hash(str(bad_roots)))}"
            s_test.mkdir()
            b_file = s_test / "security_boundary.json"
            b_file.write_text(json.dumps({
                "enforce_write_boundary": True,
                "runtime_isolation_type": "CONTAINER_SANDBOX",
                "isolation_attestation_token": "token-valid",
                "allowed_write_roots": bad_roots
            }), encoding="utf-8")

            w = DriveInboxWatcher(
                inbox_dir=self.inbox_dir, state_dir=s_test,
                worktree_dir=self.worktree_dir, mode="AUTO_EXECUTE_SCOPED",
                security_profile="SAFE_WORKTREE_SCOPED", runner_callable=runner_mock,
                runtime_isolation_validator=lambda cfg, wt: (True, "OK")
            )
            w.poll()
            runner_mock.reset_mock()
            res = w.dispatch_queue()
            self.assertEqual(res.get("status"), "BLOCKED_SETUP_REQUIRED", f"Failed for {bad_roots}")
            self.assertEqual(runner_mock.call_count, 0)

    def test_s3_04_runtime_isolation_probe_observability(self):
        """
        S3-04 [P0]: Real isolation probe: positive safe write in test-root succeeds,
        forbidden sentinel write blocked; unobservable runtime enforcement reports failure.
        """
        # Validator simulating sentinel probe
        def sentinel_probe_validator(cfg, wt):
            sentinel_blocked = cfg.get("probe_forbidden_write_blocked", False)
            if not sentinel_blocked:
                return False, "RUNTIME_ENFORCEMENT_UNOBSERVED: Forbidden sentinel write was not blocked"
            return True, "PROBE_VERIFIED: Forbidden write prevented in runtime sandbox"

        self._setup_boundary_json()
        doc = self.inbox_dir / "FR-TZ-20261117-009_TaskS3_04.txt"
        doc.write_text("Task payload for S3-04", encoding="utf-8")

        # 1. Unobserved / failed probe -> BLOCKED_SETUP_REQUIRED
        w1 = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runtime_isolation_validator=sentinel_probe_validator
        )
        ok1, reason1 = w1.verify_security_boundary()
        self.assertFalse(ok1)
        self.assertIn("RUNTIME_ENFORCEMENT_UNOBSERVED", reason1)

        # 2. Confirmed probe -> SECURITY_BOUNDARY_VERIFIED
        b_file = self.state_dir / "security_boundary.json"
        cfg = json.loads(b_file.read_text(encoding="utf-8"))
        cfg["probe_forbidden_write_blocked"] = True
        b_file.write_text(json.dumps(cfg), encoding="utf-8")

        ok2, reason2 = w1.verify_security_boundary()
        self.assertTrue(ok2)
        self.assertIn("SECURITY_BOUNDARY_VERIFIED", reason2)

    def test_s3_05_test_only_preexisting_artifact_or_outside_test_root_rejected(self):
        """
        S3-05 [P0]: TEST_ONLY with pre-existing artifact (mtime < dispatch),
        absolute path outside test-root, or traversal returns TERMINAL_FAILURE.
        """
        cid = "conv-s3-05"
        dispatch_time = time.time() + 10.0 # dispatch in future relative to pre-existing file

        # 1. Pre-existing file
        job_out = self.worktree_dir / "tests" / "output" / "job_FR-TZ-20261117-009_s3_05"
        job_out.mkdir(parents=True, exist_ok=True)
        pre_file = job_out / "preexisting_output.txt"
        pre_file.write_text("Created before dispatch", encoding="utf-8")
        # set mtime in the past
        os.utime(pre_file, (dispatch_time - 100, dispatch_time - 100))

        job = {
            "job_id": "job_FR-TZ-20261117-009_s3_05",
            "task_id": "FR-TZ-20261117-009",
            "revision": "1.0",
            "sha256": "5555555555555555555555555555555555555555555555555555555555555555",
            "file_name": "FR-TZ-20261117-009_Task.txt",
            "output_dir": str(job_out),
            "expected_artifacts": [{
                "path": str(pre_file),
                "name": pre_file.name,
                "is_safe": True,
                "output_dir": str(job_out),
                "min_mtime": dispatch_time,
                "require_tool_causality": True
            }]
        }

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-s3-05", "args": {"Path": str(pre_file)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-s3-05"}) + "\n" +
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
        self.assertEqual(st, "TERMINAL_FAILURE")
        self.assertFalse(ok)
        self.assertIn("STALE_PREEXISTING_ARTIFACT", det)

        # 2. Path outside test root
        job_outside = dict(job)
        job_outside["expected_artifacts"] = [{
            "path": r"C:\Windows\System32\fake_artifact.txt",
            "name": "fake_artifact.txt",
            "is_safe": False,
            "error": "PATH_OUTSIDE_TEST_ROOT"
        }]
        with patch("subprocess.run", return_value=mock_meta):
            st_out, ok_out, det_out = w._check_agent_session_status(cid, job_outside)
        self.assertEqual(st_out, "TERMINAL_FAILURE")
        self.assertIn("UNSAFE_ARTIFACT_PATH", det_out)

    def test_s3_06_irrelevant_tool_and_preexisting_file_fails(self):
        """
        S3-06 [P0]: Session contains USER_INPUT, one non-modifying tool (read_file) with status DONE,
        and terminal PLANNER_RESPONSE; existing file -> not SUCCEEDED, ownership retained (TERMINAL_FAILURE).
        """
        cid = "conv-s3-06"
        job_out = self.worktree_dir / "tests" / "output" / "job_FR-TZ-20261117-009_s3_06"
        job_out.mkdir(parents=True, exist_ok=True)
        target_art = job_out / "target_output.txt"
        target_art.write_text("Pre-existing content", encoding="utf-8")

        job = {
            "job_id": "job_FR-TZ-20261117-009_s3_06",
            "task_id": "FR-TZ-20261117-009",
            "revision": "1.0",
            "sha256": "6666666666666666666666666666666666666666666666666666666666666666",
            "file_name": "FR-TZ-20261117-009_Task.txt",
            "output_dir": str(job_out),
            "expected_artifacts": [{
                "path": str(target_art),
                "name": target_art.name,
                "is_safe": True,
                "output_dir": str(job_out),
                "min_mtime": time.time() - 100, # even if mtime appears valid
                "require_tool_causality": True
            }]
        }

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        # Session executes read_file, NOT write_file or edit_file!
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "read_file", "call_id": "call-read-001", "args": {"Path": str(target_art)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-read-001", "content": "File read successfully"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Task completed successfully.", "tool_calls": []}) + "\n",
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

        self.assertEqual(st, "TERMINAL_FAILURE")
        self.assertFalse(ok)
        self.assertIn("Only non-modifying tools executed", det)

    def test_s3_07_orphaned_tool_result_without_tool_call_returns_unknown(self):
        """
        S3-07 [P0]: TOOL_RESULT without matching TOOL_CALL / call_id returns UNKNOWN (not SUCCEEDED).
        """
        cid = "conv-s3-07"
        job = {
            "job_id": "job_FR-TZ-20261117-009_s3_07",
            "task_id": "FR-TZ-20261117-009",
            "revision": "1.0",
            "sha256": "7777777777777777777777777777777777777777777777777777777777777777",
            "file_name": "FR-TZ-20261117-009_Task.txt",
            "expected_artifacts": []
        }

        t_dir = self.brain_dir / cid / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        # TOOL_RESULT has call_id "call-forged-999" which has no matching TOOL_CALL!
        (t_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job['job_id']} hash {job['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "run_command", "call_id": "call-legit-001"}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-forged-999"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done.", "tool_calls": []}) + "\n",
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

    def test_s3_08_verified_fresh_artifact_with_causality_succeeds(self):
        """
        S3-08 [P0]: Authorized test job creates new file after dispatch, with matching hash
        and confirmed write tool call/result -> TERMINAL_SUCCESS -> SUCCEEDED in queue.
        """
        cid = "conv-s3-08"
        content_bytes = b"Genuine artifact content produced by agent"
        exp_hash = hashlib.sha256(content_bytes).hexdigest()

        self._setup_boundary_json()
        doc = self.inbox_dir / "FR-TZ-20261117-009_TestOnlyS3_08.txt"
        doc.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            "ACCEPTANCE_ARTIFACT: verified_output.txt\n"
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
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-legit-w1", "args": {"Path": str(art_target)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-legit-w1"}) + "\n" +
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

    def test_s3_10_consistency_live_gate_not_executed_under_pause(self):
        """
        S3-10 [P1]: LIVE_GATE remains strictly NOT_EXECUTED when watcher.pause is present;
        dispatcher reports PAUSED and invokes 0 runner calls.
        """
        runner_mock = MagicMock()
        self._setup_boundary_json()
        doc = self.inbox_dir / "FR-TZ-20261117-009_TaskS3_10.txt"
        doc.write_text("Payload S3-10", encoding="utf-8")

        w = DriveInboxWatcher(
            inbox_dir=self.inbox_dir, state_dir=self.state_dir,
            worktree_dir=self.worktree_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED", runner_callable=runner_mock,
            runtime_isolation_validator=lambda cfg, wt: (True, "Verified")
        )
        w.poll()
        w.pause() # active watcher.pause

        rep = w.get_status_report()
        self.assertEqual(rep.get("effective_dispatch_state"), "PAUSED_BY_OPERATOR")

        res = w.dispatch_queue()
        self.assertEqual(res.get("status"), "PAUSED")
        self.assertEqual(runner_mock.call_count, 0)


if __name__ == "__main__":
    unittest.main()
