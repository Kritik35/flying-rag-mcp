"""
scripts/drive_inbox_watcher.py

Automated Google Drive Inbox Watcher & Autonomous Dispatcher for FlyingRAG.
Supports Stage 4.2.5 (Block M0) and Stage 4.2.8 (AUTO-START-01 / Section 8).

Monitors Google Drive inbox folder for new ТЗ documents in .txt / .md format.
Maintains state outside Git and production, performs cross-process locking,
handles atomic persistence, state migration, input sanitization, policy veto,
and autonomous execution dispatch via Antigravity agent runner.
"""

from __future__ import annotations
import os
import sys
import json
import time
import hashlib
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple, Callable

logger = logging.getLogger("DriveInboxWatcher")

# Default directories
DEFAULT_INBOX_DIR = Path(r"G:\Мой диск\FlyingRAG_TZ_Inbox")
DEFAULT_STATE_DIR = Path(r"C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher")
DEFAULT_AGENT_RUNNER = Path(r"C:\Users\almax\.gemini\antigravity\bin\agentapi.bat")

# Supported file extensions
SUPPORTED_EXTENSIONS = {".txt", ".md"}
CLOUD_SHORTCUT_EXTENSIONS = {".gdoc", ".gsheet", ".gslides"}


def _sanitize_path(p: str | Path | None) -> str:
    """Sanitizes absolute filesystem paths for telemetry privacy."""
    if not p:
        return ""
    s = str(p).replace("\\", "/")
    import re
    s = re.sub(r'^[a-zA-Z]:[/]+(?:Мой диск|Мой\s+диск|Normative_Docs|Docs|docs|Corpus|corpus)[/]+', '[DRIVE_INBOX]/', s, flags=re.IGNORECASE)
    s = re.sub(r'^[a-zA-Z]:[/]+(?:Acer_System_Audit|rag_quality_ab_[^/]+)[/]+', '[AUDIT_ROOT]/', s, flags=re.IGNORECASE)
    s = re.sub(r'^[a-zA-Z]:[/]+(?:rag_acer|repos)[/]+flying-rag-mcp[/]+', '[REPO_ROOT]/', s, flags=re.IGNORECASE)
    s = re.sub(r'^[a-zA-Z]:[/]+Users[/]+[^/]+[/]+', '/Users/[USER]/', s, flags=re.IGNORECASE)
    s = re.sub(r'^[a-zA-Z]:[/]+', '[DRIVE]/', s)
    return s


def check_policy_veto(content: str) -> Tuple[bool, str]:
    """
    Validates task content against mandatory safety constraints (Section 8.0 & 8.6 / AS-09).
    Strictly vetoes tasks commanding:
      - Direct production database write / mutation / schema changes
      - Corpus reindexing or reindex triggers
      - Merging to protected branch without human review
      - Force pushing (git push --force)
      - Unauthorized local model load or llama-server starts
      - Production snapshot overwriting
      - Disabling safety guard or security bypass
    """
    lower_lines = [line.strip().lower() for line in content.splitlines()]
    for line in lower_lines:
        # Ignore negation lines like "no production writes", "не изменять", "запрещено", etc.
        if any(neg in line for neg in ["no ", "не ", "запрет", "strictly forbidden", "do not", "never", "без "]):
            continue
        if "production-write" in line or "write_production" in line:
            return False, "POLICY_VETO: Direct production write directive detected in task (AS-09)"
        if "reindex corpus" in line or "reindex_all" in line or "force_reindex" in line:
            return False, "POLICY_VETO: Corpus reindex directive detected in task (AS-09)"
        if "git push --force" in line or "git push -f" in line:
            return False, "POLICY_VETO: Force push directive detected in task (AS-09)"
        if "git merge main" in line or "git merge master" in line:
            return False, "POLICY_VETO: Direct merge to production branch detected in task (AS-09)"
        if "disable_safety" in line or "bypass_allowlist" in line:
            return False, "POLICY_VETO: Security bypass directive detected in task (AS-09)"
        if "llama_server_start" in line or "load_model_direct" in line:
            return False, "POLICY_VETO: Unauthorized model load directive detected in task (AS-09)"
        if "copy_to_production" in line or "overwrite_production" in line:
            return False, "POLICY_VETO: Production overwrite directive detected in task (AS-09)"
    return True, ""


