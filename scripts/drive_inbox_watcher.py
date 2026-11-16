"""
scripts/drive_inbox_watcher.py

Automated Google Drive Inbox Watcher for FlyingRAG (Stage 4.2.5 / Block M0).
Monitors the Google Drive inbox folder for new ТЗ documents in .txt / .md format.
Maintains state outside Git and production, performs cross-process locking,
handles atomic persistence, and operates strictly in DETECTION_ONLY mode.
"""

from __future__ import annotations
import os
import sys
import json
import time
import hashlib
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("DriveInboxWatcher")

# Default directories
DEFAULT_INBOX_DIR = Path(r"G:\Мой диск\FlyingRAG_TZ_Inbox")
DEFAULT_STATE_DIR = Path(r"C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher")

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
    Autonomous inbox watcher for Google Drive ТЗ documents.
    Tracks file states across poll cycles: DETECTED -> FETCHED -> ACKNOWLEDGED.
    Strictly operates in DETECTION_ONLY mode without external agent execution.
    """
    def __init__(
        self,
        inbox_dir: Path | str | None = None,
        state_dir: Path | str | None = None,
        mode: str = "DETECTION_ONLY"
    ):
        env_inbox = os.environ.get("FLYING_RAG_DRIVE_INBOX_DIR", "").strip()
        self.inbox_dir = Path(inbox_dir or env_inbox or DEFAULT_INBOX_DIR)

        env_state = os.environ.get("FLYING_RAG_DRIVE_WATCHER_DIR", "").strip()
        self.state_dir = Path(state_dir or env_state or DEFAULT_STATE_DIR)
        self.state_file = self.state_dir / "state.json"
        self.lock_file = self.state_dir / "watcher.lock"
        self.spool_dir = self.state_dir / "inbox_spool"
        self.notifications_dir = self.state_dir / "notifications"

        self.mode = mode
        self.lock = FileLock(self.lock_file)
        self.state = self._load_state()

    def _load_state(self) -> dict:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"CRITICAL: Error reading state file {self.state_file}: {e}")
                corrupt_backup = self.state_dir / f"state.json.corrupt_{int(time.time()*1000)}"
                try:
                    import shutil
                    shutil.copy2(self.state_file, corrupt_backup)
                    logger.error(f"Preserved corrupt state file copy at {corrupt_backup}")
                except Exception:
                    pass
        return {
            "version": 1,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "last_poll_utc": None,
            "watcher_mode": self.mode,
            "inbox_path": _sanitize_path(self.inbox_dir),
            "state_path": _sanitize_path(self.state_dir),
            "tracked_files": {},
            "history": [],
            "ignored_cloud_shortcuts": []
        }

    def _save_state(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = self.state_dir / f"state_{os.getpid()}_{int(time.time()*1000)}.tmp"
        try:
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

    @staticmethod
    def compute_sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def poll(self, bootstrap: bool = False) -> dict:
        """
        Executes a single poll cycle across the inbox directory.
        Returns a summary dictionary of actions taken during this cycle.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        cycle_result = {
            "timestamp_utc": now_utc,
            "inbox_exists": self.inbox_dir.exists(),
            "detected_count": 0,
            "fetched_count": 0,
            "acknowledged_count": 0,
            "failed_retry_count": 0,
            "new_events": [],
            "status": "OK"
        }

        if not self.inbox_dir.exists():
            cycle_result["status"] = "INBOX_NOT_FOUND"
            cycle_result["error"] = f"Directory {self.inbox_dir} does not exist or volume is unmounted"
            logger.warning(cycle_result["error"])
            return cycle_result

        # Scan folder
        try:
            entries = list(self.inbox_dir.iterdir())
        except Exception as e:
            cycle_result["status"] = "SCAN_ERROR"
            cycle_result["error"] = str(e)
            return cycle_result

        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self.notifications_dir.mkdir(parents=True, exist_ok=True)

        tracked = self.state.setdefault("tracked_files", {})
        ignored_shortcuts = []

        for entry in entries:
            # Skip hidden and temp files
            if entry.name.startswith("~$") or entry.name.startswith("."):
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

            file_key = entry.name
            existing_record = tracked.get(file_key)

            # Check if file is new, modified, or in a retryable failure state
            is_new = existing_record is None
            is_modified = False
            prev_status = existing_record.get("lifecycle_status") if existing_record else None
            is_retryable = prev_status in ("FAILED_RETRY", "BASELINE_UNREADABLE", "DETECTED")

            if existing_record:
                if existing_record.get("mtime") != mtime or existing_record.get("size_bytes") != size_bytes:
                    is_modified = True

            # If file was already successfully acknowledged and is unchanged, skip
            if not is_new and not is_modified and not is_retryable:
                continue

            # If bootstrap mode and file is new (or unreadable baseline)
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
                "notes": "Modified version detected" if is_modified else "New ТЗ detected in inbox"
            }

            # FETCH
            try:
                content = entry.read_bytes()
                file_sha = self.compute_sha256(content)
                record["sha256"] = file_sha
                record["lifecycle_status"] = "FETCHED"
                record["fetched_at"] = datetime.now(timezone.utc).isoformat()
                cycle_result["fetched_count"] += 1

                # Archive copy to local spool
                spool_filename = f"{entry.stem}_v{version_num}_{file_sha[:8]}{entry.suffix}"
                spool_target = self.spool_dir / spool_filename
                spool_target.write_bytes(content)
                record["spool_path"] = _sanitize_path(spool_target)

                # ACKNOWLEDGE (DETECTION_ONLY)
                record["lifecycle_status"] = "ACKNOWLEDGED"
                record["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
                cycle_result["acknowledged_count"] += 1

                # Emit notification event
                event_id = f"event_{int(time.time()*1000)}_{entry.stem[:20]}"
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
                    "action_required": "Operator review required; autonomous agent launch disabled in DETECTION_ONLY mode."
                }
                event_path = self.notifications_dir / f"{event_id}.json"
                event_path.write_text(json.dumps(event_data, indent=2, ensure_ascii=False), encoding="utf-8")

                cycle_result["new_events"].append(event_data)
                self.state.setdefault("history", []).append({
                    "event_id": event_id,
                    "file_name": entry.name,
                    "version_number": version_num,
                    "sha256": file_sha,
                    "timestamp_utc": record["acknowledged_at"]
                })

            except Exception as read_err:
                record["lifecycle_status"] = "FAILED_RETRY"
                record["last_error"] = str(read_err)
                record["retry_count"] = record.get("retry_count", 0) + 1
                cycle_result["failed_retry_count"] += 1
                logger.warning(f"Failed to fetch {entry.name}: {read_err}")

            tracked[file_key] = record

        self.state["last_poll_utc"] = now_utc
        self.state["ignored_cloud_shortcuts"] = ignored_shortcuts
        self._save_state()
        return cycle_result

    def run_locked_cycle(self, bootstrap: bool = False) -> dict:
        """Runs a poll cycle protected by cross-process non-blocking lock."""
        if not self.lock.acquire():
            msg = "Another instance of DriveInboxWatcher is currently active. Skipping cycle."
            logger.info(msg)
            return {"status": "SKIPPED_LOCKED", "message": msg}
        try:
            # Re-read state from disk inside critical section to prevent stale state across processes
            self.state = self._load_state()
            return self.poll(bootstrap=bootstrap)
        finally:
            self.lock.release()

    def get_status_report(self) -> dict:
        """Returns comprehensive status report for audit and diagnostics."""
        tracked = self.state.get("tracked_files", {})
        return {
            "watcher_mode": self.mode,
            "status": "MONITOR_READY_DETECTION_ONLY",
            "inbox_path": _sanitize_path(self.inbox_dir),
            "state_path": _sanitize_path(self.state_dir),
            "last_poll_utc": self.state.get("last_poll_utc"),
            "tracked_files_count": len(tracked),
            "tracked_files": {k: {
                "file_id": v.get("file_id"),
                "lifecycle_status": v.get("lifecycle_status"),
                "version_number": v.get("version_number"),
                "sha256": v.get("sha256"),
                "size_bytes": v.get("size_bytes"),
                "acknowledged_at": v.get("acknowledged_at"),
                "notes": v.get("notes")
            } for k, v in tracked.items()},
            "history_events_count": len(self.state.get("history", [])),
            "ignored_cloud_shortcuts_count": len(self.state.get("ignored_cloud_shortcuts", [])),
            "task_scheduler_task_name": "FlyingRAG_Drive_Inbox_Watcher",
            "task_scheduler_interval": "PT5M (every 5 minutes)"
        }


def main():
    parser = argparse.ArgumentParser(description="FlyingRAG Google Drive Inbox Watcher")
    parser.add_argument("--poll-once", action="store_true", help="Execute single poll cycle and exit")
    parser.add_argument("--bootstrap", action="store_true", help="Initialize baseline without triggering new events")
    parser.add_argument("--status", action="store_true", help="Print watcher status JSON and exit")
    parser.add_argument("--inbox-dir", type=str, default=None, help="Custom inbox directory")
    parser.add_argument("--state-dir", type=str, default=None, help="Custom state directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    watcher = DriveInboxWatcher(inbox_dir=args.inbox_dir, state_dir=args.state_dir)

    if args.status:
        report = watcher.get_status_report()
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    res = watcher.run_locked_cycle(bootstrap=args.bootstrap)
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
