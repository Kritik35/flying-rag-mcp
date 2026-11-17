# scripts/replay_tz010_rev1_1_scenarios.py
# Native verification script for FR-TZ-20261117-010 Rev 1.1 acceptance scenarios:
# Scenarios A1..A3, Foreign Attempt Root, and Cross-Job Isolation.

import os
import sys
import json
import time
import shutil
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.drive_inbox_watcher import DriveInboxWatcher


def run_replays():
    print("=" * 70)
    print("STARTING NATIVE EXCERPT REPLAYS: FR-TZ-20261117-010 REV 1.1")
    print("=" * 70)

    test_dir = Path(tempfile.mkdtemp(prefix="replay_tz010_rev1_1_"))
    inbox_dir = test_dir / "inbox"
    state_dir = test_dir / "state"
    brain_dir = test_dir / "brain"
    worktree_dir = test_dir / "worktree"
    job_output_dir = worktree_dir / "tests" / "output"

    for d in (inbox_dir, state_dir, brain_dir, worktree_dir, job_output_dir):
        d.mkdir(parents=True)

    w = DriveInboxWatcher(
        inbox_dir=inbox_dir, state_dir=state_dir,
        worktree_dir=worktree_dir, brain_dir=brain_dir, mode="AUTO_EXECUTE_SCOPED"
    )

    results = {}

    try:
        # -------------------------------------------------------------
        # SCENARIO A1: Duplicate call_id reuse with unverified write
        # -------------------------------------------------------------
        cid_a1 = "conv-replay-a1"
        job_out_a1 = job_output_dir / "job_a1"
        job_out_a1.mkdir(parents=True)
        art_a1 = job_out_a1 / "artifact_a1.txt"
        payload_a1 = b"Payload A1"
        art_a1.write_bytes(payload_a1)
        sha_a1 = hashlib.sha256(payload_a1).hexdigest()

        job_a1 = {
            "job_id": "job_a1", "task_id": "TZ-010", "revision": "1.1", "sha256": "11" * 32,
            "output_dir": str(job_out_a1),
            "expected_artifacts": [{
                "path": str(art_a1), "name": art_a1.name, "expected_sha256": sha_a1,
                "is_safe": True, "output_dir": str(job_out_a1), "min_mtime": time.time() - 50,
                "require_tool_causality": True
            }]
        }
        t_dir_a1 = brain_dir / cid_a1 / ".system_generated" / "logs"
        t_dir_a1.mkdir(parents=True)
        (t_dir_a1 / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job_a1['job_id']} hash {job_a1['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "read_file", "call_id": "call-x", "args": {"Path": "doc.txt"}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-x", "name": "read_file"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-x", "args": {"Path": str(art_a1)}}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with all work.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )
        mock_meta = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid_a1, "createdAt": "2026-11-17T06:00:00Z"}}}
        }))
        with patch("subprocess.run", return_value=mock_meta):
            st_a1, ok_a1, det_a1 = w._check_agent_session_status(cid_a1, job_a1)

        print(f"Scenario A1 (Duplicate call_id reuse): status={st_a1}, ok={ok_a1}, detail={det_a1}")
        assert st_a1 != "TERMINAL_SUCCESS", "A1 must NOT yield TERMINAL_SUCCESS"
        assert not ok_a1, "A1 outcome must be False"
        assert "AMBIGUOUS_TOOL_CALL_ID" in det_a1, "A1 must report AMBIGUOUS_TOOL_CALL_ID"
        results["A1"] = {"status": st_a1, "ok": ok_a1, "detail": det_a1, "verdict": "PASS"}

        # -------------------------------------------------------------
        # SCENARIO A2: TOOL_RESULT preceding TOOL_CALL
        # -------------------------------------------------------------
        cid_a2 = "conv-replay-a2"
        job_out_a2 = job_output_dir / "job_a2"
        job_out_a2.mkdir(parents=True)
        art_a2 = job_out_a2 / "artifact_a2.txt"
        payload_a2 = b"Payload A2"
        art_a2.write_bytes(payload_a2)
        sha_a2 = hashlib.sha256(payload_a2).hexdigest()

        job_a2 = {
            "job_id": "job_a2", "task_id": "TZ-010", "revision": "1.1", "sha256": "22" * 32,
            "output_dir": str(job_out_a2),
            "expected_artifacts": [{
                "path": str(art_a2), "name": art_a2.name, "expected_sha256": sha_a2,
                "is_safe": True, "output_dir": str(job_out_a2), "min_mtime": time.time() - 50,
                "require_tool_causality": True
            }]
        }
        t_dir_a2 = brain_dir / cid_a2 / ".system_generated" / "logs"
        t_dir_a2.mkdir(parents=True)
        (t_dir_a2 / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job_a2['job_id']} hash {job_a2['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-y", "name": "write_file"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-y", "args": {"Path": str(art_a2)}}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with all work.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )
        mock_meta_a2 = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid_a2, "createdAt": "2026-11-17T06:00:00Z"}}}
        }))
        with patch("subprocess.run", return_value=mock_meta_a2):
            st_a2, ok_a2, det_a2 = w._check_agent_session_status(cid_a2, job_a2)

        print(f"Scenario A2 (Result preceding call): status={st_a2}, ok={ok_a2}, detail={det_a2}")
        assert st_a2 == "UNKNOWN", "A2 must yield UNKNOWN"
        assert not ok_a2, "A2 outcome must be False"
        assert "CAUSAL_ORDER_VIOLATION" in det_a2 or "ORPHANED_TOOL_RESULT" in det_a2
        results["A2"] = {"status": st_a2, "ok": ok_a2, "detail": det_a2, "verdict": "PASS"}

        # -------------------------------------------------------------
        # SCENARIO A3: Identity conflict in TOOL_CALL / TOOL_RESULT
        # -------------------------------------------------------------
        cid_a3 = "conv-replay-a3"
        job_out_a3 = job_output_dir / "job_a3"
        job_out_a3.mkdir(parents=True)
        art_a3 = job_out_a3 / "artifact_a3.txt"
        payload_a3 = b"Payload A3"
        art_a3.write_bytes(payload_a3)
        sha_a3 = hashlib.sha256(payload_a3).hexdigest()

        job_a3 = {
            "job_id": "job_a3", "task_id": "TZ-010", "revision": "1.1", "sha256": "33" * 32,
            "output_dir": str(job_out_a3),
            "expected_artifacts": [{
                "path": str(art_a3), "name": art_a3.name, "expected_sha256": sha_a3,
                "is_safe": True, "output_dir": str(job_out_a3), "min_mtime": time.time() - 50,
                "require_tool_causality": True
            }]
        }
        t_dir_a3 = brain_dir / cid_a3 / ".system_generated" / "logs"
        t_dir_a3.mkdir(parents=True)
        (t_dir_a3 / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job_a3['job_id']} hash {job_a3['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-z", "job_id": "job_FOREIGN_INTRUDER", "args": {"Path": str(art_a3)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-z", "name": "write_file"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with all work.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )
        mock_meta_a3 = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid_a3, "createdAt": "2026-11-17T06:00:00Z"}}}
        }))
        with patch("subprocess.run", return_value=mock_meta_a3):
            st_a3, ok_a3, det_a3 = w._check_agent_session_status(cid_a3, job_a3)

        print(f"Scenario A3 (Identity conflict): status={st_a3}, ok={ok_a3}, detail={det_a3}")
        assert st_a3 == "UNKNOWN", "A3 must yield UNKNOWN"
        assert not ok_a3, "A3 outcome must be False"
        assert "IDENTITY_CONFLICT" in det_a3
        results["A3"] = {"status": st_a3, "ok": ok_a3, "detail": det_a3, "verdict": "PASS"}

        # -------------------------------------------------------------
        # SCENARIO C4-05: Foreign job attempt in temp rejected
        # -------------------------------------------------------------
        foreign_temp_file = Path(tempfile.gettempdir()) / "review" / "other-job-attempt" / "result.txt"
        doc_foreign = inbox_dir / "FR-TZ-20261117-010_ForeignTemp.txt"
        doc_foreign.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            f"ACCEPTANCE_ARTIFACT: {foreign_temp_file}\n"
            f"ACCEPTANCE_ARTIFACT_SHA256: {'44' * 32}\n"
            "Foreign temp attempt payload.\n",
            encoding="utf-8"
        )
        w.poll()
        job_f = [j for j in w.state["execution_queue"].values() if "ForeignTemp" in j["file_name"]][0]
        f_safe = job_f["expected_artifacts"][0]["is_safe"]
        f_err = job_f["expected_artifacts"][0]["error"]
        print(f"Scenario C4-05 (Foreign Temp Attempt in poll): is_safe={f_safe}, error={f_err}")
        assert not f_safe, "Foreign temp attempt must have is_safe=False"
        assert "PATH_OUTSIDE_JOB_TEST_ROOT" in f_err
        results["C4_05_Foreign_Temp"] = {"is_safe": f_safe, "error": f_err, "verdict": "PASS"}

        # -------------------------------------------------------------
        # SCENARIO C4-05: Cross-Job Isolation (Job A vs Job B)
        # -------------------------------------------------------------
        job_out_a = job_output_dir / "job_A_001"
        job_out_b = job_output_dir / "job_B_002"
        job_out_a.mkdir(parents=True)
        job_out_b.mkdir(parents=True)
        file_b = job_out_b / "output.txt"
        file_b.write_bytes(b"Content of Job B")
        sha_b = hashlib.sha256(b"Content of Job B").hexdigest()

        # Job A evaluates file located in Job B's output directory
        job_a_cross = {
            "job_id": "job_A_001", "task_id": "TZ-010", "revision": "1.1", "sha256": "55" * 32,
            "output_dir": str(job_out_a),
            "expected_artifacts": [{
                "path": str(file_b), "name": file_b.name, "expected_sha256": sha_b,
                "is_safe": True, "output_dir": str(job_out_a), "min_mtime": time.time() - 50,
                "require_tool_causality": True
            }]
        }
        cid_cross = "conv-replay-cross"
        t_dir_cr = brain_dir / cid_cross / ".system_generated" / "logs"
        t_dir_cr.mkdir(parents=True)
        (t_dir_cr / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{job_a_cross['job_id']} hash {job_a_cross['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-cr", "args": {"Path": str(file_b)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-cr", "name": "write_file"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done with work.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )
        mock_meta_cr = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid_cross, "createdAt": "2026-11-17T06:00:00Z"}}}
        }))
        with patch("subprocess.run", return_value=mock_meta_cr):
            st_cr, ok_cr, det_cr = w._check_agent_session_status(cid_cross, job_a_cross)

        print(f"Scenario Cross-Job Isolation: status={st_cr}, ok={ok_cr}, detail={det_cr}")
        assert st_cr == "TERMINAL_FAILURE", "Cross-job artifact must yield TERMINAL_FAILURE"
        assert not ok_cr, "Cross-job outcome must be False"
        assert "UNSAFE_ARTIFACT_PATH" in det_cr
        results["Cross_Job_Isolation"] = {"status": st_cr, "ok": ok_cr, "detail": det_cr, "verdict": "PASS"}

        # -------------------------------------------------------------
        # SCENARIO C4-08: Genuine CONTRACT_ONLY Positive Verification
        # -------------------------------------------------------------
        inbox_pos = test_dir / "inbox_pos"
        state_pos = test_dir / "state_pos"
        inbox_pos.mkdir(parents=True)
        state_pos.mkdir(parents=True)

        doc_contract = inbox_pos / "FR-TZ-20261117-016_PositiveContract.txt"
        contract_bytes = b"Genuine CONTRACT_ONLY output"
        contract_sha = hashlib.sha256(contract_bytes).hexdigest()
        doc_contract.write_text(
            "TASK_TYPE: TEST_ONLY\n"
            "ACCEPTANCE_ARTIFACT: contract_verified.txt\n"
            f"ACCEPTANCE_ARTIFACT_SHA256: {contract_sha}\n"
            "Positive contract payload.\n",
            encoding="utf-8"
        )
        cid_pos = "conv-replay-pos"
        w_pos = DriveInboxWatcher(
            inbox_dir=inbox_pos, state_dir=state_pos, worktree_dir=worktree_dir,
            brain_dir=brain_dir, mode="AUTO_EXECUTE_SCOPED",
            security_profile="SAFE_WORKTREE_SCOPED",
            runner_callable=lambda j, s: (True, 0, json.dumps({"response": {"conversationId": cid_pos}}), "", cid_pos),
            runtime_isolation_validator=lambda cfg, wt: (True, "Verified")
        )
        b_file = state_pos / "security_boundary.json"
        b_file.write_text(json.dumps({
            "enforce_write_boundary": True, "runtime_isolation_type": "CONTAINER_SANDBOX",
            "isolation_attestation_token": "attest-pos-token", "allowed_write_roots": [str(worktree_dir)]
        }), encoding="utf-8")

        w_pos.poll()
        w_pos.dispatch_queue()

        to_job_pos = [j for j in w_pos.state["execution_queue"].values() if "PositiveContract" in j["file_name"]][0]
        art_pos = Path(to_job_pos["expected_artifacts"][0]["path"])
        art_pos.parent.mkdir(parents=True, exist_ok=True)
        art_pos.write_bytes(contract_bytes)

        t_dir_pos = brain_dir / cid_pos / ".system_generated" / "logs"
        t_dir_pos.mkdir(parents=True)
        (t_dir_pos / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": f"{to_job_pos['job_id']} hash {to_job_pos['sha256']}"}) + "\n" +
            json.dumps({"type": "TOOL_CALL", "name": "write_file", "call_id": "call-pos-01", "args": {"Path": str(art_pos)}}) + "\n" +
            json.dumps({"type": "TOOL_RESULT", "status": "DONE", "call_id": "call-pos-01", "name": "write_file"}) + "\n" +
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Done, artifact written successfully.", "tool_calls": []}) + "\n",
            encoding="utf-8"
        )
        mock_meta_pos = MagicMock(returncode=0, stdout=json.dumps({
            "response": {"conversationMetadata": {"metadata": {"rootConversationId": cid_pos, "createdAt": "2026-11-17T06:00:00Z"}}}
        }))
        with patch("subprocess.run", return_value=mock_meta_pos):
            res_pos = w_pos.dispatch_queue()

        status_pos = w_pos.state["execution_queue"][to_job_pos["job_id"]]["execution_status"]
        print(f"Scenario C4-08 (Positive CONTRACT_ONLY): status={status_pos}")
        assert status_pos == "SUCCEEDED", "Positive CONTRACT_ONLY must yield SUCCEEDED"
        results["C4_08_Positive_Contract"] = {"status": status_pos, "verdict": "PASS"}

        print("=" * 70)
        print("ALL REPLAY SCENARIOS COMPLETED SUCCESSFULLY:")
        for sc, r in results.items():
            print(f"  {sc}: {r['verdict']}")
        print("=" * 70)
        return True

    finally:
        try:
            shutil.rmtree(test_dir)
        except Exception:
            pass


if __name__ == "__main__":
    ok = run_replays()
    sys.exit(0 if ok else 1)