def extract_task_id(filename: str, text: str) -> str:
    """Extracts standard task ID from filename or document header."""
    import re
    # Try filename matching FR-TZ-YYYYMMDD-XXX
    m = re.search(r'(FR-TZ-\d{8}-\d{3})', filename, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # Try header match
    m_hdr = re.search(r'(FR-TZ-\d{8}-\d{3})', text[:1000], re.IGNORECASE)
    if m_hdr:
        return m_hdr.group(1).upper()
    # Fallback to file stem
    return Path(filename).stem


class FileLock:
    """Cross-platform non-blocking file lock / mutex."""
    def __init__(self, lock_file_path: Path):
        self.lock_path = lock_file_path
        self._fd = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
            if sys.platform == "win32":
                import msvcrt
                try:
                    msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                    return True
                except (OSError, IOError):
                    os.close(self._fd)
                    self._fd = None
                    return False
            else:
                import fcntl
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except (OSError, IOError):
                    os.close(self._fd)
                    self._fd = None
                    return False
        except Exception as e:
            logger.warning(f"Failed to open lock file {self.lock_path}: {e}")
            return False

    def release(self):
        if self._fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None


class DriveInboxWatcher:
    """
    Autonomous inbox watcher and dispatcher for Google Drive ТЗ documents.
    Tracks file states across poll cycles: DETECTED -> FETCHED -> ACKNOWLEDGED.
    In AUTO_EXECUTE_SCOPED mode: enqueues validated work and dispatches to agent runner.
    Guarantees:
      - Cross-process locking (watcher.lock and execution.lock)
      - Atomic persistence with migration backup
      - Crash recovery (DISPATCH_UNKNOWN without blind retry, AS-06)
      - Pre-dispatch spool hash verification (AS-08)
      - Policy veto (AS-09)
      - Single active agent worker lease (AS-04)
      - Pause / resume control (AS-11)
    """
    MAX_RETRIES = 5
    MAX_DISPATCH_ATTEMPTS = 3
    LEASE_TIMEOUT_SEC = 300.0

    def __init__(
        self,
        inbox_dir: Path | str | None = None,
        state_dir: Path | str | None = None,
        mode: Optional[str] = None,
        runner_cmd: Optional[str | Path] = None,
        runner_callable: Optional[Callable[[Dict[str, Any], Path], Tuple[bool, int, str, str, Optional[str]]]] = None
    ):
        env_inbox = os.environ.get("FLYING_RAG_DRIVE_INBOX_DIR", "").strip()
        self.inbox_dir = Path(inbox_dir or env_inbox or DEFAULT_INBOX_DIR)

        env_state = os.environ.get("FLYING_RAG_DRIVE_WATCHER_DIR", "").strip()
        self.state_dir = Path(state_dir or env_state or DEFAULT_STATE_DIR)
        self.state_file = self.state_dir / "state.json"
        self.lock_file = self.state_dir / "watcher.lock"
        self.exec_lock_file = self.state_dir / "execution.lock"
        self.pause_file = self.state_dir / "watcher.pause"
        self.spool_dir = self.state_dir / "inbox_spool"
        self.notifications_dir = self.state_dir / "notifications"

        self.mode = mode or "DETECTION_ONLY"
        self.runner_cmd = runner_cmd
        self.runner_callable = runner_callable

        self.lock = FileLock(self.lock_file)
        self.exec_lock = FileLock(self.exec_lock_file)
        self._state_is_corrupt = False
        self.state = self._load_state()

    def _migrate_state_if_needed(self, loaded_state: dict) -> dict:
        """Migrates state schema to version 2 (with execution_queue and active_execution) while preserving history."""
        v = loaded_state.get("version", 1)
        if v < 2 or "execution_queue" not in loaded_state:
            logger.info("Migrating state schema to version 2 with execution_queue (AS-10)")
            # Create migration backup
            backup_path = self.state_dir / f"state.json.bak_migration_{int(time.time()*1000)}"
            try:
                if self.state_file.exists():
                    import shutil
                    shutil.copy2(self.state_file, backup_path)
                    logger.info(f"Preserved pre-migration state backup at {backup_path}")
            except Exception as e:
                logger.warning(f"Could not create migration backup: {e}")

            loaded_state["version"] = 2
            queue = loaded_state.setdefault("execution_queue", {})
            loaded_state.setdefault("active_execution", None)

            # Populate queue from existing acknowledged files as HISTORICALLY_COMPLETED / DELIVERY_CONFIRMED
            tracked = loaded_state.get("tracked_files", {})
            for fname, rec in tracked.items():
                if rec.get("lifecycle_status") == "ACKNOWLEDGED":
                    j_id = f"job_legacy_{fname[:20]}_v{rec.get('version_number', 1)}_{str(rec.get('sha256'))[:8]}"
                    if j_id not in queue:
                        queue[j_id] = {
                            "job_id": j_id,
                            "task_id": fname,
                            "file_name": fname,
                            "version_number": rec.get("version_number", 1),
                            "sha256": rec.get("sha256"),
                            "delivery_status": "ACKNOWLEDGED",
                            "execution_status": "HISTORICALLY_COMPLETED",
                            "enqueued_at": rec.get("acknowledged_at") or loaded_state.get("created_utc"),
                            "dispatched_at": rec.get("acknowledged_at"),
                            "finished_at": rec.get("acknowledged_at"),
                            "lease_pid": None,
                            "lease_expires_at": None,
                            "attempts": 1,
                            "max_attempts": self.MAX_DISPATCH_ATTEMPTS,
                            "last_error": None,
                            "conversation_id": None,
                            "spool_path": rec.get("spool_path"),
                            "notes": "Migrated from legacy ACKNOWLEDGED record (historical stage completed with verified commit)"
                        }
        return loaded_state

    def _load_state(self) -> dict:
        self._state_is_corrupt = False
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data = self._migrate_state_if_needed(data)
                # Respect persisted mode unless explicitly overridden in constructor
                if not getattr(self, "_mode_overridden", False):
                    if "watcher_mode" in data and self.mode == "DETECTION_ONLY":
                        self.mode = data.get("watcher_mode", self.mode)
                return data
            except Exception as e:
                self._state_is_corrupt = True
                logger.error(f"CRITICAL: Error reading state file {self.state_file}: {e}")
                corrupt_backup = self.state_dir / f"state.json.corrupt_{int(time.time()*1000)}"
                try:
                    import shutil
                    shutil.copy2(self.state_file, corrupt_backup)
                    logger.error(f"Preserved corrupt state file copy at {corrupt_backup}")
                except Exception:
                    pass
        return {
            "version": 2,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "last_poll_utc": None,
            "last_dispatch_utc": None,
            "watcher_mode": self.mode,
            "inbox_path": _sanitize_path(self.inbox_dir),
            "state_path": _sanitize_path(self.state_dir),
            "tracked_files": {},
            "execution_queue": {},
            "active_execution": None,
            "history": [],
            "ignored_cloud_shortcuts": []
        }

    def _save_state(self):
        if getattr(self, "_state_is_corrupt", False):
            logger.warning("Skipping _save_state: state is marked corrupt. Refusing to clobber state.json.")
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = self.state_dir / f"state_{os.getpid()}_{int(time.time()*1000)}.tmp"
        try:
            self.state["watcher_mode"] = self.mode
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self.state_file)
        finally:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    def reconstruct_state_from_artifacts(self) -> dict:
        """Safely reconstructs state from notifications and inbox_spool without emitting new events."""
        tracked = {}
        history = []
        queue = {}
        seen_event_ids = set()

        if self.notifications_dir.exists():
            for p in sorted(self.notifications_dir.glob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    eid = data.get("event_id")
                    if eid and eid not in seen_event_ids:
                        seen_event_ids.add(eid)
                        history.append({
                            "event_id": eid,
                            "file_name": data.get("file_name"),
                            "version_number": data.get("version_number", 1),
                            "sha256": data.get("sha256"),
                            "timestamp_utc": data.get("timestamp_utc")
                        })
                        fn = data.get("file_name")
                        if fn:
                            inbox_file = self.inbox_dir / fn
                            file_mtime = inbox_file.stat().st_mtime if inbox_file.exists() else 0.0
                            file_size = data.get("size_bytes", 0) or (inbox_file.stat().st_size if inbox_file.exists() else 0)
                            tracked[fn] = {
                                "file_id": fn,
                                "relative_path": fn,
                                "mime_type": "text/plain" if fn.endswith(".txt") else "text/markdown",
                                "mtime": file_mtime,
                                "size_bytes": file_size,
                                "sha256": data.get("sha256"),
                                "lifecycle_status": "ACKNOWLEDGED",
                                "detected_at": data.get("timestamp_utc"),
                                "fetched_at": data.get("timestamp_utc"),
                                "acknowledged_at": data.get("timestamp_utc"),
                                "version_number": data.get("version_number", 1),
                                "retry_count": 0,
                                "notes": "Reconstructed from notification artifacts",
                                "spool_path": data.get("spool_file")
                            }
                            # Enqueue legacy job
                            j_id = f"job_reconstructed_{fn[:20]}_v{data.get('version_number', 1)}_{str(data.get('sha256'))[:8]}"
                            queue[j_id] = {
                                "job_id": j_id,
                                "task_id": fn,
                                "file_name": fn,
                                "version_number": data.get("version_number", 1),
                                "sha256": data.get("sha256"),
                                "delivery_status": "ACKNOWLEDGED",
                                "execution_status": "HISTORICALLY_COMPLETED",
                                "enqueued_at": data.get("timestamp_utc"),
                                "dispatched_at": data.get("timestamp_utc"),
                                "finished_at": data.get("timestamp_utc"),
                                "lease_pid": None,
                                "lease_expires_at": None,
                                "attempts": 1,
                                "max_attempts": self.MAX_DISPATCH_ATTEMPTS,
                                "last_error": None,
                                "conversation_id": None,
                                "spool_path": data.get("spool_file"),
                                "notes": "Reconstructed from notification artifacts"
                            }
                except Exception:
                    pass

        self.state["tracked_files"] = tracked
        self.state["execution_queue"] = queue
        self.state["history"] = history
        self._state_is_corrupt = False
        self._save_state()
        return self.state

    @staticmethod
    def compute_sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def is_paused(self) -> bool:
        """Returns True if operator pause sentinel exists or pause flag is set."""
        return self.pause_file.exists()

    def pause(self):
        """Creates pause sentinel file."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.pause_file.write_text(f"PAUSED_BY_OPERATOR at {datetime.now(timezone.utc).isoformat()}\n", encoding="utf-8")
        logger.info(f"Watcher paused: created {self.pause_file}")

    def resume(self):
        """Removes pause sentinel file."""
        if self.pause_file.exists():
            try:
                self.pause_file.unlink()
                logger.info(f"Watcher resumed: removed {self.pause_file}")
            except Exception as e:
                logger.warning(f"Could not remove pause file {self.pause_file}: {e}")

    def enable_autostart(self):
        """Switches watcher mode to AUTO_EXECUTE_SCOPED."""
        self.mode = "AUTO_EXECUTE_SCOPED"
        self._mode_overridden = True
        self.state["watcher_mode"] = self.mode
        self._save_state()
        logger.info("Watcher mode set to AUTO_EXECUTE_SCOPED")

    def disable_autostart(self):
        """Switches watcher mode to DETECTION_ONLY."""
        self.mode = "DETECTION_ONLY"
        self._mode_overridden = True
        self.state["watcher_mode"] = self.mode
        self._save_state()
        logger.info("Watcher mode set to DETECTION_ONLY")

    def poll(self, bootstrap: bool = False) -> dict:
        """
        Executes a single poll cycle across the inbox directory.
        Detects, validates, spools, acknowledges, and enqueues tasks.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        cycle_result = {
            "timestamp_utc": now_utc,
            "inbox_exists": self.inbox_dir.exists(),
            "detected_count": 0,
            "fetched_count": 0,
            "acknowledged_count": 0,
            "failed_retry_count": 0,
            "enqueued_count": 0,
            "new_events": [],
            "status": "OK"
        }

        if getattr(self, "_state_is_corrupt", False):
            cycle_result["status"] = "STATE_CORRUPT_HALTED"
            cycle_result["error"] = "state.json is corrupt and archived; poll halted to prevent duplicate events or state clobbering"
            logger.error(cycle_result["error"])
            return cycle_result

        if not self.inbox_dir.exists():
            cycle_result["status"] = "INBOX_NOT_FOUND"
            cycle_result["error"] = f"Directory {self.inbox_dir} does not exist or volume is unmounted"
            logger.warning(cycle_result["error"])
            return cycle_result

        try:
            entries = list(self.inbox_dir.iterdir())
        except Exception as e:
            cycle_result["status"] = "SCAN_ERROR"
            cycle_result["error"] = str(e)
            return cycle_result

        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self.notifications_dir.mkdir(parents=True, exist_ok=True)

        tracked = self.state.setdefault("tracked_files", {})
        queue = self.state.setdefault("execution_queue", {})
        ignored_shortcuts = []

        for entry in entries:
            # Skip hidden and temp office files
            if entry.name.startswith("~$") or entry.name.startswith("."):
                continue

            # AS-07: Reject directory traversal or dangerous shell metacharacters in filename
            bad_chars = [";", "&", "|", "`", "$", "\n", "\r", "<", ">"]
            if any(c in entry.name for c in bad_chars) or ".." in entry.name or "/" in entry.name or "\\" in entry.name:
                logger.warning(f"AS-07: Rejected entry with dangerous characters or traversal in name: {entry.name}")
                tracked[entry.name] = {
                    "file_id": entry.name,
                    "lifecycle_status": "REJECTED_INVALID_NAME",
                    "detected_at": now_utc,
                    "notes": "Rejected due to directory traversal or shell metacharacters (AS-07)"
                }
                continue

            # AS-07: Reject symlinks / junctions
            if entry.is_symlink():
                logger.warning(f"AS-07: Rejected symlink entry: {entry.name}")
                tracked[entry.name] = {
                    "file_id": entry.name,
                    "lifecycle_status": "REJECTED_SYMLINK",
                    "detected_at": now_utc,
                    "notes": "Rejected symbolic link or junction target (AS-07)"
                }
                continue

            ext = entry.suffix.lower()

            # Record cloud shortcuts without crashing or attempting invalid read
            if ext in CLOUD_SHORTCUT_EXTENSIONS:
                ignored_shortcuts.append({
                    "name": entry.name,
                    "extension": ext,
                    "mtime": entry.stat().st_mtime if entry.exists() else 0,
                    "reason": "Google Docs cloud shortcut (.gdoc). Plain text (.txt) or markdown (.md) file required."
                })
                continue

            if ext not in SUPPORTED_EXTENSIONS or not entry.is_file():
                continue

            try:
                st = entry.stat()
                mtime = st.st_mtime
                size_bytes = st.st_size
            except Exception as e:
                logger.warning(f"Could not stat {entry.name}: {e}")
                continue

            # AS-07: Reject empty files
            if size_bytes == 0:
                logger.warning(f"AS-07: Rejected empty file (0 bytes): {entry.name}")
                tracked[entry.name] = {
                    "file_id": entry.name,
                    "lifecycle_status": "REJECTED_EMPTY_FILE",
                    "detected_at": now_utc,
                    "notes": "Rejected empty file (0 bytes) (AS-07)"
                }
                continue

            file_key = entry.name
            existing_record = tracked.get(file_key)

            is_new = existing_record is None
            is_modified = False
            prev_status = existing_record.get("lifecycle_status") if existing_record else None
            existing_retry_count = existing_record.get("retry_count", 0) if existing_record else 0

            if existing_record:
                if existing_record.get("mtime") != mtime or existing_record.get("size_bytes") != size_bytes:
                    is_modified = True

            if is_modified:
                existing_retry_count = 0

            if prev_status == "FAILED_PERMANENT" and not is_modified:
                continue

            is_retryable = prev_status in ("FAILED_RETRY", "BASELINE_UNREADABLE", "DETECTED")

            if not is_new and not is_modified and not is_retryable:
                continue

            # Bootstrap mode
            if bootstrap:
                try:
                    content = entry.read_bytes()
                    file_sha256 = self.compute_sha256(content)
                    tracked[file_key] = {
                        "file_id": entry.name,
                        "relative_path": entry.name,
                        "mime_type": "text/plain" if ext == ".txt" else "text/markdown",
                        "mtime": mtime,
                        "size_bytes": size_bytes,
                        "sha256": file_sha256,
                        "lifecycle_status": "ACKNOWLEDGED",
                        "detected_at": now_utc,
                        "fetched_at": now_utc,
                        "acknowledged_at": now_utc,
                        "version_number": 1,
                        "retry_count": 0,
                        "notes": "Baseline task registered on bootstrap"
                    }
                    cycle_result["acknowledged_count"] += 1
                except Exception as b_err:
                    logger.warning(f"Bootstrap read error for {entry.name}: {b_err}")
                    tracked[file_key] = {
                        "file_id": entry.name,
                        "relative_path": entry.name,
                        "mime_type": "text/plain" if ext == ".txt" else "text/markdown",
                        "mtime": mtime,
                        "size_bytes": size_bytes,
                        "sha256": None,
                        "lifecycle_status": "BASELINE_UNREADABLE",
                        "detected_at": now_utc,
                        "fetched_at": None,
                        "acknowledged_at": None,
                        "version_number": 0,
                        "retry_count": 1,
                        "last_error": str(b_err),
                        "notes": "Unreadable at bootstrap - pending retry"
                    }
                    cycle_result["failed_retry_count"] += 1
                continue

            # Standard poll
            cycle_result["detected_count"] += 1
            if existing_record and prev_status == "ACKNOWLEDGED" and is_modified:
                version_num = (existing_record.get("version_number", 1) or 1) + 1
            elif existing_record:
                version_num = existing_record.get("version_number", 1) or 1
            else:
                version_num = 1

            record = {
                "file_id": entry.name,
                "relative_path": entry.name,
                "mime_type": "text/plain" if ext == ".txt" else "text/markdown",
                "mtime": mtime,
                "size_bytes": size_bytes,
                "sha256": None,
                "lifecycle_status": "DETECTED",
                "detected_at": now_utc,
                "fetched_at": None,
                "acknowledged_at": None,
                "version_number": version_num,
                "retry_count": existing_retry_count,
                "notes": "Modified version detected" if is_modified else "New ТЗ detected in inbox"
            }

            # FETCH
            try:
                content = entry.read_bytes()

                # AS-07: UTF-8 validation
                try:
                    text_content = content.decode("utf-8")
                except UnicodeDecodeError as ue:
                    logger.warning(f"AS-07: Rejected non-UTF-8 content in {entry.name}: {ue}")
                    record["lifecycle_status"] = "REJECTED_NON_UTF8"
                    record["last_error"] = str(ue)
                    tracked[file_key] = record
                    continue

                file_sha = self.compute_sha256(content)
                record["sha256"] = file_sha
                record["lifecycle_status"] = "FETCHED"
                record["fetched_at"] = datetime.now(timezone.utc).isoformat()
                record["retry_count"] = 0

                # Content idempotency check
                if existing_record and prev_status == "ACKNOWLEDGED" and existing_record.get("sha256") == file_sha:
                    record["lifecycle_status"] = "ACKNOWLEDGED"
                    record["acknowledged_at"] = existing_record.get("acknowledged_at")
                    record["version_number"] = existing_record.get("version_number", 1)
                    record["spool_path"] = existing_record.get("spool_path")
                    tracked[file_key] = record
                    continue

                cycle_result["fetched_count"] += 1

                # Archive copy to local spool
                spool_filename = f"{entry.stem}_v{version_num}_{file_sha[:8]}{entry.suffix}"
                spool_target = self.spool_dir / spool_filename
                spool_target.write_bytes(content)
                record["spool_path"] = _sanitize_path(spool_target)

                # ACKNOWLEDGE
                record["lifecycle_status"] = "ACKNOWLEDGED"
                record["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
                cycle_result["acknowledged_count"] += 1

                event_id = f"event_{entry.stem[:24]}_v{version_num}_{file_sha[:8]}"
                event_data = {
                    "event_id": event_id,
                    "timestamp_utc": record["acknowledged_at"],
                    "watcher_mode": self.mode,
                    "event_type": "NEW_TZ_DETECTED" if is_new else "TZ_VERSION_UPDATED",
                    "file_name": entry.name,
                    "version_number": version_num,
                    "size_bytes": size_bytes,
                    "sha256": file_sha,
                    "spool_file": _sanitize_path(spool_target),
                    "action_required": "Autonomous dispatch enqueued" if self.mode == "AUTO_EXECUTE_SCOPED" else "Operator review required; autonomous agent launch disabled in DETECTION_ONLY mode."
                }
                event_path = self.notifications_dir / f"{event_id}.json"
                if not event_path.exists():
                    event_path.write_text(json.dumps(event_data, indent=2, ensure_ascii=False), encoding="utf-8")

                history = self.state.setdefault("history", [])
                if not any(h.get("event_id") == event_id for h in history):
                    history.append({
                        "event_id": event_id,
                        "file_name": entry.name,
                        "version_number": version_num,
                        "sha256": file_sha,
                        "timestamp_utc": record["acknowledged_at"]
                    })
                    cycle_result["new_events"].append(event_data)

                # ENQUEUE FOR EXECUTION
                job_id = f"job_{entry.stem[:24]}_v{version_num}_{file_sha[:8]}"
                task_id = extract_task_id(entry.name, text_content)

                # P0-D2 & Section 8.4: Supersede pending versions of the same file/task
                for old_jid, old_job in queue.items():
                    if old_job.get("file_name") == entry.name or old_job.get("task_id") == task_id:
                        if old_job.get("execution_status") in ("QUEUED", "PENDING"):
                            old_job["execution_status"] = "SUPERSEDED"
                            old_job["notes"] = f"Superseded by newer version {version_num} ({job_id})"

                if job_id not in queue or queue[job_id].get("execution_status") not in ("SUCCEEDED", "HISTORICALLY_COMPLETED"):
                    job_record = {
                        "job_id": job_id,
                        "task_id": task_id,
                        "file_name": entry.name,
                        "version_number": version_num,
                        "sha256": file_sha,
                        "delivery_status": "ACKNOWLEDGED",
                        "execution_status": "QUEUED" if self.mode == "AUTO_EXECUTE_SCOPED" else "DETECTION_ONLY",
                        "enqueued_at": record["acknowledged_at"],
                        "dispatched_at": None,
                        "finished_at": None,
                        "lease_pid": None,
                        "lease_expires_at": None,
                        "attempts": 0,
                        "max_attempts": self.MAX_DISPATCH_ATTEMPTS,
                        "last_error": None,
                        "conversation_id": None,
                        "spool_path": str(spool_target),
                        "notes": "Enqueued for autonomous execution" if self.mode == "AUTO_EXECUTE_SCOPED" else "Awaiting operator authorization (DETECTION_ONLY)"
                    }
                    queue[job_id] = job_record
                    cycle_result["enqueued_count"] += 1

            except Exception as read_err:
                new_retry_count = existing_retry_count + 1
                record["retry_count"] = new_retry_count
                record["last_error"] = str(read_err)
                if new_retry_count >= self.MAX_RETRIES:
                    record["lifecycle_status"] = "FAILED_PERMANENT"
                    record["notes"] = f"Retry limit reached ({new_retry_count}/{self.MAX_RETRIES}). Terminal failure."
                else:
                    record["lifecycle_status"] = "FAILED_RETRY"
                    record["notes"] = f"Read failed (attempt {new_retry_count}/{self.MAX_RETRIES}). Will retry on next scheduled poll."
                cycle_result["failed_retry_count"] += 1
                logger.warning(f"Failed to fetch {entry.name}: {read_err}")

            tracked[file_key] = record

        self.state["last_poll_utc"] = now_utc
        self.state["ignored_cloud_shortcuts"] = ignored_shortcuts
        self._save_state()
        return cycle_result

    def dispatch_queue(self) -> dict:
        """
        Processes the execution queue in AUTO_EXECUTE_SCOPED mode under execution.lock.
        Guarantees single worker concurrency (AS-04), crash recovery (AS-06),
        pre-dispatch spool hash check (AS-08), and policy validation (AS-09).
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        dispatch_result = {
            "timestamp_utc": now_utc,
            "dispatched_count": 0,
            "status": "IDLE",
            "active_job": None
        }

        # Check pause sentinel (AS-11)
        if self.is_paused():
            dispatch_result["status"] = "PAUSED"
            dispatch_result["message"] = "Watcher is paused (watcher.pause exists). Skipping dispatch."
            logger.info(dispatch_result["message"])
            return dispatch_result

        if self.mode != "AUTO_EXECUTE_SCOPED":
            dispatch_result["status"] = "DETECTION_ONLY"
            dispatch_result["message"] = "Autonomous execution disabled in DETECTION_ONLY mode."
            return dispatch_result

        # Cross-process execution lock (AS-04)
        if not self.exec_lock.acquire():
            dispatch_result["status"] = "EXECUTION_LOCKED"
            dispatch_result["message"] = "Another dispatcher or worker holds execution.lock. Skipping dispatch."
            logger.info(dispatch_result["message"])
            return dispatch_result

        try:
            self.state = self._load_state()
            queue = self.state.setdefault("execution_queue", {})

            # 1. Lease & Crash Recovery Check (AS-04 & AS-06)
            active = self.state.get("active_execution")
            if active:
                act_pid = active.get("pid")
                act_expires = active.get("lease_expires_at")
                now_ts = time.time()
                pid_alive = False
                if act_pid and act_pid > 0:
                    try:
                        import psutil
                        pid_alive = psutil.pid_exists(act_pid)
                    except Exception:
                        pass

                expires_ts = 0.0
                if act_expires:
                    try:
                        expires_ts = datetime.fromisoformat(act_expires).timestamp()
                    except Exception:
                        pass

                if pid_alive and expires_ts > now_ts:
                    dispatch_result["status"] = "ACTIVE_WORKER_BUSY"
                    dispatch_result["active_job"] = active.get("job_id")
                    dispatch_result["message"] = f"Worker PID {act_pid} is active on {active.get('job_id')}"
                    return dispatch_result
                else:
                    # AS-06: Crash recovery - process vanished or lease expired without receipt
                    crashed_job_id = active.get("job_id")
                    if crashed_job_id and crashed_job_id in queue:
                        c_job = queue[crashed_job_id]
                        if c_job.get("execution_status") == "RUNNING":
                            c_job["execution_status"] = "DISPATCH_UNKNOWN"
                            c_job["last_error"] = f"CRASH_RECOVERY: Process PID {act_pid} vanished or lease expired without receipt"
                            c_job["notes"] = "Crash recovery: status set to DISPATCH_UNKNOWN. No blind retries (AS-06)."
                            logger.error(f"AS-06: Set job {crashed_job_id} to DISPATCH_UNKNOWN without blind retry")
                    self.state["active_execution"] = None
                    self._save_state()

            # 2. Select next QUEUED job
            queued_jobs = [j for j in queue.values() if j.get("execution_status") == "QUEUED"]
            if not queued_jobs:
                dispatch_result["status"] = "IDLE"
                return dispatch_result

            # Sort by enqueued_at ascending
            queued_jobs.sort(key=lambda x: x.get("enqueued_at") or "")
            job = queued_jobs[0]
            job_id = job["job_id"]

            # 3. Pre-dispatch Spool Hash Verification (AS-08)
            raw_spool = job.get("spool_path")
            spool_path = Path(raw_spool) if raw_spool else None
            if not spool_path or not spool_path.exists() or not spool_path.is_file():
                # Attempt lookup in spool dir
                fname = job.get('file_name', '')
                if fname:
                    spool_path = self.spool_dir / f"{Path(fname).stem}_v{job.get('version_number', 1)}_{job.get('sha256', '')[:8]}{Path(fname).suffix}"

            if not spool_path or not spool_path.exists() or not spool_path.is_file():
                job["execution_status"] = "BLOCKED"
                job["last_error"] = f"SPOOL_MISSING: Spool file not found at {spool_path}"
                self._save_state()
                dispatch_result["status"] = "BLOCKED"
                dispatch_result["error"] = job["last_error"]
                return dispatch_result

            spool_bytes = spool_path.read_bytes()
            actual_spool_hash = self.compute_sha256(spool_bytes)
            if actual_spool_hash != job.get("sha256"):
                logger.error(f"AS-08: Spool hash mismatch for {job_id}: actual {actual_spool_hash[:12]} != expected {job.get('sha256')[:12]}")
                job["execution_status"] = "BLOCKED"
                job["last_error"] = f"SPOOL_HASH_MISMATCH: Actual {actual_spool_hash[:12]} != expected {job.get('sha256')[:12]} (AS-08)"
                self._save_state()
                dispatch_result["status"] = "BLOCKED"
                dispatch_result["error"] = job["last_error"]
                return dispatch_result

            # 4. Policy Veto (AS-09)
            try:
                spool_text = spool_bytes.decode("utf-8")
            except Exception:
                spool_text = ""
            policy_ok, policy_reason = check_policy_veto(spool_text)
            if not policy_ok:
                logger.error(f"AS-09: Policy veto for {job_id}: {policy_reason}")
                job["execution_status"] = "BLOCKED"
                job["last_error"] = policy_reason
                self._save_state()
                dispatch_result["status"] = "BLOCKED"
                dispatch_result["error"] = policy_reason
                return dispatch_result

            # 5. Transition to RUNNING & Claim Lease
            job["execution_status"] = "RUNNING"
            job["dispatched_at"] = now_utc
            job["lease_pid"] = os.getpid()
            lease_exp_ts = time.time() + self.LEASE_TIMEOUT_SEC
            job["lease_expires_at"] = datetime.fromtimestamp(lease_exp_ts, timezone.utc).isoformat()
            job["attempts"] = job.get("attempts", 0) + 1

            self.state["active_execution"] = {
                "job_id": job_id,
                "pid": os.getpid(),
                "dispatched_at": job["dispatched_at"],
                "lease_expires_at": job["lease_expires_at"]
            }
            self._save_state()

            # 6. Execute Agent Runner
            if self.runner_callable:
                res_ok, exit_code, stdout, stderr, cid = self.runner_callable(job, spool_path)
            else:
                res_ok, exit_code, stdout, stderr, cid = self._invoke_external_runner(job, spool_path)

            # 7. Evaluate Execution Result (AS-05)
            if res_ok:
                job["execution_status"] = "SUCCEEDED"
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                job["conversation_id"] = cid
                job["last_error"] = None
                job["notes"] = f"Execution succeeded via agent session {cid}" if cid else "Execution completed successfully"
            else:
                # Soft-denied, missing runner, missing auth, or process error yields BLOCKED/FAILED
                if "RUNNER_NOT_FOUND" in stderr or "AUTH_REQUIRED" in stderr or "SOFT_DENIED" in stderr or "PERMISSION_DENIED" in stderr:
                    job["execution_status"] = "BLOCKED"
                else:
                    job["execution_status"] = "FAILED"
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                job["last_error"] = f"RUNNER_FAILURE (exit={exit_code}): {stderr.strip() or stdout.strip()}"
                job["notes"] = f"Terminal failure without blind retry (AS-05)"

            self.state["active_execution"] = None
            self.state["last_dispatch_utc"] = datetime.now(timezone.utc).isoformat()
            self._save_state()

            dispatch_result["dispatched_count"] = 1
            dispatch_result["status"] = job["execution_status"]
            dispatch_result["active_job"] = job_id
            return dispatch_result

        finally:
            self.exec_lock.release()

    def _invoke_external_runner(self, job: dict, spool_file: Path) -> Tuple[bool, int, str, str, Optional[str]]:
        """Invokes Antigravity agent runner via CLI / RPC (P0-D1)."""
        runner_exe = self.runner_cmd or os.environ.get("FLYING_RAG_AUTOSTART_RUNNER") or DEFAULT_AGENT_RUNNER
        runner_p = Path(runner_exe)
        if not runner_p.exists():
            return False, 127, "", f"RUNNER_NOT_FOUND: Runner executable not found at {runner_p}", None

        prompt = (
            f"Автоматический запуск задачи {job.get('task_id', '')} (редакция {job.get('version_number', 1)}, SHA-256 {job.get('sha256', '')[:12]}).\n"
            f"ТЗ спулировано в: {spool_file}\n"
            "Приступай к выполнению разрешённых работ согласно ТЗ в безопасном контуре. "
            "Вопрос «Начинаем?» не задавать."
        )

        title = f"FlyingRAG Auto-Start: {job.get('task_id', '')}"
        cmd = [str(runner_p), "new-conversation", f"--title={title}", prompt]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30.0,
                check=False
            )
            stdout = proc.stdout
            stderr = proc.stderr
            exitcode = proc.returncode

            cid = None
            if stdout:
                try:
                    data = json.loads(stdout.strip())
                    cid = data.get("response", {}).get("conversationId") or data.get("conversationId")
                except Exception:
                    pass

            if exitcode == 0:
                return True, exitcode, stdout, stderr, cid
            return False, exitcode, stdout, stderr, cid

        except subprocess.TimeoutExpired:
            return False, 124, "", "RUNNER_TIMEOUT_EXPIRED: Subprocess timed out after 30s", None
        except Exception as e:
            return False, 1, "", f"RUNNER_EXCEPTION: {e}", None

    def run_locked_cycle(self, bootstrap: bool = False) -> dict:
        """Runs a poll cycle and dispatch protected by cross-process non-blocking locks."""
        if not self.lock.acquire():
            msg = "Another instance of DriveInboxWatcher is currently active. Skipping cycle."
            logger.info(msg)
            return {"status": "SKIPPED_LOCKED", "message": msg}
        try:
            self.state = self._load_state()
            poll_res = self.poll(bootstrap=bootstrap)
            dispatch_res = {}
            if self.mode == "AUTO_EXECUTE_SCOPED":
                dispatch_res = self.dispatch_queue()
            res = dict(poll_res)
            res["dispatch"] = dispatch_res
            return res
        finally:
            self.lock.release()

    def get_status_report(self) -> dict:
        """Returns comprehensive status report for audit and diagnostics."""
        paused = self.is_paused()
        if getattr(self, "_state_is_corrupt", False):
            status = "STATE_CORRUPT_SAFE_HALT"
        elif not self.inbox_dir.exists():
            status = "INBOX_UNAVAILABLE"
        elif paused:
            status = "PAUSED_BY_OPERATOR"
        elif self.mode == "AUTO_EXECUTE_SCOPED":
            status = "MONITOR_READY_AUTO_EXECUTE_SCOPED"
        else:
            status = "MONITOR_READY_DETECTION_ONLY"

        tracked = self.state.get("tracked_files", {})
        queue = self.state.get("execution_queue", {})
        active = self.state.get("active_execution")

        return {
            "watcher_mode": self.mode,
            "status": status,
            "paused": paused,
            "inbox_path": _sanitize_path(self.inbox_dir),
            "state_path": _sanitize_path(self.state_dir),
            "last_poll_utc": self.state.get("last_poll_utc"),
            "last_dispatch_utc": self.state.get("last_dispatch_utc"),
            "active_execution": active,
            "tracked_files_count": len(tracked),
            "execution_queue_count": len(queue),
            "execution_queue": {k: {
                "job_id": v.get("job_id"),
                "task_id": v.get("task_id"),
                "file_name": v.get("file_name"),
                "version_number": v.get("version_number"),
                "sha256": v.get("sha256"),
                "delivery_status": v.get("delivery_status"),
                "execution_status": v.get("execution_status"),
                "enqueued_at": v.get("enqueued_at"),
                "dispatched_at": v.get("dispatched_at"),
                "finished_at": v.get("finished_at"),
                "attempts": v.get("attempts", 0),
                "last_error": v.get("last_error"),
                "conversation_id": v.get("conversation_id"),
                "spool_path": v.get("spool_path")
            } for k, v in queue.items()},
            "tracked_files": {k: {
                "file_id": v.get("file_id"),
                "lifecycle_status": v.get("lifecycle_status"),
                "version_number": v.get("version_number"),
                "sha256": v.get("sha256"),
                "size_bytes": v.get("size_bytes"),
                "retry_count": v.get("retry_count", 0),
                "acknowledged_at": v.get("acknowledged_at"),
                "notes": v.get("notes")
            } for k, v in tracked.items()},
            "history_events_count": len(self.state.get("history", [])),
            "ignored_cloud_shortcuts_count": len(self.state.get("ignored_cloud_shortcuts", [])),
            "retry_policy": {
                "strategy": "periodic_scheduled_poll",
                "interval_minutes": 5,
                "max_attempts": self.MAX_RETRIES,
                "terminal_status": "FAILED_PERMANENT"
            },
            "task_scheduler_task_name": "FlyingRAG_Drive_Inbox_Watcher",
            "task_scheduler_interval": "PT5M (every 5 minutes)",
            "task_scheduler_settings": {
                "StartWhenAvailable": True,
                "MultipleInstancesPolicy": "IgnoreNew",
                "DisallowStartIfOnBatteries": True,
                "LogonType": "InteractiveToken"
            }
        }


def main():
    parser = argparse.ArgumentParser(description="FlyingRAG Google Drive Inbox Watcher & Dispatcher")
    parser.add_argument("--poll-once", action="store_true", help="Execute single poll cycle (and dispatch if auto-start enabled)")
    parser.add_argument("--bootstrap", action="store_true", help="Initialize baseline without triggering new events")
    parser.add_argument("--status", action="store_true", help="Print watcher and queue status JSON and exit")
    parser.add_argument("--enable-autostart", action="store_true", help="Switch watcher mode to AUTO_EXECUTE_SCOPED")
    parser.add_argument("--disable-autostart", action="store_true", help="Switch watcher mode to DETECTION_ONLY")
    parser.add_argument("--pause", action="store_true", help="Create watcher.pause sentinel")
    parser.add_argument("--resume", action="store_true", help="Remove watcher.pause sentinel")
    parser.add_argument("--dispatch-pending", action="store_true", help="Explicitly dispatch pending execution queue items")
    parser.add_argument("--inbox-dir", type=str, default=None, help="Custom inbox directory")
    parser.add_argument("--state-dir", type=str, default=None, help="Custom state directory")
    parser.add_argument("--runner-cmd", type=str, default=None, help="Custom agent runner command")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    watcher = DriveInboxWatcher(
        inbox_dir=args.inbox_dir,
        state_dir=args.state_dir,
        runner_cmd=args.runner_cmd
    )

    if args.pause:
        watcher.pause()
        print(json.dumps({"status": "PAUSED", "pause_file": str(watcher.pause_file)}))
        return

    if args.resume:
        watcher.resume()
        print(json.dumps({"status": "RESUMED", "pause_file": str(watcher.pause_file)}))
        return

    if args.enable_autostart:
        watcher.enable_autostart()
        print(json.dumps({"status": "MODE_UPDATED", "watcher_mode": watcher.mode}))
        return

    if args.disable_autostart:
        watcher.disable_autostart()
        print(json.dumps({"status": "MODE_UPDATED", "watcher_mode": watcher.mode}))
        return

    if args.status:
        report = watcher.get_status_report()
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    if args.dispatch_pending:
        res = watcher.dispatch_queue()
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    res = watcher.run_locked_cycle(bootstrap=args.bootstrap)
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
